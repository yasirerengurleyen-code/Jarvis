"""
mobile/ios/istemci.py
---------------------
iPhone istemci iskeleti (PlatformIstemciTabani).

Görev:
- PC host'a bağlanma / kopma
- Mobil komut gönder / al (MobilKomutIstegi ↔ MobilKomutYaniti)
- dry_run / sahte modda gerçek iPhone olmadan test

Motorlar:
  - dry_run: ağ yok; bellek içi oturum + sahte komut yanıtları
  - sahte: websockets yok / zorla_sahte; aynı bellek içi davranış
  - memory: isteğe bağlı WsSunucu ile protokol AUTH (canlı WS değil)

Not: Native Swift uygulaması sonraki sürüm; köprü `kopru.py` üst katmanda.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import PlatformIstemciTabani
from core.events import (
    OLAY_IPHONE_BAGLANDI,
    OLAY_IPHONE_KOPTU,
    OLAY_MOBIL_BILDIRIM,
    OLAY_MOBIL_KOMUT,
    OLAY_MOBIL_PIL,
    olay_yolu,
)
from core.exceptions import MobileBridgeError
from core.logger import audit_yaz, logger_al
from mobile.bridge.komutlar import (
    KomutDurum,
    KomutYon,
    MobilKomut,
    MobilKomutIstegi,
    MobilKomutSozlesmesi,
    MobilKomutYaniti,
    istek_olustur,
    komut_coz,
    komut_yonu,
)
from mobile.ios.modeller import (
    IosCihaz,
    IosOturum,
    IosOturumDurumu,
    IosPilBilgisi,
    ios_cihaz_olustur,
    ios_oturum_olustur,
)
from network.device.modeller import BaglantiDurumu

log = logger_al("mobile.ios.istemci")

MobilKomutGirdi = Union[MobilKomut, str, MobilKomutIstegi]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IosIstemci(PlatformIstemciTabani):
    """
    Python tarafı iPhone istemci iskeleti.

    Gerçek cihaz yerine dry_run/sahte ile komut sözleşmesini çalıştırır.
    """

    platform = "ios"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        cihaz: Optional[IosCihaz] = None,
        oturum: Optional[IosOturum] = None,
        sozlesme: Optional[MobilKomutSozlesmesi] = None,
        ws_sunucu: Optional[Any] = None,
        varsayilan_pil: int = 87,
    ) -> None:
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.sozlesme = sozlesme or MobilKomutSozlesmesi(self.ayarlar)
        self.ws_sunucu = ws_sunucu

        self.cihaz = cihaz or ios_cihaz_olustur(
            ad=str(self.ayarlar.al("assistant.name", "iPhone") or "iPhone"),
            model="iPhone",
        )
        if self.cihaz.pil is None:
            self.cihaz.pil = IosPilBilgisi(yuzde=int(varsayilan_pil))

        self.oturum = oturum or ios_oturum_olustur(cihaz_id=self.cihaz.cihaz_id)
        self._token: Optional[str] = None
        self._ws_oturum_id: Optional[str] = None
        self._motor = self._motor_sec()

        # Test / dry_run kuyrukları
        self._gelen: Deque[MobilKomutIstegi] = deque()
        self._giden_yanit: Deque[MobilKomutYaniti] = deque()
        self._giden_istek: Deque[MobilKomutIstegi] = deque()  # phone → PC

    # ------------------------------------------------------------------ motor

    @property
    def motor(self) -> str:
        return self._motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self.ws_sunucu is not None:
            return "memory"
        # Gerçek WS istemcisi sonraki sürüm — şimdilik sahte
        return "sahte"

    @property
    def bagli_mi(self) -> bool:
        return self.oturum.bagli_mi() and self.cihaz.cevrimici_mi()

    # ------------------------------------------------------------------ PlatformIstemciTabani

    async def baglan(self, host: str, token: str) -> bool:
        """
        Host'a bağlanır.

        dry_run / sahte: ağ yok; token boş değilse başarılı.
        memory: isteğe bağlı WsSunucu üzerinde bellek içi AUTH.
        """
        token = str(token or "").strip()
        if not token:
            self.oturum.durum = IosOturumDurumu.HATA
            raise MobileBridgeError(
                "Baglanti tokeni bos",
                kod="MOB_0030",
                modul="mobile.ios",
            )

        host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        self._motor = self._motor_sec()
        self.oturum.host = host
        self.oturum.durum = IosOturumDurumu.BAGLANIYOR
        self.oturum.dokun()
        self.cihaz.durum = BaglantiDurumu.ESLESME
        self.cihaz.dokun()

        try:
            if self._motor == "memory" and self.ws_sunucu is not None:
                await self._ws_ile_baglan(token)
            else:
                # dry_run / sahte — anında kimlikli
                self._bellek_baglan(token)
        except MobileBridgeError:
            self.oturum.kopar(hata=True)
            self.cihaz.durum = BaglantiDurumu.HATA
            raise
        except Exception as exc:  # noqa: BLE001
            self.oturum.kopar(hata=True)
            self.cihaz.durum = BaglantiDurumu.HATA
            raise MobileBridgeError(
                f"iOS istemci baglanamadi: {exc}",
                kod="MOB_0031",
                modul="mobile.ios",
                detay={"host": host, "engine": self._motor},
            ) from exc

        self._token = token
        audit_yaz(
            "ios.client.connected",
            modul="mobile.ios",
            detay={
                "device_id": self.cihaz.cihaz_id,
                "session_id": self.oturum.oturum_id,
                "host": host,
                "engine": self._motor,
            },
        )
        await olay_yolu.publish(
            OLAY_IPHONE_BAGLANDI,
            {
                "device_id": self.cihaz.cihaz_id,
                "session_id": self.oturum.oturum_id,
                "host": host,
                "engine": self._motor,
            },
            kaynak="mobile.ios",
        )
        log.info(
            "iOS istemci baglandi (motor=%s, cihaz=%s, host=%s)",
            self._motor,
            self.cihaz.cihaz_id[:12],
            host,
        )
        return True

    async def baglantiyi_kes(self) -> None:
        """Bağlantıyı kapatır; zaten kopuksa no-op."""
        if (
            self.oturum.durum
            in {IosOturumDurumu.BAGLI_DEGIL, IosOturumDurumu.KOPUK}
            and not self.oturum.kimlikli
        ):
            return

        cihaz_id = self.cihaz.cihaz_id
        oturum_id = self.oturum.oturum_id

        if self._ws_oturum_id and self.ws_sunucu is not None:
            try:
                self.ws_sunucu.oturum_kapat(self._ws_oturum_id, neden="ios_client")
            except Exception as exc:  # noqa: BLE001
                log.debug("WS oturum kapatma: %s", exc)
            self._ws_oturum_id = None

        self.oturum.kopar(hata=False)
        self.cihaz.durum = BaglantiDurumu.CEVRIMDISI
        self.cihaz.dokun()
        self._token = None

        audit_yaz(
            "ios.client.disconnected",
            modul="mobile.ios",
            detay={"device_id": cihaz_id, "session_id": oturum_id},
        )
        await olay_yolu.publish(
            OLAY_IPHONE_KOPTU,
            {"device_id": cihaz_id, "session_id": oturum_id},
            kaynak="mobile.ios",
        )
        log.info("iOS istemci koptu (cihaz=%s)", cihaz_id[:12])

    async def durum(self) -> dict[str, Any]:
        """İstemci durum özeti."""
        return {
            "platform": self.platform,
            "engine": self._motor,
            "connected": self.bagli_mi,
            "host": self.oturum.host,
            "device": self.cihaz.to_dict(),
            "session": self.oturum.to_dict(),
            "pending_incoming": len(self._gelen),
            "pending_responses": len(self._giden_yanit),
            "pending_pc_commands": len(self._giden_istek),
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ komut API

    async def komut_al(
        self,
        istek: MobilKomutGirdi,
        *,
        args: Optional[dict[str, Any]] = None,
        dogrula: bool = True,
    ) -> MobilKomutYaniti:
        """
        PC → telefon komutunu alır ve yanıtlar (dry_run/sahte yerel işler).

        Gerçek iPhone olmadan find_phone / battery / notification test edilir.
        """
        if not self.bagli_mi:
            raise MobileBridgeError(
                "iOS istemci bagli degil; once baglan() cagirin",
                kod="MOB_0032",
                modul="mobile.ios",
            )

        nesne = self._istege_cevir(istek, args=args, dogrula=dogrula)
        if nesne.yon is not KomutYon.PC_TO_PHONE:
            raise MobileBridgeError(
                f"komut_al yalnizca pc_to_phone kabul eder: {nesne.komut.value}",
                kod="MOB_0033",
                modul="mobile.ios",
                detay={"direction": nesne.yon.value},
            )

        if nesne.cihaz_id is None:
            nesne.cihaz_id = self.cihaz.cihaz_id

        self._gelen.append(nesne)
        self.oturum.dokun()
        self.cihaz.dokun()

        yanit = await self._komut_isle_yerel(nesne)
        self._giden_yanit.append(yanit)

        await olay_yolu.publish(
            OLAY_MOBIL_KOMUT,
            {
                "command": nesne.komut.value,
                "direction": nesne.yon.value,
                "status": yanit.durum.value,
                "device_id": self.cihaz.cihaz_id,
                "request_id": nesne.istek_id,
            },
            kaynak="mobile.ios",
        )
        audit_yaz(
            "ios.client.command",
            modul="mobile.ios",
            detay={
                "command": nesne.komut.value,
                "status": yanit.durum.value,
                "device_id": self.cihaz.cihaz_id,
            },
        )
        return yanit

    async def komut_gonder(
        self,
        komut: MobilKomutGirdi,
        *,
        args: Optional[dict[str, Any]] = None,
        dogrula: bool = True,
    ) -> MobilKomutIstegi:
        """
        Telefon → PC komutu kuyruğa alır (gönderim; host tarafı sonra işler).

        dry_run/sahte: bellek kuyruğuna yazar, gerçek PC eylemi yok.
        """
        if not self.bagli_mi:
            raise MobileBridgeError(
                "iOS istemci bagli degil; once baglan() cagirin",
                kod="MOB_0032",
                modul="mobile.ios",
            )

        if isinstance(komut, MobilKomutIstegi):
            nesne = komut
        else:
            k = komut_coz(komut)
            if komut_yonu(k) is not KomutYon.PHONE_TO_PC:
                raise MobileBridgeError(
                    f"komut_gonder yalnizca phone_to_pc kabul eder: {k.value}",
                    kod="MOB_0034",
                    modul="mobile.ios",
                    detay={"direction": komut_yonu(k).value},
                )
            nesne = self.sozlesme.istek_olustur(
                k,
                cihaz_id=self.cihaz.cihaz_id,
                args=args,
                dogrula=dogrula,
            )

        if nesne.yon is not KomutYon.PHONE_TO_PC:
            raise MobileBridgeError(
                f"komut_gonder yalnizca phone_to_pc kabul eder: {nesne.komut.value}",
                kod="MOB_0034",
                modul="mobile.ios",
            )

        if nesne.cihaz_id is None:
            nesne.cihaz_id = self.cihaz.cihaz_id

        self._giden_istek.append(nesne)
        self.oturum.dokun()

        await olay_yolu.publish(
            OLAY_MOBIL_KOMUT,
            {
                "command": nesne.komut.value,
                "direction": nesne.yon.value,
                "status": "queued",
                "device_id": self.cihaz.cihaz_id,
                "request_id": nesne.istek_id,
            },
            kaynak="mobile.ios",
        )
        log.debug(
            "phone_to_pc kuyruk: %s cihaz=%s",
            nesne.komut.value,
            self.cihaz.cihaz_id[:12],
        )
        return nesne

    def gelen_cek(self) -> list[MobilKomutIstegi]:
        """Alınan PC→telefon isteklerini alıp temizler (test)."""
        items = list(self._gelen)
        self._gelen.clear()
        return items

    def yanit_cek(self) -> list[MobilKomutYaniti]:
        """Üretilen yanıtları alıp temizler (test)."""
        items = list(self._giden_yanit)
        self._giden_yanit.clear()
        return items

    def pc_komut_cek(self) -> list[MobilKomutIstegi]:
        """Kuyruktaki telefon→PC isteklerini alıp temizler (test)."""
        items = list(self._giden_istek)
        self._giden_istek.clear()
        return items

    def pil_ayarla(
        self,
        yuzde: int,
        *,
        sarj_oluyor: bool = False,
        dusuk_guc: bool = False,
    ) -> IosPilBilgisi:
        """Sahte cihaz pil durumunu günceller."""
        return self.cihaz.pil_guncelle(
            yuzde, sarj_oluyor=sarj_oluyor, dusuk_guc=dusuk_guc
        )

    # ------------------------------------------------------------------ iç: bağlantı

    def _bellek_baglan(self, token: str) -> None:
        """dry_run / sahte anında bağlantı."""
        parmak = token[:16] if len(token) >= 8 else uuid4().hex[:16]
        self.oturum.baglan(
            self.cihaz.cihaz_id,
            token_parmak_izi=parmak,
            shortcuts_aktif=bool(
                self.ayarlar.al("mobile.features.qr_pairing", True)
            ),
        )
        self.cihaz.durum = BaglantiDurumu.CEVRIMICI
        self.cihaz.oturum_id = self.oturum.oturum_id
        self.cihaz.token_parmak_izi = parmak
        self.cihaz.dokun()

    async def _ws_ile_baglan(self, token: str) -> None:
        """Bellek içi WsSunucu oturumu + AUTH."""
        from network.websocket.protokol import MesajTipi, auth_mesaji

        srv = self.ws_sunucu
        if srv is None:
            raise MobileBridgeError(
                "WsSunucu tanimli degil",
                kod="MOB_0031",
                modul="mobile.ios",
            )
        if not getattr(srv, "calisiyor", False):
            await srv.baslat()

        oturum = srv.oturum_ac(
            uzak_adres=f"ios:{self.cihaz.cihaz_id[:12]}",
            meta={"platform": "ios", "device_id": self.cihaz.cihaz_id},
        )
        self._ws_oturum_id = oturum.oturum_id
        # Host hello temizle
        try:
            srv.giden_cek(oturum.oturum_id)
        except Exception:  # noqa: BLE001
            pass

        yanitlar = srv.mesaj_isle(
            oturum.oturum_id,
            auth_mesaji(token, cihaz_id=self.cihaz.cihaz_id),
        )
        if not yanitlar or yanitlar[0].tip is not MesajTipi.AUTH_OK:
            kod = "MOB_0031"
            mesaj = "WS AUTH basarisiz"
            if yanitlar:
                mesaj = str(yanitlar[0].yuk.get("message") or mesaj)
            raise MobileBridgeError(mesaj, kod=kod, modul="mobile.ios")

        cihaz_id = str(
            yanitlar[0].yuk.get("device_id") or self.cihaz.cihaz_id
        )
        self.cihaz.cihaz_id = cihaz_id
        self._bellek_baglan(token)

    # ------------------------------------------------------------------ iç: komut işleme

    def _istege_cevir(
        self,
        istek: MobilKomutGirdi,
        *,
        args: Optional[dict[str, Any]] = None,
        dogrula: bool = True,
    ) -> MobilKomutIstegi:
        if isinstance(istek, MobilKomutIstegi):
            return istek
        return self.sozlesme.istek_olustur(
            istek,
            cihaz_id=self.cihaz.cihaz_id,
            args=args,
            dogrula=dogrula,
        )

    async def _komut_isle_yerel(self, istek: MobilKomutIstegi) -> MobilKomutYaniti:
        """dry_run / sahte yerel yanıt üretir."""
        k = istek.komut

        if not self.cihaz.yetenek_var_mi(k.value) and k.value not in {
            "find_phone",
            "battery_status",
            "send_notification",
            "open_camera",
            "request_location",
        }:
            return self.sozlesme.yanit_hata(
                k,
                f"Desteklenmeyen komut: {k.value}",
                durum=KomutDurum.DESTEKLENMIYOR,
                istek_id=istek.istek_id,
                cihaz_id=self.cihaz.cihaz_id,
            )

        if k is MobilKomut.FIND_PHONE:
            return await self._yanit_find_phone(istek)
        if k is MobilKomut.BATTERY_STATUS:
            return await self._yanit_battery(istek)
        if k is MobilKomut.SEND_NOTIFICATION:
            return await self._yanit_notification(istek)
        if k is MobilKomut.OPEN_CAMERA:
            return self.sozlesme.yanit_ok(
                k,
                mesaj="Kamera acildi (sahte)",
                veri={"opened": True, "engine": self._motor},
                istek_id=istek.istek_id,
                cihaz_id=self.cihaz.cihaz_id,
            )
        if k is MobilKomut.REQUEST_LOCATION:
            return self.sozlesme.yanit_ok(
                k,
                mesaj="Konum (sahte)",
                veri={
                    "lat": 41.0082,
                    "lon": 28.9784,
                    "accuracy_m": 25,
                    "engine": self._motor,
                },
                istek_id=istek.istek_id,
                cihaz_id=self.cihaz.cihaz_id,
            )

        return self.sozlesme.yanit_hata(
            k,
            f"Islenmeyen komut: {k.value}",
            durum=KomutDurum.DESTEKLENMIYOR,
            istek_id=istek.istek_id,
            cihaz_id=self.cihaz.cihaz_id,
        )

    async def _yanit_find_phone(self, istek: MobilKomutIstegi) -> MobilKomutYaniti:
        titreşim = bool(istek.args.get("vibrate", True))
        ses = bool(istek.args.get("sound", True))
        return self.sozlesme.yanit_ok(
            istek.komut,
            mesaj="Telefonumu Bul sinyali gonderildi (sahte)",
            veri={
                "played": True,
                "vibrate": titreşim,
                "sound": ses,
                "engine": self._motor,
            },
            istek_id=istek.istek_id,
            cihaz_id=self.cihaz.cihaz_id,
        )

    async def _yanit_battery(self, istek: MobilKomutIstegi) -> MobilKomutYaniti:
        pil = self.cihaz.pil or IosPilBilgisi(yuzde=87)
        self.cihaz.pil = pil
        await olay_yolu.publish(
            OLAY_MOBIL_PIL,
            {
                "device_id": self.cihaz.cihaz_id,
                "percent": pil.yuzde,
                "charging": pil.sarj_oluyor,
            },
            kaynak="mobile.ios",
        )
        return self.sozlesme.yanit_ok(
            istek.komut,
            mesaj="Pil durumu",
            veri=pil.to_dict(),
            istek_id=istek.istek_id,
            cihaz_id=self.cihaz.cihaz_id,
        )

    async def _yanit_notification(self, istek: MobilKomutIstegi) -> MobilKomutYaniti:
        baslik = str(istek.args.get("title") or istek.args.get("baslik") or "WhiteCore")
        govde = str(istek.args.get("body") or istek.args.get("govde") or "")
        await olay_yolu.publish(
            OLAY_MOBIL_BILDIRIM,
            {
                "device_id": self.cihaz.cihaz_id,
                "title": baslik,
                "body": govde,
            },
            kaynak="mobile.ios",
        )
        return self.sozlesme.yanit_ok(
            istek.komut,
            mesaj="Bildirim gosterildi (sahte)",
            veri={
                "delivered": True,
                "title": baslik,
                "body": govde,
                "engine": self._motor,
            },
            istek_id=istek.istek_id,
            cihaz_id=self.cihaz.cihaz_id,
        )


def ios_istemci_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    cihaz_id: Optional[str] = None,
    ad: str = "iPhone",
    ayarlar: Optional[Ayarlar] = None,
    ws_sunucu: Optional[Any] = None,
) -> IosIstemci:
    """Test / demo için hazır IosIstemci üretir."""
    cihaz = ios_cihaz_olustur(cihaz_id, ad=ad)
    return IosIstemci(
        ayarlar,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        cihaz=cihaz,
        ws_sunucu=ws_sunucu,
    )


# Kısa yol: sözleşmeden istek üret (modül düzeyi)
def pc_komut_istegi(
    komut: Union[MobilKomut, str],
    *,
    cihaz_id: Optional[str] = None,
    args: Optional[dict[str, Any]] = None,
    ayarlar: Optional[Ayarlar] = None,
) -> MobilKomutIstegi:
    """PC → telefon istek kısayolu."""
    return istek_olustur(
        komut, cihaz_id=cihaz_id, args=args, ayarlar=ayarlar, dogrula=True
    )


__all__ = [
    "IosIstemci",
    "ios_istemci_olustur",
    "pc_komut_istegi",
]

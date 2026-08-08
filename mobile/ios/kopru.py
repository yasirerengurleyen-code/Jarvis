"""
mobile/ios/kopru.py
-------------------
PC host ↔ iPhone komut köprüsü (MobilKopru gerçek uygulaması).

Görev:
- Engine / Network tarafına MobilKopru arayüzünü sunmak
- Komutları kayıtlı IosIstemci örneklerine yönlendirmek
- dry_run / sahte modda gerçek iPhone olmadan test

Motorlar:
  - dry_run: ağ yok; bellek içi istemci + sahte yanıtlar
  - sahte: websockets yok / zorla_sahte; aynı bellek içi davranış
  - memory: isteğe bağlı WsSunucu / NetworkYoneticisi ile

Not: Shortcuts sözleşmesi `shortcuts.py`; Mobile Manager `yoneticisi.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import OLAY_MOBIL_KOMUT, olay_yolu
from core.exceptions import MobileBridgeError
from core.logger import audit_yaz, logger_al
from mobile.bridge.arayuzler import MobilKopru
from mobile.bridge.komutlar import (
    KomutDurum,
    MobilKomut,
    MobilKomutIstegi,
    MobilKomutSozlesmesi,
    MobilKomutYaniti,
)
from mobile.ios.istemci import IosIstemci, ios_istemci_olustur
from network.device.modeller import BaglantiDurumu, BagliCihaz

log = logger_al("mobile.ios.kopru")

IstemciGirdi = Union[IosIstemci, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IosKopru(MobilKopru, ModulTabani):
    """
    Windows host üzerinde iPhone komut köprüsü.

    MobilKopru metotlarını bağlı IosIstemci örneklerine iletir.
    """

    ad = "mobile.ios.kopru"
    surum = "0.1.0"
    aciklama = "iPhone komut koprusu (MobilKopru → IosIstemci)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        sozlesme: Optional[MobilKomutSozlesmesi] = None,
        cihaz_yoneticisi: Optional[Any] = None,
        network: Optional[Any] = None,
        bildirim_kopru: Optional[Any] = None,
        ws_sunucu: Optional[Any] = None,
        varsayilan_host: Optional[str] = None,
        varsayilan_token: Optional[str] = None,
    ) -> None:
        ModulTabani.__init__(self)
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.sozlesme = sozlesme or MobilKomutSozlesmesi(self.ayarlar)
        self.cihaz_yoneticisi = cihaz_yoneticisi
        self.network = network
        self.bildirim_kopru = bildirim_kopru
        self.ws_sunucu = ws_sunucu

        if self.cihaz_yoneticisi is None and network is not None:
            self.cihaz_yoneticisi = getattr(network, "cihazlar", None)
        if self.bildirim_kopru is None and network is not None:
            self.bildirim_kopru = getattr(network, "bildirim", None)
        if self.ws_sunucu is None and network is not None:
            self.ws_sunucu = getattr(network, "ws", None)

        self.varsayilan_host = str(
            varsayilan_host
            or self.ayarlar.al("network.host", "127.0.0.1")
            or "127.0.0.1"
        )
        if self.varsayilan_host in {"0.0.0.0", "::"}:
            self.varsayilan_host = "127.0.0.1"
        self.varsayilan_token = str(
            varsayilan_token
            or self.ayarlar.al("network.pairing.demo_token", "whitecore-demo")
            or "whitecore-demo"
        )

        self._istemciler: dict[str, IosIstemci] = {}
        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ yaşam

    @property
    def motor(self) -> str:
        return self._motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self.ws_sunucu is not None or self.network is not None:
            return "memory"
        return "sahte"

    async def baslat(self) -> None:
        """Köprüyü başlatır (idempotent)."""
        if self._calisiyor:
            return
        self._motor = self._motor_sec()
        # Config kapalı olsa bile dry_run / sahte ile test edilebilir
        bridge_on = bool(self.ayarlar.al("mobile.bridge_enabled", False))
        mobile_on = bool(self.ayarlar.al("mobile.enabled", False))
        if (
            not bridge_on
            and not mobile_on
            and not self.dry_run
            and not self.zorla_sahte
        ):
            log.warning(
                "mobile.bridge_enabled/mobile.enabled kapali; "
                "kopru yine baslatildi (ust katman kontrol eder)"
            )
        self._calisiyor = True
        audit_yaz(
            "ios.bridge.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "devices": len(self._istemciler),
                "dry_run": self.dry_run,
            },
        )
        log.info(
            "iOS kopru basladi (motor=%s, cihaz=%d)",
            self._motor,
            len(self._istemciler),
        )

    async def durdur(self) -> None:
        """Bağlı istemcileri koparır ve köprüyü durdurur."""
        if not self._calisiyor:
            return
        for istemci in list(self._istemciler.values()):
            try:
                await istemci.baglantiyi_kes()
            except Exception as exc:  # noqa: BLE001
                log.debug("Istemci koparma: %s", exc)
        self._calisiyor = False
        audit_yaz(
            "ios.bridge.stopped",
            modul=self.ad,
            detay={"engine": self._motor, "devices": len(self._istemciler)},
        )
        log.info("iOS kopru durduruldu (motor=%s)", self._motor)

    async def durum(self) -> dict[str, Any]:
        """Köprü durum özeti."""
        bagli = [
            cid
            for cid, istemci in self._istemciler.items()
            if istemci.bagli_mi
        ]
        return {
            "module": self.ad,
            "engine": self._motor,
            "running": self._calisiyor,
            "dry_run": self.dry_run,
            "device_count": len(self._istemciler),
            "connected": bagli,
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ kayıt

    def istemci_ekle(self, istemci: IosIstemci) -> IosIstemci:
        """Mevcut IosIstemci'yi köprüye kaydeder."""
        if not isinstance(istemci, IosIstemci):
            raise MobileBridgeError(
                "istemci IosIstemci olmali",
                kod="MOB_0040",
                modul=self.ad,
            )
        cid = str(istemci.cihaz.cihaz_id or "").strip()
        if not cid:
            raise MobileBridgeError(
                "cihaz_id zorunlu",
                kod="MOB_0041",
                modul=self.ad,
            )
        self._istemciler[cid] = istemci
        log.debug("Istemci kaydedildi: %s", cid[:12])
        return istemci

    def istemci_olustur(
        self,
        *,
        cihaz_id: Optional[str] = None,
        ad: str = "iPhone",
        dry_run: Optional[bool] = None,
        zorla_sahte: Optional[bool] = None,
        kaydet: bool = True,
    ) -> IosIstemci:
        """Yeni IosIstemci üretir ve varsayılan olarak kaydeder."""
        istemci = ios_istemci_olustur(
            dry_run=self.dry_run if dry_run is None else bool(dry_run),
            zorla_sahte=self.zorla_sahte
            if zorla_sahte is None
            else bool(zorla_sahte),
            cihaz_id=cihaz_id,
            ad=ad,
            ayarlar=self.ayarlar,
            ws_sunucu=self.ws_sunucu,
        )
        if kaydet:
            self.istemci_ekle(istemci)
        return istemci

    def istemci_al(self, cihaz_id: str) -> IosIstemci:
        """Kayıtlı istemciyi döner; yoksa hata."""
        cid = str(cihaz_id or "").strip()
        if not cid:
            raise MobileBridgeError(
                "cihaz_id zorunlu",
                kod="MOB_0041",
                modul=self.ad,
            )
        istemci = self._istemciler.get(cid)
        if istemci is None:
            raise MobileBridgeError(
                f"iOS istemci bulunamadi: {cid}",
                kod="MOB_0042",
                modul=self.ad,
                detay={"device_id": cid},
            )
        return istemci

    def istemci_var_mi(self, cihaz_id: str) -> bool:
        return str(cihaz_id or "").strip() in self._istemciler

    def istemci_kaldir(self, cihaz_id: str) -> bool:
        """Kayıttan çıkarır (bağlantıyı kesmez)."""
        return self._istemciler.pop(str(cihaz_id or "").strip(), None) is not None

    async def cihaz_bagla(
        self,
        cihaz_id: Optional[str] = None,
        *,
        host: Optional[str] = None,
        token: Optional[str] = None,
        ad: str = "iPhone",
        olustur: bool = True,
    ) -> IosIstemci:
        """
        İstemciyi bağlar; yoksa dry_run dostu yeni istemci oluşturur.

        Network CihazYoneticisi varsa çevrimiçi kaydı günceller.
        """
        self._calisiyor_gerekli()
        cid = str(cihaz_id or "").strip()
        if cid and self.istemci_var_mi(cid):
            istemci = self.istemci_al(cid)
        elif olustur:
            istemci = self.istemci_olustur(cihaz_id=cid or None, ad=ad)
            cid = istemci.cihaz.cihaz_id
        else:
            raise MobileBridgeError(
                f"iOS istemci bulunamadi: {cid or '?'}",
                kod="MOB_0042",
                modul=self.ad,
            )

        if not istemci.bagli_mi:
            await istemci.baglan(
                host or self.varsayilan_host,
                token or self.varsayilan_token,
            )
        self._cihaz_kayit_guncelle(istemci)
        return istemci

    async def cihaz_kopar(self, cihaz_id: str) -> None:
        """İstemci bağlantısını keser; kayıt kalır."""
        self._calisiyor_gerekli()
        istemci = self.istemci_al(cihaz_id)
        await istemci.baglantiyi_kes()
        self._cihaz_kayit_guncelle(istemci)

    # ------------------------------------------------------------------ MobilKopru

    async def telefonumu_bul(self, cihaz_id: str) -> dict[str, Any]:
        """Telefonda ses / titreşim ile bulma sinyali gönderir."""
        self._ozellik_gerekli("find_phone", "mobile.features.find_phone")
        yanit = await self.komut_gonder(
            cihaz_id,
            MobilKomut.FIND_PHONE,
            args={"vibrate": True, "sound": True},
        )
        return self._yanit_dict(yanit)

    async def pil_durumu(self, cihaz_id: str) -> dict[str, Any]:
        """Pil yüzdesi ve şarj durumunu döner."""
        self._ozellik_gerekli("battery_status", "mobile.features.battery_status")
        yanit = await self.komut_gonder(cihaz_id, MobilKomut.BATTERY_STATUS)
        # Cihaz yöneticisi pil alanını senkron tut
        if yanit.basarili_mi and yanit.veri:
            self._pil_kayit_guncelle(cihaz_id, yanit.veri)
        return self._yanit_dict(yanit)

    async def bildirim_gonder(
        self,
        cihaz_id: str,
        baslik: str,
        govde: str,
        veri: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Telefona bildirim gönderir; isteğe bağlı sync.BildirimKopru kuyruğu."""
        self._ozellik_gerekli("notifications", "mobile.features.notifications")
        args: dict[str, Any] = {
            "title": str(baslik or "WhiteCore"),
            "body": str(govde or ""),
        }
        if veri:
            args["data"] = dict(veri)

        # Sync bildirim köprüsü varsa önce kuyruğa yaz (host tarafı kayıt)
        if self.bildirim_kopru is not None and getattr(
            self.bildirim_kopru, "calisiyor", False
        ):
            try:
                await self.bildirim_kopru.ilet(
                    cihaz_id, args["title"], args["body"], veri=veri
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("BildirimKopru.ilet atlandi: %s", exc)

        yanit = await self.komut_gonder(
            cihaz_id, MobilKomut.SEND_NOTIFICATION, args=args
        )
        return self._yanit_dict(yanit)

    async def baglanti_durumu(self, cihaz_id: str) -> BaglantiDurumu:
        """Cihazın anlık bağlantı durumunu döner."""
        self._calisiyor_gerekli()
        cid = str(cihaz_id or "").strip()
        if self.istemci_var_mi(cid):
            return self.istemci_al(cid).cihaz.durum
        if self.cihaz_yoneticisi is not None:
            try:
                return self.cihaz_yoneticisi.al(cid).durum
            except Exception:  # noqa: BLE001
                pass
        raise MobileBridgeError(
            f"iOS cihaz bulunamadi: {cid}",
            kod="MOB_0042",
            modul=self.ad,
            detay={"device_id": cid},
        )

    async def bagli_cihazlar(self) -> list[BagliCihaz]:
        """Köprüdeki bilinen iOS cihazları listeler."""
        self._calisiyor_gerekli()
        sonuc: dict[str, BagliCihaz] = {}

        # Önce kayıtlı istemciler (canlı durum)
        for istemci in self._istemciler.values():
            bagli = istemci.cihaz.bagli_cihaza()
            sonuc[bagli.cihaz_id] = bagli

        # Network cihaz yöneticisindeki ios kayıtlarını birleştir
        if self.cihaz_yoneticisi is not None:
            try:
                for c in self.cihaz_yoneticisi.listele(platform="ios"):
                    sonuc.setdefault(c.cihaz_id, c)
            except Exception as exc:  # noqa: BLE001
                log.debug("cihaz_yoneticisi.listele: %s", exc)

        return list(sonuc.values())

    # ------------------------------------------------------------------ komut API

    async def komut_gonder(
        self,
        cihaz_id: str,
        komut: Union[MobilKomut, str, MobilKomutIstegi],
        *,
        args: Optional[dict[str, Any]] = None,
        dogrula: bool = True,
        bagla: bool = True,
    ) -> MobilKomutYaniti:
        """
        PC → telefon komutunu hedef istemciye iletir.

        bagla=True ve istemci kopuksa dry_run token ile otomatik bağlanır.
        """
        self._calisiyor_gerekli()
        cid = str(cihaz_id or "").strip()
        if not cid:
            raise MobileBridgeError(
                "cihaz_id zorunlu",
                kod="MOB_0041",
                modul=self.ad,
            )

        if not self.istemci_var_mi(cid):
            if bagla and (self.dry_run or self.zorla_sahte or self._motor == "memory"):
                await self.cihaz_bagla(cid, olustur=True)
            else:
                raise MobileBridgeError(
                    f"iOS istemci bulunamadi: {cid}",
                    kod="MOB_0042",
                    modul=self.ad,
                    detay={"device_id": cid},
                )

        istemci = self.istemci_al(cid)
        if not istemci.bagli_mi:
            if bagla:
                await istemci.baglan(self.varsayilan_host, self.varsayilan_token)
                self._cihaz_kayit_guncelle(istemci)
            else:
                raise MobileBridgeError(
                    "iOS istemci bagli degil; once cihaz_bagla() cagirin",
                    kod="MOB_0043",
                    modul=self.ad,
                    detay={"device_id": cid},
                )

        yanit = await istemci.komut_al(komut, args=args, dogrula=dogrula)
        self._cihaz_kayit_guncelle(istemci)

        audit_yaz(
            "ios.bridge.command",
            modul=self.ad,
            detay={
                "command": yanit.komut.value,
                "status": yanit.durum.value,
                "device_id": cid,
                "engine": self._motor,
            },
        )
        await olay_yolu.publish(
            OLAY_MOBIL_KOMUT,
            {
                "command": yanit.komut.value,
                "direction": "pc_to_phone",
                "status": yanit.durum.value,
                "device_id": cid,
                "request_id": yanit.istek_id,
                "bridge": True,
            },
            kaynak=self.ad,
        )
        return yanit

    def phone_komut_cek(self, cihaz_id: str) -> list[MobilKomutIstegi]:
        """Telefon → PC kuyruğunu alıp temizler (test / üst katman)."""
        return self.istemci_al(cihaz_id).pc_komut_cek()

    # ------------------------------------------------------------------ iç yardımcılar

    def _calisiyor_gerekli(self) -> None:
        if not self._calisiyor:
            raise MobileBridgeError(
                "iOS kopru calismiyor; once baslat() cagirin",
                kod="MOB_0044",
                modul=self.ad,
            )

    def _ozellik_gerekli(self, ozellik: str, ayar_yolu: str) -> None:
        self._calisiyor_gerekli()
        if self.dry_run or self.zorla_sahte:
            return
        if not bool(self.ayarlar.al(ayar_yolu, True)):
            raise MobileBridgeError(
                f"Ozellik kapali: {ozellik}",
                kod="MOB_0045",
                modul=self.ad,
                detay={"feature": ozellik, "config": ayar_yolu},
            )

    def _yanit_dict(self, yanit: MobilKomutYaniti) -> dict[str, Any]:
        veri = yanit.to_dict()
        veri["ok"] = yanit.basarili_mi
        veri["engine"] = self._motor
        veri["dry_run"] = self.dry_run
        if yanit.durum is not KomutDurum.OK and not yanit.basarili_mi:
            # MobilKopru sözleşme: dict döner; hata durumunda da dict
            veri.setdefault("error", yanit.mesaj or yanit.durum.value)
        return veri

    def _cihaz_kayit_guncelle(self, istemci: IosIstemci) -> None:
        """İsteğe bağlı CihazYoneticisi senkronu."""
        yonetici = self.cihaz_yoneticisi
        if yonetici is None:
            return
        cihaz = istemci.cihaz
        try:
            mevcut = None
            try:
                mevcut = yonetici.al(cihaz.cihaz_id)
            except Exception:  # noqa: BLE001
                mevcut = None
            if mevcut is None and hasattr(yonetici, "olustur"):
                yonetici.olustur(
                    cihaz.ad,
                    "ios",
                    durum=cihaz.durum,
                    pil_yuzde=cihaz.pil.yuzde if cihaz.pil else None,
                    token_parmak_izi=cihaz.token_parmak_izi,
                    meta=cihaz.bagli_cihaza().meta,
                    cihaz_id=cihaz.cihaz_id,
                )
            elif hasattr(yonetici, "durum_ayarla"):
                yonetici.durum_ayarla(
                    cihaz.cihaz_id,
                    cihaz.durum,
                    pil_yuzde=cihaz.pil.yuzde if cihaz.pil else None,
                )
            elif hasattr(yonetici, "cihaz_durum_ayarla"):
                yonetici.cihaz_durum_ayarla(cihaz.cihaz_id, cihaz.durum.value)
        except Exception as exc:  # noqa: BLE001
            log.debug("Cihaz kayit guncelleme atlandi: %s", exc)

    def _pil_kayit_guncelle(self, cihaz_id: str, veri: dict[str, Any]) -> None:
        yonetici = self.cihaz_yoneticisi
        if yonetici is None:
            return
        yuzde = veri.get("percent", veri.get("yuzde"))
        if yuzde is None:
            return
        try:
            if hasattr(yonetici, "durum_ayarla"):
                cihaz = yonetici.al(cihaz_id)
                yonetici.durum_ayarla(
                    cihaz_id, cihaz.durum, pil_yuzde=int(yuzde)
                )
            else:
                cihaz = yonetici.al(cihaz_id)
                cihaz.pil_yuzde = int(yuzde)
                cihaz.dokun()
        except Exception as exc:  # noqa: BLE001
            log.debug("Pil kayit guncelleme atlandi: %s", exc)


def ios_kopru_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    network: Optional[Any] = None,
    cihaz_yoneticisi: Optional[Any] = None,
    bildirim_kopru: Optional[Any] = None,
    ws_sunucu: Optional[Any] = None,
) -> IosKopru:
    """Test / demo için hazır IosKopru üretir (henüz başlatılmaz)."""
    return IosKopru(
        ayarlar,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        network=network,
        cihaz_yoneticisi=cihaz_yoneticisi,
        bildirim_kopru=bildirim_kopru,
        ws_sunucu=ws_sunucu,
    )


__all__ = [
    "IosKopru",
    "ios_kopru_olustur",
]

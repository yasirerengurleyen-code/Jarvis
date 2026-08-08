"""
network/yoneticisi.py
--------------------
Network Manager — ağ eşleştirme / keşif / WebSocket orkestrasyonu.

Görev:
- Cihaz, eşleştirme, keşif ve WS alt modüllerini birleştirmek
- Sync modüllerine (sohbet / dosya / bildirim / yedek) kanca sağlamak
- dry_run / sahte modda gerçek ağ olmadan test edilebilmek
- EventBus üzerinden OLAY_AG_BAGLANDI / OLAY_AG_KOPTU yayınlamak

Not: Tam Sync Manager (`sync/yoneticisi.py`) Engine tarafından
`SyncYoneticisi.agdan(network)` ile bağlanır; bu sınıf sync örneklerini
tutar / başlatır (hook), üst orkestrasyon Engine köprüsündedir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import (
    OLAY_AG_BAGLANDI,
    OLAY_AG_KOPTU,
    EventBus,
    olay_yolu,
)
from core.exceptions import NetworkError
from core.logger import audit_yaz, logger_al
from network.device.modeller import BagliCihaz, PlatformTuru
from network.device.yonetici import CihazYoneticisi
from network.discovery.kesif import KesifKaydi, KesifServisi
from network.http.sunucu import TelefonHttpSunucu, lan_ip_al
from network.pairing.arayuzler import EslestirmeOturumu
from network.pairing.servis import EslestirmeServisi
from network.pairing.token import TokenYoneticisi
from network.websocket.protokol import WsMesaj
from network.websocket.sunucu import WsOturum, WsSunucu
from sync.chat.senkron import SohbetSenkron
from sync.cloud.yedek import BulutYedek
from sync.files.paylasim import DosyaPaylasim
from sync.notifications.bildirim import BildirimKopru

log = logger_al("network.yoneticisi")

PlatformGirdi = Union[PlatformTuru, str]
MesajYuku = Union[WsMesaj, dict[str, Any], str, bytes]


def _platform_coz(deger: PlatformGirdi) -> PlatformTuru:
    if isinstance(deger, PlatformTuru):
        return deger
    try:
        return PlatformTuru(str(deger).lower().strip())
    except ValueError as hata:
        raise NetworkError(
            f"Bilinmeyen platform: {deger!r}",
            kod="NET_0002",
            modul="network",
        ) from hata


class NetworkYoneticisi(ModulTabani):
    """
    J.A.R.V.I.S. ağ yöneticisi (host tarafı facade).

    Alt bileşenler:
      cihazlar → eşleştirme → keşif → WebSocket → (opsiyonel) sync*
    """

    ad = "network"
    surum = "0.1.0"
    aciklama = "Network Manager — eşleştirme / keşif / WS / sync kancaları"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        cihazlar: Optional[CihazYoneticisi] = None,
        tokenlar: Optional[TokenYoneticisi] = None,
        eslestirme: Optional[EslestirmeServisi] = None,
        kesif: Optional[KesifServisi] = None,
        ws: Optional[WsSunucu] = None,
        sohbet: Optional[SohbetSenkron] = None,
        dosya: Optional[DosyaPaylasim] = None,
        bildirim: Optional[BildirimKopru] = None,
        yedek: Optional[BulutYedek] = None,
        sync_olustur: bool = True,
        kayit_yolu: Optional[Path] = None,
        sync_depo_kok: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(self.ayarlar.al("network.enabled", True))
        self.host = str(self.ayarlar.al("network.host", "0.0.0.0"))
        self.http_port = int(self.ayarlar.al("network.http_port", 8741))
        self.websocket_port = int(self.ayarlar.al("network.websocket_port", 8742))

        # --- ağ çekirdeği ---
        self.cihazlar = cihazlar or CihazYoneticisi(
            self.ayarlar,
            self.bus,
            kayit_yolu=kayit_yolu,
        )
        self.tokenlar = tokenlar or TokenYoneticisi(self.ayarlar)
        self.eslestirme = eslestirme or EslestirmeServisi(
            self.cihazlar,
            self.tokenlar,
            ayarlar=self.ayarlar,
        )
        self.kesif = kesif or KesifServisi(
            self.ayarlar,
            dry_run=self.dry_run,
            zorla_sahte=self.zorla_sahte,
        )
        self.ws = ws or WsSunucu(
            self.ayarlar,
            dry_run=self.dry_run,
            zorla_sahte=self.zorla_sahte,
            token_dogrulayici=self._ws_token_dogrula,
            asistan_adi=str(self.ayarlar.al("assistant.name", "J.A.R.V.I.S.")),
        )
        # Enjekte edilen WsSunucu'da doğrulayıcı yoksa bağla
        if self.ws.token_dogrulayici is None:
            self.ws.token_dogrulayici = self._ws_token_dogrula

        # Telefon PWA paneli (HTTP) — live modda başlar
        self.http: Optional[TelefonHttpSunucu] = None

        # --- sync kancaları (SyncYoneticisi gelene kadar burada yaşar) ---
        kok = Path(sync_depo_kok) if sync_depo_kok else None
        self.sohbet = sohbet
        self.dosya = dosya
        self.bildirim = bildirim
        self.yedek = yedek
        if sync_olustur:
            if self.sohbet is None:
                self.sohbet = SohbetSenkron(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "chat" / "messages.json") if kok else None,
                )
            if self.dosya is None:
                self.dosya = DosyaPaylasim(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "files") if kok else None,
                )
            if self.bildirim is None:
                self.bildirim = BildirimKopru(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "notifications" / "notifications.json")
                    if kok
                    else None,
                )
            if self.yedek is None:
                self.yedek = BulutYedek(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "cloud") if kok else None,
                )

        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — test / bellek ayarları
                pass

        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise NetworkError(
                "Ag config ile kapali (network.enabled=false)",
                kod="NET_0050",
                modul=self.ad,
            )

        self._motor = self._motor_sec()

        await self.cihazlar.baslat()
        await self.kesif.baslat()
        await self.ws.baslat()
        self._telefon_http_baslat()

        for ad, modul in self._sync_modulleri():
            try:
                await modul.baslat()
            except Exception as exc:  # noqa: BLE001 — sync kanca kırılmasın
                log.warning("Sync kanca baslatilamadi (%s): %s", ad, exc)

        self._isaret_basladi()
        audit_yaz(
            "network.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "host": self.host,
                "http_port": self.http_port,
                "websocket_port": self.websocket_port,
                "devices": self.cihazlar.adet(),
                "discovery": self.kesif.motor,
                "websocket": self.ws.motor,
                "phone_http": bool(self.http and self.http.calisiyor),
                "panel_url": (
                    self.http.panel_url if self.http and self.http.calisiyor else ""
                ),
            },
        )
        await self._yayin(
            OLAY_AG_BAGLANDI,
            {
                "engine": self._motor,
                "host": self.host,
                "http_port": self.http_port,
                "websocket_port": self.websocket_port,
            },
        )
        log.info(
            "Network Manager hazir (motor=%s, cihaz=%s, kesif=%s, ws=%s)",
            self._motor,
            self.cihazlar.adet(),
            self.kesif.motor,
            self.ws.motor,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return

        for ad, modul in reversed(self._sync_modulleri()):
            try:
                await modul.durdur()
            except Exception as exc:  # noqa: BLE001
                log.warning("Sync kanca durdurma (%s): %s", ad, exc)

        try:
            await self.ws.durdur()
        except Exception as exc:  # noqa: BLE001
            log.warning("WS durdurma: %s", exc)
        try:
            self._telefon_http_durdur()
        except Exception as exc:  # noqa: BLE001
            log.warning("Telefon HTTP durdurma: %s", exc)
        try:
            await self.kesif.durdur()
        except Exception as exc:  # noqa: BLE001
            log.warning("Kesif durdurma: %s", exc)
        try:
            await self.cihazlar.durdur()
        except Exception as exc:  # noqa: BLE001
            log.warning("Cihaz durdurma: %s", exc)

        self._isaret_durdu()
        audit_yaz(
            "network.stopped",
            modul=self.ad,
            detay={"engine": self._motor},
        )
        await self._yayin(
            OLAY_AG_KOPTU,
            {"engine": self._motor},
        )
        log.info("Network Manager durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ özellikler

    @property
    def motor(self) -> str:
        return self._motor

    def sync_bagla(
        self,
        *,
        sohbet: Optional[SohbetSenkron] = None,
        dosya: Optional[DosyaPaylasim] = None,
        bildirim: Optional[BildirimKopru] = None,
        yedek: Optional[BulutYedek] = None,
    ) -> None:
        """Dışarıdan (veya SyncYoneticisi'nden) sync örneklerini bağlar."""
        if sohbet is not None:
            self.sohbet = sohbet
        if dosya is not None:
            self.dosya = dosya
        if bildirim is not None:
            self.bildirim = bildirim
        if yedek is not None:
            self.yedek = yedek

    # ------------------------------------------------------------------ eşleştirme

    async def eslestirme_baslat(
        self,
        platform: PlatformGirdi = PlatformTuru.IOS,
    ) -> EslestirmeOturumu:
        """QR + 6 haneli kod oturumu açar."""
        self._calisiyor_mi()
        return await self.eslestirme.oturum_baslat(_platform_coz(platform))

    async def kod_ile_eslestir(
        self,
        kod: str,
        cihaz_adi: str,
        platform: PlatformGirdi = PlatformTuru.IOS,
    ) -> BagliCihaz:
        """6 haneli kod ile cihaz kaydı oluşturur."""
        self._calisiyor_mi()
        return await self.eslestirme.kod_ile_eslestir(
            kod,
            cihaz_adi,
            _platform_coz(platform),
        )

    async def qr_ile_eslestir(
        self,
        qr_payload: str,
        cihaz_adi: str,
        platform: PlatformGirdi = PlatformTuru.IOS,
    ) -> BagliCihaz:
        """QR yükü ile cihaz kaydı oluşturur."""
        self._calisiyor_mi()
        return await self.eslestirme.qr_ile_eslestir(
            qr_payload,
            cihaz_adi,
            _platform_coz(platform),
        )

    async def eslestirme_iptal(self, oturum_id: str) -> None:
        self._calisiyor_mi()
        await self.eslestirme.oturum_iptal(oturum_id)

    # ------------------------------------------------------------------ cihaz

    def cihaz_listele(self, *, sadece_cevrimici: bool = False) -> list[BagliCihaz]:
        return self.cihazlar.listele(sadece_cevrimici=sadece_cevrimici)

    def cihaz_al(self, cihaz_id: str) -> BagliCihaz:
        return self.cihazlar.al(cihaz_id)

    def cihaz_kaldir(self, cihaz_id: str) -> bool:
        return self.cihazlar.kaldir(cihaz_id)

    def cihaz_durum_ayarla(self, cihaz_id: str, durum: str) -> BagliCihaz:
        return self.cihazlar.durum_ayarla(cihaz_id, durum)

    # ------------------------------------------------------------------ keşif

    def kesif_ilan(self) -> dict[str, Any]:
        self._calisiyor_mi()
        return self.kesif.ilan_et()

    async def kesif_tara(self, *, bekle_saniye: float = 0.0) -> list[KesifKaydi]:
        self._calisiyor_mi()
        return await self.kesif.tara(bekle_saniye=bekle_saniye)

    def kesif_listele(self) -> list[KesifKaydi]:
        return self.kesif.listele()

    # ------------------------------------------------------------------ websocket

    def ws_oturum_ac(
        self,
        *,
        uzak_adres: str = "memory",
        meta: Optional[dict[str, Any]] = None,
    ) -> WsOturum:
        """Bellek içi / test WS oturumu (dry_run dostu)."""
        self._calisiyor_mi()
        return self.ws.oturum_ac(uzak_adres=uzak_adres, meta=meta)

    def ws_mesaj_isle(self, oturum_id: str, ham: MesajYuku) -> list[WsMesaj]:
        self._calisiyor_mi()
        return self.ws.mesaj_isle(oturum_id, ham)

    def ws_yayinla(self, mesaj: MesajYuku, *, sadece_kimlikli: bool = True) -> int:
        self._calisiyor_mi()
        return self.ws.yayinla(mesaj, sadece_kimlikli=sadece_kimlikli)

    # ------------------------------------------------------------------ özet

    def ozet(self) -> dict[str, Any]:
        sync_ozet: dict[str, Any] = {}
        for ad, modul in self._sync_modulleri():
            try:
                sync_ozet[ad] = modul.ozet()
            except Exception as exc:  # noqa: BLE001
                sync_ozet[ad] = {"error": str(exc)}

        http_ozet: dict[str, Any] = {}
        if self.http is not None:
            try:
                http_ozet = self.http.ozet()
            except Exception as exc:  # noqa: BLE001
                http_ozet = {"error": str(exc)}

        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "host": self.host,
            "http_port": self.http_port,
            "websocket_port": self.websocket_port,
            "lan_ip": lan_ip_al(),
            "panel_url": (
                self.http.panel_url if self.http and self.http.calisiyor else ""
            ),
            "devices": self.cihazlar.ozet(),
            "pairing_sessions": self.eslestirme.aktif_oturum_sayisi(),
            "discovery": self.kesif.ozet(),
            "websocket": self.ws.ozet(),
            "phone_http": http_ozet,
            "sync": sync_ozet,
        }

    # ------------------------------------------------------------------ iç

    def _telefon_http_baslat(self) -> None:
        """Telefon PWA paneli — dry_run/sahte'de port kapma."""
        if self.dry_run or self.zorla_sahte:
            return
        if self.http is not None and self.http.calisiyor:
            return
        try:
            self.http = TelefonHttpSunucu(
                host=self.host if self.host != "127.0.0.1" else "0.0.0.0",
                port=self.http_port,
                ws_port=self.websocket_port,
                pair_handler=self._http_pair,
                status_handler=self._http_status,
            )
            self.http.baslat()
        except Exception as exc:  # noqa: BLE001
            log.warning("Telefon HTTP paneli baslatilamadi: %s", exc)
            self.http = None

    def _telefon_http_durdur(self) -> None:
        if self.http is not None:
            self.http.durdur()
        self.http = None

    def _http_pair(self, kod: str, ad: str) -> dict[str, Any]:
        """HTTP thread → senkron eşleştirme + WS bilgisi."""
        cihaz, token = self.eslestirme.kod_ile_eslestir_token(
            kod,
            ad,
            PlatformTuru.WEB,
        )
        lan = lan_ip_al()
        return {
            "device_id": cihaz.cihaz_id,
            "device_name": cihaz.ad,
            "token": token,
            "ws_url": f"ws://{lan}:{self.websocket_port}",
            "panel_url": f"http://{lan}:{self.http_port}/",
            "lan_ip": lan,
            "ws_port": self.websocket_port,
        }

    def _http_status(self) -> dict[str, Any]:
        lan = lan_ip_al()
        return {
            "online": self._calisiyor,
            "lan_ip": lan,
            "ws_port": self.websocket_port,
            "http_port": self.http_port,
            "panel_url": f"http://{lan}:{self.http_port}/",
            "devices": self.cihazlar.adet(),
            "pairing_sessions": self.eslestirme.aktif_oturum_sayisi(),
            "assistant": str(self.ayarlar.al("assistant.name", "J.A.R.V.I.S.")),
        }

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "live"

    def _calisiyor_mi(self) -> None:
        if not self._calisiyor:
            raise NetworkError(
                "Network Manager calismiyor; once baslat() cagirin",
                kod="NET_0051",
                modul=self.ad,
            )

    def _sync_modulleri(self) -> list[tuple[str, Any]]:
        adaylar: list[tuple[str, Any]] = [
            ("chat", self.sohbet),
            ("files", self.dosya),
            ("notifications", self.bildirim),
            ("cloud", self.yedek),
        ]
        return [(ad, m) for ad, m in adaylar if m is not None]

    def _ws_token_dogrula(
        self,
        token: str,
        cihaz_id: Optional[str],
    ) -> Optional[str]:
        """
        WS AUTH: ham token ↔ kayıtlı cihaz parmak izi.

        dry_run / sahte: eşleşen cihaz yoksa boş olmayan token kabul edilir.
        """
        temiz = (token or "").strip()
        if not temiz:
            return None

        for cihaz in self.cihazlar.listele():
            iz = cihaz.token_parmak_izi
            if not iz:
                continue
            if not self.tokenlar.dogrula(temiz, iz):
                continue
            if cihaz_id and cihaz.cihaz_id != cihaz_id:
                continue
            return cihaz.cihaz_id

        if self._motor in {"dry_run", "sahte"} or self.ws.motor in {"dry_run", "sahte"}:
            return cihaz_id or ("sahte-" + uuid4().hex[:8])
        return None

    async def _yayin(self, olay: str, veri: dict[str, Any]) -> None:
        try:
            await self.bus.publish(olay, veri, kaynak=self.ad)
        except Exception:  # noqa: BLE001
            log.debug("Ag olay yayinlanamadi: %s", olay)


__all__ = [
    "NetworkYoneticisi",
    "OLAY_AG_BAGLANDI",
    "OLAY_AG_KOPTU",
]

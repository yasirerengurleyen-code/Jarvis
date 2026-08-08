"""
mobile/yoneticisi.py
--------------------
Mobile Manager — iPhone köprü / istemci / Shortcuts orkestrasyonu.

Görev:
- IosKopru + IosShortcuts (+ isteğe bağlı IosIstemci) birleştirmek
- start/stop yaşam döngüsü ve özet API sağlamak
- NetworkYoneticisi ile kanca bağlamak (döngüsel import yok)
- find_phone / pil / bildirim / shortcut facade metotları
- dry_run / sahte modda gerçek iPhone olmadan test edilebilir olmak

Not: Engine `mobile.iphone_bridge` köprüsü `core/engine.py` üzerinden
`engine.mobile` olarak bağlanır; GUI `CihazPaneli.mobile_bagla` ile erişir.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import MobileBridgeError
from core.logger import audit_yaz, logger_al
from mobile.bridge.komutlar import (
    MobilKomut,
    MobilKomutIstegi,
    MobilKomutSozlesmesi,
    MobilKomutYaniti,
)
from mobile.ios.istemci import IosIstemci, ios_istemci_olustur
from mobile.ios.kopru import IosKopru, ios_kopru_olustur
from mobile.ios.shortcuts import IosShortcuts, ios_shortcuts_olustur
from mobile.web.kopru import WebKopru, web_kopru_olustur
from network.device.modeller import BagliCihaz, BaglantiDurumu

log = logger_al("mobile.yoneticisi")

MobilKomutGirdi = Union[MobilKomut, str, MobilKomutIstegi]


class MobilYoneticisi(ModulTabani):
    """
    J.A.R.V.I.S. mobil yöneticisi (host tarafı facade).

    Alt bileşenler:
      kopru (IosKopru) → shortcuts (IosShortcuts) → (opsiyonel) network
    """

    ad = "mobile"
    surum = "0.1.0"
    aciklama = "Mobile Manager — iPhone kopru / istemci / shortcuts"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        kopru: Optional[IosKopru] = None,
        shortcuts: Optional[IosShortcuts] = None,
        sozlesme: Optional[MobilKomutSozlesmesi] = None,
        network: Optional[Any] = None,
        web_kopru: Optional[WebKopru] = None,
        olustur: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(self.ayarlar.al("mobile.enabled", False))
        self.bridge_enabled = bool(self.ayarlar.al("mobile.bridge_enabled", False))
        self.primary_mobile = str(
            self.ayarlar.al("mobile.primary_mobile", "ios") or "ios"
        ).lower()
        self.web_enabled = bool(
            self.ayarlar.al("mobile.platforms.web.enabled", False)
        )

        self.sozlesme = sozlesme or MobilKomutSozlesmesi(self.ayarlar)
        self._network: Any = network
        self.kopru = kopru
        self.shortcuts = shortcuts
        self.web_kopru = web_kopru

        if olustur:
            if self.kopru is None:
                self.kopru = ios_kopru_olustur(
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    ayarlar=self.ayarlar,
                    network=self._network,
                )
                self.kopru.sozlesme = self.sozlesme
            if self.shortcuts is None:
                self.shortcuts = ios_shortcuts_olustur(
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    ayarlar=self.ayarlar,
                    kopru=self.kopru,
                )
                self.shortcuts.sozlesme = self.sozlesme
            elif self.shortcuts.kopru is None:
                self.shortcuts.kopru = self.kopru
            if self.web_kopru is None and self.web_enabled:
                self.web_kopru = web_kopru_olustur(
                    ayarlar=self.ayarlar,
                    network=self._network,
                )

        if self._network is not None:
            self.ag_bagla(self._network)

        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ fabrika

    @classmethod
    def agdan(
        cls,
        network: Any,
        *,
        bus: Optional[EventBus] = None,
        dry_run: Optional[bool] = None,
        zorla_sahte: Optional[bool] = None,
    ) -> MobilYoneticisi:
        """
        NetworkYoneticisi üzerinden MobilYoneticisi üretir.

        dry_run / zorla_sahte network'ten miras alınır (override edilebilir).
        """
        dry = (
            bool(getattr(network, "dry_run", False))
            if dry_run is None
            else bool(dry_run)
        )
        sahte = (
            bool(getattr(network, "zorla_sahte", False))
            if zorla_sahte is None
            else bool(zorla_sahte)
        )
        ayar = getattr(network, "ayarlar", None)
        return cls(
            ayarlar=ayar,
            bus=bus or getattr(network, "bus", None),
            dry_run=dry,
            zorla_sahte=sahte,
            network=network,
            olustur=True,
        )

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — test / bellek ayarları
                pass

        # Config kapalı olsa bile dry_run / sahte ile test edilebilir
        if (
            not self.enabled
            and not self.bridge_enabled
            and not self.dry_run
            and not self.zorla_sahte
        ):
            raise MobileBridgeError(
                "Mobile config ile kapali (mobile.enabled/bridge_enabled=false)",
                kod="MOB_0060",
                modul=self.ad,
            )

        self._motor = self._motor_sec()

        if self.kopru is None:
            raise MobileBridgeError(
                "iOS kopru bagli degil",
                kod="MOB_0062",
                modul=self.ad,
            )

        # Network kancalarını yenile (örnekler değişmiş olabilir)
        if self._network is not None:
            self.ag_bagla(self._network)

        # Shortcuts → kopru bağlantısı
        if self.shortcuts is not None and self.shortcuts.kopru is None:
            self.shortcuts.kopru = self.kopru

        try:
            await self.kopru.baslat()
        except Exception as exc:  # noqa: BLE001
            raise MobileBridgeError(
                f"iOS kopru baslatilamadi: {exc}",
                kod="MOB_0063",
                modul=self.ad,
            ) from exc

        if self.web_enabled:
            if self.web_kopru is None:
                self.web_kopru = web_kopru_olustur(
                    ayarlar=self.ayarlar,
                    network=self._network,
                )
            if self._network is not None:
                self.web_kopru.network_bagla(self._network)
            try:
                await self.web_kopru.baslat()
            except Exception as exc:  # noqa: BLE001
                log.warning("Web telefon koprusu baslatilamadi: %s", exc)

        self._isaret_basladi()
        audit_yaz(
            "mobile.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "primary": self.primary_mobile,
                "bridge_engine": getattr(self.kopru, "motor", None),
                "shortcuts": self.shortcuts is not None,
                "network_bound": self._network is not None,
                "web_enabled": self.web_enabled,
                "panel_url": (
                    self.web_kopru.panel.ozet().panel_url
                    if self.web_kopru is not None
                    else ""
                ),
            },
        )
        log.info(
            "Mobile Manager hazir (motor=%s, kopru=%s, primary=%s, web=%s)",
            self._motor,
            getattr(self.kopru, "motor", "?"),
            self.primary_mobile,
            self.web_enabled,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return

        if self.web_kopru is not None:
            try:
                await self.web_kopru.durdur()
            except Exception as exc:  # noqa: BLE001
                log.warning("Web telefon koprusu durdurma: %s", exc)

        if self.kopru is not None:
            try:
                await self.kopru.durdur()
            except Exception as exc:  # noqa: BLE001
                log.warning("iOS kopru durdurma: %s", exc)

        self._isaret_durdu()
        audit_yaz(
            "mobile.stopped",
            modul=self.ad,
            detay={"engine": self._motor},
        )
        log.info("Mobile Manager durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ özellikler

    @property
    def motor(self) -> str:
        return self._motor

    def ag_bagla(self, network: Any) -> None:
        """
        NetworkYoneticisi kancalarını IosKopru'ya bağlar.

        Döngüsel import yok: duck-typing (cihazlar / bildirim / ws).
        """
        self._network = network
        if self.web_kopru is not None:
            self.web_kopru.network_bagla(network)
        if self.kopru is None:
            return
        self.kopru.network = network
        if getattr(self.kopru, "cihaz_yoneticisi", None) is None:
            self.kopru.cihaz_yoneticisi = getattr(network, "cihazlar", None)
        if getattr(self.kopru, "bildirim_kopru", None) is None:
            self.kopru.bildirim_kopru = getattr(network, "bildirim", None)
        if getattr(self.kopru, "ws_sunucu", None) is None:
            self.kopru.ws_sunucu = getattr(network, "ws", None)
        log.debug("Mobile kancalari Network Manager'a baglandi")

    def modul_bagla(
        self,
        *,
        kopru: Optional[IosKopru] = None,
        shortcuts: Optional[IosShortcuts] = None,
        sozlesme: Optional[MobilKomutSozlesmesi] = None,
    ) -> None:
        """Dışarıdan alt örnekleri bağlar / değiştirir."""
        if sozlesme is not None:
            self.sozlesme = sozlesme
        if kopru is not None:
            self.kopru = kopru
            if self.sozlesme is not None:
                self.kopru.sozlesme = self.sozlesme
        if shortcuts is not None:
            self.shortcuts = shortcuts
            if self.kopru is not None and self.shortcuts.kopru is None:
                self.shortcuts.kopru = self.kopru
            if self.sozlesme is not None:
                self.shortcuts.sozlesme = self.sozlesme
        if self._network is not None:
            self.ag_bagla(self._network)

    # ------------------------------------------------------------------ cihaz / istemci

    def istemci_olustur(
        self,
        *,
        cihaz_id: Optional[str] = None,
        ad: str = "iPhone",
        kaydet: bool = True,
    ) -> IosIstemci:
        """Yeni IosIstemci üretir; varsayılan olarak köprüye kaydeder."""
        self._kopru_gerekli()
        return self.kopru.istemci_olustur(
            cihaz_id=cihaz_id,
            ad=ad,
            kaydet=kaydet,
        )

    async def cihaz_bagla(
        self,
        cihaz_id: Optional[str] = None,
        *,
        host: Optional[str] = None,
        token: Optional[str] = None,
        ad: str = "iPhone",
        olustur: bool = True,
    ) -> IosIstemci:
        """İstemciyi bağlar (dry_run dostu otomatik oluşturma)."""
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.cihaz_bagla(
            cihaz_id,
            host=host,
            token=token,
            ad=ad,
            olustur=olustur,
        )

    async def cihaz_kopar(self, cihaz_id: str) -> None:
        self._calisiyor_mi()
        self._kopru_gerekli()
        await self.kopru.cihaz_kopar(cihaz_id)

    # ------------------------------------------------------------------ MobilKopru facade

    async def telefonumu_bul(self, cihaz_id: str) -> dict[str, Any]:
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.telefonumu_bul(cihaz_id)

    async def pil_durumu(self, cihaz_id: str) -> dict[str, Any]:
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.pil_durumu(cihaz_id)

    async def bildirim_gonder(
        self,
        cihaz_id: str,
        baslik: str,
        govde: str,
        veri: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.bildirim_gonder(
            cihaz_id, baslik, govde, veri=veri
        )

    async def baglanti_durumu(self, cihaz_id: str) -> BaglantiDurumu:
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.baglanti_durumu(cihaz_id)

    async def bagli_cihazlar(self) -> list[BagliCihaz]:
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.bagli_cihazlar()

    async def komut_gonder(
        self,
        cihaz_id: str,
        komut: MobilKomutGirdi,
        *,
        args: Optional[dict[str, Any]] = None,
        dogrula: bool = True,
        bagla: bool = True,
    ) -> MobilKomutYaniti:
        self._calisiyor_mi()
        self._kopru_gerekli()
        return await self.kopru.komut_gonder(
            cihaz_id,
            komut,
            args=args,
            dogrula=dogrula,
            bagla=bagla,
        )

    # ------------------------------------------------------------------ Shortcuts facade

    def shortcut_katalog(self) -> list[dict[str, Any]]:
        self._shortcuts_gerekli()
        return self.shortcuts.katalog()

    def shortcut_url(
        self,
        aksiyon: str,
        *,
        cihaz_id: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> str:
        """Companion whitecore:// URL üretir."""
        self._shortcuts_gerekli()
        return self.shortcuts.companion_url(
            aksiyon,
            cihaz_id=cihaz_id,
            args=args,
            token=token,
        )

    async def shortcut_isle(
        self,
        girdi: Any,
        *,
        dogrula: bool = True,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """URL / ShortcutYuk / istek işler (köprüye iletebilir)."""
        self._calisiyor_mi()
        self._shortcuts_gerekli()
        return await self.shortcuts.isle(
            girdi, dogrula=dogrula, cihaz_id=cihaz_id
        )

    # ------------------------------------------------------------------ özet

    def ozet(self) -> dict[str, Any]:
        kopru_ozet: dict[str, Any] = {}
        if self.kopru is not None:
            try:
                kopru_ozet = {
                    "engine": self.kopru.motor,
                    "running": self.kopru.calisiyor,
                    "devices": len(getattr(self.kopru, "_istemciler", {})),
                }
            except Exception as exc:  # noqa: BLE001
                kopru_ozet = {"error": str(exc)}

        shortcuts_ozet: dict[str, Any] = {}
        if self.shortcuts is not None:
            try:
                shortcuts_ozet = self.shortcuts.durum()
            except Exception as exc:  # noqa: BLE001
                shortcuts_ozet = {"error": str(exc)}

        web_ozet: dict[str, Any] = {}
        if self.web_kopru is not None:
            try:
                web_ozet = self.web_kopru.ozet()
            except Exception as exc:  # noqa: BLE001
                web_ozet = {"error": str(exc)}

        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "bridge_enabled": self.bridge_enabled,
            "dry_run": self.dry_run,
            "primary_mobile": self.primary_mobile,
            "web_enabled": self.web_enabled,
            "network_bound": self._network is not None,
            "bridge": kopru_ozet,
            "shortcuts": shortcuts_ozet,
            "web": web_ozet,
            "panel_url": (web_ozet.get("panel") or {}).get("panel_url", ""),
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._network is not None:
            return "memory"
        return "live"

    def _calisiyor_mi(self) -> None:
        if not self._calisiyor:
            raise MobileBridgeError(
                "Mobile Manager calismiyor; once baslat() cagirin",
                kod="MOB_0061",
                modul=self.ad,
            )

    def _kopru_gerekli(self) -> IosKopru:
        if self.kopru is None:
            raise MobileBridgeError(
                "iOS kopru bagli degil",
                kod="MOB_0062",
                modul=self.ad,
            )
        return self.kopru

    def _shortcuts_gerekli(self) -> IosShortcuts:
        if self.shortcuts is None:
            raise MobileBridgeError(
                "iOS shortcuts bagli degil",
                kod="MOB_0064",
                modul=self.ad,
            )
        return self.shortcuts


def mobil_yoneticisi_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    network: Optional[Any] = None,
) -> MobilYoneticisi:
    """Test / demo için hazır MobilYoneticisi üretir (henüz başlatılmaz)."""
    if network is not None:
        return MobilYoneticisi.agdan(
            network,
            bus=bus,
            dry_run=dry_run,
            zorla_sahte=zorla_sahte,
        )
    return MobilYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        olustur=True,
    )


__all__ = [
    "MobilYoneticisi",
    "mobil_yoneticisi_olustur",
]

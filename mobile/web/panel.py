"""
mobile/web/panel.py
-------------------
Telefon web paneli facade — Network HTTP sunucusuna bakar.

API key istemez; eşleştirme kodu / QR ile bağlanır.
"""

from __future__ import annotations

from typing import Any, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.logger import logger_al
from mobile.web.modeller import TelefonPanelOzeti
from network.http.sunucu import lan_ip_al

log = logger_al("mobile.web.panel")


class TelefonPaneli:
    """Telefon PWA paneli durumu (HTTP NetworkYoneticisi'nde yaşar)."""

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        network: Optional[Any] = None,
    ) -> None:
        self.ayarlar = ayarlar or global_ayarlar
        self.network = network
        self.http_port = int(self.ayarlar.al("network.http_port", 8741))
        self.ws_port = int(self.ayarlar.al("network.websocket_port", 8742))
        self._aktif = False

    def network_bagla(self, network: Any) -> None:
        self.network = network

    async def baslat(self) -> None:
        """Network HTTP zaten ayaktaysa panel aktif sayılır."""
        http = getattr(self.network, "http", None) if self.network else None
        if http is not None and getattr(http, "calisiyor", False):
            self._aktif = True
            log.info("Telefon paneli hazir: %s", self.ozet().panel_url)
            return
        # Network dry_run ise HTTP yoktur — panel pasif ama hata değil
        self._aktif = False
        log.info(
            "Telefon paneli bekliyor (HTTP yok — live network gerekir)"
        )

    async def durdur(self) -> None:
        self._aktif = False

    def ozet(self) -> TelefonPanelOzeti:
        lan = lan_ip_al()
        http = getattr(self.network, "http", None) if self.network else None
        http_ok = bool(http and getattr(http, "calisiyor", False))
        oturum = 0
        if self.network and getattr(self.network, "ws", None):
            try:
                oturum = int(self.network.ws.ozet().get("authenticated_count", 0))
            except Exception:
                oturum = 0
        return TelefonPanelOzeti(
            online=http_ok or self._aktif,
            panel_url=f"http://{lan}:{self.http_port}/" if http_ok else "",
            lan_ip=lan,
            http_port=self.http_port,
            ws_port=self.ws_port,
            oturum_sayisi=oturum,
            ekstra={"engine": "phone_web", "http_bound": http_ok},
        )


__all__ = ["TelefonPaneli"]

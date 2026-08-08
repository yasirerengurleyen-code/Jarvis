"""
mobile/web/kopru.py
-------------------
Telefon web köprüsü — Network + panel facade.
"""

from __future__ import annotations

from typing import Any, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.logger import logger_al
from mobile.web.istemci import WebIstemci, web_istemci_olustur
from mobile.web.panel import TelefonPaneli

log = logger_al("mobile.web.kopru")


class WebKopru:
    """PWA telefon istemcileri için host köprüsü."""

    ad = "mobile.web.kopru"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        network: Optional[Any] = None,
        panel: Optional[TelefonPaneli] = None,
    ) -> None:
        self.ayarlar = ayarlar or global_ayarlar
        self.network = network
        self.panel = panel or TelefonPaneli(ayarlar=self.ayarlar, network=network)
        self._istemciler: dict[str, WebIstemci] = {}
        self._calisiyor = False

    @property
    def calisiyor(self) -> bool:
        return self._calisiyor

    def network_bagla(self, network: Any) -> None:
        self.network = network
        self.panel.network_bagla(network)

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if self.network is not None:
            self.panel.network_bagla(self.network)
        await self.panel.baslat()
        self._calisiyor = True
        log.info("Web telefon koprusu hazir")

    async def durdur(self) -> None:
        await self.panel.durdur()
        self._istemciler.clear()
        self._calisiyor = False

    def istemci_olustur(self, *, ad: str = "iPhone", kaydet: bool = True) -> WebIstemci:
        istemci = web_istemci_olustur(ad=ad)
        ozet = self.panel.ozet()
        istemci.panel_url = ozet.panel_url
        istemci.ws_url = f"ws://{ozet.lan_ip}:{ozet.ws_port}"
        if kaydet:
            self._istemciler[istemci.cihaz_id] = istemci
        return istemci

    def ozet(self) -> dict[str, Any]:
        return {
            "module": self.ad,
            "running": self._calisiyor,
            "devices": len(self._istemciler),
            "panel": self.panel.ozet().to_dict(),
        }


def web_kopru_olustur(
    *,
    ayarlar: Optional[Ayarlar] = None,
    network: Optional[Any] = None,
) -> WebKopru:
    return WebKopru(ayarlar=ayarlar, network=network)


__all__ = ["WebKopru", "web_kopru_olustur"]

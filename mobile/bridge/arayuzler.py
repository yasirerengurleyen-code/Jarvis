"""
mobile/bridge/arayuzler.py
--------------------------
Windows ↔ mobil istemci köprü sözleşmeleri (iskelet).

Öncelik: iOS / iPadOS. Web aynı sözleşmeyi kullanır.
Android aynı arayüzleri uygulayarak sonradan eklenebilir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from network.device.modeller import BagliCihaz, BaglantiDurumu


class MobilKopru(ABC):
    """PC → telefon ve telefon → PC komut köprüsü."""

    @abstractmethod
    async def telefonumu_bul(self, cihaz_id: str) -> dict[str, Any]:
        """Telefonda ses / titreşim ile bulma sinyali gönderir."""

    @abstractmethod
    async def pil_durumu(self, cihaz_id: str) -> dict[str, Any]:
        """Pil yüzdesi ve şarj durumunu döner."""

    @abstractmethod
    async def bildirim_gonder(
        self,
        cihaz_id: str,
        baslik: str,
        govde: str,
        veri: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Telefona bildirim gönderir."""

    @abstractmethod
    async def baglanti_durumu(self, cihaz_id: str) -> BaglantiDurumu:
        """Cihazın anlık bağlantı durumunu döner."""

    @abstractmethod
    async def bagli_cihazlar(self) -> list[BagliCihaz]:
        """Tüm bilinen cihazları listeler."""


class MobilKopruIskelet(MobilKopru):
    """v0.1 yer tutucu uygulama."""

    async def telefonumu_bul(self, cihaz_id: str) -> dict[str, Any]:
        raise NotImplementedError("Mobil köprü iskelet — sonraki sürüm")

    async def pil_durumu(self, cihaz_id: str) -> dict[str, Any]:
        raise NotImplementedError("Mobil köprü iskelet — sonraki sürüm")

    async def bildirim_gonder(
        self,
        cihaz_id: str,
        baslik: str,
        govde: str,
        veri: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("Mobil köprü iskelet — sonraki sürüm")

    async def baglanti_durumu(self, cihaz_id: str) -> BaglantiDurumu:
        raise NotImplementedError("Mobil köprü iskelet — sonraki sürüm")

    async def bagli_cihazlar(self) -> list[BagliCihaz]:
        raise NotImplementedError("Mobil köprü iskelet — sonraki sürüm")

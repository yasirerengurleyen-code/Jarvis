"""
sync/arayuzler.py
-----------------
Sohbet, dosya ve bildirim senkron arayüzleri (iskelet).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class SohbetSenkronu(ABC):
    """Yapay zekâ sohbet geçmişi senkronizasyonu."""

    @abstractmethod
    async def gonder(self, cihaz_id: str, mesajlar: list[dict[str, Any]]) -> None:
        """Sohbet kayıtlarını hedef cihaza / depoya gönderir."""

    @abstractmethod
    async def cek(self, cihaz_id: str, son_sonra: Optional[str] = None) -> list[dict[str, Any]]:
        """Eksik sohbet kayıtlarını çeker."""


class DosyaPaylasimi(ABC):
    """Cihazlar arası dosya paylaşımı."""

    @abstractmethod
    async def gonder(self, cihaz_id: str, yerel_yol: str, uzak_ad: Optional[str] = None) -> str:
        """Dosya gönderir; transfer kimliği döner."""

    @abstractmethod
    async def al(self, transfer_id: str, hedef_yol: str) -> str:
        """Dosyayı indirir; kaydedilen yolu döner."""


class BildirimSenkronu(ABC):
    """Çapraz cihaz bildirim köprüsü."""

    @abstractmethod
    async def ilet(self, cihaz_id: str, baslik: str, govde: str) -> None:
        """Bildirimi hedef cihaza iletir."""


class SohbetSenkronuIskelet(SohbetSenkronu):
    async def gonder(self, cihaz_id: str, mesajlar: list[dict[str, Any]]) -> None:
        raise NotImplementedError("Sohbet senkronu iskelet")

    async def cek(self, cihaz_id: str, son_sonra: Optional[str] = None) -> list[dict[str, Any]]:
        raise NotImplementedError("Sohbet senkronu iskelet")


class DosyaPaylasimiIskelet(DosyaPaylasimi):
    async def gonder(self, cihaz_id: str, yerel_yol: str, uzak_ad: Optional[str] = None) -> str:
        raise NotImplementedError("Dosya paylaşımı iskelet")

    async def al(self, transfer_id: str, hedef_yol: str) -> str:
        raise NotImplementedError("Dosya paylaşımı iskelet")


class BildirimSenkronuIskelet(BildirimSenkronu):
    async def ilet(self, cihaz_id: str, baslik: str, govde: str) -> None:
        raise NotImplementedError("Bildirim senkronu iskelet")

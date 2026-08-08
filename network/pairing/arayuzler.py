"""
network/pairing/arayuzler.py
----------------------------
QR kod ve 6 haneli kod ile eşleştirme arayüzleri (iskelet).

Tam işlevsellik sonraki sürümlerde uygulanacak.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from network.device.modeller import BagliCihaz, PlatformTuru


@dataclass
class EslestirmeOturumu:
    """Aktif bir eşleştirme oturumu."""

    oturum_id: str
    kod: str
    qr_payload: str
    olusturma: str
    son_gecerlilik: str
    kullanildi: bool = False

    @staticmethod
    def zaman_utc() -> str:
        return datetime.now(timezone.utc).isoformat()


class EslestirmeServisi(ABC):
    """
    Cihaz eşleştirme sözleşmesi.

    - 6 haneli kod üretimi
    - QR kod yükü üretimi
    - Kod / QR ile onay
    """

    @abstractmethod
    async def oturum_baslat(self, platform: PlatformTuru) -> EslestirmeOturumu:
        """Yeni QR + kod oturumu başlatır."""

    @abstractmethod
    async def kod_ile_eslestir(
        self,
        kod: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        """6 haneli kod ile cihazı bağlar."""

    @abstractmethod
    async def qr_ile_eslestir(
        self,
        qr_payload: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        """QR içerği ile cihazı bağlar."""

    @abstractmethod
    async def oturum_iptal(self, oturum_id: str) -> None:
        """Bekleyen oturumu iptal eder."""


class EslestirmeServisiIskelet(EslestirmeServisi):
    """v0.1 yer tutucu — NotImplementedError yükseltir."""

    async def oturum_baslat(self, platform: PlatformTuru) -> EslestirmeOturumu:
        raise NotImplementedError("Eşleştirme v0.1'de iskelet; sonraki sürümde uygulanacak")

    async def kod_ile_eslestir(
        self,
        kod: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        raise NotImplementedError("Eşleştirme v0.1'de iskelet; sonraki sürümde uygulanacak")

    async def qr_ile_eslestir(
        self,
        qr_payload: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        raise NotImplementedError("Eşleştirme v0.1'de iskelet; sonraki sürümde uygulanacak")

    async def oturum_iptal(self, oturum_id: str) -> None:
        raise NotImplementedError("Eşleştirme v0.1'de iskelet; sonraki sürümde uygulanacak")

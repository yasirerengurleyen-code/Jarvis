"""
network/device/modeller.py
--------------------------
Bağlı cihaz veri modelleri (iskelet).

Windows host'a bağlanan iPhone / iPad / Web (ve ileride Android)
cihazlarının ortak temsilini tanımlar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class PlatformTuru(str, Enum):
    """Desteklenen / planlanan istemci platformları."""

    WINDOWS = "windows"
    IOS = "ios"
    IPADOS = "ipados"
    WEB = "web"
    ANDROID = "android"  # v1'de etkin değil


class BaglantiDurumu(str, Enum):
    """Cihaz bağlantı durumu."""

    CEVRIMDISI = "offline"
    ESLESME = "pairing"
    CEVRIMICI = "online"
    SENKRON = "syncing"
    HATA = "error"


@dataclass
class BagliCihaz:
    """Tek bir bağlı cihazın durumu."""

    cihaz_id: str
    ad: str
    platform: PlatformTuru
    durum: BaglantiDurumu = BaglantiDurumu.CEVRIMDISI
    pil_yuzde: Optional[int] = None
    son_gorulme: Optional[str] = None
    token_parmak_izi: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def cevrimici_mi(self) -> bool:
        return self.durum in {BaglantiDurumu.CEVRIMICI, BaglantiDurumu.SENKRON}

    def dokun(self) -> None:
        """Son görülme zamanını günceller."""
        self.son_gorulme = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.cihaz_id,
            "name": self.ad,
            "platform": self.platform.value,
            "status": self.durum.value,
            "battery_percent": self.pil_yuzde,
            "last_seen": self.son_gorulme,
            "meta": self.meta,
        }

"""
mobile/web/modeller.py
----------------------
Web / telefon paneli oturum modelleri.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WebOturum:
    """Telefon web istemci oturumu."""

    oturum_id: str
    cihaz_id: str = ""
    cihaz_adi: str = "iPhone"
    token_parmak: str = ""
    bagli: bool = False
    olusturma: str = field(default_factory=_utc)
    son_gorulme: str = field(default_factory=_utc)
    platform: str = "web"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.oturum_id,
            "device_id": self.cihaz_id,
            "device_name": self.cihaz_adi,
            "connected": self.bagli,
            "created": self.olusturma,
            "last_seen": self.son_gorulme,
            "platform": self.platform,
        }


@dataclass
class TelefonPanelOzeti:
    """HTTP panel durum özeti."""

    online: bool = False
    panel_url: str = ""
    lan_ip: str = ""
    http_port: int = 8741
    ws_port: int = 8742
    oturum_sayisi: int = 0
    ekstra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "online": self.online,
            "panel_url": self.panel_url,
            "lan_ip": self.lan_ip,
            "http_port": self.http_port,
            "ws_port": self.ws_port,
            "sessions": self.oturum_sayisi,
            **self.ekstra,
        }


__all__ = ["WebOturum", "TelefonPanelOzeti"]

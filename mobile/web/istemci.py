"""
mobile/web/istemci.py
---------------------
Telefon web istemci modeli (PWA / Safari).

Native app değil — tarayıcı `static/app.js` gerçek istemcidir.
Bu sınıf test / host tarafı temsil içindir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from network.device.modeller import BaglantiDurumu


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WebIstemci:
    """Host tarafında kayıtlı telefon web oturumu."""

    cihaz_id: str = field(default_factory=lambda: uuid4().hex)
    ad: str = "iPhone"
    platform: str = "web"
    durum: BaglantiDurumu = BaglantiDurumu.CEVRIMDISI
    token_parmak: str = ""
    panel_url: str = ""
    ws_url: str = ""
    olusturma: str = field(default_factory=_utc)
    son_gorulme: str = field(default_factory=_utc)

    def baglan(self) -> None:
        self.durum = BaglantiDurumu.CEVRIMICI
        self.son_gorulme = _utc()

    def kop(self) -> None:
        self.durum = BaglantiDurumu.CEVRIMDISI
        self.son_gorulme = _utc()

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.cihaz_id,
            "name": self.ad,
            "platform": self.platform,
            "status": self.durum.value,
            "panel_url": self.panel_url,
            "ws_url": self.ws_url,
            "created": self.olusturma,
            "last_seen": self.son_gorulme,
        }


def web_istemci_olustur(
    *,
    ad: str = "iPhone",
    cihaz_id: Optional[str] = None,
) -> WebIstemci:
    return WebIstemci(
        cihaz_id=cihaz_id or uuid4().hex,
        ad=ad,
    )


__all__ = ["WebIstemci", "web_istemci_olustur"]

"""mobile/web paneli / köprü birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from mobile.web.istemci import web_istemci_olustur
from mobile.web.kopru import web_kopru_olustur
from mobile.web.panel import TelefonPaneli


def test_web_istemci() -> None:
    c = web_istemci_olustur(ad="Safari")
    assert c.ad == "Safari"
    assert c.platform == "web"
    c.baglan()
    assert c.durum.value == "online"
    d = c.to_dict()
    assert d["name"] == "Safari"


def test_panel_ozet() -> None:
    panel = TelefonPaneli()
    o = panel.ozet()
    assert o.http_port == 8741
    assert o.ws_port == 8742
    assert "lan_ip" in o.to_dict() or o.lan_ip


def test_web_kopru() -> None:
    async def _run() -> None:
        kopru = web_kopru_olustur()
        await kopru.baslat()
        assert kopru.calisiyor
        istemci = kopru.istemci_olustur(ad="iPhone Web")
        assert istemci.cihaz_id in kopru._istemciler
        ozet = kopru.ozet()
        assert ozet["module"] == "mobile.web.kopru"
        assert ozet["devices"] == 1
        await kopru.durdur()
        assert not kopru.calisiyor

    asyncio.run(_run())


if __name__ == "__main__":
    test_web_istemci()
    test_panel_ozet()
    test_web_kopru()
    print("OK test_panel")

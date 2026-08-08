"""network/http/sunucu.py — telefon paneli HTTP testleri."""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.events import EventBus
from network.device.modeller import PlatformTuru
from network.device.yonetici import CihazYoneticisi
from network.http.sunucu import TelefonHttpSunucu, lan_ip_al
from network.pairing.servis import EslestirmeServisi
from network.pairing.token import TokenYoneticisi


def _port_bul() -> int:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def test_lan_ip_al() -> None:
    ip = lan_ip_al()
    assert isinstance(ip, str) and ip


def test_status_ve_static() -> None:
    port = _port_bul()
    sunucu = TelefonHttpSunucu(
        host="127.0.0.1",
        port=port,
        ws_port=8742,
        status_handler=lambda: {"assistant": "J.A.R.V.I.S."},
    )
    sunucu.baslat()
    assert sunucu.calisiyor
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as r:
            veri = json.loads(r.read().decode("utf-8"))
        assert veri["online"] is True
        assert veri["ws_port"] == 8742
        assert veri["assistant"] == "J.A.R.V.I.S."

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
            html = r.read().decode("utf-8")
        assert "J.A.R.V.I.S." in html
        assert "Bağlan" in html or "baglan" in html.lower()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js", timeout=3) as r:
            js = r.read().decode("utf-8")
        assert "/api/pair" in js
    finally:
        sunucu.durdur()
    assert not sunucu.calisiyor


def test_pair_api() -> None:
    import asyncio

    async def _hazir() -> tuple[EslestirmeServisi, str]:
        tmp = Path(tempfile.mkdtemp()) / "devices.json"
        cihazlar = CihazYoneticisi(bus=EventBus(ad="test.http.pair"), kayit_yolu=tmp)
        await cihazlar.baslat()
        servis = EslestirmeServisi(cihazlar, TokenYoneticisi())
        oturum = await servis.oturum_baslat(PlatformTuru.WEB)
        return servis, oturum.kod

    servis, kod = asyncio.run(_hazir())
    port = _port_bul()

    def _pair(c: str, ad: str) -> dict:
        cihaz, token = servis.kod_ile_eslestir_token(c, ad, PlatformTuru.WEB)
        return {
            "device_id": cihaz.cihaz_id,
            "token": token,
            "ws_url": "ws://127.0.0.1:8742",
        }

    sunucu = TelefonHttpSunucu(
        host="127.0.0.1",
        port=port,
        pair_handler=_pair,
    )
    sunucu.baslat()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/pair",
            data=json.dumps({"code": kod, "name": "Test Phone"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            veri = json.loads(r.read().decode("utf-8"))
        assert veri["ok"] is True
        assert veri["token"]
        assert veri["device_id"]

        # Tek kullanımlık
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/pair",
            data=json.dumps({"code": kod, "name": "Again"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req2, timeout=3)
            raise AssertionError("ikinci pair basarisiz olmaliydi")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        sunucu.durdur()


if __name__ == "__main__":
    test_lan_ip_al()
    test_status_ve_static()
    test_pair_api()
    print("OK test_telefon_http")

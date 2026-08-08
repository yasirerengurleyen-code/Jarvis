"""sync/notifications/bildirim.py birim testleri (çevrimdışı / dry_run)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import WhiteCoreError
from network.websocket.protokol import MesajTipi, decode_mesaj, encode_mesaj
from sync.notifications.bildirim import (
    BildirimDurumu,
    BildirimKopru,
    bildirim_normalize,
)


def test_bildirim_normalize() -> None:
    b = bildirim_normalize(
        {
            "bildirim_id": "n1",
            "baslik": "Jarvis",
            "govde": "Selam",
            "durum": "queued",
            "cihaz_id": "iphone-1",
            "veri": {"cmd": "ping"},
        }
    )
    assert b["id"] == "n1"
    assert b["title"] == "Jarvis"
    assert b["body"] == "Selam"
    assert b["status"] == BildirimDurumu.KUYRUKTA.value
    assert b["device_id"] == "iphone-1"
    assert b["data"]["cmd"] == "ping"


def test_dry_run_ilet_giden() -> None:
    async def _run() -> None:
        kopru = BildirimKopru(dry_run=True)
        assert kopru.motor == "dry_run"
        await kopru.baslat()
        assert kopru.calisiyor

        await kopru.ilet("iphone-1", "Baslik", "Govde metni", veri={"k": 1})
        giden = kopru.giden_cek("iphone-1")
        assert len(giden) == 1
        assert giden[0]["title"] == "Baslik"
        assert giden[0]["body"] == "Govde metni"
        assert giden[0]["data"]["k"] == 1
        assert giden[0]["status"] == BildirimDurumu.ILETILDI.value
        assert kopru.giden_cek("iphone-1") == []

        durum = kopru.ozet()
        assert durum["engine"] == "dry_run"
        assert durum["count"] == 1
        assert durum["running"] is True

        await kopru.durdur()
        assert not kopru.calisiyor

    asyncio.run(_run())


def test_json_persist() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        depo = tmp / "notifications.json"

        k1 = BildirimKopru(depo_yolu=depo)
        await k1.baslat()
        assert k1.motor == "json"
        await k1.ilet("c1", "Kalici", "Disk")
        await k1.durdur()

        assert depo.is_file()
        ham = json.loads(depo.read_text(encoding="utf-8"))
        assert ham["version"] == 1
        assert len(ham["notifications"]) == 1
        assert ham["notifications"][0]["title"] == "Kalici"

        k2 = BildirimKopru(depo_yolu=depo)
        await k2.baslat()
        assert len(k2.listele()) == 1
        assert k2.listele(cihaz_id="c1")[0]["body"] == "Disk"
        await k2.durdur()

    asyncio.run(_run())


def test_notification_protokol() -> None:
    async def _run() -> None:
        kopru = BildirimKopru(dry_run=True)
        await kopru.baslat()
        await kopru.ilet("c1", "P", "protokol")

        liste = kopru.listele(cihaz_id="c1")
        nid = liste[0]["id"]
        ws = kopru.notification_mesaji(
            bildirim_id=nid, cihaz_id="c1", islem="push"
        )
        assert ws.tip is MesajTipi.NOTIFICATION
        assert ws.yuk["op"] == "push"
        assert ws.yuk["title"] == "P"
        geri = decode_mesaj(encode_mesaj(ws))
        assert geri.tip is MesajTipi.NOTIFICATION

        # uzak push
        k2 = BildirimKopru(dry_run=True)
        await k2.baslat()
        sonuc = k2.notification_isle(
            {
                "op": "push",
                "title": "Uzak",
                "body": "Merhaba",
                "id": "remote1",
            },
            cihaz_id="c2",
        )
        assert sonuc["ok"] is True
        assert sonuc["op"] == "apply"
        assert sonuc["added"] == 1
        assert k2.bildirim_al("remote1")["title"] == "Uzak"
        giden = k2.giden_cek("c2")
        assert len(giden) == 1

        liste2 = k2.notification_isle({"op": "list"}, cihaz_id="c2")
        assert liste2["count"] == 1

        ack = k2.notification_isle(
            {"op": "read", "notification_id": "remote1"}
        )
        assert ack["notification"]["status"] == BildirimDurumu.OKUNDU.value

        await kopru.durdur()
        await k2.durdur()

    asyncio.run(_run())


def test_govde_limiti_ve_baslatmadan_hata() -> None:
    async def _run() -> None:
        kopru = BildirimKopru(dry_run=True, max_govde=20)
        try:
            await kopru.ilet("c1", "T", "x" * 50)
            raise AssertionError("baslatmadan hata bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0032"

        await kopru.baslat()
        try:
            await kopru.ilet("c1", "T", "x" * 50)
            raise AssertionError("govde limiti bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0035"

        try:
            await kopru.ilet("", "T", "ok")
            raise AssertionError("cihaz_id hatasi bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0033"

        try:
            await kopru.ilet("c1", "", "   ")
            raise AssertionError("bos icerik hatasi bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0034"

        await kopru.durdur()

    asyncio.run(_run())


def test_iptal() -> None:
    async def _run() -> None:
        kopru = BildirimKopru(dry_run=True)
        await kopru.baslat()
        await kopru.ilet("c1", "Iptal", "test")
        nid = kopru.listele()[0]["id"]
        assert kopru.ozet()["devices_queued"]["c1"] == 1
        t = kopru.iptal(nid)
        assert t["status"] == BildirimDurumu.IPTAL.value
        assert "c1" not in kopru.ozet()["devices_queued"]
        await kopru.durdur()

    asyncio.run(_run())


def test_bildirim() -> None:
    """Tek giriş noktası — tüm senaryolar."""
    test_bildirim_normalize()
    test_dry_run_ilet_giden()
    test_json_persist()
    test_notification_protokol()
    test_govde_limiti_ve_baslatmadan_hata()
    test_iptal()
    print("OK test_bildirim")


if __name__ == "__main__":
    test_bildirim()

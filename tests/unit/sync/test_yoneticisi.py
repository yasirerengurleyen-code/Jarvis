"""sync/yoneticisi.py birim testleri (dry_run / ağsız)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.events import EventBus
from core.exceptions import WhiteCoreError
from network.websocket.protokol import MesajTipi, mesaj_olustur
from network.yoneticisi import NetworkYoneticisi
from sync.chat.senkron import SohbetSenkron
from sync.yoneticisi import SyncYoneticisi


def _yonetici() -> SyncYoneticisi:
    tmp = Path(tempfile.mkdtemp())
    bus = EventBus(ad="test.sync")
    return SyncYoneticisi(
        bus=bus,
        dry_run=True,
        depo_kok=tmp / "sync",
        olustur=True,
    )


def test_dry_run_baslat_durdur_ozet() -> None:
    async def _run() -> None:
        sync = _yonetici()
        assert sync.motor == "dry_run"
        assert sync.sohbet is not None
        assert sync.dosya is not None
        assert sync.bildirim is not None
        assert sync.yedek is not None

        await sync.baslat()
        assert sync.calisiyor
        assert sync.sohbet.calisiyor
        assert sync.dosya.calisiyor
        assert sync.bildirim.calisiyor
        assert sync.yedek.calisiyor

        ozet = sync.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert "chat" in ozet["modules"]
        assert "files" in ozet["modules"]
        assert "notifications" in ozet["modules"]
        assert "cloud" in ozet["modules"]
        assert ozet["modules"]["chat"]["engine"] == "dry_run"

        await sync.durdur()
        assert not sync.calisiyor
        assert not sync.sohbet.calisiyor

    asyncio.run(_run())


def test_sohbet_ve_bildirim_facade() -> None:
    async def _run() -> None:
        sync = _yonetici()
        await sync.baslat()

        await sync.sohbet_gonder(
            "iphone-1",
            [{"id": "m1", "role": "user", "content": "Merhaba"}],
        )
        giden = sync.sohbet.giden_cek("iphone-1")
        assert len(giden) == 1
        assert giden[0]["content"] == "Merhaba"
        # Yerel depoda görünür (cek imleci son gönderiyi dışlar)
        assert any(m["id"] == "m1" for m in sync.sohbet.listele())
        # Boş imleç sonrası çekim API'si çalışır
        cekilen = await sync.sohbet_cek("iphone-2")
        assert isinstance(cekilen, list)

        await sync.bildirim_ilet("iphone-1", "Test", "Govde")
        bildirimler = sync.bildirim.giden_cek("iphone-1")
        assert len(bildirimler) == 1
        assert bildirimler[0]["title"] == "Test"

        await sync.durdur()

    asyncio.run(_run())


def test_yedek_ve_dosya_facade() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        sync = SyncYoneticisi(dry_run=True, depo_kok=tmp / "sync")
        await sync.baslat()

        yid = await sync.yedekle({"prefs": {"tema": "koyu"}}, etiket="unit")
        assert yid
        ozet = await sync.yedek_yukle(yid)
        assert ozet.to_dict()["backup_id"] == yid
        assert sync.yedek.yedek_al(yid)["status"] == "cloud"

        kaynak = tmp / "hello.txt"
        kaynak.write_text("merhaba", encoding="utf-8")
        tid = await sync.dosya_gonder("dev-1", str(kaynak), "hello.txt")
        assert tid
        hedef = await sync.dosya_al(tid, "")
        assert "hello.txt" in hedef

        await sync.durdur()

    asyncio.run(_run())


def test_protokol_yonlendirme() -> None:
    async def _run() -> None:
        sync = _yonetici()
        await sync.baslat()

        chat_msg = mesaj_olustur(
            MesajTipi.CHAT_SYNC,
            {
                "op": "push",
                "messages": [
                    {
                        "id": "p1",
                        "role": "assistant",
                        "content": "Selam",
                        "timestamp": "2026-08-07T12:00:00+00:00",
                    }
                ],
            },
            cihaz_id="c1",
        )
        sonuc = sync.protokol_isle(chat_msg)
        assert sonuc["ok"] is True
        assert sonuc["op"] == "apply"
        assert sonuc["added"] >= 1

        notif = mesaj_olustur(
            MesajTipi.NOTIFICATION,
            {"op": "push", "title": "Bildirim", "body": "Icerik"},
            cihaz_id="c1",
        )
        nson = sync.protokol_isle(notif)
        assert nson["ok"] is True
        assert nson["op"] == "apply"

        cloud = mesaj_olustur(
            MesajTipi.EVENT,
            {
                "kind": "cloud_backup",
                "op": "list",
            },
            cihaz_id="c1",
        )
        cson = sync.protokol_isle(cloud)
        assert cson["ok"] is True
        assert cson["op"] == "list"

        await sync.durdur()

    asyncio.run(_run())


def test_baslatmadan_api_hata() -> None:
    sync = _yonetici()
    try:
        sync.protokol_isle({"type": "chat_sync", "payload": {"op": "list"}})
        raise AssertionError("WhiteCoreError bekleniyordu")
    except WhiteCoreError as exc:
        assert exc.kod == "SYNC_0061"


def test_ag_bagla_ve_agdan() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        net = NetworkYoneticisi(
            dry_run=True,
            sync_olustur=False,
            kayit_yolu=tmp / "devices.json",
        )
        assert net.sohbet is None

        sync = SyncYoneticisi(dry_run=True, depo_kok=tmp / "sync")
        sync.ag_bagla(net)
        assert net.sohbet is sync.sohbet
        assert net.dosya is sync.dosya
        assert net.bildirim is sync.bildirim
        assert net.yedek is sync.yedek
        assert sync.ozet()["network_bound"] is True

        await sync.baslat()
        await net.baslat()
        assert sync.sohbet.calisiyor
        assert net.sohbet is sync.sohbet
        await net.durdur()
        await sync.durdur()

        # agdan: network'ün kendi sync örneklerini sarar
        net2 = NetworkYoneticisi(
            dry_run=True,
            kayit_yolu=tmp / "devices2.json",
            sync_depo_kok=tmp / "sync2",
            sync_olustur=True,
        )
        sync2 = SyncYoneticisi.agdan(net2)
        assert sync2.sohbet is net2.sohbet
        await sync2.baslat()
        assert sync2.sohbet.calisiyor
        await sync2.durdur()

    asyncio.run(_run())


def test_modul_bagla() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        sync = SyncYoneticisi(dry_run=True, olustur=False)
        assert sync.sohbet is None
        s = SohbetSenkron(dry_run=True, depo_yolu=tmp / "chat.json")
        sync.modul_bagla(sohbet=s)
        assert sync.sohbet is s
        await sync.baslat()
        assert s.calisiyor
        await sync.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_dry_run_baslat_durdur_ozet()
    print("OK test_dry_run_baslat_durdur_ozet")
    test_sohbet_ve_bildirim_facade()
    print("OK test_sohbet_ve_bildirim_facade")
    test_yedek_ve_dosya_facade()
    print("OK test_yedek_ve_dosya_facade")
    test_protokol_yonlendirme()
    print("OK test_protokol_yonlendirme")
    test_baslatmadan_api_hata()
    print("OK test_baslatmadan_api_hata")
    test_ag_bagla_ve_agdan()
    print("OK test_ag_bagla_ve_agdan")
    test_modul_bagla()
    print("OK test_modul_bagla")
    print("OK test_yoneticisi")

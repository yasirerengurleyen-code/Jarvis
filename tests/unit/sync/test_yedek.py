"""sync/cloud/yedek.py birim testleri (çevrimdışı / dry_run / sahte bulut)."""

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
from sync.cloud.yedek import (
    BulutYedek,
    YedekDurumu,
    yedek_normalize,
)


def test_yedek_normalize() -> None:
    y = yedek_normalize(
        {
            "yedek_id": "b1",
            "etiket": "chat",
            "durum": "local",
            "boyut": 42,
            "cihaz_id": "iphone-1",
            "tur": "snapshot",
        }
    )
    assert y["id"] == "b1"
    assert y["label"] == "chat"
    assert y["status"] == YedekDurumu.YEREL.value
    assert y["size"] == 42
    assert y["device_id"] == "iphone-1"
    assert y["kind"] == "snapshot"


def test_dry_run_yedekle_yukle_geri() -> None:
    async def _run() -> None:
        by = BulutYedek(dry_run=True)
        assert by.motor == "dry_run"
        assert by.bulut_sahte_mi is True
        await by.baslat()
        assert by.calisiyor

        yid = await by.yedekle(
            {"messages": [{"id": "m1", "content": "selam"}]},
            etiket="sohbet",
            cihaz_id="iphone-1",
        )
        assert yid
        assert by.listele(cihaz_id="iphone-1")[0]["label"] == "sohbet"
        assert by.listele()[0]["status"] == YedekDurumu.YEREL.value

        ozet = await by.yukle(yid)
        assert ozet.guncellenen == 1
        assert ozet.detay["cloud_fake"] is True
        assert by.yedek_al(yid)["status"] == YedekDurumu.BULUTTA.value
        assert len(by.bulut_listele()) == 1

        payload = await by.geri_yukle(yid)
        assert payload["messages"][0]["content"] == "selam"
        assert by.yedek_al(yid)["status"] == YedekDurumu.GERI_YUKLENDI.value

        durum = by.ozet()
        assert durum["engine"] == "dry_run"
        assert durum["cloud_fake"] is True
        assert durum["count"] == 1

        await by.durdur()
        assert not by.calisiyor

    asyncio.run(_run())


def test_local_persist() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        depo = tmp / "cloud"

        b1 = BulutYedek(depo_yolu=depo)
        await b1.baslat()
        assert b1.motor == "local"
        yid = await b1.yedekle(
            {"settings": {"tema": "tony"}},
            etiket="ayarlar",
            buluta_yukle=True,
        )
        await b1.durdur()

        assert (depo / "backups.json").is_file()
        ham = json.loads((depo / "backups.json").read_text(encoding="utf-8"))
        assert ham["version"] == 1
        assert len(ham["backups"]) == 1
        assert ham["backups"][0]["label"] == "ayarlar"
        assert (depo / "snapshots" / f"{yid}.json").is_file()

        b2 = BulutYedek(depo_yolu=depo)
        await b2.baslat()
        assert len(b2.listele()) == 1
        assert b2.icerik_al(yid)["settings"]["tema"] == "tony"
        # bulut bellek oturumlar arası paylaşılmaz; yeniden yükle
        await b2.yukle(yid)
        assert b2.yedek_al(yid)["status"] == YedekDurumu.BULUTTA.value
        await b2.durdur()

    asyncio.run(_run())


def test_sahte_bulut_indir() -> None:
    async def _run() -> None:
        kaynak = BulutYedek(zorla_sahte=True)
        await kaynak.baslat()
        yid = await kaynak.yedekle({"k": 1}, etiket="paylas")
        await kaynak.yukle(yid)
        cloud_id = kaynak.yedek_al(yid)["cloud_id"]
        paket = kaynak._bulut[cloud_id]

        hedef = BulutYedek(dry_run=True)
        await hedef.baslat()
        # sahte bulut paketini hedefe aktar (offline senkron simülasyonu)
        hedef._bulut[cloud_id] = paket
        yeni = await hedef.indir(cloud_id)
        assert hedef.icerik_al(yeni)["k"] == 1
        await kaynak.durdur()
        await hedef.durdur()

    asyncio.run(_run())


def test_cloud_backup_protokol() -> None:
    async def _run() -> None:
        by = BulutYedek(dry_run=True)
        await by.baslat()
        yid = await by.yedekle({"x": True}, etiket="p", cihaz_id="c1")

        ws = by.cloud_backup_mesaji(yedek_id=yid, cihaz_id="c1", islem="get")
        assert ws.tip is MesajTipi.EVENT
        assert ws.yuk["kind"] == "cloud_backup"
        assert ws.yuk["backup"]["id"] == yid
        geri = decode_mesaj(encode_mesaj(ws))
        assert geri.tip is MesajTipi.EVENT

        liste = by.cloud_backup_isle({"kind": "cloud_backup", "op": "list"}, cihaz_id="c1")
        assert liste["ok"] is True
        assert liste["count"] == 1

        up = by.cloud_backup_isle(
            {"kind": "cloud_backup", "op": "upload", "backup_id": yid}
        )
        assert up["op"] == "upload"
        assert up["detail"]["cloud_fake"] is True

        rst = by.cloud_backup_isle(
            {"kind": "cloud_backup", "op": "restore", "backup_id": yid}
        )
        assert rst["payload"]["x"] is True

        apply = by.cloud_backup_isle(
            {
                "kind": "cloud_backup",
                "op": "create",
                "backup": {"id": "remote1", "label": "uzak"},
                "payload": {"v": 2},
            },
            cihaz_id="c2",
        )
        assert apply["added"] == 1
        assert by.icerik_al("remote1")["v"] == 2

        await by.durdur()

    asyncio.run(_run())


def test_limit_ve_baslatmadan_hata() -> None:
    async def _run() -> None:
        by = BulutYedek(dry_run=True, max_bayt=40)
        try:
            await by.yedekle({"data": "x" * 100})
            raise AssertionError("baslatmadan hata bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0043"

        await by.baslat()
        try:
            await by.yedekle({"data": "x" * 200})
            raise AssertionError("boyut limiti bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0045"

        try:
            await by.yukle("yok")
            raise AssertionError("bulunamadi bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0042"

        await by.durdur()

    asyncio.run(_run())


def test_sil() -> None:
    async def _run() -> None:
        by = BulutYedek(dry_run=True)
        await by.baslat()
        yid = await by.yedekle({"a": 1}, buluta_yukle=True)
        assert by.ozet()["cloud_count"] == 1
        t = by.sil(yid)
        assert t["status"] == YedekDurumu.SILINDI.value
        assert by.ozet()["cloud_count"] == 0
        assert by.ozet()["count"] == 0
        try:
            await by.geri_yukle(yid)
            raise AssertionError("silinmis geri yukleme hatasi bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0046"
        await by.durdur()

    asyncio.run(_run())


def test_yedek() -> None:
    """Tek giriş noktası — tüm senaryolar."""
    test_yedek_normalize()
    test_dry_run_yedekle_yukle_geri()
    test_local_persist()
    test_sahte_bulut_indir()
    test_cloud_backup_protokol()
    test_limit_ve_baslatmadan_hata()
    test_sil()
    print("OK test_yedek")


if __name__ == "__main__":
    test_yedek()

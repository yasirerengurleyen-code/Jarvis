"""sync/files/paylasim.py birim testleri (çevrimdışı / dry_run)."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import WhiteCoreError
from network.websocket.protokol import MesajTipi, decode_mesaj, encode_mesaj
from sync.files.paylasim import (
    DosyaPaylasim,
    TransferDurumu,
    guvenli_dosya_adi,
    sandbox_yolu,
    transfer_normalize,
)


def test_guvenli_ad_ve_sandbox() -> None:
    assert guvenli_dosya_adi("rapor.txt") == "rapor.txt"
    assert guvenli_dosya_adi("alt/yol/dosya.pdf") == "dosya.pdf"
    try:
        guvenli_dosya_adi("../etc/passwd")
        raise AssertionError("traversal bekleniyordu")
    except WhiteCoreError as exc:
        assert exc.kod == "SYNC_0011"

    try:
        guvenli_dosya_adi("C:\\Windows\\a.txt")
        raise AssertionError("mutlak yol bekleniyordu")
    except WhiteCoreError as exc:
        assert exc.kod == "SYNC_0011"

    kok = Path(tempfile.mkdtemp())
    p = sandbox_yolu(kok, "t1", "a.txt", olustur=True)
    assert p.parent.is_dir()
    assert p.name == "a.txt"
    assert str(kok.resolve()) in str(p)


def test_transfer_normalize() -> None:
    t = transfer_normalize(
        {
            "transfer_id": "abc",
            "ad": "not.txt",
            "boyut": 12,
            "durum": "ready",
            "cihaz_id": "iphone-1",
        }
    )
    assert t["id"] == "abc"
    assert t["name"] == "not.txt"
    assert t["size"] == 12
    assert t["status"] == TransferDurumu.HAZIR.value
    assert t["device_id"] == "iphone-1"


def test_dry_run_gonder_al() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        kaynak = tmp / "giden.txt"
        kaynak.write_text("Merhaba WhiteCore", encoding="utf-8")

        pay = DosyaPaylasim(dry_run=True, depo_yolu=tmp / "store")
        assert pay.motor == "dry_run"
        await pay.baslat()
        assert pay.calisiyor

        tid = await pay.gonder("iphone-1", str(kaynak), uzak_ad="selam.txt")
        assert tid
        giden = pay.giden_cek("iphone-1")
        assert len(giden) == 1
        assert giden[0]["name"] == "selam.txt"
        assert giden[0]["size"] == len("Merhaba WhiteCore".encode("utf-8"))
        assert pay.giden_cek("iphone-1") == []

        hedef = await pay.al(tid, str(tmp / "indir"))
        assert hedef.endswith("selam.txt") or "selam.txt" in hedef
        # dry_run: disk yazmaz
        assert not Path(hedef).is_file()

        durum = pay.ozet()
        assert durum["engine"] == "dry_run"
        assert durum["count"] == 1
        assert durum["running"] is True

        await pay.durdur()
        assert not pay.calisiyor

    asyncio.run(_run())


def test_disk_staging_persist() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        kaynak = tmp / "kalici.bin"
        kaynak.write_bytes(b"ABC123")
        depo = tmp / "files"

        p1 = DosyaPaylasim(depo_yolu=depo)
        await p1.baslat()
        assert p1.motor == "disk"
        tid = await p1.gonder("c1", str(kaynak), uzak_ad="kalici.bin")
        await p1.durdur()

        manifest = depo / "transfers.json"
        assert manifest.is_file()
        ham = json.loads(manifest.read_text(encoding="utf-8"))
        assert ham["version"] == 1
        assert len(ham["transfers"]) == 1

        p2 = DosyaPaylasim(depo_yolu=depo)
        await p2.baslat()
        assert len(p2.listele()) == 1
        out = await p2.al(tid, str(tmp / "inbox_out"))
        assert Path(out).is_file()
        assert Path(out).read_bytes() == b"ABC123"
        assert p2.transfer_al(tid)["status"] == TransferDurumu.TAMAMLANDI.value
        await p2.durdur()

    asyncio.run(_run())


def test_file_share_protokol() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        kaynak = tmp / "p.txt"
        kaynak.write_text("protokol", encoding="utf-8")

        pay = DosyaPaylasim(dry_run=True, depo_yolu=tmp / "s")
        await pay.baslat()
        tid = await pay.gonder("c1", str(kaynak))

        ws = pay.file_share_mesaji(
            transfer_id=tid, cihaz_id="c1", islem="offer", icerik_dahil=True
        )
        assert ws.tip is MesajTipi.FILE_SHARE
        assert ws.yuk["op"] == "offer"
        assert "content_b64" in ws.yuk
        geri = decode_mesaj(encode_mesaj(ws))
        assert geri.tip is MesajTipi.FILE_SHARE

        # uzak push
        pay2 = DosyaPaylasim(dry_run=True, depo_yolu=tmp / "s2")
        await pay2.baslat()
        sonuc = pay2.file_share_isle(
            {
                "op": "push",
                "transfer": {
                    "id": "remote1",
                    "name": "uzak.txt",
                    "size": 4,
                },
                "content_b64": base64.b64encode(b"uzak").decode("ascii"),
            },
            cihaz_id="c2",
        )
        assert sonuc["ok"] is True
        assert sonuc["op"] == "apply"
        assert sonuc["added"] == 1
        assert pay2.icerik_al("remote1") == b"uzak"

        liste = pay2.file_share_isle({"op": "list"}, cihaz_id="c2")
        assert liste["count"] == 1

        await pay.durdur()
        await pay2.durdur()

    asyncio.run(_run())


def test_boyut_limiti_ve_baslatmadan_hata() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        kaynak = tmp / "buyuk.bin"
        kaynak.write_bytes(b"x" * 100)

        pay = DosyaPaylasim(dry_run=True, max_bayt=50)
        try:
            await pay.gonder("c1", str(kaynak))
            raise AssertionError("baslatmadan hata bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0015"

        await pay.baslat()
        try:
            await pay.gonder("c1", str(kaynak))
            raise AssertionError("boyut limiti bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0018"
        await pay.durdur()

    asyncio.run(_run())


def test_iptal() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        kaynak = tmp / "a.txt"
        kaynak.write_text("x", encoding="utf-8")
        pay = DosyaPaylasim(dry_run=True)
        await pay.baslat()
        tid = await pay.gonder("c1", str(kaynak))
        t = pay.iptal(tid)
        assert t["status"] == TransferDurumu.IPTAL.value
        try:
            await pay.al(tid, str(tmp / "out"))
            raise AssertionError("iptal hata bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0020"
        await pay.durdur()

    asyncio.run(_run())


def test_paylasim() -> None:
    """Tek giriş noktası — tüm senaryolar."""
    test_guvenli_ad_ve_sandbox()
    test_transfer_normalize()
    test_dry_run_gonder_al()
    test_disk_staging_persist()
    test_file_share_protokol()
    test_boyut_limiti_ve_baslatmadan_hata()
    test_iptal()
    print("OK test_paylasim")


if __name__ == "__main__":
    test_paylasim()

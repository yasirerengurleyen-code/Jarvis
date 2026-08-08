"""sync/chat/senkron.py birim testleri (çevrimdışı / dry_run)."""

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
from network.websocket.protokol import MesajTipi, decode_mesaj
from sync.chat.senkron import (
    SohbetSenkron,
    birlestir,
    fark,
    mesaj_normalize,
)


def test_normalize_ve_birlestir_fark() -> None:
    a = mesaj_normalize(
        {
            "mesaj_id": "m1",
            "rol": "user",
            "icerik": "Merhaba",
            "zaman": "2026-08-07T10:00:00+00:00",
        }
    )
    assert a["id"] == "m1"
    assert a["role"] == "user"
    assert a["content"] == "Merhaba"

    yerel = [
        a,
        {
            "id": "m2",
            "role": "assistant",
            "content": "Eski",
            "timestamp": "2026-08-07T10:01:00+00:00",
        },
    ]
    uzak = [
        {
            "id": "m2",
            "role": "assistant",
            "content": "Yeni",
            "timestamp": "2026-08-07T10:02:00+00:00",
        },
        {
            "id": "m3",
            "role": "user",
            "content": "Ek",
            "timestamp": "2026-08-07T10:03:00+00:00",
        },
    ]
    birlesik = birlestir(yerel, uzak)
    ids = [m["id"] for m in birlesik]
    assert ids == ["m1", "m2", "m3"]
    assert next(m for m in birlesik if m["id"] == "m2")["content"] == "Yeni"

    d = fark(yerel, uzak)
    assert {m["id"] for m in d["only_local"]} == {"m1"}
    assert {m["id"] for m in d["only_remote"]} == {"m3"}
    assert {m["id"] for m in d["newer_remote"]} == {"m2"}


def test_dry_run_gonder_cek_uygula() -> None:
    async def _run() -> None:
        sync = SohbetSenkron(dry_run=True)
        assert sync.motor == "dry_run"
        await sync.baslat()
        assert sync.calisiyor

        await sync.gonder(
            "iphone-1",
            [
                {
                    "id": "a1",
                    "role": "user",
                    "content": "Selam",
                    "timestamp": "2026-08-07T12:00:00+00:00",
                }
            ],
        )
        giden = sync.giden_cek("iphone-1")
        assert len(giden) == 1
        assert giden[0]["content"] == "Selam"
        assert sync.giden_cek("iphone-1") == []

        ozet = sync.uygula(
            [
                {
                    "id": "a2",
                    "role": "assistant",
                    "content": "Buyurun",
                    "timestamp": "2026-08-07T12:01:00+00:00",
                }
            ],
            cihaz_id="iphone-1",
        )
        assert ozet.eklenen == 1
        assert ozet.dry_run is True

        cekilen = await sync.cek("iphone-1", son_sonra="2026-08-07T12:00:30+00:00")
        assert len(cekilen) == 1
        assert cekilen[0]["id"] == "a2"

        durum = sync.ozet()
        assert durum["engine"] == "dry_run"
        assert durum["count"] == 2
        assert durum["running"] is True

        await sync.durdur()
        assert not sync.calisiyor

    asyncio.run(_run())


def test_json_depo_persist() -> None:
    async def _run() -> None:
        depo = Path(tempfile.mkdtemp()) / "messages.json"

        s1 = SohbetSenkron(depo_yolu=depo)
        await s1.baslat()
        assert s1.motor == "json"
        s1.kaydet(
            [
                {
                    "id": "p1",
                    "role": "user",
                    "content": "Kalici",
                    "timestamp": "2026-08-07T13:00:00+00:00",
                }
            ]
        )
        await s1.durdur()
        assert depo.is_file()
        ham = json.loads(depo.read_text(encoding="utf-8"))
        assert ham["version"] == 1
        assert len(ham["messages"]) == 1

        s2 = SohbetSenkron(depo_yolu=depo)
        await s2.baslat()
        assert len(s2.listele()) == 1
        assert s2.listele()[0]["content"] == "Kalici"
        await s2.durdur()

    asyncio.run(_run())


def test_chat_sync_protokol_ve_ack_detay() -> None:
    async def _run() -> None:
        sync = SohbetSenkron(dry_run=True)
        await sync.baslat()
        sync.kaydet(
            [
                {
                    "id": "h1",
                    "role": "user",
                    "content": "Host",
                    "timestamp": "2026-08-07T14:00:00+00:00",
                }
            ]
        )

        ws = sync.chat_sync_mesaji(cihaz_id="c1", islem="push")
        assert ws.tip is MesajTipi.CHAT_SYNC
        assert ws.cihaz_id == "c1"
        assert ws.yuk["op"] == "push"
        assert len(ws.yuk["messages"]) == 1

        # encode/decode roundtrip
        from network.websocket.protokol import encode_mesaj

        ham = encode_mesaj(ws)
        assert isinstance(ham, str)
        geri = decode_mesaj(ham)
        assert geri.tip is MesajTipi.CHAT_SYNC

        sonuc = sync.chat_sync_isle(
            {
                "op": "push",
                "messages": [
                    {
                        "id": "r1",
                        "role": "user",
                        "content": "Remote",
                        "timestamp": "2026-08-07T14:05:00+00:00",
                    }
                ],
            },
            cihaz_id="c1",
        )
        assert sonuc["ok"] is True
        assert sonuc["type"] == "chat_sync"
        assert sonuc["op"] == "apply"
        assert sonuc["added"] == 1

        diff = sync.chat_sync_isle(
            {
                "op": "diff",
                "messages": [
                    {
                        "id": "h1",
                        "role": "user",
                        "content": "Host",
                        "timestamp": "2026-08-07T14:00:00+00:00",
                    }
                ],
            },
            cihaz_id="c1",
        )
        assert diff["op"] == "diff"
        assert any(m["id"] == "r1" for m in diff["only_local"])

        await sync.durdur()

    asyncio.run(_run())


def test_baslatmadan_gonder_hata() -> None:
    async def _run() -> None:
        sync = SohbetSenkron(dry_run=True)
        try:
            await sync.gonder("c1", [])
            raise AssertionError("WhiteCoreError bekleniyordu")
        except WhiteCoreError as exc:
            assert exc.kod == "SYNC_0003"

    asyncio.run(_run())


def test_merge_eski_ezilmez() -> None:
    async def _run() -> None:
        sync = SohbetSenkron(dry_run=True)
        await sync.baslat()
        sync.kaydet(
            [
                {
                    "id": "x1",
                    "role": "user",
                    "content": "Yeni yerel",
                    "timestamp": "2026-08-07T15:10:00+00:00",
                }
            ]
        )
        ozet = sync.uygula(
            [
                {
                    "id": "x1",
                    "role": "user",
                    "content": "Eski uzak",
                    "timestamp": "2026-08-07T15:00:00+00:00",
                }
            ]
        )
        assert ozet.atlanan == 1
        assert sync.listele()[0]["content"] == "Yeni yerel"
        await sync.durdur()

    asyncio.run(_run())


def test_senkron() -> None:
    """Tek giriş noktası — tüm senaryolar."""
    test_normalize_ve_birlestir_fark()
    test_dry_run_gonder_cek_uygula()
    test_json_depo_persist()
    test_chat_sync_protokol_ve_ack_detay()
    test_baslatmadan_gonder_hata()
    test_merge_eski_ezilmez()
    print("OK test_senkron")


if __name__ == "__main__":
    test_senkron()

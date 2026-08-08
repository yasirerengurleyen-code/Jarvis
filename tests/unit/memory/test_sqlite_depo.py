"""memory/stores/sqlite_depo.py birim testi."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import MemoryError
from core.logger import logger_yapilandir
from memory.stores.sqlite_depo import SqliteDepo


def test_sqlite_depo() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp()) / "test_whitecore.db"
    depo = SqliteDepo(tmp)

    assert not depo.acik_mi
    conn = depo.baglan()
    assert depo.acik_mi
    assert tmp.exists()

    # Tablolar
    tablolar = {
        r["name"]
        for r in depo.getir_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for t in (
        "kullanicilar",
        "sohbet_oturumlari",
        "sohbet_mesajlari",
        "uzun_sureli_hafiza",
    ):
        assert t in tablolar, f"eksik tablo: {t}"

    depo.calistir(
        "INSERT INTO kullanicilar (anahtar, deger, guncelleme) VALUES (?, ?, ?)",
        ("ad", "Yasir", "2026-01-01T00:00:00+00:00"),
    )
    row = depo.getir_one(
        "SELECT deger FROM kullanicilar WHERE anahtar = ?",
        ("ad",),
    )
    assert row is not None
    assert row["deger"] == "Yasir"

    async def _async() -> None:
        depo2 = SqliteDepo(tmp)
        await depo2.abaglan()
        await depo2.acalistir(
            "INSERT INTO uzun_sureli_hafiza "
            "(anahtar, icerik, etiketler, onem, olusturma, guncelleme) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("pref", "VS Code sever", "tercih", 1, "t1", "t1"),
        )
        rows = await depo2.agetir_all(
            "SELECT icerik FROM uzun_sureli_hafiza WHERE anahtar = ?",
            ("pref",),
        )
        assert rows[0]["icerik"] == "VS Code sever"
        await depo2.akapat()

    asyncio.run(_async())

    # Hatalı SQL
    try:
        depo.calistir("INSERT INTO yok_tablo VALUES (1)")
        raise AssertionError("MemoryError bekleniyordu")
    except MemoryError:
        pass

    depo.kapat()
    assert not depo.acik_mi

    # Yeniden açılabilir
    depo.baglan()
    assert depo.getir_one("SELECT COUNT(*) AS c FROM kullanicilar")["c"] == 1
    depo.kapat()

    print("TEST_OK")
    print("db:", tmp)
    print("tables:", sorted(tablolar))


if __name__ == "__main__":
    test_sqlite_depo()

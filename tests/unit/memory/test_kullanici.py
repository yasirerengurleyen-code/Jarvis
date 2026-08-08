"""memory/stores/kullanici.py birim testi."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import MemoryError
from core.logger import logger_yapilandir
from memory.stores.kullanici import KullaniciDeposu
from memory.stores.sqlite_depo import SqliteDepo


def test_kullanici_deposu() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp()) / "kullanici.db"
    depo = SqliteDepo(tmp)
    depo.baglan()
    k = KullaniciDeposu(depo)

    assert k.adi_al() is None
    k.adi_ayarla("Yasir")
    assert k.adi_al() == "Yasir"

    k.dil_ayarla("tr")
    assert k.dil_al() == "tr"

    k.tercih_ayarla("editor", "vscode")
    k.tercih_ayarla("tema", "tony_stark")
    assert k.tercih_al("editor") == "vscode"
    assert k.tercih_al("yok", "x") == "x"

    # Güncelleme
    k.adi_ayarla("Yasir K.")
    assert k.adi_al() == "Yasir K."

    # JSON / sayı
    k.ayarla("user.score", 42)
    assert k.al("user.score") == 42
    k.ayarla("user.flags", {"beta": True})
    assert k.al("user.flags")["beta"] is True

    ozet = k.profil_ozeti()
    assert ozet["name"] == "Yasir K."
    assert ozet["preferences"]["tema"] == "tony_stark"

    tum = k.tumu()
    assert "user.name" in tum

    assert k.var_mi("user.name")
    assert k.sil("user.name") is True
    assert not k.var_mi("user.name")

    try:
        k.ayarla("", "x")
        raise AssertionError("MemoryError bekleniyordu")
    except MemoryError:
        pass

    depo.kapat()
    print("TEST_OK")
    print("profil:", ozet)


if __name__ == "__main__":
    test_kullanici_deposu()

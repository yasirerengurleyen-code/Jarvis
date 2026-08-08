"""memory/stores/uzun_sureli.py birim testi."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import MemoryError
from core.logger import logger_yapilandir
from memory.stores.sqlite_depo import SqliteDepo
from memory.stores.uzun_sureli import UzunSureliHafiza


def test_uzun_sureli() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp()) / "uzun.db"
    depo = SqliteDepo(tmp)
    depo.baglan()
    hafiza = UzunSureliHafiza(depo)

    id1 = hafiza.ekle(
        "Kullanıcı VS Code tercih eder",
        anahtar="pref.editor",
        etiketler=["tercih", "editor"],
        onem=5,
    )
    id2 = hafiza.ekle(
        "İstanbul'da yaşıyor",
        anahtar="fact.city",
        etiketler="konum,profil",
        onem=3,
    )
    assert id1 > 0 and id2 > 0

    kayit = hafiza.getir(id1)
    assert kayit is not None
    assert "VS Code" in kayit["icerik"]
    assert "tercih" in kayit["etiketler"]

    assert len(hafiza.anahtarla_getir("pref.editor")) == 1

    hafiza.guncelle(id2, onem=10, icerik="İstanbul / Türkiye")
    assert hafiza.getir(id2)["onem"] == 10

    liste = hafiza.listele(limit=10)
    assert liste[0]["id"] == id2  # daha yüksek önem

    etiketli = hafiza.listele(etiket="tercih")
    assert any(r["id"] == id1 for r in etiketli)

    ara = hafiza.metin_ara("VS Code")
    assert len(ara) >= 1

    notlar = hafiza.prompt_notlari(limit=5)
    assert any("İstanbul" in n for n in notlar)

    try:
        hafiza.ekle("   ")
        raise AssertionError("MemoryError bekleniyordu")
    except MemoryError:
        pass

    assert hafiza.sil(id1) is True
    assert hafiza.getir(id1) is None

    depo.kapat()
    print("TEST_OK")
    print("notlar:", notlar)


if __name__ == "__main__":
    test_uzun_sureli()

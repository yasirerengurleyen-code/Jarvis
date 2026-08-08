"""memory/stores/sohbet.py birim testi."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.base import Mesaj
from core.exceptions import MemoryError
from core.logger import logger_yapilandir
from memory.stores.sohbet import SohbetDeposu
from memory.stores.sqlite_depo import SqliteDepo


def test_sohbet_deposu() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp()) / "sohbet.db"
    depo = SqliteDepo(tmp)
    depo.baglan()
    sohbet = SohbetDeposu(depo)

    oid = sohbet.oturum_olustur(baslik="Test sohbet")
    assert sohbet.oturum_var_mi(oid)

    sohbet.mesaj_ekle(oid, Mesaj.kullanici("Merhaba Jarvis"))
    sohbet.mesaj_ekle(oid, Mesaj.asistan("Sistemler çevrimiçi."))
    sohbet.mesaj_ekle(oid, Mesaj.kullanici("Hava nasıl?"))

    assert sohbet.mesaj_sayisi(oid) == 3

    tum = sohbet.mesajlari_getir(oid)
    assert len(tum) == 3
    assert tum[0].icerik == "Merhaba Jarvis"
    assert tum[1].rol.value == "assistant"

    son2 = sohbet.son_mesajlar(oid, 2)
    assert len(son2) == 2
    assert son2[0].icerik == "Sistemler çevrimiçi."
    assert son2[1].icerik == "Hava nasıl?"

    sohbet.oturum_guncelle(oid, baslik="Güncellendi")
    liste = sohbet.oturumlari_listele()
    assert liste[0]["baslik"] == "Güncellendi"

    try:
        sohbet.mesaj_ekle("yok", Mesaj.kullanici("x"))
        raise AssertionError("MemoryError bekleniyordu")
    except MemoryError:
        pass

    sohbet.oturum_sil(oid)
    assert not sohbet.oturum_var_mi(oid)
    assert sohbet.mesaj_sayisi(oid) == 0

    depo.kapat()
    print("TEST_OK")
    print("oturum:", oid)
    print("mesaj_ornek:", tum[1].icerik)


if __name__ == "__main__":
    test_sohbet_deposu()

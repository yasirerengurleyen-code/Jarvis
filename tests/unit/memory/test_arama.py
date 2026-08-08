"""memory/arama.py birim testi."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.base import Mesaj
from core.logger import logger_yapilandir
from memory.arama import HafizaArama
from memory.stores.kullanici import KullaniciDeposu
from memory.stores.sohbet import SohbetDeposu
from memory.stores.sqlite_depo import SqliteDepo
from memory.stores.uzun_sureli import UzunSureliHafiza


def test_hafiza_arama() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp()) / "arama.db"
    depo = SqliteDepo(tmp)
    depo.baglan()

    sohbet = SohbetDeposu(depo)
    kullanici = KullaniciDeposu(depo)
    uzun = UzunSureliHafiza(depo)
    arama = HafizaArama(depo, sohbet=sohbet, kullanici=kullanici, uzun_sureli=uzun)

    kullanici.adi_ayarla("Yasir")
    kullanici.tercih_ayarla("editor", "VS Code")

    uzun.ekle("Kullanıcı VS Code sever", etiketler=["tercih"], onem=5)
    uzun.ekle("Kedisi var", etiketler=["profil"], onem=1)

    oid = sohbet.oturum_olustur(baslik="ara")
    sohbet.mesaj_ekle(oid, Mesaj.kullanici("VS Code ile proje aç"))
    sohbet.mesaj_ekle(oid, Mesaj.asistan("Tabii, açıyorum."))

    sonuclar = arama.ara("VS Code", limit=10)
    assert len(sonuclar) >= 2
    kaynaklar = {s.kaynak for s in sonuclar}
    assert "uzun_sureli" in kaynaklar
    assert "sohbet" in kaynaklar or "kullanici" in kaynaklar

    skorlar = [s.skor for s in sonuclar]
    assert skorlar == sorted(skorlar, reverse=True)

    sadece_uzun = arama.ara("VS Code", kaynaklar=["uzun_sureli"])
    assert all(s.kaynak == "uzun_sureli" for s in sadece_uzun)

    ozet = arama.ozet_metinleri("kedi", limit=5)
    assert any("kedi" in x.lower() for x in ozet)

    assert arama.ara("") == []

    depo.kapat()
    print("TEST_OK")
    print("hit_count:", len(sonuclar))
    print("top:", sonuclar[0].kaynak, sonuclar[0].icerik[:40])


if __name__ == "__main__":
    test_hafiza_arama()

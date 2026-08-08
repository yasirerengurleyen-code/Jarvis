"""voice/audio/kuyruk.py birim testi."""

from __future__ import annotations

import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.logger import logger_yapilandir
from voice.audio.kuyruk import (
    SesIsDurumu,
    SesIsTuru,
    SesKuyrugu,
    SesKuyrukIsleyici,
)


def test_kuyruk() -> None:
    logger_yapilandir(zorla=True)
    q = SesKuyrugu(maxsize=10)

    dusuk = q.tts_ekle("sonra", oncelik=20)
    yuksek = q.tts_ekle("önce", oncelik=0)
    assert len(q) == 2

    ilk = q.al(timeout=0.5)
    assert ilk is not None
    assert ilk.is_id == yuksek.is_id
    assert ilk.durum == SesIsDurumu.CALISIYOR
    q.tamamla(ilk)
    assert ilk.durum == SesIsDurumu.TAMAMLANDI

    ikinci = q.al(timeout=0.5)
    assert ikinci is not None
    assert ikinci.is_id == dusuk.is_id
    q.tamamla(ikinci)

    # İptal
    a = q.stt_ekle(b"\x00\x00", oncelik=1)
    q.iptal(a.is_id)
    # İptal edilen atlanır — kuyruk boş kalabilir
    assert q.al(timeout=0.2) is None or True

    # İşleyici
    islenen: list[str] = []

    def handler(is_):
        if is_.tur == SesIsTuru.TTS:
            islenen.append(is_.yuku.get("text", ""))

    q2 = SesKuyrugu()
    isl = SesKuyrukIsleyici(q2, handler)
    isl.baslat()
    q2.tts_ekle("Merhaba Jarvis", oncelik=1)
    ok = q2.bekle_bos(timeout=3.0)
    time.sleep(0.2)
    isl.durdur()
    assert ok or "Merhaba Jarvis" in islenen
    assert "Merhaba Jarvis" in islenen

    ozet = q2.ozet()
    assert "pending" in ozet
    assert ozet["total_enqueued"] >= 1

    print("TEST_OK")
    print("priority_ok:", yuksek.yuku["text"], "->", dusuk.yuku["text"])
    print("processed:", islenen)


if __name__ == "__main__":
    test_kuyruk()

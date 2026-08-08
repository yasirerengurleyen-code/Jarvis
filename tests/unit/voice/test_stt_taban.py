"""voice/stt/taban.py birim testi."""

from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import VoiceError
from core.logger import logger_yapilandir
from voice.stt.taban import STTMotoru, SahteSTT, SttAyarlari, SttSonucu


def test_stt_taban() -> None:
    logger_yapilandir(zorla=True)

    ayar = SttAyarlari.sozlukten(
        {
            "engine": "faster_whisper",
            "model_size": "tiny",
            "device": "cpu",
            "compute_type": "int8",
        },
        dil="tr",
    )
    assert ayar.motor == "faster_whisper"
    assert ayar.dil == "tr"

    stt = SahteSTT(ayar, varsayilan_metin="Merhaba Jarvis")
    assert not stt.hazir
    sonuc = stt.pcm_coz(b"\x00\x00" * 100)
    assert stt.hazir
    assert sonuc.metin == "Merhaba Jarvis"
    assert sonuc.motor == "sahte"
    assert sonuc.to_dict()["text"] == "Merhaba Jarvis"
    assert not sonuc.bos_mu

    stt.sonraki_metni_ayarla("Hava nasıl?")
    assert stt.pcm_coz(b"\x00\x00" * 10).metin == "Hava nasıl?"

    try:
        stt.pcm_coz(b"")
        raise AssertionError("VoiceError bekleniyordu")
    except VoiceError:
        pass

    # ABC doğrudan örneklenemez
    try:
        STTMotoru(ayar)  # type: ignore[abstract]
        raise AssertionError("ABC örneklenmemeli")
    except TypeError:
        pass

    bos = SttSonucu(metin="  ")
    assert bos.bos_mu

    print("TEST_OK")
    print("sample:", sonuc.metin)
    print("engine:", ayar.motor)


if __name__ == "__main__":
    test_stt_taban()

"""voice/tts/taban.py birim testi."""

from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import VoiceError
from core.logger import logger_yapilandir
from voice.tts.taban import TTSMotoru, SahteTTS, TtsAyarlari, TtsSonucu


def test_tts_taban() -> None:
    logger_yapilandir(zorla=True)

    ayar = TtsAyarlari.sozlukten(
        {
            "engine": "piper",
            "fallback": "coqui",
            "voice": "tr_TR-dfki-medium",
            "speed": 1.0,
            "style": "robotic_natural",
        }
    )
    assert ayar.motor == "piper"

    tts = SahteTTS(ayar)
    assert not tts.hazir
    sonuc = tts.konus("Sistemler çevrimiçi.")
    assert tts.hazir
    assert sonuc.metin == "Sistemler çevrimiçi."
    assert len(sonuc.pcm) > 0
    assert sonuc.motor == "sahte"
    assert not sonuc.bos_mu
    assert sonuc.to_dict()["bytes"] == len(sonuc.pcm)

    try:
        tts.konus("   ")
        raise AssertionError("VoiceError bekleniyordu")
    except VoiceError:
        pass

    try:
        TTSMotoru(ayar)  # type: ignore[abstract]
        raise AssertionError("ABC örneklenmemeli")
    except TypeError:
        pass

    bos = TtsSonucu(metin="x")
    assert bos.bos_mu

    print("TEST_OK")
    print("sample:", sonuc.metin)
    print("pcm_bytes:", len(sonuc.pcm))


if __name__ == "__main__":
    test_tts_taban()

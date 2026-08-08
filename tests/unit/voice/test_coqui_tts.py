"""voice/tts/coqui_tts.py birim testi (mock)."""

from __future__ import annotations

import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import VoiceError
from core.logger import logger_yapilandir
from voice.tts.coqui_tts import CoquiTTS, coqui_olustur
from voice.tts.taban import TtsAyarlari


def test_coqui_tts() -> None:
    logger_yapilandir(zorla=True)

    ayar = TtsAyarlari(motor="coqui", voice="tts_models/tr/common-voice/glow-tts")
    tts = CoquiTTS(ayar)

    with patch("voice.tts.coqui_tts._coqui_var_mi", return_value=False):
        try:
            tts.yukle()
            raise AssertionError("VoiceError bekleniyordu")
        except VoiceError as exc:
            assert "Coqui TTS" in exc.mesaj

    tts2 = CoquiTTS(ayar)
    mock = MagicMock()

    def _to_file(text=None, file_path=None, **kwargs):  # noqa: ANN001
        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x20\x00" * 800)

    mock.tts_to_file.side_effect = _to_file
    tts2._tts = mock
    tts2._yuklendi = True

    sonuc = tts2.konus("Asistan nasıl yardımcı olabilir?")
    assert sonuc.metin.startswith("Asistan")
    assert sonuc.motor == "coqui"
    assert len(sonuc.pcm) > 0

    try:
        tts2.konus("  ")
        raise AssertionError("boş metin hatası bekleniyordu")
    except VoiceError:
        pass

    assert isinstance(coqui_olustur({"engine": "coqui"}), CoquiTTS)

    print("TEST_OK")
    print("text:", sonuc.metin)
    print("pcm_bytes:", len(sonuc.pcm))


if __name__ == "__main__":
    test_coqui_tts()

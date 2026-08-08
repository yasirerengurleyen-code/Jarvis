"""voice/tts/piper_tts.py birim testi (mock)."""

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
from voice.tts.piper_tts import PiperTTS, piper_olustur
from voice.tts.taban import TtsAyarlari


def _yaz_wav(yol: str, ornek: int = 1000, sr: int = 22050) -> None:
    with wave.open(yol, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x01" * ornek)


def test_piper_tts() -> None:
    logger_yapilandir(zorla=True)

    ayar = TtsAyarlari(motor="piper", voice="tr_TR-dfki-medium")
    tts = PiperTTS(ayar)

    with patch("voice.tts.piper_tts._piper_python_var_mi", return_value=False):
        with patch("voice.tts.piper_tts._piper_cli_var_mi", return_value=False):
            try:
                tts.yukle()
                raise AssertionError("VoiceError bekleniyordu")
            except VoiceError as exc:
                assert "Piper bulunamadı" in exc.mesaj

    # Python modu — model + synthesize_wav mock
    tts2 = PiperTTS(ayar)
    tts2._mod = "python"
    tts2._yuklendi = True

    with tempfile.TemporaryDirectory() as td:
        model = Path(td) / "voice.onnx"
        model.write_bytes(b"fake")
        tts2.model_yolu = str(model)

        voice = MagicMock()

        def _synth_wav(metin, wf):  # noqa: ANN001
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x10\x00" * 500)

        voice.synthesize_wav.side_effect = _synth_wav
        tts2._voice = voice

        sonuc = tts2.konus("Merhaba Jarvis")
        assert sonuc.metin == "Merhaba Jarvis"
        assert sonuc.motor == "piper"
        assert len(sonuc.pcm) > 0
        assert sonuc.ham["mode"] == "python"

    # Model yok
    tts3 = PiperTTS(ayar)
    tts3._mod = "python"
    tts3._yuklendi = True
    tts3._voice = MagicMock()
    try:
        tts3.konus("test")
        raise AssertionError("model yok hatası bekleniyordu")
    except VoiceError as exc:
        assert "model" in exc.mesaj.lower() or "Model" in exc.mesaj

    assert isinstance(piper_olustur({"voice": "x"}), PiperTTS)

    print("TEST_OK")
    print("pcm_bytes:", len(sonuc.pcm))
    print("mode:", sonuc.ham["mode"])


if __name__ == "__main__":
    test_piper_tts()

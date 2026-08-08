"""voice/stt/openai_whisper_stt.py birim testi (mock model)."""

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
from voice.stt.openai_whisper_stt import OpenAIWhisperSTT, openai_whisper_olustur
from voice.stt.taban import SttAyarlari


def test_openai_whisper_stt() -> None:
    logger_yapilandir(zorla=True)

    ayar = SttAyarlari(motor="openai_whisper", model_size="tiny", dil="tr")
    stt = OpenAIWhisperSTT(ayar)

    with patch("voice.stt.openai_whisper_stt._openai_whisper_var_mi", return_value=False):
        try:
            stt.yukle()
            raise AssertionError("VoiceError bekleniyordu")
        except VoiceError as exc:
            assert "openai-whisper" in exc.mesaj

    stt2 = OpenAIWhisperSTT(ayar)
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {
        "text": "  Sistemler çevrimiçi. ",
        "language": "tr",
        "segments": [{"end": 1.5}],
    }
    stt2._model = mock_model
    stt2._yuklendi = True

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        yol = tmp.name
    with wave.open(yol, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 800)

    try:
        mock_model.transcribe.side_effect = [
            {
                "text": "  Sistemler çevrimiçi. ",
                "language": "tr",
                "segments": [{"end": 1.5}],
            },
            {
                "text": "PCM ok",
                "language": "tr",
                "segments": [{"end": 0.5}],
            },
        ]
        sonuc = stt2.dosya_coz(yol)
        assert sonuc.metin == "Sistemler çevrimiçi."
        assert sonuc.motor == "openai_whisper"
        assert sonuc.sure_saniye == 1.5

        pcm_sonuc = stt2.pcm_coz(b"\x00\x00" * 400)
        assert pcm_sonuc.metin == "PCM ok"
    finally:
        Path(yol).unlink(missing_ok=True)

    assert isinstance(openai_whisper_olustur({"model_size": "base"}), OpenAIWhisperSTT)

    print("TEST_OK")
    print("text:", sonuc.metin)
    print("engine:", sonuc.motor)


if __name__ == "__main__":
    test_openai_whisper_stt()

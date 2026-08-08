"""voice/stt/faster_whisper_stt.py birim testi (mock model)."""

from __future__ import annotations

import sys
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import VoiceError
from core.logger import logger_yapilandir
from voice.stt.faster_whisper_stt import FasterWhisperSTT, faster_whisper_olustur
from voice.stt.taban import SttAyarlari


class _Seg:
    def __init__(self, text: str) -> None:
        self.text = text


def test_faster_whisper_stt() -> None:
    logger_yapilandir(zorla=True)

    ayar = SttAyarlari(motor="faster_whisper", model_size="tiny", dil="tr")
    stt = FasterWhisperSTT(ayar)

    with patch("voice.stt.faster_whisper_stt._faster_whisper_var_mi", return_value=False):
        try:
            stt.yukle()
            raise AssertionError("VoiceError bekleniyordu")
        except VoiceError as exc:
            assert "faster-whisper" in exc.mesaj

    # Model enjekte (paket olmadan dosya/pcm yolu test edilir)
    stt2 = FasterWhisperSTT(ayar)
    mock_model = MagicMock()
    info = SimpleNamespace(language="tr", language_probability=0.91, duration=1.2)
    mock_model.transcribe.return_value = (
        iter([_Seg(" Merhaba Jarvis "), _Seg("hazır")]),
        info,
    )
    stt2._model = mock_model
    stt2._yuklendi = True

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        yol = tmp.name
    with wave.open(yol, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)

    try:
        # pcm_coz ikinci transcribe için yeni iterator gerekir
        mock_model.transcribe.side_effect = [
            (iter([_Seg(" Merhaba Jarvis "), _Seg("hazır")]), info),
            (iter([_Seg("PCM test")]), info),
        ]
        sonuc = stt2.dosya_coz(yol)
        assert sonuc.metin == "Merhaba Jarvis hazır"
        assert sonuc.dil == "tr"
        assert sonuc.guven == 0.91
        assert sonuc.motor == "faster_whisper"

        pcm_sonuc = stt2.pcm_coz(b"\x00\x00" * 800, ornek_hizi=16000)
        assert pcm_sonuc.metin == "PCM test"
    finally:
        Path(yol).unlink(missing_ok=True)

    assert isinstance(faster_whisper_olustur({"model_size": "base"}), FasterWhisperSTT)

    print("TEST_OK")
    print("text:", sonuc.metin)
    print("confidence:", sonuc.guven)


if __name__ == "__main__":
    test_faster_whisper_stt()

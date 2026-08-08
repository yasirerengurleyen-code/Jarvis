# WhiteCore AI paketi: voice.tts
"""Metinden konuşmaya motorları."""

from voice.tts.coqui_tts import CoquiTTS, coqui_olustur
from voice.tts.piper_tts import PiperTTS, piper_olustur
from voice.tts.taban import TTSMotoru, SahteTTS, TtsAyarlari, TtsSonucu

__all__ = [
    "TtsSonucu",
    "TtsAyarlari",
    "TTSMotoru",
    "SahteTTS",
    "PiperTTS",
    "piper_olustur",
    "CoquiTTS",
    "coqui_olustur",
]

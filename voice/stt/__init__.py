# WhiteCore AI paketi: voice.stt
"""Konuşmadan metne motorları."""

from voice.stt.faster_whisper_stt import FasterWhisperSTT, faster_whisper_olustur
from voice.stt.openai_whisper_stt import OpenAIWhisperSTT, openai_whisper_olustur
from voice.stt.taban import STTMotoru, SahteSTT, SttAyarlari, SttSonucu

__all__ = [
    "SttSonucu",
    "SttAyarlari",
    "STTMotoru",
    "SahteSTT",
    "FasterWhisperSTT",
    "faster_whisper_olustur",
    "OpenAIWhisperSTT",
    "openai_whisper_olustur",
]

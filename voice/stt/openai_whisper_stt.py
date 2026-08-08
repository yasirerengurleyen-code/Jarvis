"""
voice/stt/openai_whisper_stt.py
-------------------------------
OpenAI Whisper (openai-whisper) STT motoru — fallback.

Görev:
- Faster Whisper yoksa veya config fallback seçiliyse kullanmak
- PCM / dosyadan transkripsiyon
- openai-whisper yüklü değilse açık VoiceError

Kurulum (isteğe bağlı):
    pip install openai-whisper
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any, Optional

from core.exceptions import VoiceError
from core.logger import logger_al
from voice.stt.taban import STTMotoru, SttAyarlari, SttSonucu

log = logger_al("voice.stt.openai_whisper")


def _openai_whisper_var_mi() -> bool:
    try:
        import whisper  # noqa: F401

        return True
    except ImportError:
        return False


class OpenAIWhisperSTT(STTMotoru):
    """openai-whisper (GitHub OpenAI Whisper) tabanlı STT."""

    ad = "openai_whisper"

    def __init__(self, ayarlar: Optional[SttAyarlari] = None) -> None:
        super().__init__(ayarlar or SttAyarlari(motor="openai_whisper"))
        self._model: Any = None

    def _yukle_impl(self) -> None:
        if not _openai_whisper_var_mi():
            raise VoiceError(
                "openai-whisper yüklü değil. Kurulum: pip install openai-whisper",
                detay={"engine": self.ad},
                logla=False,
            )
        import whisper

        cihaz = self.ayarlar.device
        # whisper.load_model device: cuda / cpu
        try:
            self._model = whisper.load_model(self.ayarlar.model_size, device=cihaz)
        except Exception as exc:
            raise VoiceError(
                f"OpenAI Whisper model yüklenemedi: {exc}",
                detay={
                    "engine": self.ad,
                    "model": self.ayarlar.model_size,
                    "hata": str(exc),
                },
            ) from exc

    def pcm_coz(
        self,
        pcm: bytes,
        *,
        ornek_hizi: Optional[int] = None,
        dil: Optional[str] = None,
    ) -> SttSonucu:
        self.yukle()
        self.dogrula_pcm(pcm)
        sr = int(ornek_hizi or self.ayarlar.ornek_hizi)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            yol = tmp.name
        try:
            self._pcm_wav_yaz(yol, pcm, sr)
            return self.dosya_coz(yol, dil=dil)
        finally:
            Path(yol).unlink(missing_ok=True)

    def dosya_coz(
        self,
        yol: str,
        *,
        dil: Optional[str] = None,
    ) -> SttSonucu:
        self.yukle()
        if self._model is None:
            raise VoiceError(
                "OpenAI Whisper modeli hazır değil",
                detay={"engine": self.ad},
            )
        if not Path(yol).exists():
            raise VoiceError(
                f"Ses dosyası bulunamadı: {yol}",
                detay={"engine": self.ad, "path": yol},
            )

        dil_kodu = dil or self.ayarlar.dil
        language = None if dil_kodu in {"", "auto", "none"} else dil_kodu

        try:
            sonuc = self._model.transcribe(
                yol,
                language=language,
                fp16=False,
                verbose=False,
            )
            metin = str(sonuc.get("text", "")).strip()
            tespit = sonuc.get("language") or dil_kodu
            # Segment süreleri
            segs = sonuc.get("segments") or []
            sure = 0.0
            if segs:
                sure = float(segs[-1].get("end", 0.0) or 0.0)
            return SttSonucu(
                metin=metin,
                dil=str(tespit),
                guven=0.0,  # openai-whisper genel skor vermez
                motor=self.ad,
                sure_saniye=sure,
                ham={
                    "language": tespit,
                    "segment_count": len(segs),
                },
            )
        except VoiceError:
            raise
        except Exception as exc:
            raise VoiceError(
                f"OpenAI Whisper çözümleme hatası: {exc}",
                detay={"engine": self.ad, "hata": str(exc)},
            ) from exc

    @staticmethod
    def _pcm_wav_yaz(yol: str, pcm: bytes, ornek_hizi: int) -> None:
        with wave.open(yol, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(ornek_hizi)
            wf.writeframes(pcm)


def openai_whisper_olustur(
    ayar_dict: Optional[dict[str, Any]] = None,
    *,
    dil: str = "tr",
) -> OpenAIWhisperSTT:
    veri = dict(ayar_dict or {})
    veri.setdefault("engine", "openai_whisper")
    return OpenAIWhisperSTT(SttAyarlari.sozlukten(veri, dil=dil))


__all__ = ["OpenAIWhisperSTT", "openai_whisper_olustur"]

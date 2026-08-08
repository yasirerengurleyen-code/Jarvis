"""
voice/stt/faster_whisper_stt.py
-------------------------------
Faster Whisper STT motoru.

Görev:
- PCM (int16 mono) veya ses dosyasını metne çevirmek
- config.voice.stt ayarlarını kullanmak (model_size, device, compute_type)
- faster-whisper yüklü değilse açık VoiceError vermek

Kurulum (isteğe bağlı):
    pip install faster-whisper
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any, Optional

from core.exceptions import VoiceError
from core.logger import logger_al
from voice.stt.taban import STTMotoru, SttAyarlari, SttSonucu

log = logger_al("voice.stt.faster_whisper")


def _faster_whisper_var_mi() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False


class FasterWhisperSTT(STTMotoru):
    """faster-whisper tabanlı STT."""

    ad = "faster_whisper"

    def __init__(self, ayarlar: Optional[SttAyarlari] = None) -> None:
        super().__init__(ayarlar or SttAyarlari())
        self._model: Any = None

    def _yukle_impl(self) -> None:
        if not _faster_whisper_var_mi():
            raise VoiceError(
                "faster-whisper yüklü değil. Kurulum: pip install faster-whisper",
                detay={"engine": self.ad},
                logla=False,
            )
        from faster_whisper import WhisperModel

        try:
            self._model = WhisperModel(
                self.ayarlar.model_size,
                device=self.ayarlar.device,
                compute_type=self.ayarlar.compute_type,
            )
        except Exception as exc:
            raise VoiceError(
                f"Faster Whisper model yüklenemedi: {exc}",
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
        # faster-whisper dosya veya numpy ister — geçici wav
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
                "Faster Whisper modeli hazır değil",
                detay={"engine": self.ad},
            )
        if not Path(yol).exists():
            raise VoiceError(
                f"Ses dosyası bulunamadı: {yol}",
                detay={"engine": self.ad, "path": yol},
            )

        dil_kodu = dil or self.ayarlar.dil
        # 'tr' gibi kısa kodlar; auto için None
        language = None if dil_kodu in {"", "auto", "none"} else dil_kodu

        try:
            segments, info = self._model.transcribe(
                yol,
                language=language,
                beam_size=1,
                vad_filter=True,
            )
            parcalar: list[str] = []
            for seg in segments:
                parcalar.append(seg.text.strip())
            metin = " ".join(p for p in parcalar if p).strip()
            tespit_dil = getattr(info, "language", dil_kodu) or dil_kodu
            olasilik = float(getattr(info, "language_probability", 0.0) or 0.0)
            sure = float(getattr(info, "duration", 0.0) or 0.0)
            return SttSonucu(
                metin=metin,
                dil=str(tespit_dil),
                guven=olasilik,
                motor=self.ad,
                sure_saniye=sure,
                ham={
                    "language": tespit_dil,
                    "language_probability": olasilik,
                    "duration": sure,
                },
            )
        except VoiceError:
            raise
        except Exception as exc:
            raise VoiceError(
                f"Faster Whisper çözümleme hatası: {exc}",
                detay={"engine": self.ad, "hata": str(exc)},
            ) from exc

    @staticmethod
    def _pcm_wav_yaz(yol: str, pcm: bytes, ornek_hizi: int) -> None:
        with wave.open(yol, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(ornek_hizi)
            wf.writeframes(pcm)


def faster_whisper_olustur(
    ayar_dict: Optional[dict[str, Any]] = None,
    *,
    dil: str = "tr",
) -> FasterWhisperSTT:
    veri = dict(ayar_dict or {})
    return FasterWhisperSTT(SttAyarlari.sozlukten(veri, dil=dil))


__all__ = ["FasterWhisperSTT", "faster_whisper_olustur"]

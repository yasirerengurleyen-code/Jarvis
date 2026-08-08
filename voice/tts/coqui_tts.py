"""
voice/tts/coqui_tts.py
----------------------
Coqui TTS motoru (fallback).

Görev:
- Metni Coqui TTS ile PCM / WAV'a çevirmek
- Piper yoksa veya config fallback seçiliyse kullanmak
- TTS paketi yoksa net VoiceError

Kurulum (isteğe bağlı):
    pip install TTS
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any, Optional

from core.exceptions import VoiceError
from core.logger import logger_al
from voice.tts.taban import TTSMotoru, TtsAyarlari, TtsSonucu

log = logger_al("voice.tts.coqui")


def _coqui_var_mi() -> bool:
    try:
        from TTS.api import TTS  # noqa: F401

        return True
    except ImportError:
        return False


class CoquiTTS(TTSMotoru):
    """Coqui TTS (TTS.api) motoru."""

    ad = "coqui"

    def __init__(
        self,
        ayarlar: Optional[TtsAyarlari] = None,
        *,
        model_adi: Optional[str] = None,
    ) -> None:
        super().__init__(ayarlar or TtsAyarlari(motor="coqui", fallback="coqui"))
        # voice alanı model adı olarak da kullanılabilir
        self.model_adi = model_adi or self.ayarlar.voice or "tts_models/tr/common-voice/glow-tts"
        self._tts: Any = None

    def _yukle_impl(self) -> None:
        if not _coqui_var_mi():
            raise VoiceError(
                "Coqui TTS yüklü değil. Kurulum: pip install TTS",
                detay={"engine": self.ad},
                logla=False,
            )
        from TTS.api import TTS

        try:
            self._tts = TTS(model_name=self.model_adi, progress_bar=False)
        except Exception as exc:
            raise VoiceError(
                f"Coqui model yüklenemedi: {exc}",
                detay={
                    "engine": self.ad,
                    "model": self.model_adi,
                    "hata": str(exc),
                },
            ) from exc

    def konus(
        self,
        metin: str,
        *,
        speed: Optional[float] = None,
        voice: Optional[str] = None,
    ) -> TtsSonucu:
        self.yukle()
        temiz = self.dogrula_metin(metin)
        if self._tts is None:
            raise VoiceError(
                "Coqui TTS modeli hazır değil",
                detay={"engine": self.ad},
            )

        hiz = float(speed if speed is not None else self.ayarlar.speed)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name

        try:
            # Çoğu Coqui modeli tts_to_file kullanır
            kwargs: dict[str, Any] = {"text": temiz, "file_path": out}
            # speaker / language opsiyonel
            if voice:
                kwargs["speaker"] = voice
            try:
                self._tts.tts_to_file(**kwargs)
            except TypeError:
                # Daha sade imza
                self._tts.tts_to_file(text=temiz, file_path=out)

            pcm, sr = self._wav_oku(out)
            return TtsSonucu(
                metin=temiz,
                pcm=pcm,
                ornek_hizi=sr,
                dosya_yolu=out,
                motor=self.ad,
                sure_saniye=len(pcm) / 2 / float(sr) if sr else 0.0,
                ham={
                    "model": self.model_adi,
                    "speed": hiz,
                    "voice": voice,
                },
            )
        except VoiceError:
            Path(out).unlink(missing_ok=True)
            raise
        except Exception as exc:
            Path(out).unlink(missing_ok=True)
            raise VoiceError(
                f"Coqui sentez hatası: {exc}",
                detay={"engine": self.ad, "hata": str(exc)},
            ) from exc

    @staticmethod
    def _wav_oku(yol: str) -> tuple[bytes, int]:
        with wave.open(yol, "rb") as wf:
            return wf.readframes(wf.getnframes()), int(wf.getframerate())


def coqui_olustur(
    ayar_dict: Optional[dict[str, Any]] = None,
    *,
    model_adi: Optional[str] = None,
) -> CoquiTTS:
    ayar = TtsAyarlari.sozlukten(dict(ayar_dict or {}))
    return CoquiTTS(ayar, model_adi=model_adi)


__all__ = ["CoquiTTS", "coqui_olustur"]

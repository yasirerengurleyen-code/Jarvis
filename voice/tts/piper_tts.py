"""
voice/tts/piper_tts.py
----------------------
Piper TTS motoru (birincil).

Görev:
- Metni Piper ile PCM / WAV'a çevirmek
- config.voice.tts.voice model adını kullanmak
- piper paketi veya piper CLI yoksa net VoiceError

Kurulum seçenekleri:
    pip install piper-tts
    # veya sistemde `piper` komutu
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Optional

from core.exceptions import VoiceError
from core.logger import logger_al
from voice.tts.taban import TTSMotoru, TtsAyarlari, TtsSonucu

log = logger_al("voice.tts.piper")


def _piper_python_var_mi() -> bool:
    try:
        import piper  # noqa: F401

        return True
    except ImportError:
        try:
            from piper import PiperVoice  # noqa: F401

            return True
        except ImportError:
            return False


def _piper_cli_var_mi() -> bool:
    return shutil.which("piper") is not None


class PiperTTS(TTSMotoru):
    """Piper metinden-konuşmaya motoru."""

    ad = "piper"

    def __init__(
        self,
        ayarlar: Optional[TtsAyarlari] = None,
        *,
        model_yolu: Optional[str] = None,
    ) -> None:
        super().__init__(ayarlar or TtsAyarlari(motor="piper"))
        self.model_yolu = model_yolu
        self._voice: Any = None
        self._mod: str = "none"  # python | cli | none

    def _yukle_impl(self) -> None:
        if _piper_python_var_mi():
            self._mod = "python"
            # Model yolu verilmişse yükle; yoksa ilk konus()'ta kontrol
            if self.model_yolu and Path(self.model_yolu).exists():
                self._python_model_yukle(self.model_yolu)
            else:
                log.info("Piper Python API hazır (model yolu konuşmada çözülecek)")
            return
        if _piper_cli_var_mi():
            self._mod = "cli"
            log.info("Piper CLI kullanılacak")
            return
        raise VoiceError(
            "Piper bulunamadı. Kurulum: pip install piper-tts veya piper CLI ekleyin",
            detay={"engine": self.ad},
            logla=False,
        )

    def _python_model_yukle(self, yol: str) -> None:
        try:
            from piper import PiperVoice

            self._voice = PiperVoice.load(yol)
        except Exception as exc:
            raise VoiceError(
                f"Piper model yüklenemedi: {exc}",
                detay={"engine": self.ad, "model": yol, "hata": str(exc)},
            ) from exc

    def _model_yolunu_coz(self, voice: Optional[str]) -> Optional[str]:
        if self.model_yolu and Path(self.model_yolu).exists():
            return self.model_yolu
        # assets/models/piper/<voice>.onnx varsayımı
        ad = voice or self.ayarlar.voice
        adaylar = [
            Path("assets") / "models" / "piper" / f"{ad}.onnx",
            Path("assets") / "models" / f"{ad}.onnx",
            Path(ad),
        ]
        for p in adaylar:
            if p.exists():
                return str(p)
        return None

    def konus(
        self,
        metin: str,
        *,
        speed: Optional[float] = None,
        voice: Optional[str] = None,
    ) -> TtsSonucu:
        self.yukle()
        temiz = self.dogrula_metin(metin)
        hiz = float(speed if speed is not None else self.ayarlar.speed)

        if self._mod == "python":
            return self._konus_python(temiz, hiz=hiz, voice=voice)
        if self._mod == "cli":
            return self._konus_cli(temiz, hiz=hiz, voice=voice)
        raise VoiceError(
            "Piper motoru hazır değil",
            detay={"engine": self.ad, "mode": self._mod},
        )

    def _konus_python(
        self,
        metin: str,
        *,
        hiz: float,
        voice: Optional[str],
    ) -> TtsSonucu:
        yol = self._model_yolunu_coz(voice)
        if yol is None:
            raise VoiceError(
                "Piper model dosyası bulunamadı "
                f"(voice={voice or self.ayarlar.voice}). "
                "assets/models/piper/ altına .onnx koyun veya model_yolu verin.",
                detay={"engine": self.ad, "voice": voice or self.ayarlar.voice},
            )
        if self._voice is None:
            self._python_model_yukle(yol)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        try:
            # piper API sürümleri değişebilir — synthesize_wav / synthesize
            try:
                with wave.open(out, "wb") as wf:
                    self._voice.synthesize_wav(metin, wf)
            except AttributeError:
                audio_stream = self._voice.synthesize(metin)
                # fallback: ham int16 birleştir
                parcalar = []
                ornek_hizi = getattr(
                    getattr(self._voice, "config", None),
                    "sample_rate",
                    self.ayarlar.ornek_hizi,
                )
                for chunk in audio_stream:
                    if hasattr(chunk, "audio_int16_bytes"):
                        parcalar.append(chunk.audio_int16_bytes)
                    elif isinstance(chunk, (bytes, bytearray)):
                        parcalar.append(bytes(chunk))
                pcm = b"".join(parcalar)
                self._pcm_wav_yaz(out, pcm, int(ornek_hizi))

            pcm, sr = self._wav_oku(out)
            # speed: basit yeniden örnekleme yok; meta olarak sakla
            return TtsSonucu(
                metin=metin,
                pcm=pcm,
                ornek_hizi=sr,
                dosya_yolu=out,
                motor=self.ad,
                sure_saniye=len(pcm) / 2 / float(sr) if sr else 0.0,
                ham={"mode": "python", "speed": hiz, "model": yol},
            )
        except VoiceError:
            Path(out).unlink(missing_ok=True)
            raise
        except Exception as exc:
            Path(out).unlink(missing_ok=True)
            raise VoiceError(
                f"Piper sentez hatası: {exc}",
                detay={"engine": self.ad, "hata": str(exc)},
            ) from exc

    def _konus_cli(
        self,
        metin: str,
        *,
        hiz: float,
        voice: Optional[str],
    ) -> TtsSonucu:
        model = self._model_yolunu_coz(voice)
        if model is None:
            raise VoiceError(
                "Piper CLI için model (.onnx) bulunamadı",
                detay={"engine": self.ad, "voice": voice or self.ayarlar.voice},
            )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        try:
            cmd = [
                "piper",
                "--model",
                model,
                "--output_file",
                out,
            ]
            # length_scale ~ 1/speed
            if hiz and hiz > 0:
                cmd.extend(["--length_scale", str(1.0 / hiz)])
            proc = subprocess.run(
                cmd,
                input=metin.encode("utf-8"),
                capture_output=True,
                check=False,
                timeout=120,
            )
            if proc.returncode != 0:
                raise VoiceError(
                    f"Piper CLI hata: {proc.stderr.decode('utf-8', errors='replace')[:300]}",
                    detay={"engine": self.ad, "code": proc.returncode},
                )
            pcm, sr = self._wav_oku(out)
            return TtsSonucu(
                metin=metin,
                pcm=pcm,
                ornek_hizi=sr,
                dosya_yolu=out,
                motor=self.ad,
                sure_saniye=len(pcm) / 2 / float(sr) if sr else 0.0,
                ham={"mode": "cli", "speed": hiz, "model": model},
            )
        except VoiceError:
            Path(out).unlink(missing_ok=True)
            raise
        except Exception as exc:
            Path(out).unlink(missing_ok=True)
            raise VoiceError(
                f"Piper CLI çalıştırılamadı: {exc}",
                detay={"engine": self.ad, "hata": str(exc)},
            ) from exc

    @staticmethod
    def _wav_oku(yol: str) -> tuple[bytes, int]:
        with wave.open(yol, "rb") as wf:
            sr = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
            return pcm, int(sr)

    @staticmethod
    def _pcm_wav_yaz(yol: str, pcm: bytes, ornek_hizi: int) -> None:
        with wave.open(yol, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(ornek_hizi)
            wf.writeframes(pcm)


def piper_olustur(
    ayar_dict: Optional[dict[str, Any]] = None,
    *,
    model_yolu: Optional[str] = None,
) -> PiperTTS:
    return PiperTTS(TtsAyarlari.sozlukten(dict(ayar_dict or {})), model_yolu=model_yolu)


__all__ = ["PiperTTS", "piper_olustur"]

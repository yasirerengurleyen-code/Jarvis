"""
voice/stt/taban.py
------------------
Konuşmadan metne (STT) ortak arayüz.

Görev:
- Faster Whisper / OpenAI Whisper sağlayıcıları için ABC
- PCM baytlarından ve dosyadan transkripsiyon sözleşmesi
- Standart SttSonucu modeli
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.exceptions import VoiceError
from core.logger import logger_al

log = logger_al("voice.stt.taban")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SttSonucu:
    """STT çıktısı."""

    metin: str
    dil: str = "tr"
    guven: float = 0.0
    motor: str = ""
    sure_saniye: float = 0.0
    zaman: str = field(default_factory=_utc)
    ham: dict[str, Any] = field(default_factory=dict)

    @property
    def bos_mu(self) -> bool:
        return not (self.metin or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.metin,
            "language": self.dil,
            "confidence": self.guven,
            "engine": self.motor,
            "duration_seconds": self.sure_saniye,
            "timestamp": self.zaman,
            "raw": self.ham,
        }


@dataclass
class SttAyarlari:
    """STT yapılandırması (config.voice.stt)."""

    motor: str = "faster_whisper"
    fallback: str = "openai_whisper"
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    dil: str = "tr"
    ornek_hizi: int = 16000

    @classmethod
    def sozlukten(cls, veri: dict[str, Any], *, dil: str = "tr") -> "SttAyarlari":
        return cls(
            motor=str(veri.get("engine", "faster_whisper")),
            fallback=str(veri.get("fallback", "openai_whisper")),
            model_size=str(veri.get("model_size", "base")),
            device=str(veri.get("device", "cpu")),
            compute_type=str(veri.get("compute_type", "int8")),
            dil=dil,
            ornek_hizi=int(veri.get("sample_rate", 16000) or 16000),
        )


class STTMotoru(ABC):
    """Konuşmadan metne motor tabanı."""

    ad: str = "stt"

    def __init__(self, ayarlar: SttAyarlari) -> None:
        self.ayarlar = ayarlar
        self._yuklendi = False
        self._log = logger_al(f"voice.stt.{self.ad}")

    @property
    def hazir(self) -> bool:
        return self._yuklendi

    def yukle(self) -> None:
        """Model / bağımlılıkları yükler (idempotent)."""
        if self._yuklendi:
            return
        self._yukle_impl()
        self._yuklendi = True
        self._log.info("STT motoru yüklendi: %s", self.ad)

    def _yukle_impl(self) -> None:
        """Alt sınıf override eder."""

    @abstractmethod
    def pcm_coz(
        self,
        pcm: bytes,
        *,
        ornek_hizi: Optional[int] = None,
        dil: Optional[str] = None,
    ) -> SttSonucu:
        """Ham PCM (int16 mono) → metin."""

    def dosya_coz(
        self,
        yol: str,
        *,
        dil: Optional[str] = None,
    ) -> SttSonucu:
        """Ses dosyasını çözer; varsayılan PCM yoluna düşer."""
        raise VoiceError(
            f"{self.ad} dosya_coz desteklemiyor — alt sınıf uygulamalı",
            detay={"engine": self.ad, "path": yol},
        )

    def dogrula_pcm(self, pcm: bytes) -> None:
        if not pcm:
            raise VoiceError(
                "STT için boş PCM verisi",
                detay={"engine": self.ad},
            )


class SahteSTT(STTMotoru):
    """
    Test / geliştirme STT'si.

    PCM içeriğine bakmadan sabit veya enjekte metin döner.
    """

    ad = "sahte"

    def __init__(
        self,
        ayarlar: Optional[SttAyarlari] = None,
        *,
        varsayilan_metin: str = "",
    ) -> None:
        super().__init__(ayarlar or SttAyarlari(motor="sahte"))
        self.varsayilan_metin = varsayilan_metin
        self._sonraki: Optional[str] = None

    def _yukle_impl(self) -> None:
        return

    def sonraki_metni_ayarla(self, metin: str) -> None:
        self._sonraki = metin

    def pcm_coz(
        self,
        pcm: bytes,
        *,
        ornek_hizi: Optional[int] = None,
        dil: Optional[str] = None,
    ) -> SttSonucu:
        self.yukle()
        self.dogrula_pcm(pcm)
        metin = self._sonraki if self._sonraki is not None else self.varsayilan_metin
        self._sonraki = None
        return SttSonucu(
            metin=metin,
            dil=dil or self.ayarlar.dil,
            guven=1.0 if metin else 0.0,
            motor=self.ad,
            sure_saniye=len(pcm) / 2 / float(ornek_hizi or self.ayarlar.ornek_hizi),
            ham={"bytes": len(pcm)},
        )


__all__ = [
    "SttSonucu",
    "SttAyarlari",
    "STTMotoru",
    "SahteSTT",
]

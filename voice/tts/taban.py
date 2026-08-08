"""
voice/tts/taban.py
------------------
Metinden konuşmaya (TTS) ortak arayüz.

Görev:
- Piper / Coqui TTS sağlayıcıları için ABC
- Standart TtsSonucu modeli (PCM veya dosya yolu)
- SahteTTS ile testsiz bağımlılık
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.exceptions import VoiceError
from core.logger import logger_al

log = logger_al("voice.tts.taban")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TtsSonucu:
    """TTS çıktısı."""

    metin: str
    pcm: bytes = b""
    ornek_hizi: int = 22050
    kanallar: int = 1
    dosya_yolu: Optional[str] = None
    motor: str = ""
    sure_saniye: float = 0.0
    zaman: str = field(default_factory=_utc)
    ham: dict[str, Any] = field(default_factory=dict)

    @property
    def bos_mu(self) -> bool:
        return not self.pcm and not self.dosya_yolu

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.metin,
            "sample_rate": self.ornek_hizi,
            "channels": self.kanallar,
            "bytes": len(self.pcm),
            "path": self.dosya_yolu,
            "engine": self.motor,
            "duration_seconds": self.sure_saniye,
            "timestamp": self.zaman,
        }


@dataclass
class TtsAyarlari:
    """TTS yapılandırması (config.voice.tts)."""

    motor: str = "piper"
    fallback: str = "coqui"
    voice: str = "tr_TR-dfki-medium"
    speed: float = 1.0
    style: str = "robotic_natural"
    ornek_hizi: int = 22050

    @classmethod
    def sozlukten(cls, veri: dict[str, Any]) -> "TtsAyarlari":
        return cls(
            motor=str(veri.get("engine", "piper")),
            fallback=str(veri.get("fallback", "coqui")),
            voice=str(veri.get("voice", "tr_TR-dfki-medium")),
            speed=float(veri.get("speed", 1.0) or 1.0),
            style=str(veri.get("style", "robotic_natural")),
            ornek_hizi=int(veri.get("sample_rate", 22050) or 22050),
        )


class TTSMotoru(ABC):
    """Metinden konuşmaya motor tabanı."""

    ad: str = "tts"

    def __init__(self, ayarlar: TtsAyarlari) -> None:
        self.ayarlar = ayarlar
        self._yuklendi = False
        self._log = logger_al(f"voice.tts.{self.ad}")

    @property
    def hazir(self) -> bool:
        return self._yuklendi

    def yukle(self) -> None:
        if self._yuklendi:
            return
        self._yukle_impl()
        self._yuklendi = True
        self._log.info("TTS motoru yüklendi: %s", self.ad)

    def _yukle_impl(self) -> None:
        """Alt sınıf override eder."""

    @abstractmethod
    def konus(
        self,
        metin: str,
        *,
        speed: Optional[float] = None,
        voice: Optional[str] = None,
    ) -> TtsSonucu:
        """Metni sese çevirir."""

    def dogrula_metin(self, metin: str) -> str:
        temiz = (metin or "").strip()
        if not temiz:
            raise VoiceError(
                "TTS için boş metin",
                detay={"engine": self.ad},
            )
        return temiz


class SahteTTS(TTSMotoru):
    """
    Test TTS'si — sessiz (veya bip benzeri) kısa PCM üretir.

    Gerçek ses çalmaz; kuyruk / orkestrasyon testleri için yeterlidir.
    """

    ad = "sahte"

    def __init__(self, ayarlar: Optional[TtsAyarlari] = None) -> None:
        super().__init__(ayarlar or TtsAyarlari(motor="sahte"))

    def _yukle_impl(self) -> None:
        return

    def konus(
        self,
        metin: str,
        *,
        speed: Optional[float] = None,
        voice: Optional[str] = None,
    ) -> TtsSonucu:
        self.yukle()
        temiz = self.dogrula_metin(metin)
        sr = self.ayarlar.ornek_hizi
        # ~0.1 sn sessizlik; uzunluk metne orantılı üst sınır
        ornek = max(int(sr * 0.1), min(len(temiz) * 40, sr))
        pcm = b"\x00\x00" * ornek
        return TtsSonucu(
            metin=temiz,
            pcm=pcm,
            ornek_hizi=sr,
            motor=self.ad,
            sure_saniye=ornek / float(sr),
            ham={
                "speed": speed or self.ayarlar.speed,
                "voice": voice or self.ayarlar.voice,
            },
        )


__all__ = [
    "TtsSonucu",
    "TtsAyarlari",
    "TTSMotoru",
    "SahteTTS",
]

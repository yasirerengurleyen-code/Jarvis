"""
core/exceptions.py
------------------
WhiteCore AI özel hata sınıfları.

Görev:
- Tüm modüller için tutarlı, kodlu ve zaman damgalı hatalar sağlamak
- Logger ve audit sistemiyle entegre çalışmak
- Mobil / ağ / eklenti gibi gelecekteki modüllere genişleyebilir temel sunmak

Kullanım:
    from core.exceptions import ConfigurationError

    raise ConfigurationError(
        "config.json okunamadı",
        modul="config",
        detay={"dosya": "config/config.json"},
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import audit_yaz, logger_al

log = logger_al("core.exceptions")


class WhiteCoreError(Exception):
    """
    WhiteCore AI ana hata sınıfı.

    Tüm özel hatalar bundan türer.
    """

    varsayilan_kod: str = "WC_0001"
    varsayilan_modul: str = "core"

    def __init__(
        self,
        mesaj: str,
        *,
        kod: Optional[str] = None,
        modul: Optional[str] = None,
        detay: Optional[dict[str, Any]] = None,
        logla: bool = True,
        audit: bool = False,
    ) -> None:
        self.mesaj = mesaj
        self.kod = kod or self.varsayilan_kod
        self.modul = modul or self.varsayilan_modul
        self.detay = detay or {}
        self.zaman_damgasi = datetime.now(timezone.utc).isoformat()

        super().__init__(self.mesaj)

        if logla:
            self._loggera_yaz()
        if audit:
            self._audite_yaz()

    def _loggera_yaz(self) -> None:
        """Hatayı merkezi logger'a yazar."""
        modul_log = logger_al(self.modul)
        modul_log.error(
            "[%s] %s | detay=%s | zaman=%s",
            self.kod,
            self.mesaj,
            self.detay,
            self.zaman_damgasi,
        )

    def _audite_yaz(self) -> None:
        """Kritik hataları audit.jsonl dosyasına kaydeder."""
        audit_yaz(
            "exception",
            modul=self.modul,
            seviye="ERROR",
            detay={
                "kod": self.kod,
                "mesaj": self.mesaj,
                "exception": self.__class__.__name__,
                **self.detay,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """Hatayı serileştirilebilir sözlüğe çevirir."""
        return {
            "type": self.__class__.__name__,
            "code": self.kod,
            "message": self.mesaj,
            "module": self.modul,
            "timestamp": self.zaman_damgasi,
            "detail": self.detay,
        }

    def __str__(self) -> str:
        return f"[{self.kod}] ({self.modul}) {self.mesaj}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(kod={self.kod!r}, "
            f"modul={self.modul!r}, mesaj={self.mesaj!r})"
        )


class ConfigurationError(WhiteCoreError):
    """Yapılandırma / config.json hataları."""

    varsayilan_kod = "CFG_0001"
    varsayilan_modul = "config"


class AIProviderError(WhiteCoreError):
    """LLM sağlayıcı (OpenAI, Ollama, Gemini vb.) hataları."""

    varsayilan_kod = "AI_0001"
    varsayilan_modul = "brain"


class VoiceError(WhiteCoreError):
    """STT / TTS ses sistemi hataları."""

    varsayilan_kod = "VOICE_0001"
    varsayilan_modul = "voice"


class WakeWordError(WhiteCoreError):
    """Wake word (Jarvis) dinleme / tanıma hataları."""

    varsayilan_kod = "WAKE_0001"
    varsayilan_modul = "voice.wakeword"


class PluginError(WhiteCoreError):
    """Eklenti yükleme veya çalıştırma hataları."""

    varsayilan_kod = "PLG_0001"
    varsayilan_modul = "plugins"


class NetworkError(WhiteCoreError):
    """Ağ, WebSocket ve cihaz keşfi hataları."""

    varsayilan_kod = "NET_0001"
    varsayilan_modul = "network"


class MobileBridgeError(WhiteCoreError):
    """Mobil köprü / telefon eşleştirme hataları (iskelet)."""

    varsayilan_kod = "MOB_0001"
    varsayilan_modul = "mobile"


class SecurityError(WhiteCoreError):
    """Güvenlik, onay ve yetkilendirme hataları."""

    varsayilan_kod = "SEC_0001"
    varsayilan_modul = "security"

    def __init__(
        self,
        mesaj: str,
        *,
        kod: Optional[str] = None,
        modul: Optional[str] = None,
        detay: Optional[dict[str, Any]] = None,
        logla: bool = True,
        audit: bool = True,
    ) -> None:
        # Güvenlik hataları varsayılan olarak audit'e yazılır
        super().__init__(
            mesaj,
            kod=kod,
            modul=modul,
            detay=detay,
            logla=logla,
            audit=audit,
        )


class VisionError(WhiteCoreError):
    """Kamera, OCR ve görüntü analizi hataları."""

    varsayilan_kod = "VIS_0001"
    varsayilan_modul = "vision"


class MemoryError(WhiteCoreError):
    """
    SQLite hafıza / uzun süreli bellek hataları.

    Not: Python yerleşik MemoryError ile karıştırılmamalıdır.
    Tercihen: ``from core.exceptions import MemoryError as HafizaHatasi``
    """

    varsayilan_kod = "MEM_0001"
    varsayilan_modul = "memory"


__all__ = [
    "WhiteCoreError",
    "ConfigurationError",
    "AIProviderError",
    "VoiceError",
    "WakeWordError",
    "PluginError",
    "NetworkError",
    "MobileBridgeError",
    "SecurityError",
    "VisionError",
    "MemoryError",
]

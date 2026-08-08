"""
brain/providers/taban.py
------------------------
Tüm LLM sağlayıcıları için ortak arayüz (ABC).

Görev:
- OpenAI / Ollama / Gemini / Claude / DeepSeek / OpenRouter / Local
  sağlayıcılarının aynı sözleşmeyi uygulamasını sağlamak
- Tek satır config değişikliği ile sağlayıcı değiştirmeye zemin hazırlamak

Bu dosya yalnızca sözleşme + veri modelleridir; gerçek API çağrısı yok.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from core.base import Mesaj, MesajRolu
from core.exceptions import AIProviderError
from core.logger import logger_al

log = logger_al("brain.providers.taban")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SaglayiciYaniti:
    """Sağlayıcıdan dönen standart yanıt."""

    icerik: str
    model: str
    saglayici: str
    kullanim: dict[str, Any] = field(default_factory=dict)
    ham: dict[str, Any] = field(default_factory=dict)
    zaman: str = field(default_factory=_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.icerik,
            "model": self.model,
            "provider": self.saglayici,
            "usage": self.kullanim,
            "raw": self.ham,
            "timestamp": self.zaman,
        }

    def mesaj_olarak(self) -> Mesaj:
        """Yanıtı çekirdek Mesaj modeline çevirir."""
        return Mesaj.asistan(
            self.icerik,
            provider=self.saglayici,
            model=self.model,
            usage=self.kullanim,
        )


@dataclass
class SaglayiciAyarlari:
    """Sağlayıcı yapılandırması (config.json ai.providers.*)."""

    ad: str
    model: str
    enabled: bool = True
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    ekstra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def sozlukten(cls, ad: str, veri: dict[str, Any]) -> "SaglayiciAyarlari":
        bilinen = {
            "model",
            "enabled",
            "api_key",
            "api_key_env",
            "base_url",
            "temperature",
            "max_tokens",
            "timeout_seconds",
        }
        ekstra = {k: v for k, v in veri.items() if k not in bilinen}
        return cls(
            ad=ad,
            model=str(veri.get("model", "")),
            enabled=bool(veri.get("enabled", True)),
            api_key=veri.get("api_key"),
            api_key_env=veri.get("api_key_env"),
            base_url=veri.get("base_url"),
            temperature=float(veri.get("temperature", 0.7)),
            max_tokens=int(veri.get("max_tokens", 2048)),
            timeout_seconds=float(veri.get("timeout_seconds", 60.0)),
            ekstra=ekstra,
        )


class LLMSaglayici(ABC):
    """
    Yapay zekâ sağlayıcı tabanı.

    Alt sınıflar yalnızca ``_istek_gonder`` ve gerekirse ``saglik_kontrolu``
    uygular; ortak doğrulama burada kalır.
    """

    ad: str = "base"

    def __init__(self, ayarlar: SaglayiciAyarlari) -> None:
        self.ayarlar = ayarlar
        self._log = logger_al(f"brain.providers.{ayarlar.ad}")

    @property
    def model(self) -> str:
        return self.ayarlar.model

    @property
    def etkin_mi(self) -> bool:
        return self.ayarlar.enabled

    def dogrula(self) -> None:
        """Temel ayar doğrulaması; geçersizse AIProviderError."""
        if not self.ayarlar.model:
            raise AIProviderError(
                "Model adı boş",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad},
            )
        if not self.ayarlar.enabled:
            raise AIProviderError(
                f"Sağlayıcı kapalı: {self.ad}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "enabled": False},
            )

    async def sohbet(
        self,
        mesajlar: Sequence[Mesaj],
        *,
        sistem_promptu: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> SaglayiciYaniti:
        """
        Sohbet tamamlaması üretir.

        Args:
            mesajlar: Konuşma geçmişi (kullanıcı / asistan / sistem)
            sistem_promptu: İsteğe bağlı sistem mesajı (başa eklenir)
            temperature: Ayarları geçersiz kılar
            max_tokens: Ayarları geçersiz kılar
        """
        self.dogrula()
        if not mesajlar and not sistem_promptu:
            raise AIProviderError(
                "Boş mesaj listesi",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad},
            )

        paket = self._mesajlari_hazirla(mesajlar, sistem_promptu)
        self._log.debug(
            "Sohbet isteği: model=%s mesaj_sayisi=%s",
            self.model,
            len(paket),
        )

        try:
            return await self._istek_gonder(
                paket,
                temperature=temperature if temperature is not None else self.ayarlar.temperature,
                max_tokens=max_tokens if max_tokens is not None else self.ayarlar.max_tokens,
            )
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(
                f"Sağlayıcı hatası: {exc}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "model": self.model, "hata": str(exc)},
            ) from exc

    async def tek_tur(
        self,
        kullanici_metni: str,
        *,
        sistem_promptu: Optional[str] = None,
    ) -> SaglayiciYaniti:
        """Tek kullanıcı mesajı ile hızlı sohbet."""
        return await self.sohbet(
            [Mesaj.kullanici(kullanici_metni)],
            sistem_promptu=sistem_promptu,
        )

    @abstractmethod
    async def _istek_gonder(
        self,
        mesajlar: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> SaglayiciYaniti:
        """Sağlayıcıya özgü HTTP / SDK çağrısı."""

    async def saglik_kontrolu(self) -> bool:
        """
        Sağlayıcının erişilebilir olup olmadığını kontrol eder.

        Varsayılan: True (alt sınıflar override eder).
        """
        return self.ayarlar.enabled and bool(self.ayarlar.model)

    def _mesajlari_hazirla(
        self,
        mesajlar: Sequence[Mesaj],
        sistem_promptu: Optional[str],
    ) -> list[dict[str, str]]:
        """Mesajları OpenAI uyumlu role/content listesine çevirir."""
        paket: list[dict[str, str]] = []
        if sistem_promptu:
            paket.append({"role": MesajRolu.SISTEM.value, "content": sistem_promptu})

        for m in mesajlar:
            rol = m.rol.value if isinstance(m.rol, MesajRolu) else str(m.rol)
            # tool rolünü çoğu sağlayıcıda user'a yakın tutuyoruz; alt sınıf override edebilir
            if rol == MesajRolu.ARAC.value:
                rol = MesajRolu.KULLANICI.value
            paket.append({"role": rol, "content": m.icerik})
        return paket

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(ad={self.ad!r}, model={self.model!r})"


__all__ = [
    "SaglayiciYaniti",
    "SaglayiciAyarlari",
    "LLMSaglayici",
]

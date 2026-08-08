"""
brain/providers/openai_saglayici.py
-----------------------------------
OpenAI Chat Completions sağlayıcısı.

Görev:
- config.json ai.providers.openai ayarlarıyla OpenAI API'ye bağlanmak
- Ortam değişkeninden API anahtarı okumak (OPENAI_API_KEY)
- Standart SaglayiciYaniti döndürmek

Bağımlılık: standart kütüphane (urllib). İsteğe bağlı httpx hızlandırır.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from brain.providers.taban import LLMSaglayici, SaglayiciAyarlari, SaglayiciYaniti
from core.exceptions import AIProviderError
from core.logger import logger_al

log = logger_al("brain.providers.openai")


class OpenAISaglayici(LLMSaglayici):
    """OpenAI (ve OpenAI-uyumlu) chat tamamlaması."""

    ad = "openai"

    def __init__(self, ayarlar: SaglayiciAyarlari) -> None:
        super().__init__(ayarlar)
        self.ad = ayarlar.ad or "openai"

    def _api_anahtari(self) -> str:
        if self.ayarlar.api_key:
            return self.ayarlar.api_key
        env_adi = self.ayarlar.api_key_env or "OPENAI_API_KEY"
        deger = os.environ.get(env_adi, "").strip()
        if not deger:
            raise AIProviderError(
                f"API anahtarı bulunamadı ({env_adi})",
                modul=f"brain.providers.{self.ad}",
                detay={"env": env_adi, "provider": self.ad},
            )
        return deger

    def _endpoint(self) -> str:
        taban = (self.ayarlar.base_url or "https://api.openai.com/v1").rstrip("/")
        if taban.endswith("/chat/completions"):
            return taban
        return f"{taban}/chat/completions"

    def dogrula(self) -> None:
        super().dogrula()
        # Anahtar yoksa erken fail (sağlık kontrolünde de kullanılır)
        self._api_anahtari()

    async def _istek_gonder(
        self,
        mesajlar: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> SaglayiciYaniti:
        govde = {
            "model": self.model,
            "messages": mesajlar,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        ham = await asyncio.to_thread(self._http_post, govde)
        return self._yaniti_ayristir(ham)

    def _http_post(self, govde: dict[str, Any]) -> dict[str, Any]:
        """Senkron HTTP POST (thread pool'da çalışır)."""
        veri = json.dumps(govde).encode("utf-8")
        istek = urllib.request.Request(
            self._endpoint(),
            data=veri,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_anahtari()}",
                "User-Agent": "WhiteCoreAI/0.1",
            },
        )
        timeout = self.ayarlar.timeout_seconds
        try:
            with urllib.request.urlopen(istek, timeout=timeout) as yanit:
                metin = yanit.read().decode("utf-8")
                return json.loads(metin)
        except urllib.error.HTTPError as exc:
            govde_hata = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(
                f"OpenAI HTTP {exc.code}: {govde_hata[:300]}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "status": exc.code, "body": govde_hata[:500]},
            ) from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(
                f"OpenAI bağlantı hatası: {exc.reason}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc.reason)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "OpenAI yanıtı geçersiz JSON",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc)},
            ) from exc

    def _yaniti_ayristir(self, ham: dict[str, Any]) -> SaglayiciYaniti:
        try:
            secimler = ham["choices"]
            icerik = secimler[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "OpenAI yanıt formatı beklenmeyen",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "raw_keys": list(ham.keys())},
            ) from exc

        kullanim = ham.get("usage") or {}
        return SaglayiciYaniti(
            icerik=str(icerik).strip(),
            model=str(ham.get("model", self.model)),
            saglayici=self.ad,
            kullanim=dict(kullanim) if isinstance(kullanim, dict) else {},
            ham=ham,
        )

    async def saglik_kontrolu(self) -> bool:
        if not self.ayarlar.enabled or not self.ayarlar.model:
            return False
        try:
            self._api_anahtari()
            return True
        except AIProviderError:
            return False


def openai_olustur(ayar_dict: Optional[dict[str, Any]] = None) -> OpenAISaglayici:
    """config dict veya varsayılanlarla OpenAISaglayici üretir."""
    veri = dict(ayar_dict or {})
    if "model" not in veri:
        veri["model"] = "gpt-4o-mini"
    if "api_key_env" not in veri:
        veri["api_key_env"] = "OPENAI_API_KEY"
    if "base_url" not in veri:
        veri["base_url"] = "https://api.openai.com/v1"
    ayar = SaglayiciAyarlari.sozlukten("openai", veri)
    return OpenAISaglayici(ayar)


__all__ = ["OpenAISaglayici", "openai_olustur"]

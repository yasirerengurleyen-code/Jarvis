"""
brain/providers/gemini_saglayici.py
-----------------------------------
Google Gemini API sağlayıcısı.

Görev:
- Gemini generateContent uç noktasına bağlanmak
- GEMINI_API_KEY ortam değişkeninden anahtar okumak
- Mesaj geçmişini Gemini contents formatına çevirmek

Bağımlılık: standart kütüphane (urllib).
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from brain.providers.taban import LLMSaglayici, SaglayiciAyarlari, SaglayiciYaniti
from core.exceptions import AIProviderError
from core.logger import logger_al

log = logger_al("brain.providers.gemini")

_VARSAYILAN_TABAN = "https://generativelanguage.googleapis.com/v1beta"


class GeminiSaglayici(LLMSaglayici):
    """Google Gemini generateContent sağlayıcısı."""

    ad = "gemini"

    def __init__(self, ayarlar: SaglayiciAyarlari) -> None:
        super().__init__(ayarlar)
        self.ad = ayarlar.ad or "gemini"

    def _api_anahtari(self) -> str:
        if self.ayarlar.api_key:
            return self.ayarlar.api_key
        env_adi = self.ayarlar.api_key_env or "GEMINI_API_KEY"
        deger = os.environ.get(env_adi, "").strip()
        if not deger:
            raise AIProviderError(
                f"API anahtarı bulunamadı ({env_adi})",
                modul=f"brain.providers.{self.ad}",
                detay={"env": env_adi, "provider": self.ad},
            )
        return deger

    def _endpoint(self) -> str:
        taban = (self.ayarlar.base_url or _VARSAYILAN_TABAN).rstrip("/")
        model = self.model
        # Tam URL verilmişse olduğu gibi kullan
        if "/models/" in taban and ":generateContent" in taban:
            return taban
        return f"{taban}/models/{urllib.parse.quote(model, safe='')}:generateContent"

    def dogrula(self) -> None:
        super().dogrula()
        self._api_anahtari()

    async def _istek_gonder(
        self,
        mesajlar: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> SaglayiciYaniti:
        sistem, contents = self._gemini_formatina(mesajlar)
        govde: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if sistem:
            govde["systemInstruction"] = {
                "parts": [{"text": sistem}],
            }

        ham = await asyncio.to_thread(self._http_post, govde)
        return self._yaniti_ayristir(ham)

    def _gemini_formatina(
        self,
        mesajlar: list[dict[str, str]],
    ) -> tuple[Optional[str], list[dict[str, Any]]]:
        """OpenAI role/content → Gemini systemInstruction + contents."""
        sistem: Optional[str] = None
        contents: list[dict[str, Any]] = []

        for m in mesajlar:
            rol = m.get("role", "user")
            metin = m.get("content", "")
            if rol == "system":
                sistem = f"{sistem}\n{metin}".strip() if sistem else metin
                continue
            # Gemini: user | model
            gemini_rol = "model" if rol == "assistant" else "user"
            contents.append(
                {
                    "role": gemini_rol,
                    "parts": [{"text": metin}],
                }
            )

        if not contents:
            raise AIProviderError(
                "Gemini için kullanıcı/asistan mesajı yok",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad},
            )
        return sistem, contents

    def _http_post(self, govde: dict[str, Any]) -> dict[str, Any]:
        anahtar = self._api_anahtari()
        url = f"{self._endpoint()}?key={urllib.parse.quote(anahtar)}"
        veri = json.dumps(govde).encode("utf-8")
        istek = urllib.request.Request(
            url,
            data=veri,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "WhiteCoreAI/0.1",
            },
        )
        try:
            with urllib.request.urlopen(istek, timeout=self.ayarlar.timeout_seconds) as yanit:
                return json.loads(yanit.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            govde_hata = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(
                f"Gemini HTTP {exc.code}: {govde_hata[:300]}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "status": exc.code, "body": govde_hata[:500]},
            ) from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(
                f"Gemini bağlantı hatası: {exc.reason}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc.reason)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "Gemini yanıtı geçersiz JSON",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc)},
            ) from exc

    def _yaniti_ayristir(self, ham: dict[str, Any]) -> SaglayiciYaniti:
        try:
            adaylar = ham["candidates"]
            parts = adaylar[0]["content"]["parts"]
            metinler = [str(p.get("text", "")) for p in parts if "text" in p]
            icerik = "".join(metinler).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "Gemini yanıt formatı beklenmeyen",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "raw_keys": list(ham.keys())},
            ) from exc

        kullanim = ham.get("usageMetadata") or {}
        return SaglayiciYaniti(
            icerik=icerik,
            model=self.model,
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


def gemini_olustur(ayar_dict: Optional[dict[str, Any]] = None) -> GeminiSaglayici:
    """config dict veya varsayılanlarla GeminiSaglayici üretir."""
    veri = dict(ayar_dict or {})
    if "model" not in veri:
        veri["model"] = "gemini-1.5-flash"
    if "api_key_env" not in veri:
        veri["api_key_env"] = "GEMINI_API_KEY"
    if "base_url" not in veri:
        veri["base_url"] = _VARSAYILAN_TABAN
    ayar = SaglayiciAyarlari.sozlukten("gemini", veri)
    return GeminiSaglayici(ayar)


__all__ = ["GeminiSaglayici", "gemini_olustur"]

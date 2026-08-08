"""
brain/providers/claude_saglayici.py
-----------------------------------
Anthropic Claude API sağlayıcısı.

Görev:
- Claude Messages API'ye bağlanmak
- ANTHROPIC_API_KEY ortam değişkeninden anahtar okumak
- Sistem promptunu ayrı alan olarak göndermek

Bağımlılık: standart kütüphane (urllib).
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

log = logger_al("brain.providers.claude")

_VARSAYILAN_TABAN = "https://api.anthropic.com"
_ANTHROPIC_SURUM = "2023-06-01"


class ClaudeSaglayici(LLMSaglayici):
    """Anthropic Claude Messages API sağlayıcısı."""

    ad = "claude"

    def __init__(self, ayarlar: SaglayiciAyarlari) -> None:
        super().__init__(ayarlar)
        self.ad = ayarlar.ad or "claude"

    def _api_anahtari(self) -> str:
        if self.ayarlar.api_key:
            return self.ayarlar.api_key
        env_adi = self.ayarlar.api_key_env or "ANTHROPIC_API_KEY"
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
        if taban.endswith("/v1/messages"):
            return taban
        return f"{taban}/v1/messages"

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
        sistem, claude_mesajlar = self._claude_formatina(mesajlar)
        govde: dict[str, Any] = {
            "model": self.model,
            "messages": claude_mesajlar,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if sistem:
            govde["system"] = sistem

        ham = await asyncio.to_thread(self._http_post, govde)
        return self._yaniti_ayristir(ham)

    def _claude_formatina(
        self,
        mesajlar: list[dict[str, str]],
    ) -> tuple[Optional[str], list[dict[str, str]]]:
        """OpenAI format → Claude system + messages (user/assistant)."""
        sistem: Optional[str] = None
        sonuc: list[dict[str, str]] = []

        for m in mesajlar:
            rol = m.get("role", "user")
            metin = m.get("content", "")
            if rol == "system":
                sistem = f"{sistem}\n{metin}".strip() if sistem else metin
                continue
            if rol not in {"user", "assistant"}:
                rol = "user"
            sonuc.append({"role": rol, "content": metin})

        if not sonuc:
            raise AIProviderError(
                "Claude için kullanıcı/asistan mesajı yok",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad},
            )
        # Claude ilk mesajın user olmasını bekler
        if sonuc[0]["role"] != "user":
            sonuc.insert(0, {"role": "user", "content": "."})
        return sistem, sonuc

    def _http_post(self, govde: dict[str, Any]) -> dict[str, Any]:
        veri = json.dumps(govde).encode("utf-8")
        istek = urllib.request.Request(
            self._endpoint(),
            data=veri,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_anahtari(),
                "anthropic-version": _ANTHROPIC_SURUM,
                "User-Agent": "WhiteCoreAI/0.1",
            },
        )
        try:
            with urllib.request.urlopen(istek, timeout=self.ayarlar.timeout_seconds) as yanit:
                return json.loads(yanit.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            govde_hata = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(
                f"Claude HTTP {exc.code}: {govde_hata[:300]}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "status": exc.code, "body": govde_hata[:500]},
            ) from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(
                f"Claude bağlantı hatası: {exc.reason}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc.reason)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "Claude yanıtı geçersiz JSON",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc)},
            ) from exc

    def _yaniti_ayristir(self, ham: dict[str, Any]) -> SaglayiciYaniti:
        try:
            bloklar = ham["content"]
            metinler = [
                str(b.get("text", ""))
                for b in bloklar
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            icerik = "".join(metinler).strip()
        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                "Claude yanıt formatı beklenmeyen",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "raw_keys": list(ham.keys())},
            ) from exc

        kullanim = ham.get("usage") or {}
        return SaglayiciYaniti(
            icerik=icerik,
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


def claude_olustur(ayar_dict: Optional[dict[str, Any]] = None) -> ClaudeSaglayici:
    """config dict veya varsayılanlarla ClaudeSaglayici üretir."""
    veri = dict(ayar_dict or {})
    if "model" not in veri:
        veri["model"] = "claude-3-5-sonnet-latest"
    if "api_key_env" not in veri:
        veri["api_key_env"] = "ANTHROPIC_API_KEY"
    if "base_url" not in veri:
        veri["base_url"] = _VARSAYILAN_TABAN
    ayar = SaglayiciAyarlari.sozlukten("claude", veri)
    return ClaudeSaglayici(ayar)


__all__ = ["ClaudeSaglayici", "claude_olustur"]

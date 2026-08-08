"""
brain/providers/ollama_saglayici.py
-----------------------------------
Ollama yerel LLM sağlayıcısı.

Görev:
- Yerel Ollama sunucusuna (varsayılan http://127.0.0.1:11434) bağlanmak
- /api/chat uç noktası ile sohbet tamamlaması üretmek
- API anahtarı gerektirmeden çalışmak

Bağımlılık: standart kütüphane (urllib).
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Optional

from brain.providers.taban import LLMSaglayici, SaglayiciAyarlari, SaglayiciYaniti
from core.exceptions import AIProviderError
from core.logger import logger_al

log = logger_al("brain.providers.ollama")


class OllamaSaglayici(LLMSaglayici):
    """Ollama chat API sağlayıcısı."""

    ad = "ollama"

    def __init__(self, ayarlar: SaglayiciAyarlari) -> None:
        super().__init__(ayarlar)
        self.ad = ayarlar.ad or "ollama"

    def _taban_url(self) -> str:
        return (self.ayarlar.base_url or "http://127.0.0.1:11434").rstrip("/")

    def _chat_endpoint(self) -> str:
        return f"{self._taban_url()}/api/chat"

    def _tags_endpoint(self) -> str:
        return f"{self._taban_url()}/api/tags"

    def dogrula(self) -> None:
        super().dogrula()
        # Ollama için API anahtarı zorunlu değil

    async def _istek_gonder(
        self,
        mesajlar: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> SaglayiciYaniti:
        # Ollama: stream=false, options.temperature / num_predict
        govde: dict[str, Any] = {
            "model": self.model,
            "messages": mesajlar,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        ham = await asyncio.to_thread(self._http_post, self._chat_endpoint(), govde)
        return self._yaniti_ayristir(ham)

    def _http_post(self, url: str, govde: dict[str, Any]) -> dict[str, Any]:
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
                f"Ollama HTTP {exc.code}: {govde_hata[:300]}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "status": exc.code, "body": govde_hata[:500]},
            ) from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(
                f"Ollama bağlantı hatası: {exc.reason}",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc.reason)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "Ollama yanıtı geçersiz JSON",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "hata": str(exc)},
            ) from exc

    def _http_get(self, url: str) -> dict[str, Any]:
        istek = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "WhiteCoreAI/0.1"},
        )
        try:
            with urllib.request.urlopen(istek, timeout=min(10.0, self.ayarlar.timeout_seconds)) as yanit:
                return json.loads(yanit.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            return {}

    def _yaniti_ayristir(self, ham: dict[str, Any]) -> SaglayiciYaniti:
        try:
            mesaj = ham["message"]
            icerik = mesaj["content"]
        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                "Ollama yanıt formatı beklenmeyen",
                modul=f"brain.providers.{self.ad}",
                detay={"provider": self.ad, "raw_keys": list(ham.keys())},
            ) from exc

        kullanim = {
            "prompt_eval_count": ham.get("prompt_eval_count"),
            "eval_count": ham.get("eval_count"),
        }
        return SaglayiciYaniti(
            icerik=str(icerik).strip(),
            model=str(ham.get("model", self.model)),
            saglayici=self.ad,
            kullanim={k: v for k, v in kullanim.items() if v is not None},
            ham=ham,
        )

    async def saglik_kontrolu(self) -> bool:
        if not self.ayarlar.enabled or not self.ayarlar.model:
            return False
        veri = await asyncio.to_thread(self._http_get, self._tags_endpoint())
        modeller = veri.get("models")
        if not isinstance(modeller, list):
            return False
        # Model adı tam veya önek eşleşmesi (llama3.2 == llama3.2:latest)
        hedef = self.model.split(":")[0]
        for m in modeller:
            ad = str(m.get("name", ""))
            if ad == self.model or ad.startswith(f"{hedef}:"):
                return True
        # Sunucu ayakta ama model listede yoksa yine de erişilebilir sayılabilir
        return len(modeller) >= 0 and "models" in veri


def ollama_olustur(ayar_dict: Optional[dict[str, Any]] = None) -> OllamaSaglayici:
    """config dict veya varsayılanlarla OllamaSaglayici üretir."""
    veri = dict(ayar_dict or {})
    if "model" not in veri:
        veri["model"] = "llama3.2"
    if "base_url" not in veri:
        veri["base_url"] = "http://127.0.0.1:11434"
    if "enabled" not in veri:
        veri["enabled"] = True
    ayar = SaglayiciAyarlari.sozlukten("ollama", veri)
    return OllamaSaglayici(ayar)


__all__ = ["OllamaSaglayici", "ollama_olustur"]

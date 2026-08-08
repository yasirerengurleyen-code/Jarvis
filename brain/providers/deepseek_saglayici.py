"""
brain/providers/deepseek_saglayici.py
-------------------------------------
DeepSeek API sağlayıcısı.

Görev:
- DeepSeek Chat Completions API'ye bağlanmak (OpenAI uyumlu)
- DEEPSEEK_API_KEY ortam değişkeninden anahtar okumak

DeepSeek uç noktası OpenAI ile aynı protokolü kullandığı için
OpenAISaglayici üzerine ince bir katman olarak uygulanır.
"""

from __future__ import annotations

from typing import Any, Optional

from brain.providers.openai_saglayici import OpenAISaglayici
from brain.providers.taban import SaglayiciAyarlari
from core.logger import logger_al

log = logger_al("brain.providers.deepseek")

_VARSAYILAN_TABAN = "https://api.deepseek.com"
_VARSAYILAN_MODEL = "deepseek-chat"


class DeepSeekSaglayici(OpenAISaglayici):
    """DeepSeek — OpenAI uyumlu chat tamamlaması."""

    ad = "deepseek"

    def __init__(self, ayarlar: SaglayiciAyarlari) -> None:
        # base_url / api_key_env varsayılanlarını doldur
        if not ayarlar.base_url:
            ayarlar.base_url = _VARSAYILAN_TABAN
        if not ayarlar.api_key_env:
            ayarlar.api_key_env = "DEEPSEEK_API_KEY"
        if not ayarlar.model:
            ayarlar.model = _VARSAYILAN_MODEL
        super().__init__(ayarlar)
        self.ad = ayarlar.ad or "deepseek"


def deepseek_olustur(ayar_dict: Optional[dict[str, Any]] = None) -> DeepSeekSaglayici:
    """config dict veya varsayılanlarla DeepSeekSaglayici üretir."""
    veri = dict(ayar_dict or {})
    if "model" not in veri:
        veri["model"] = _VARSAYILAN_MODEL
    if "api_key_env" not in veri:
        veri["api_key_env"] = "DEEPSEEK_API_KEY"
    if "base_url" not in veri:
        veri["base_url"] = _VARSAYILAN_TABAN
    ayar = SaglayiciAyarlari.sozlukten("deepseek", veri)
    return DeepSeekSaglayici(ayar)


__all__ = ["DeepSeekSaglayici", "deepseek_olustur"]

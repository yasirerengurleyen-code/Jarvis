"""
brain/providers/fabrika.py
--------------------------
LLM sağlayıcı fabrikası (provider sistemi).

Görev:
- config.json içindeki ai.default_provider ile sağlayıcı seçmek
- Tek satır değişiklikle OpenAI / Ollama / Gemini / Claude /
  DeepSeek / OpenRouter / Local arasında geçiş
- Ortak sıcaklık / token / timeout değerlerini birleştirmek

Kullanım:
    from brain.providers.fabrika import saglayici_olustur

    sag = saglayici_olustur()           # config default
    sag = saglayici_olustur("ollama")   # tek satır geçiş
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from brain.providers.claude_saglayici import ClaudeSaglayici
from brain.providers.deepseek_saglayici import DeepSeekSaglayici
from brain.providers.gemini_saglayici import GeminiSaglayici
from brain.providers.ollama_saglayici import OllamaSaglayici
from brain.providers.openai_saglayici import OpenAISaglayici
from brain.providers.taban import LLMSaglayici, SaglayiciAyarlari
from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import AIProviderError, ConfigurationError
from core.logger import logger_al

log = logger_al("brain.providers.fabrika")


def _openai_uyumlu(ad: str, veri: dict[str, Any]) -> OpenAISaglayici:
    """OpenAI protokolü kullanan sağlayıcılar (openrouter, local)."""
    ayar = SaglayiciAyarlari.sozlukten(ad, veri)
    sag = OpenAISaglayici(ayar)
    sag.ad = ad
    return sag


def _kurucu_openai(_: str, veri: dict[str, Any]) -> LLMSaglayici:
    return OpenAISaglayici(SaglayiciAyarlari.sozlukten("openai", veri))


def _kurucu_ollama(_: str, veri: dict[str, Any]) -> LLMSaglayici:
    return OllamaSaglayici(SaglayiciAyarlari.sozlukten("ollama", veri))


def _kurucu_gemini(_: str, veri: dict[str, Any]) -> LLMSaglayici:
    return GeminiSaglayici(SaglayiciAyarlari.sozlukten("gemini", veri))


def _kurucu_claude(_: str, veri: dict[str, Any]) -> LLMSaglayici:
    return ClaudeSaglayici(SaglayiciAyarlari.sozlukten("claude", veri))


def _kurucu_deepseek(_: str, veri: dict[str, Any]) -> LLMSaglayici:
    return DeepSeekSaglayici(SaglayiciAyarlari.sozlukten("deepseek", veri))


Kurucu = Callable[[str, dict[str, Any]], LLMSaglayici]

_KAYIT: dict[str, Kurucu] = {
    "openai": _kurucu_openai,
    "ollama": _kurucu_ollama,
    "gemini": _kurucu_gemini,
    "claude": _kurucu_claude,
    "deepseek": _kurucu_deepseek,
    "openrouter": _openai_uyumlu,
    "local": _openai_uyumlu,
}


def desteklenen_saglayicilar() -> list[str]:
    """Kayıtlı sağlayıcı adlarını döner."""
    return sorted(_KAYIT.keys())


def _global_ai_birlestir(
    provider_veri: dict[str, Any],
    ai_bolum: dict[str, Any],
) -> dict[str, Any]:
    """Sağlayıcı ayarına üst düzey ai.* varsayılanlarını uygular."""
    birlesik = dict(provider_veri)
    if "temperature" not in birlesik and "temperature" in ai_bolum:
        birlesik["temperature"] = ai_bolum["temperature"]
    if "max_tokens" not in birlesik and "max_tokens" in ai_bolum:
        birlesik["max_tokens"] = ai_bolum["max_tokens"]
    if "timeout_seconds" not in birlesik and "timeout_seconds" in ai_bolum:
        birlesik["timeout_seconds"] = ai_bolum["timeout_seconds"]
    # Model: provider'da yoksa global ai.model
    if not birlesik.get("model") and ai_bolum.get("model"):
        birlesik["model"] = ai_bolum["model"]
    # enabled yoksa True say
    if "enabled" not in birlesik:
        birlesik["enabled"] = True
    return birlesik


def saglayici_olustur(
    ad: Optional[str] = None,
    *,
    ayar_yonetici: Optional[Ayarlar] = None,
    override: Optional[dict[str, Any]] = None,
) -> LLMSaglayici:
    """
    İsim veya config varsayılanına göre LLM sağlayıcısı üretir.

    Args:
        ad: openai | ollama | gemini | claude | deepseek | openrouter | local
            None ise ai.default_provider kullanılır.
        ayar_yonetici: Test için özel Ayarlar örneği
        override: Sağlayıcı ayarlarını geçici olarak ezer
    """
    cfg = ayar_yonetici or global_ayarlar
    if not cfg.yuklendi:
        try:
            cfg.yukle()
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(
                f"Ayarlar yüklenemedi: {exc}",
                detay={"hata": str(exc)},
            ) from exc

    ai = cfg.bolum("ai")
    secilen = (ad or ai.get("default_provider") or "openai").strip().lower()

    if secilen not in _KAYIT:
        raise AIProviderError(
            f"Bilinmeyen sağlayıcı: {secilen}",
            modul="brain.providers.fabrika",
            detay={
                "provider": secilen,
                "desteklenen": desteklenen_saglayicilar(),
            },
        )

    providers = ai.get("providers") or {}
    if not isinstance(providers, dict):
        providers = {}

    ham = dict(providers.get(secilen) or {})
    if override:
        ham.update(override)

    # OpenRouter / Local için makul varsayılanlar
    if secilen == "openrouter":
        ham.setdefault("base_url", "https://openrouter.ai/api/v1")
        ham.setdefault("api_key_env", "OPENROUTER_API_KEY")
        ham.setdefault("model", "openai/gpt-4o-mini")
    elif secilen == "local":
        ham.setdefault("base_url", "http://127.0.0.1:8080/v1")
        ham.setdefault("api_key_env", "LOCAL_LLM_API_KEY")
        ham.setdefault("model", "local-model")
        # Yerel sunucularda anahtar opsiyonel olabilir
        if "api_key" not in ham and not ham.get("api_key_env"):
            ham["api_key"] = "local"

    birlesik = _global_ai_birlestir(ham, ai)
    # Fabrikadan üretilirken enabled=False olsa bile oluşturmaya izin ver;
    # sohbet anında dogrula() engeller. Test / geçiş kolaylığı için
    # default_provider seçildiyse enabled True'ya çekilebilir.
    if ad is None and secilen == str(ai.get("default_provider", "")).lower():
        birlesik["enabled"] = True

    kurucu = _KAYIT[secilen]
    sag = kurucu(secilen, birlesik)
    log.info(
        "Sağlayıcı oluşturuldu: %s model=%s",
        sag.ad,
        sag.model,
    )
    return sag


__all__ = [
    "saglayici_olustur",
    "desteklenen_saglayicilar",
]

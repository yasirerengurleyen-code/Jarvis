"""brain/providers/fabrika.py birim testi."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.claude_saglayici import ClaudeSaglayici
from brain.providers.deepseek_saglayici import DeepSeekSaglayici
from brain.providers.fabrika import desteklenen_saglayicilar, saglayici_olustur
from brain.providers.gemini_saglayici import GeminiSaglayici
from brain.providers.ollama_saglayici import OllamaSaglayici
from brain.providers.openai_saglayici import OpenAISaglayici
from config.ayarlar import Ayarlar
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir


def _gecici_config() -> Path:
    veri = {
        "ai": {
            "default_provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": 100,
            "timeout_seconds": 30,
            "providers": {
                "openai": {
                    "enabled": True,
                    "api_key": "sk-test",
                    "model": "gpt-4o-mini",
                    "base_url": "https://api.openai.com/v1",
                },
                "ollama": {
                    "enabled": True,
                    "base_url": "http://127.0.0.1:11434",
                    "model": "llama3.2",
                },
                "gemini": {
                    "enabled": True,
                    "api_key": "g-test",
                    "model": "gemini-1.5-flash",
                },
                "claude": {
                    "enabled": True,
                    "api_key": "c-test",
                    "model": "claude-3-5-sonnet-latest",
                },
                "deepseek": {
                    "enabled": True,
                    "api_key": "d-test",
                    "model": "deepseek-chat",
                },
                "openrouter": {
                    "enabled": True,
                    "api_key": "or-test",
                    "model": "openai/gpt-4o-mini",
                },
                "local": {
                    "enabled": True,
                    "api_key": "local",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "model": "local-model",
                },
            },
        }
    }
    tmp = Path(tempfile.mkdtemp()) / "config.json"
    tmp.write_text(json.dumps(veri), encoding="utf-8")
    return tmp


def test_fabrika() -> None:
    logger_yapilandir(zorla=True)
    yol = _gecici_config()
    cfg = Ayarlar(yol)
    cfg.yukle()

    destek = desteklenen_saglayicilar()
    for ad in (
        "openai",
        "ollama",
        "gemini",
        "claude",
        "deepseek",
        "openrouter",
        "local",
    ):
        assert ad in destek

    # Varsayılan
    s0 = saglayici_olustur(ayar_yonetici=cfg)
    assert isinstance(s0, OpenAISaglayici)
    assert s0.ad == "openai"
    assert s0.ayarlar.temperature == 0.7

    # Tek satır geçişler
    assert isinstance(saglayici_olustur("ollama", ayar_yonetici=cfg), OllamaSaglayici)
    assert isinstance(saglayici_olustur("gemini", ayar_yonetici=cfg), GeminiSaglayici)
    assert isinstance(saglayici_olustur("claude", ayar_yonetici=cfg), ClaudeSaglayici)
    assert isinstance(saglayici_olustur("deepseek", ayar_yonetici=cfg), DeepSeekSaglayici)

    or_sag = saglayici_olustur("openrouter", ayar_yonetici=cfg)
    assert isinstance(or_sag, OpenAISaglayici)
    assert or_sag.ad == "openrouter"
    assert "openrouter.ai" in (or_sag.ayarlar.base_url or "")

    local = saglayici_olustur("local", ayar_yonetici=cfg)
    assert local.ad == "local"

    # Override
    ozel = saglayici_olustur(
        "openai",
        ayar_yonetici=cfg,
        override={"model": "gpt-4o", "temperature": 0.1},
    )
    assert ozel.model == "gpt-4o"
    assert ozel.ayarlar.temperature == 0.1

    # Bilinmeyen
    try:
        saglayici_olustur("mars", ayar_yonetici=cfg)
        raise AssertionError("AIProviderError bekleniyordu")
    except AIProviderError as exc:
        assert "Bilinmeyen" in exc.mesaj

    print("TEST_OK")
    print("desteklenen:", ", ".join(destek))
    print("default:", s0.ad, s0.model)


if __name__ == "__main__":
    test_fabrika()

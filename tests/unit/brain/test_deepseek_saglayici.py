"""brain/providers/deepseek_saglayici.py birim testi (ağsız mock)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.deepseek_saglayici import DeepSeekSaglayici, deepseek_olustur
from brain.providers.openai_saglayici import OpenAISaglayici
from brain.providers.taban import SaglayiciAyarlari
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir

FAKE = {
    "id": "chatcmpl-ds",
    "model": "deepseek-chat",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "DeepSeek hazır."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
}


def test_deepseek_saglayici() -> None:
    logger_yapilandir(zorla=True)

    ayar = SaglayiciAyarlari(
        ad="deepseek",
        model="deepseek-chat",
        enabled=True,
        api_key="sk-ds-test",
        base_url="https://api.deepseek.com",
    )
    sag = DeepSeekSaglayici(ayar)
    assert isinstance(sag, OpenAISaglayici)
    assert sag.ad == "deepseek"
    assert "deepseek.com" in sag._endpoint()
    assert sag._endpoint().endswith("/chat/completions")

    async def _run() -> None:
        with patch.object(OpenAISaglayici, "_http_post", return_value=FAKE):
            yanit = await sag.tek_tur("Merhaba")
        assert yanit.icerik == "DeepSeek hazır."
        assert yanit.saglayici == "deepseek"

        # Varsayılan env adı
        s2 = deepseek_olustur({"api_key": "k"})
        assert s2.ayarlar.api_key_env == "DEEPSEEK_API_KEY"
        assert s2.ayarlar.base_url == "https://api.deepseek.com"

        bos = DeepSeekSaglayici(
            SaglayiciAyarlari(
                ad="deepseek",
                model="deepseek-chat",
                enabled=True,
                api_key_env="WHITCORE_DS_NO_KEY",
            )
        )
        assert await bos.saglik_kontrolu() is False
        try:
            await bos.tek_tur("x")
            raise AssertionError("AIProviderError bekleniyordu")
        except AIProviderError:
            pass

    asyncio.run(_run())
    print("TEST_OK")
    print("endpoint:", sag._endpoint())
    print("inherits:", OpenAISaglayici.__name__)


if __name__ == "__main__":
    test_deepseek_saglayici()

"""brain/providers/openai_saglayici.py birim testi (ağsız mock)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.openai_saglayici import OpenAISaglayici, openai_olustur
from brain.providers.taban import SaglayiciAyarlari
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir


FAKE_RESPONSE = {
    "id": "chatcmpl-test",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Sistemler çevrimiçi, efendim."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
}


def test_openai_saglayici() -> None:
    logger_yapilandir(zorla=True)

    ayar = SaglayiciAyarlari(
        ad="openai",
        model="gpt-4o-mini",
        enabled=True,
        api_key="sk-test-fake",
        base_url="https://api.openai.com/v1",
        temperature=0.2,
        max_tokens=64,
    )
    sag = OpenAISaglayici(ayar)
    assert sag.ad == "openai"
    assert sag._endpoint().endswith("/chat/completions")

    async def _run() -> None:
        with patch.object(OpenAISaglayici, "_http_post", return_value=FAKE_RESPONSE):
            yanit = await sag.tek_tur(
                "Durum raporu",
                sistem_promptu="Sen J.A.R.V.I.S.'sin.",
            )
        assert yanit.icerik == "Sistemler çevrimiçi, efendim."
        assert yanit.saglayici == "openai"
        assert yanit.kullanim["total_tokens"] == 20
        assert await sag.saglik_kontrolu() is True

        # Anahtar yok
        bos = OpenAISaglayici(
            SaglayiciAyarlari(
                ad="openai",
                model="gpt-4o-mini",
                enabled=True,
                api_key=None,
                api_key_env="WHITCORE_TEST_NO_KEY_XYZ",
            )
        )
        assert await bos.saglik_kontrolu() is False
        try:
            await bos.tek_tur("x")
            raise AssertionError("AIProviderError bekleniyordu")
        except AIProviderError as exc:
            assert "API anahtarı" in exc.mesaj

        # Bozuk yanıt
        with patch.object(OpenAISaglayici, "_http_post", return_value={"choices": []}):
            try:
                await sag.tek_tur("x")
                raise AssertionError("format hatası bekleniyordu")
            except AIProviderError:
                pass

        # Fabrika yardımcısı
        s2 = openai_olustur({"api_key": "sk-x", "model": "gpt-4o-mini"})
        assert isinstance(s2, OpenAISaglayici)

    asyncio.run(_run())
    print("TEST_OK")
    print("endpoint:", sag._endpoint())
    print("sample:", FAKE_RESPONSE["choices"][0]["message"]["content"])


if __name__ == "__main__":
    test_openai_saglayici()

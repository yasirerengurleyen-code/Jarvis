"""brain/providers/gemini_saglayici.py birim testi (ağsız mock)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.gemini_saglayici import GeminiSaglayici, gemini_olustur
from brain.providers.taban import SaglayiciAyarlari
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir

FAKE = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [{"text": "Gemini bağlantısı hazır."}],
            }
        }
    ],
    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 4},
}


def test_gemini_saglayici() -> None:
    logger_yapilandir(zorla=True)

    ayar = SaglayiciAyarlari(
        ad="gemini",
        model="gemini-1.5-flash",
        enabled=True,
        api_key="test-gemini-key",
        temperature=0.4,
        max_tokens=256,
    )
    sag = GeminiSaglayici(ayar)
    assert "gemini-1.5-flash" in sag._endpoint()
    assert sag._endpoint().endswith(":generateContent")

    async def _run() -> None:
        with patch.object(GeminiSaglayici, "_http_post", return_value=FAKE):
            yanit = await sag.tek_tur("Merhaba", sistem_promptu="Sen J.A.R.V.I.S.'sin.")
        assert yanit.icerik == "Gemini bağlantısı hazır."
        assert yanit.saglayici == "gemini"
        assert yanit.kullanim.get("promptTokenCount") == 5

        # Format dönüşümü
        sistem, contents = sag._gemini_formatina(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ]
        )
        assert sistem == "sys"
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"

        assert await sag.saglik_kontrolu() is True

        bos = GeminiSaglayici(
            SaglayiciAyarlari(
                ad="gemini",
                model="gemini-1.5-flash",
                enabled=True,
                api_key_env="WHITCORE_GEMINI_NO_KEY",
            )
        )
        assert await bos.saglik_kontrolu() is False
        try:
            await bos.tek_tur("x")
            raise AssertionError("AIProviderError bekleniyordu")
        except AIProviderError:
            pass

        with patch.object(GeminiSaglayici, "_http_post", return_value={}):
            try:
                await sag.tek_tur("x")
                raise AssertionError("format hatası bekleniyordu")
            except AIProviderError:
                pass

        s2 = gemini_olustur({"api_key": "k", "model": "gemini-1.5-flash"})
        assert isinstance(s2, GeminiSaglayici)

    asyncio.run(_run())
    print("TEST_OK")
    print("endpoint:", sag._endpoint())
    print("sample:", FAKE["candidates"][0]["content"]["parts"][0]["text"])


if __name__ == "__main__":
    test_gemini_saglayici()

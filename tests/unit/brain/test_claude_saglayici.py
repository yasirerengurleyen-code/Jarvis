"""brain/providers/claude_saglayici.py birim testi (ağsız mock)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.claude_saglayici import ClaudeSaglayici, claude_olustur
from brain.providers.taban import SaglayiciAyarlari
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir

FAKE = {
    "id": "msg_test",
    "model": "claude-3-5-sonnet-latest",
    "role": "assistant",
    "content": [{"type": "text", "text": "Claude hazır, efendim."}],
    "usage": {"input_tokens": 11, "output_tokens": 7},
}


def test_claude_saglayici() -> None:
    logger_yapilandir(zorla=True)

    ayar = SaglayiciAyarlari(
        ad="claude",
        model="claude-3-5-sonnet-latest",
        enabled=True,
        api_key="sk-ant-test",
        temperature=0.5,
        max_tokens=256,
    )
    sag = ClaudeSaglayici(ayar)
    assert sag._endpoint().endswith("/v1/messages")

    async def _run() -> None:
        with patch.object(ClaudeSaglayici, "_http_post", return_value=FAKE):
            yanit = await sag.tek_tur("Merhaba", sistem_promptu="Sen J.A.R.V.I.S.'sin.")
        assert yanit.icerik == "Claude hazır, efendim."
        assert yanit.saglayici == "claude"
        assert yanit.kullanim.get("input_tokens") == 11

        sistem, msgs = sag._claude_formatina(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
            ]
        )
        assert sistem == "sys"
        assert msgs[0]["role"] == "user"

        assert await sag.saglik_kontrolu() is True

        bos = ClaudeSaglayici(
            SaglayiciAyarlari(
                ad="claude",
                model="claude-3-5-sonnet-latest",
                enabled=True,
                api_key_env="WHITCORE_CLAUDE_NO_KEY",
            )
        )
        assert await bos.saglik_kontrolu() is False
        try:
            await bos.tek_tur("x")
            raise AssertionError("AIProviderError bekleniyordu")
        except AIProviderError:
            pass

        with patch.object(ClaudeSaglayici, "_http_post", return_value={"content": []}):
            yanit2 = await sag.tek_tur("x")
            assert yanit2.icerik == ""

        with patch.object(ClaudeSaglayici, "_http_post", return_value={}):
            try:
                await sag.tek_tur("x")
                raise AssertionError("format hatası bekleniyordu")
            except AIProviderError:
                pass

        s2 = claude_olustur({"api_key": "k"})
        assert isinstance(s2, ClaudeSaglayici)

    asyncio.run(_run())
    print("TEST_OK")
    print("endpoint:", sag._endpoint())
    print("sample:", FAKE["content"][0]["text"])


if __name__ == "__main__":
    test_claude_saglayici()

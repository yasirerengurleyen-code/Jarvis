"""brain/providers/ollama_saglayici.py birim testi (ağsız mock)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.ollama_saglayici import OllamaSaglayici, ollama_olustur
from brain.providers.taban import SaglayiciAyarlari
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir

FAKE_CHAT = {
    "model": "llama3.2",
    "message": {"role": "assistant", "content": "Yerel sistem hazır."},
    "done": True,
    "prompt_eval_count": 10,
    "eval_count": 5,
}

FAKE_TAGS = {
    "models": [
        {"name": "llama3.2:latest"},
        {"name": "mistral:latest"},
    ]
}


def test_ollama_saglayici() -> None:
    logger_yapilandir(zorla=True)

    ayar = SaglayiciAyarlari(
        ad="ollama",
        model="llama3.2",
        enabled=True,
        base_url="http://127.0.0.1:11434",
        temperature=0.3,
        max_tokens=128,
    )
    sag = OllamaSaglayici(ayar)
    assert sag._chat_endpoint() == "http://127.0.0.1:11434/api/chat"

    async def _run() -> None:
        with patch.object(OllamaSaglayici, "_http_post", return_value=FAKE_CHAT):
            yanit = await sag.tek_tur("Merhaba")
        assert yanit.icerik == "Yerel sistem hazır."
        assert yanit.saglayici == "ollama"
        assert yanit.kullanim.get("eval_count") == 5

        with patch.object(OllamaSaglayici, "_http_get", return_value=FAKE_TAGS):
            assert await sag.saglik_kontrolu() is True

        with patch.object(OllamaSaglayici, "_http_get", return_value={}):
            assert await sag.saglik_kontrolu() is False

        with patch.object(OllamaSaglayici, "_http_post", return_value={"no": "message"}):
            try:
                await sag.tek_tur("x")
                raise AssertionError("format hatası bekleniyordu")
            except AIProviderError:
                pass

        s2 = ollama_olustur({"model": "mistral"})
        assert isinstance(s2, OllamaSaglayici)
        assert s2.model == "mistral"

    asyncio.run(_run())
    print("TEST_OK")
    print("endpoint:", sag._chat_endpoint())
    print("sample:", FAKE_CHAT["message"]["content"])


if __name__ == "__main__":
    test_ollama_saglayici()

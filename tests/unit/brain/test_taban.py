"""brain/providers/taban.py birim testi."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.taban import LLMSaglayici, SaglayiciAyarlari, SaglayiciYaniti
from core.base import Mesaj
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir


class _SahteSaglayici(LLMSaglayici):
    ad = "sahte"

    async def _istek_gonder(self, mesajlar, *, temperature, max_tokens):
        son = mesajlar[-1]["content"]
        return SaglayiciYaniti(
            icerik=f"echo:{son}",
            model=self.model,
            saglayici=self.ad,
            kullanim={"prompt_tokens": 1, "completion_tokens": 1},
            ham={"messages": mesajlar, "temperature": temperature, "max_tokens": max_tokens},
        )


def test_taban() -> None:
    logger_yapilandir(zorla=True)

    ayar = SaglayiciAyarlari.sozlukten(
        "sahte",
        {
            "model": "test-model",
            "enabled": True,
            "temperature": 0.5,
            "max_tokens": 100,
            "ozel_alan": 42,
        },
    )
    assert ayar.model == "test-model"
    assert ayar.ekstra.get("ozel_alan") == 42

    sag = _SahteSaglayici(ayar)
    assert sag.etkin_mi is True
    assert sag.model == "test-model"

    async def _run() -> None:
        yanit = await sag.tek_tur("Merhaba", sistem_promptu="Sen J.A.R.V.I.S.'sin.")
        assert yanit.icerik == "echo:Merhaba"
        assert yanit.saglayici == "sahte"
        assert yanit.ham["messages"][0]["role"] == "system"
        assert yanit.ham["temperature"] == 0.5
        m = yanit.mesaj_olarak()
        assert m.icerik == "echo:Merhaba"

        # Kapalı sağlayıcı
        kapali = _SahteSaglayici(
            SaglayiciAyarlari(ad="x", model="m", enabled=False)
        )
        try:
            await kapali.tek_tur("x")
            raise AssertionError("AIProviderError bekleniyordu")
        except AIProviderError as exc:
            assert exc.kod == "AI_0001"

        # Boş model
        bos = _SahteSaglayici(SaglayiciAyarlari(ad="y", model="", enabled=True))
        try:
            await bos.tek_tur("x")
            raise AssertionError("AIProviderError bekleniyordu")
        except AIProviderError:
            pass

        # ABC doğrudan örneklenemez
        try:
            LLMSaglayici(ayar)  # type: ignore[abstract]
            raise AssertionError("ABC örneklenmemeli")
        except TypeError:
            pass

        ok = await sag.saglik_kontrolu()
        assert ok is True

    asyncio.run(_run())
    print("TEST_OK")
    print("provider:", sag.ad, sag.model)
    print("ayar_ekstra:", ayar.ekstra)


if __name__ == "__main__":
    test_taban()

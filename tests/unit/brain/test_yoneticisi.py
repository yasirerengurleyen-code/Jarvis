"""brain/yoneticisi.py birim testi (ağsız mock sağlayıcı)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.prompts.yonetici import PromptBaglami, PromptYoneticisi
from brain.providers.taban import LLMSaglayici, SaglayiciAyarlari, SaglayiciYaniti
from brain.yoneticisi import AIYoneticisi
from config.ayarlar import Ayarlar
from core.base import Mesaj
from core.events import (
    OLAY_DUSUNME_BASLADI,
    OLAY_YANIT_HAZIR,
    EventBus,
)
from core.exceptions import AIProviderError
from core.logger import logger_yapilandir


class _Sahte(LLMSaglayici):
    ad = "sahte"

    async def _istek_gonder(self, mesajlar, *, temperature, max_tokens):
        return SaglayiciYaniti(
            icerik=f"JARVIS:{mesajlar[-1]['content']}",
            model=self.model,
            saglayici=self.ad,
        )


def test_ai_yoneticisi() -> None:
    logger_yapilandir(zorla=True)

    veri = {
        "assistant": {"name": "J.A.R.V.I.S.", "language": "tr", "personality": "zarif"},
        "ai": {
            "default_provider": "openai",
            "system_prompt": "Sen J.A.R.V.I.S.'sin.",
            "providers": {
                "openai": {
                    "enabled": True,
                    "api_key": "sk-x",
                    "model": "gpt-4o-mini",
                }
            },
        },
    }
    yol = Path(tempfile.mkdtemp()) / "config.json"
    yol.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    cfg = Ayarlar(yol)
    cfg.yukle()

    bus = EventBus(ad="test-brain")
    olaylar: list[str] = []

    async def _izle(event):
        olaylar.append(event.ad)

    bus.subscribe(OLAY_DUSUNME_BASLADI, _izle)
    bus.subscribe(OLAY_YANIT_HAZIR, _izle)

    sag = _Sahte(SaglayiciAyarlari(ad="sahte", model="test", enabled=True))
    py = PromptYoneticisi(cfg)
    ai = AIYoneticisi(
        ayar_yonetici=cfg,
        promptlar=py,
        bus=bus,
        saglayici=sag,
    )

    async def _run() -> None:
        await ai.baslat()
        assert ai.calisiyor
        assert ai.aktif_saglayici == "sahte"

        ai.baglam_ayarla(PromptBaglami(kullanici_adi="Yasir"))
        yanit = await ai.dusun("Merhaba")
        assert yanit.icerik == "JARVIS:Merhaba"
        assert OLAY_DUSUNME_BASLADI in olaylar
        assert OLAY_YANIT_HAZIR in olaylar

        yanit2 = await ai.sohbet([Mesaj.kullanici("İkinci")])
        assert "İkinci" in yanit2.icerik

        try:
            await ai.dusun("   ")
            raise AssertionError("boş mesaj hatası bekleniyordu")
        except AIProviderError:
            pass

        # saglayici_degistir fabrika kullanır — openai üretir
        yeni = ai.saglayici_degistir("openai")
        assert yeni.ad == "openai"

        await ai.durdur()
        assert not ai.calisiyor

    asyncio.run(_run())
    print("TEST_OK")
    print("events:", olaylar)
    print("sample:", "JARVIS:Merhaba")


if __name__ == "__main__":
    test_ai_yoneticisi()

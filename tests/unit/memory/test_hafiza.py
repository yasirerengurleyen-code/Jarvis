"""memory/hafiza.py birim testi."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from config.ayarlar import Ayarlar
from core.events import (
    OLAY_HAFIZA_YAZILDI,
    OLAY_PREFERANS_DEGISTI,
    EventBus,
)
from core.logger import logger_yapilandir
from memory.hafiza import HafizaYoneticisi


def test_hafiza_yoneticisi() -> None:
    logger_yapilandir(zorla=True)

    veri = {
        "assistant": {
            "name": "J.A.R.V.I.S.",
            "language": "tr",
            "personality": "zarif",
        },
        "memory": {
            "max_short_term_messages": 10,
        },
    }
    cfg_yol = Path(tempfile.mkdtemp()) / "config.json"
    cfg_yol.write_text(json.dumps(veri), encoding="utf-8")
    cfg = Ayarlar(cfg_yol)
    cfg.yukle()

    db = Path(tempfile.mkdtemp()) / "hafiza.db"
    bus = EventBus(ad="mem-test")
    olaylar: list[str] = []
    bus.subscribe(OLAY_HAFIZA_YAZILDI, lambda e: olaylar.append(e.ad))
    bus.subscribe(OLAY_PREFERANS_DEGISTI, lambda e: olaylar.append(e.ad))

    h = HafizaYoneticisi(ayar_yonetici=cfg, bus=bus, db_yolu=str(db))

    async def _run() -> None:
        await h.baslat()
        assert h.calisiyor
        assert h.aktif_oturum

        h.kullanici_adi_ogren("Yasir")
        assert h.kullanici_adi() == "Yasir"
        h.tercih_ayarla("editor", "vscode")
        h.hatirla("VS Code sever", etiketler=["tercih"], onem=4)

        h.konusma_kaydet("Merhaba", "Sistemler çevrimiçi.")
        gecmis = h.sohbet_gecmisi(limit=10)
        assert len(gecmis) == 2

        baglam = h.prompt_baglami()
        assert baglam.kullanici_adi == "Yasir"
        assert any("VS Code" in n for n in baglam.hafiza_notlari)

        sonuclar = h.ara("VS Code")
        assert len(sonuclar) >= 1

        assert OLAY_HAFIZA_YAZILDI in olaylar
        assert OLAY_PREFERANS_DEGISTI in olaylar

        await h.durdur()
        assert not h.calisiyor

    asyncio.run(_run())
    print("TEST_OK")
    print("oturum:", h.aktif_oturum)
    print("events:", len(olaylar))


if __name__ == "__main__":
    test_hafiza_yoneticisi()

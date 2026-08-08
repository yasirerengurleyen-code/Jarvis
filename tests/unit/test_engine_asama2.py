"""Aşama 2 — Engine + Memory + Brain entegrasyon testi."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.taban import SaglayiciYaniti
from config.ayarlar import Ayarlar
from core.engine import Engine
from core.logger import logger_yapilandir


def test_engine_asama2() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e.db"
    cfg_yol = tmp / "config.json"

    # Gerçek config'i oku ve db yolunu değiştir
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine"
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")

    cfg = Ayarlar(cfg_yol)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "memory" in rapor.aktif_moduller
        assert "brain" in rapor.aktif_moduller
        # Aşama 3+: voice aktif; bekleyen listesinde olmamalı
        assert "voice" in rapor.aktif_moduller
        assert "voice" not in rapor.bekleyen_moduller
        assert engine.hafiza is not None and engine.hafiza.calisiyor
        assert engine.beyin is not None and engine.beyin.calisiyor
        assert engine.ses is not None

        engine.hafiza.kullanici_adi_ogren("Yasir")
        baglam = engine.hafiza.prompt_baglami()
        assert baglam.kullanici_adi == "Yasir"

        # dusun — LLM'i mock'la
        fake = SaglayiciYaniti(
            icerik="Sistemler çevrimiçi, Yasir.",
            model="test",
            saglayici="openai",
        )
        with patch.object(engine.beyin.saglayici, "sohbet", new=AsyncMock(return_value=fake)):
            yanit = await engine.dusun("Merhaba")
        assert "çevrimiçi" in yanit.icerik.lower() or "Yasir" in yanit.icerik
        assert engine.hafiza.sohbet.mesaj_sayisi(engine.hafiza.aktif_oturum) == 2

        satirlar = engine.basari_satirlari()
        assert any("Memory" in s for s in satirlar)
        assert any("Brain" in s for s in satirlar)

        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK")
    print("aktif:", ", ".join(engine.rapor.aktif_moduller if engine.rapor else []))


if __name__ == "__main__":
    test_engine_asama2()

"""Aşama 4 — Engine + GUI entegrasyon testi."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.taban import SaglayiciYaniti
from config.ayarlar import Ayarlar
from core.engine import Engine
from core.logger import logger_yapilandir


def test_engine_asama4_gui() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e4.db"
    cfg_yol = tmp / "config.json"

    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine"
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")

    cfg = Ayarlar(cfg_yol)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat(
            gui=True,
            gui_goster=False,
            gui_hava_sahte=True,
        )
        assert rapor.basarili, rapor.hata
        assert "gui" in rapor.aktif_moduller
        assert "gui" not in rapor.bekleyen_moduller
        assert engine.gui is not None and engine.gui.calisiyor
        assert engine.gui.pencere is not None

        fake = SaglayiciYaniti(
            icerik="GUI üzerinden yanıt",
            model="test",
            saglayici="openai",
        )
        with patch.object(
            engine.beyin.saglayici, "sohbet", new=AsyncMock(return_value=fake)
        ):
            yanit = await engine.gui.mesaj_isle("Merhaba")
            engine.gui.olay_isle()
            await asyncio.sleep(0.05)
            engine.gui.olay_isle()

        assert "GUI" in yanit or "yanıt" in yanit.lower()
        assert any("GUI üzerinden" in m.icerik for m in engine.gui.pencere.sohbet.model.mesajlar)

        satirlar = engine.basari_satirlari()
        assert any("GUI başlatıldı" in s for s in satirlar)

        await engine.durdur()
        assert engine.gui is None

    asyncio.run(_run())
    print("TEST_OK")


def test_engine_gui_kapali_bekleyen() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e4b.db"
    cfg_yol = tmp / "config.json"
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test"
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")

    async def _run() -> None:
        engine = Engine(ayar_yonetici=Ayarlar(cfg_yol))
        rapor = await engine.baslat(gui=False)
        assert rapor.basarili
        assert "gui" in rapor.bekleyen_moduller
        assert "gui" not in rapor.aktif_moduller
        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK_bekleyen")


if __name__ == "__main__":
    test_engine_asama4_gui()
    test_engine_gui_kapali_bekleyen()

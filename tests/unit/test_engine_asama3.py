"""Aşama 3 — Engine + Voice entegrasyon testi."""

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
from voice.stt.taban import SahteSTT, SttAyarlari
from voice.tts.taban import SahteTTS, TtsAyarlari


def test_engine_asama3() -> None:
    logger_yapilandir(zorla=True)
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e3.db"
    cfg_yol = tmp / "config.json"

    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine"
    gercek["voice"]["enabled"] = True
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")

    cfg = Ayarlar(cfg_yol)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "voice" in rapor.aktif_moduller
        assert "gui" in rapor.bekleyen_moduller
        assert engine.ses is not None and engine.ses.calisiyor

        # Sahte STT/TTS zorla (hızlı test)
        engine.ses.stt = SahteSTT(
            SttAyarlari(dil="tr"), varsayilan_metin="Merhaba Jarvis"
        )
        engine.ses.tts = SahteTTS(TtsAyarlari())
        engine.ses._dinleme_suresi = 0.35

        fake = SaglayiciYaniti(
            icerik="Asistan nasıl yardımcı olabilir?",
            model="test",
            saglayici="openai",
        )
        with patch.object(
            engine.beyin.saglayici, "sohbet", new=AsyncMock(return_value=fake)
        ):
            tur = await engine.ses.dinle_ve_yanitla(dinleme_suresi=0.35)

        assert "Merhaba" in tur["stt"].metin or tur["stt"].metin
        assert "yardımcı" in tur["yanit_metni"].lower() or len(tur["yanit_metni"]) > 0
        assert len(tur["tts"].pcm) > 0

        satirlar = engine.basari_satirlari()
        assert any("Voice" in s for s in satirlar)
        assert any("Jarvis" in s for s in satirlar)

        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK")
    print("aktif:", ", ".join(engine.rapor.aktif_moduller if engine.rapor else []))


if __name__ == "__main__":
    test_engine_asama3()

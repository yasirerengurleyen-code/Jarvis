"""voice/yoneticisi.py birim testi."""

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
from core.events import OLAY_STT_SONUC, OLAY_TTS_BITTI, EventBus
from core.logger import logger_yapilandir
from voice.audio.mikrofon import Mikrofon
from voice.stt.taban import SahteSTT, SttAyarlari
from voice.tts.taban import SahteTTS, TtsAyarlari
from voice.wakeword.dinleyici import WakeWordDinleyici
from voice.yoneticisi import VoiceYoneticisi


def test_voice_yoneticisi() -> None:
    logger_yapilandir(zorla=True)

    veri = {
        "voice": {
            "enabled": True,
            "language": "tr",
            "stt": {"engine": "faster_whisper", "fallback": "openai_whisper"},
            "tts": {"engine": "piper", "fallback": "coqui"},
            "microphone": {"sample_rate": 16000, "chunk_size": 256},
        },
        "wake_word": {
            "enabled": True,
            "phrase": "Jarvis",
            "cooldown_seconds": 0.2,
            "timeout_seconds": 2,
            "sensitivity": 0.6,
        },
    }
    yol = Path(tempfile.mkdtemp()) / "v.json"
    yol.write_text(json.dumps(veri), encoding="utf-8")
    cfg = Ayarlar(yol)
    cfg.yukle()

    bus = EventBus(ad="voice-test")
    olaylar: list[str] = []
    bus.subscribe(OLAY_STT_SONUC, lambda e: olaylar.append(e.ad))
    bus.subscribe(OLAY_TTS_BITTI, lambda e: olaylar.append(e.ad))

    mik = Mikrofon(ayar_yonetici=cfg, ornek_hizi=16000, chunk_size=256)
    stt = SahteSTT(SttAyarlari(dil="tr"), varsayilan_metin="Hava nasıl?")
    tts = SahteTTS(TtsAyarlari())
    wake = WakeWordDinleyici(ayar_yonetici=cfg, bus=bus, mikrofon=mik)

    async def brain(m: str) -> str:
        return f"İstanbul açık, efendim. (soru: {m})"

    voice = VoiceYoneticisi(
        ayar_yonetici=cfg,
        bus=bus,
        mikrofon=mik,
        stt=stt,
        tts=tts,
        wake=wake,
        brain_callback=brain,
    )

    async def _run() -> None:
        await voice.baslat()
        assert voice.calisiyor

        tur = await voice.dinle_ve_yanitla(dinleme_suresi=0.2)
        assert "Hava" in tur["stt"].metin
        assert "İstanbul" in tur["yanit_metni"]
        assert len(tur["tts"].pcm) > 0
        assert OLAY_STT_SONUC in olaylar
        assert OLAY_TTS_BITTI in olaylar

        t = await voice.konus("Sistemler çevrimiçi.")
        assert t.metin.startswith("Sistemler")

        stt.sonraki_metni_ayarla("Merhaba")
        assert voice.simule_wake() is True
        await asyncio.sleep(1.0)

        await voice.durdur()
        assert not voice.calisiyor

    asyncio.run(_run())
    print("TEST_OK")
    print("yanit:", "İstanbul açık, efendim.")
    print("events:", olaylar)


if __name__ == "__main__":
    test_voice_yoneticisi()

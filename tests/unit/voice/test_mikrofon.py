"""voice/audio/mikrofon.py birim testi."""

from __future__ import annotations

import asyncio
import struct
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.logger import logger_yapilandir
from voice.audio.mikrofon import Mikrofon, SesKaresi


def test_mikrofon() -> None:
    logger_yapilandir(zorla=True)

    # Sessiz kare RMS
    sessiz = SesKaresi(veri=struct.pack("<16h", *([0] * 16)), ornek_hizi=16000)
    assert sessiz.rms() == 0.0
    assert sessiz.ornek_sayisi == 16

    # Yüksek genlik
    yuksek = SesKaresi(
        veri=struct.pack("<16h", *([10000] * 16)),
        ornek_hizi=16000,
    )
    assert yuksek.rms() > 0.2

    mik = Mikrofon(ornek_hizi=16000, chunk_size=256)
    mik.baslat()
    assert mik.calisiyor
    # sounddevice yoksa sahte mod
    assert mik.sahte_mod is True or mik.sahte_mod is False

    kare = mik.kare_oku(timeout=1.0)
    assert kare is not None
    assert kare.ornek_hizi == 16000
    assert len(kare.veri) > 0

    # Enjekte + VAD
    mik.enerji_esigi = 0.1
    guclu = SesKaresi(
        veri=struct.pack("<256h", *([20000] * 256)),
        ornek_hizi=16000,
        zaman=time.time(),
    )
    assert mik.konusma_var_mi(guclu) is True
    assert mik.konusma_var_mi(sessiz) is False

    mik.enjekte_kare(guclu)
    assert mik.kuyruk_boyutu() >= 1

    pcm = mik.kaydet_saniye(0.15)
    assert isinstance(pcm, (bytes, bytearray))

    async def _async() -> None:
        n = 0
        async for _ in mik.akis():
            n += 1
            if n >= 2:
                break
        assert n >= 2

    asyncio.run(_async())

    mik.durdur()
    assert not mik.calisiyor

    print("TEST_OK")
    print("sahte_mod:", mik.sahte_mod)
    print("kare_bytes:", len(kare.veri))


if __name__ == "__main__":
    test_mikrofon()

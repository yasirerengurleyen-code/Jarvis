"""voice/audio/cihazlar.py birim testi."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from config.ayarlar import Ayarlar
from core.exceptions import VoiceError
from core.logger import logger_yapilandir
from voice.audio.cihazlar import CihazYoneticisi, SesCihazi


def test_cihazlar() -> None:
    logger_yapilandir(zorla=True)

    # sounddevice olmadan sanal cihazlar
    with patch("voice.audio.cihazlar._sounddevice_var_mi", return_value=False):
        cy = CihazYoneticisi()
        cihazlar = cy.cihazlari_tara(yenile=True)
        assert len(cihazlar) == 2
        assert cy.mikrofonlar()[0].mikrofon_mu
        assert cy.hoparlorler()[0].hoparlor_mu
        mik = cy.varsayilan_mikrofon()
        hop = cy.varsayilan_hoparlor()
        assert mik is not None and mik.ad.startswith("WhiteCore")
        assert hop is not None
        ozet = cy.ozet()
        assert ozet["sounddevice"] is False
        assert ozet["microphone_count"] == 1

    # config index
    veri = {
        "voice": {
            "microphone": {"device_index": 0},
            "speaker": {"device_index": 1},
        }
    }
    yol = Path(tempfile.mkdtemp()) / "c.json"
    yol.write_text(json.dumps(veri), encoding="utf-8")
    cfg = Ayarlar(yol)
    cfg.yukle()

    with patch("voice.audio.cihazlar._sounddevice_var_mi", return_value=False):
        cy2 = CihazYoneticisi(cfg)
        assert cy2.varsayilan_mikrofon().index == 0
        assert cy2.varsayilan_hoparlor().index == 1

        # Geçersiz index
        cfg._veri["voice"]["microphone"]["device_index"] = 99
        try:
            cy2.varsayilan_mikrofon()
            raise AssertionError("VoiceError bekleniyordu")
        except VoiceError:
            pass

    d = SesCihazi(0, "test", max_girdi_kanal=1).to_dict()
    assert d["is_mic"] is True

    print("TEST_OK")
    print("virtual_mic:", mik.ad)
    print("ozet_keys:", sorted(ozet.keys()))


if __name__ == "__main__":
    test_cihazlar()

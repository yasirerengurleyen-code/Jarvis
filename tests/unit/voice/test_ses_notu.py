"""voice/ses_notu.py birim testi."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from voice.ses_notu import sahte_pcm, ses_notu_kaydet, wav_yaz


def test_ses_notu_demo(tmp_path: Path | None = None) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as d:
        klasor = Path(d)
        sonuc = ses_notu_kaydet(sure_saniye=1.0, hedef_dir=klasor, mikrofon=None)
        assert sonuc["demo"] is True
        assert Path(sonuc["path"]).is_file()
        assert sonuc["bytes"] > 0
        pcm = sahte_pcm(sure_saniye=0.5)
        yol = wav_yaz(klasor / "x.wav", pcm)
        assert yol.is_file()


if __name__ == "__main__":
    test_ses_notu_demo()
    print("OK test_ses_notu")

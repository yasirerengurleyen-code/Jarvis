"""brain/prompts/yonetici.py birim testi."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[3]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.prompts.yonetici import PromptBaglami, PromptYoneticisi
from config.ayarlar import Ayarlar
from core.logger import logger_yapilandir


def test_prompt_yoneticisi() -> None:
    logger_yapilandir(zorla=True)

    veri = {
        "assistant": {
            "name": "J.A.R.V.I.S.",
            "language": "tr",
            "personality": "profesyonel, zarif",
        },
        "ai": {
            "system_prompt": "Sen test asistanısın.",
        },
    }
    yol = Path(tempfile.mkdtemp()) / "config.json"
    yol.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    cfg = Ayarlar(yol)
    cfg.yukle()

    py = PromptYoneticisi(cfg)
    assert py.taban_sistem_promptu() == "Sen test asistanısın."

    prompt = py.sistem_promptu_olustur(
        PromptBaglami(
            kullanici_adi="Yasir",
            hafiza_notlari=["VS Code tercih eder", "Türkçe konuş"],
        )
    )
    assert "J.A.R.V.I.S." in prompt
    assert "Yasir" in prompt
    assert "VS Code" in prompt
    assert "Tehlikeli işlemlerde" in prompt
    assert "Sen test asistanısın." in prompt

    # Şablon
    py.sablon_kaydet("selam", "Merhaba $ad")
    assert py.sablon_doldur("selam", ad="Jarvis") == "Merhaba Jarvis"

    try:
        py.sablon_al("yok")
        raise AssertionError("KeyError bekleniyordu")
    except KeyError:
        pass

    zarf = py.kullanici_mesaji_zarfla("hava?", onek="[SORU]", sonek="[SON]")
    assert zarf.startswith("[SORU]")
    assert "hava?" in zarf

    # Gerçek proje config ile duman testi
    gercek = PromptYoneticisi()
    gercek.ayarlar.yukle()
    p2 = gercek.sistem_promptu_olustur()
    assert "J.A.R.V.I.S." in p2 or "Jarvis" in p2 or len(p2) > 20

    print("TEST_OK")
    print("prompt_len:", len(prompt))
    print("snippet:", prompt[:80].replace("\n", " "))


if __name__ == "__main__":
    test_prompt_yoneticisi()

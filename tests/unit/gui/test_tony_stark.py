"""gui/themes/tony_stark.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from gui.themes.tony_stark import (
    TEMA_ADI,
    VARSAYILAN_RENKLER,
    Rgba,
    TonyStarkTema,
    renk_ayikla,
    tema_yukle,
)


def test_hex_ve_rgba_ayiklama() -> None:
    assert renk_ayikla("#0A0A0A") == Rgba(10, 10, 10, 1.0)
    assert renk_ayikla("#0a0a0a").hex() == "#0A0A0A"
    assert renk_ayikla("#0F8") == Rgba(0, 255, 136, 1.0)
    cam = renk_ayikla("rgba(18, 18, 18, 0.72)")
    assert cam.r == 18 and cam.g == 18 and cam.b == 18
    assert abs(cam.a - 0.72) < 1e-6
    assert "rgba" in cam.css()


def test_varsayilan_tema() -> None:
    tema = TonyStarkTema.varsayilan()
    assert tema.ad == TEMA_ADI
    assert tema.background.hex() == "#050A0C"
    assert tema.accent.hex() == "#00E8C8"
    assert tema.efektler.neon_glow is True
    assert tema.efektler.glassmorphism is True
    renkler = tema.renkler_dict()
    assert set(renkler) == set(VARSAYILAN_RENKLER)


def test_config_birlestirme() -> None:
    tema = TonyStarkTema.from_config(
        {
            "theme": "tony_stark",
            "colors": {"accent": "#11FF99", "background": "#050505"},
            "effects": {"neon_glow": False},
        }
    )
    assert tema.accent.hex() == "#11FF99"
    assert tema.background.hex() == "#050505"
    assert tema.efektler.neon_glow is False
    assert tema.efektler.microphone_animation is True


def test_ayarlar_ile_yukle() -> None:
    from config.ayarlar import Ayarlar

    ayar = Ayarlar()
    ayar.yukle()
    tema = TonyStarkTema.ayarlardan(ayar)
    assert tema.ad == "tony_stark"
    assert tema.accent.hex() == "#00E8C8"
    assert tema.glass.a < 1.0
    paket = tema.to_dict()
    assert paket["theme"] == "tony_stark"
    assert "colors" in paket and "effects" in paket


def test_tema_yukle_kisayol() -> None:
    tema = tema_yukle({"colors": {"text": "#FFFFFF"}})
    assert tema.text.hex() == "#FFFFFF"


def test_gecersiz_renk() -> None:
    try:
        renk_ayikla("mavi")
        raise AssertionError("ValueError bekleniyordu")
    except ValueError:
        pass


if __name__ == "__main__":
    test_hex_ve_rgba_ayiklama()
    test_varsayilan_tema()
    test_config_birlestirme()
    test_ayarlar_ile_yukle()
    test_tema_yukle_kisayol()
    test_gecersiz_renk()
    print("OK test_tony_stark")

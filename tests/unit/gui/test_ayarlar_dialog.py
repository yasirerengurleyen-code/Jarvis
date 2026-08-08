"""Ayarlar diyaloğu + mobil API key kuralı."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.windows.ayarlar_dialog import (
    AyarlarDialog,
    api_key_gosterilsin_mi,
    mobil_mod_mu,
)


def test_mobil_api_key_kurali() -> None:
    assert api_key_gosterilsin_mi(mobil=False) is True
    assert api_key_gosterilsin_mi(mobil=True) is False
    assert mobil_mod_mu(zorla=True) is True
    assert mobil_mod_mu(zorla=False) is False


def test_dialog_masaüstü_ve_mobil() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    d = AyarlarDialog(mobil=False)
    try:
        assert d.api_key_alani_var is True
        assert d.api_giris is not None
    finally:
        d.close()
        d.deleteLater()

    m = AyarlarDialog(mobil=True)
    try:
        assert m.api_key_alani_var is False
        assert m.api_giris is None
    finally:
        m.close()
        m.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_mobil_api_key_kurali()
    test_dialog_masaüstü_ve_mobil()
    print("OK test_ayarlar_dialog")

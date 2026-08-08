"""gui/themes/stil.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from gui.themes.stil import StilUretici, qss_uret
from gui.themes.tony_stark import TonyStarkTema


def test_qss_temel_icerik() -> None:
    stil = StilUretici(TonyStarkTema.varsayilan())
    qss = stil.qss()
    assert "tony_stark" in qss
    assert "#050A0C" in qss or "#0A0A0A" in qss or "rgb" in qss.lower()
    assert "#00E8C8" in qss or "#00FF88" in qss
    assert "QPushButton" in qss
    assert "QMainWindow" in qss
    assert "CamPanel" in qss or "HudPanel" in qss


def test_ozel_renkler_qss_e_yansir() -> None:
    tema = TonyStarkTema.from_config(
        {"colors": {"accent": "#ABCDEF", "background": "#010101"}}
    )
    qss = StilUretici(tema).qss()
    assert "#ABCDEF" in qss
    assert "#010101" in qss


def test_neon_kapali_kenar() -> None:
    tema = TonyStarkTema.from_config({"effects": {"neon_glow": False}})
    qss = StilUretici(tema).qss()
    assert "QFrame#CamPanel" in qss
    assert len(qss) > 200


def test_degiskenler() -> None:
    d = StilUretici().degiskenler()
    assert d["--wc-accent"] == "#00E8C8"
    assert d["--wc-bg"] == "#050A0C"
    assert set(d) >= {
        "--wc-bg",
        "--wc-surface",
        "--wc-glass",
        "--wc-accent",
        "--wc-text",
        "--wc-danger",
        "--wc-warning",
    }


def test_qss_uret_kisayol() -> None:
    qss = qss_uret()
    assert "QWidget" in qss


def test_uygula_pyside_yoksa_veya_app_yok() -> None:
    uretici = StilUretici()
    try:
        import PySide6  # noqa: F401
    except ImportError:
        try:
            uretici.uygula()
            raise AssertionError("RuntimeError bekleniyordu")
        except RuntimeError as exc:
            assert "PySide6" in str(exc)
        return

    # PySide6 var ama QApplication yok → RuntimeError
    from PySide6.QtWidgets import QApplication

    onceki = QApplication.instance()
    if onceki is None:
        try:
            uretici.uygula()
            raise AssertionError("RuntimeError bekleniyordu")
        except RuntimeError as exc:
            assert "QApplication" in str(exc)


if __name__ == "__main__":
    test_qss_temel_icerik()
    test_ozel_renkler_qss_e_yansir()
    test_neon_kapali_kenar()
    test_degiskenler()
    test_qss_uret_kisayol()
    test_uygula_pyside_yoksa_veya_app_yok()
    print("OK test_stil")

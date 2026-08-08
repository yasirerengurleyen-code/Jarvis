"""gui/widgets/karekod.py birim testi."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.karekod import qr_pixmap, qr_png_bytes


def test_qr_png() -> None:
    png = qr_png_bytes("whitecore://pair?code=123456")
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_pixmap() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    pm = qr_pixmap("whitecore://pair?code=654321", piksel=120)
    assert pm is not None
    assert not pm.isNull()
    assert pm.width() <= 120
    assert app is not None


if __name__ == "__main__":
    test_qr_png()
    test_qr_pixmap()
    print("OK test_karekod")

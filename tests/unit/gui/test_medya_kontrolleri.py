"""gui/widgets/medya_kontrolleri.py birim testleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_medya_kontrolleri_toggle() -> None:
    from PySide6.QtWidgets import QApplication

    from gui.widgets.medya_kontrolleri import MedyaKontrolleri

    app = QApplication.instance() or QApplication([])
    w = MedyaKontrolleri()
    try:
        assert w.ses_acik is True
        assert w.kamera_acik is True
        assert w.mikrofon_acik is True
        assert "LIVE" in w.btn_mikrofon.text()

        alinan: list[tuple[str, bool]] = []
        w.ses_degisti.connect(lambda v: alinan.append(("ses", v)))
        w.kamera_degisti.connect(lambda v: alinan.append(("kamera", v)))
        w.mikrofon_degisti.connect(lambda v: alinan.append(("mikrofon", v)))

        w.btn_ses.click()
        w.btn_kamera.click()
        w.btn_mikrofon.click()

        assert w.ses_acik is False
        assert w.kamera_acik is False
        assert w.mikrofon_acik is False
        assert ("ses", False) in alinan
        assert ("kamera", False) in alinan
        assert ("mikrofon", False) in alinan
        assert "RESUME" in w.btn_ses.text() or "MUTED" in w.btn_mikrofon.text()

        w.durumlari_ayarla(ses=True, kamera=True, mikrofon=True)
        assert w.ses_acik is True
        assert alinan.count(("ses", True)) == 0
    finally:
        w.close()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_medya_kontrolleri_toggle()
    print("OK test_medya_kontrolleri")

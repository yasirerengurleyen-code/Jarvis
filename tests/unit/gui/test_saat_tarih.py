"""gui/widgets/saat_tarih.py birim testleri."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.saat_tarih import (
    SaatTarihModel,
    SaatTarihWidget,
    saat_metni,
    tarih_metni,
)


def test_saat_tarih_metinleri() -> None:
    an = datetime(2026, 8, 6, 19, 33, 5)
    assert saat_metni(an) == "19:33:05"
    assert saat_metni(an, saniye=False) == "19:33"
    assert "Ağustos" in tarih_metni(an, dil="tr")
    assert "2026" in tarih_metni(an, dil="tr")


def test_model_config() -> None:
    model = SaatTarihModel.from_config(
        {"language": "tr", "widgets": {"show_clock": True, "show_date": False}}
    )
    assert model.saat_goster is True
    assert model.tarih_goster is False
    assert model.tarih() == ""
    assert ":" in model.saat()


def test_model_ayarlardan() -> None:
    from config.ayarlar import Ayarlar

    ayar = Ayarlar()
    ayar.yukle()
    model = SaatTarihModel.ayarlardan(ayar)
    assert model.saat_goster is True
    assert model.tarih_goster is True
    assert model.timezone == "Europe/Istanbul"
    paket = model.to_dict()
    assert paket["show_clock"] is True
    assert len(paket["clock"]) >= 5


def test_widget_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = SaatTarihWidget(
        SaatTarihModel(saat_goster=True, tarih_goster=True, timezone="Europe/Istanbul"),
        guncelleme_ms=500,
    )
    try:
        w.yenile()
        assert ":" in w.saat_metni_gosterilen
        assert len(w.tarih_metni_gosterilen) > 5
        assert w.objectName() in {"CamPanel", "HudPanel"}
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_saat_tarih_metinleri()
    test_model_config()
    test_model_ayarlardan()
    test_widget_offscreen()
    print("OK test_saat_tarih")

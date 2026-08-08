"""gui/windows/ana_pencere.py birim testleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.windows.ana_pencere import AnaPencere, pencere_ayarlari


def test_pencere_ayarlari() -> None:
    a = pencere_ayarlari(
        {"theme": "tony_stark", "window": {"width": 1000, "height": 700, "frameless": True}}
    )
    assert a["width"] == 1000
    assert a["height"] == 700
    assert a["frameless"] is True
    assert a["theme"] == "tony_stark"


def test_ana_pencere_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    from config.ayarlar import Ayarlar
    from core.events import EventBus

    app = QApplication.instance() or QApplication([])
    ayar = Ayarlar()
    ayar.yukle()
    bus = EventBus(ad="test.ana")
    alinan: list[str] = []

    w = AnaPencere(
        ayar_yonetici=ayar,
        bus=bus,
        hava_zorla_sahte=True,
    )
    w.mesaj_gonderildi.connect(alinan.append)
    try:
        assert "WhiteCore" in w.windowTitle() or "J.A.R.V.I.S" in w.windowTitle()
        assert w.width() >= 1000 or w.size().width() >= 100
        assert w.sohbet.mesaj_sayisi() >= 1
        assert w.mikrofon is not None
        assert w.ai is not None
        assert w.cihazlar is not None
        assert w.metrikler is not None
        assert w.medya is not None
        assert w.marka is not None
        assert w.marka.width() >= 260
        assert hasattr(w, "ayarlari_ac")
        assert hasattr(w, "karekod_ac")
        assert w.btn_karekod is not None
        w.online_ayarla(True, detay="test")
        assert "ONLINE" in w.online.text()
        assert w.medya.ses_acik is True
        assert w.medya.mikrofon_acik is True
        assert w.medya.kamera_acik is True
        ay = pencere_ayarlari(ayar.bolum("gui") if hasattr(ayar, "bolum") else {})
        assert ay["width"] >= 1200
        assert ay["height"] >= 700
        assert "start_fullscreen" in ay
        assert (
            "#00FF88" in w.styleSheet()
            or "#00E8C8" in w.styleSheet()
            or "tony_stark" in w.styleSheet()
        )
        w.sohbet.giris_ayarla("test mesaj")
        w.sohbet.gonder()
        assert alinan == ["test mesaj"]
        w.asistan_yaniti_goster("Yanıt")
        assert w.sohbet.mesaj_sayisi() >= 3
        w.durum_mesaji("ok")
    finally:
        w.kapat_hazirlik()
        w.close()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_pencere_ayarlari()
    test_ana_pencere_offscreen()
    print("OK test_ana_pencere")

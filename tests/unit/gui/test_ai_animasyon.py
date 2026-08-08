"""gui/widgets/ai_animasyon.py birim testleri."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.ai_animasyon import (
    AiAnimasyonModel,
    AiAnimasyonWidget,
    AiDurum,
    ai_halka_acisi,
    ai_parlaklik,
    durum_etiketi,
    durum_rengi,
)


def test_saf_fonksiyonlar() -> None:
    assert "dinlen" in durum_etiketi(AiDurum.BOS).lower()
    assert durum_rengi(AiDurum.BOS).upper() == "#00FF88"
    assert durum_rengi(AiDurum.DINLIYOR).upper() == "#00FF88"
    assert durum_rengi(AiDurum.DUSUNUYOR).upper() == "#FFC857"
    assert durum_rengi(AiDurum.KONUSUYOR).upper() == "#3BA7FF"
    assert durum_rengi(AiDurum.HATA).upper() == "#FF3B4A"
    p_bos = ai_parlaklik(0.0, AiDurum.BOS)
    p_dus = ai_parlaklik(1.0, AiDurum.DUSUNUYOR)
    assert 0.2 <= p_bos <= 1.0
    assert 0.2 <= p_dus <= 1.0
    a0 = ai_halka_acisi(0.5, AiDurum.DUSUNUYOR, 0)
    a1 = ai_halka_acisi(0.5, AiDurum.DUSUNUYOR, 1)
    assert a0 != a1


def test_model_config() -> None:
    m = AiAnimasyonModel(durum=AiDurum.DUSUNUYOR)
    m.adim(0.2)
    assert m.faz != 0.0
    cfg = AiAnimasyonModel.from_config(
        {"effects": {"ai_animation": False}, "colors": {"accent": "#00FFAA"}}
    )
    assert cfg.animasyon_acik is False
    assert cfg.accent == "#00FFAA"
    from config.ayarlar import Ayarlar

    a = Ayarlar()
    a.yukle()
    m2 = AiAnimasyonModel.ayarlardan(a)
    assert m2.animasyon_acik is True
    assert m2.to_dict()["state"] == "bos"


def test_widget_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = AiAnimasyonWidget(AiAnimasyonModel(), boyut=100, fps=20)
    try:
        w.dusunmeye_basla()
        assert w.model.durum == AiDurum.DUSUNUYOR
        w.yanit_hazir(sure_ms=200)
        assert w.model.durum == AiDurum.YANIT
        w.durum_ayarla(AiDurum.HATA, mesaj="Test hata")
        assert w.model.durum == AiDurum.HATA
        assert w.objectName() == "JarvisCekirdek"
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


def test_bus_bagla() -> None:
    from PySide6.QtWidgets import QApplication

    from core.events import (
        EventBus,
        OLAY_DUSUNME_BASLADI,
        OLAY_TTS_BASLADI,
        OLAY_YANIT_HAZIR,
    )

    app = QApplication.instance() or QApplication([])
    bus = EventBus(ad="test.ai")
    w = AiAnimasyonWidget(AiAnimasyonModel())
    try:
        w.bus_bagla(bus)
        asyncio.run(bus.publish(OLAY_DUSUNME_BASLADI, {}, kaynak="test"))
        assert w.model.durum == AiDurum.DUSUNUYOR
        asyncio.run(bus.publish(OLAY_YANIT_HAZIR, {}, kaynak="test"))
        assert w.model.durum == AiDurum.YANIT
        asyncio.run(bus.publish(OLAY_TTS_BASLADI, {}, kaynak="test"))
        assert w.model.durum == AiDurum.KONUSUYOR
        w.bus_coz()
        assert bus.abone_sayisi(OLAY_DUSUNME_BASLADI) == 0
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_saf_fonksiyonlar()
    test_model_config()
    test_widget_offscreen()
    test_bus_bagla()
    print("OK test_ai_animasyon")

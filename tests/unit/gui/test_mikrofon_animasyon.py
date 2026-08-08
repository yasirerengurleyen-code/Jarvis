"""gui/widgets/mikrofon_animasyon.py birim testleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.mikrofon_animasyon import (
    MikrofonAnimasyonModel,
    MikrofonAnimasyonWidget,
    MikrofonDurum,
    durum_etiketi,
    pulse_olcek,
)


def test_pulse_ve_etiket() -> None:
    assert pulse_olcek(0.0, MikrofonDurum.KAPALI) == 0.55
    bek = pulse_olcek(0.0, MikrofonDurum.BEKLEMEDE)
    assert 0.6 < bek < 1.0
    din = pulse_olcek(0.0, MikrofonDurum.DINLIYOR, seviye=1.0)
    assert din > pulse_olcek(0.0, MikrofonDurum.DINLIYOR, seviye=0.0)
    assert "Jarvis" in durum_etiketi(MikrofonDurum.BEKLEMEDE)


def test_model_adim_ve_config() -> None:
    m = MikrofonAnimasyonModel(durum=MikrofonDurum.DINLIYOR, seviye=0.5)
    o1 = m.adim(0.2)
    o2 = m.adim(0.2)
    assert o1 > 0
    assert m.faz != 0.0 or o2 > 0
    cfg = MikrofonAnimasyonModel.from_config(
        {
            "effects": {"microphone_animation": False},
            "colors": {"accent": "#11FF99"},
        }
    )
    assert cfg.animasyon_acik is False
    assert cfg.accent == "#11FF99"
    from config.ayarlar import Ayarlar

    a = Ayarlar()
    a.yukle()
    m2 = MikrofonAnimasyonModel.ayarlardan(a)
    assert m2.animasyon_acik is True
    assert m2.to_dict()["state"] == MikrofonDurum.BEKLEMEDE.value


def test_widget_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = MikrofonAnimasyonWidget(
        MikrofonAnimasyonModel(durum=MikrofonDurum.BEKLEMEDE),
        boyut=100,
        fps=20,
    )
    try:
        w.durum_ayarla(MikrofonDurum.DINLIYOR)
        w.seviye_ayarla(0.7)
        assert w.model.durum == MikrofonDurum.DINLIYOR
        assert abs(w.model.seviye - 0.7) < 1e-6
        w.wake_flas(sure_ms=200)
        assert w.model.durum == MikrofonDurum.ISIK
        assert w.objectName() == "CamPanel"
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


def test_bus_bagla() -> None:
    import asyncio

    from PySide6.QtWidgets import QApplication

    from core.events import EventBus, OLAY_DINLEME_BASLADI, OLAY_WAKE_WORD

    app = QApplication.instance() or QApplication([])
    bus = EventBus(ad="test.mikrofon")
    w = MikrofonAnimasyonWidget(MikrofonAnimasyonModel())
    try:
        w.bus_bagla(bus)
        asyncio.run(bus.publish(OLAY_DINLEME_BASLADI, {}, kaynak="test"))
        assert w.model.durum == MikrofonDurum.DINLIYOR
        asyncio.run(bus.publish(OLAY_WAKE_WORD, {}, kaynak="test"))
        assert w.model.durum == MikrofonDurum.ISIK
        w.bus_coz()
        assert bus.abone_sayisi(OLAY_DINLEME_BASLADI) == 0
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_pulse_ve_etiket()
    test_model_adim_ve_config()
    test_widget_offscreen()
    test_bus_bagla()
    print("OK test_mikrofon_animasyon")

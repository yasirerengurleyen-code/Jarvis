"""gui/widgets/cihaz_paneli.py birim testleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.cihaz_paneli import (
    CihazPaneli,
    CihazPaneliModel,
    EslestirmeGosterim,
    kod_uret,
    qr_yuku_uret,
)
from network.device.modeller import BaglantiDurumu, PlatformTuru


def test_kod_ve_qr() -> None:
    kod = kod_uret(6)
    assert len(kod) == 6 and kod.isdigit()
    yuku = qr_yuku_uret(kod, host="192.168.1.10", http_port=8741, ws_port=8742)
    assert kod in yuku
    assert yuku.startswith("http://")
    assert "port=8741" in yuku
    assert "ws_port=8742" in yuku


def test_model_oturum_ve_cihaz() -> None:
    m = CihazPaneliModel(kod_uzunluk=6, ttl_saniye=120, host="127.0.0.1")
    ot = m.oturum_baslat()
    assert isinstance(ot, EslestirmeGosterim)
    assert len(ot.kod) == 6
    assert ot.ttl_saniye == 120
    c = m.demo_cihaz_ekle()
    assert c.platform == PlatformTuru.IOS
    assert c.cevrimici_mi()
    assert any("iPhone" in s for s in m.ozet_satirlari())
    assert m.cihaz_kaldir(c.cihaz_id) is True


def test_eslestirme_gosterim_agdan() -> None:
    class _Oturum:
        oturum_id = "abc"
        kod = "123456"
        qr_payload = "http://192.168.1.10:8741/?code=123456&ws_port=8742"
        olusturma = "2026-01-01T00:00:00+00:00"
        son_gecerlilik = "2026-01-01T00:05:00+00:00"

    g = EslestirmeGosterim.agdan(_Oturum(), ttl_saniye=300)
    assert g.kod == "123456"
    assert g.oturum_id == "abc"
    assert "code=123456" in g.qr_payload


def test_model_ayarlardan() -> None:
    from config.ayarlar import Ayarlar

    a = Ayarlar()
    a.yukle()
    m = CihazPaneliModel.ayarlardan(a)
    assert m.kod_uzunluk == 6
    assert m.http_port == 8741


def test_widget_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    sinyaller: list[object] = []

    w = CihazPaneli(CihazPaneliModel())
    w.cihaz_bagla_istedi.connect(sinyaller.append)
    try:
        ot = w.cihaz_bagla()
        assert w.aktif_sayfa() == CihazPaneli.SAYFA_BAGLA
        assert w.son_kod() == ot.kod
        assert len(sinyaller) == 1
        w.model.demo_cihaz_ekle()
        w.sayfa_goster(CihazPaneli.SAYFA_LISTE)
        assert w.aktif_sayfa() == CihazPaneli.SAYFA_LISTE
        assert w._liste.count() == 1
        assert w.objectName() == "CamPanel"
        assert BaglantiDurumu.CEVRIMICI.value in w.model.ozet_satirlari()[0]
    finally:
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_kod_ve_qr()
    test_model_oturum_ve_cihaz()
    test_eslestirme_gosterim_agdan()
    test_model_ayarlardan()
    test_widget_offscreen()
    print("OK test_cihaz_paneli")

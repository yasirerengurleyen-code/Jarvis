"""gui/widgets/hava_durumu.py birim testleri."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.hava_durumu import (
    HavaAyarlari,
    HavaDurumu,
    HavaDurumuWidget,
    hava_getir,
    sahte_hava,
    wmo_aciklama,
)


class _SahteYanit:
    def __init__(self, veri: dict) -> None:
        self._ham = json.dumps(veri).encode("utf-8")

    def read(self) -> bytes:
        return self._ham

    def __enter__(self) -> "_SahteYanit":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_wmo_ve_sahte() -> None:
    assert wmo_aciklama(0) == "Açık"
    assert "yağmur" in wmo_aciklama(63).lower() or "Yağmur" in wmo_aciklama(63)
    h = sahte_hava("Ankara")
    assert h.sehir == "Ankara"
    assert h.kaynak == "sahte"
    assert "°C" in h.ozet


def test_hava_getir_mock() -> None:
    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        return _SahteYanit(
            {
                "current": {
                    "temperature_2m": 18.4,
                    "weather_code": 61,
                    "wind_speed_10m": 14.0,
                    "relative_humidity_2m": 70.0,
                }
            }
        )

    ayar = HavaAyarlari(sehir="İstanbul")
    h = hava_getir(ayar, urlac=fake_urlopen)
    assert isinstance(h, HavaDurumu)
    assert h.kaynak == "open-meteo"
    assert h.sicaklik_c == 18.4
    assert h.kod == 61
    assert "yağmur" in h.durum.lower() or "Yağmur" in h.durum


def test_hava_getir_hata_sahteye_dusur() -> None:
    def patla(req, timeout=0):  # noqa: ANN001
        raise TimeoutError("zaman aşımı")

    h = hava_getir(HavaAyarlari(sehir="İzmir"), urlac=patla)
    assert h.kaynak == "sahte"
    assert h.sehir == "İzmir"


def test_ayarlar() -> None:
    a = HavaAyarlari.from_config(
        {
            "widgets": {"show_weather": False},
            "weather": {"city": "Bursa", "latitude": 40.1, "longitude": 29.0},
        }
    )
    assert a.goster is False
    assert a.sehir == "Bursa"
    from config.ayarlar import Ayarlar

    ayar = Ayarlar()
    ayar.yukle()
    # config'te weather yok → varsayılan İstanbul + show_weather True
    m = HavaAyarlari.ayarlardan(ayar)
    assert m.goster is True
    assert m.sehir == "İstanbul"


def test_widget_offscreen_sahte() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = HavaDurumuWidget(HavaAyarlari(sehir="İstanbul"), zorla_sahte=True)
    try:
        w.yenile()
        assert w.son is not None
        assert w.son.kaynak == "sahte"
        assert "İstanbul" in w.ozet_metni()
        assert w.objectName() in {"CamPanel", "HudPanel"}
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_wmo_ve_sahte()
    test_hava_getir_mock()
    test_hava_getir_hata_sahteye_dusur()
    test_ayarlar()
    test_widget_offscreen_sahte()
    print("OK test_hava_durumu")

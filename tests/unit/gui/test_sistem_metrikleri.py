"""gui/widgets/sistem_metrikleri.py birim testleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.sistem_metrikleri import (
    MetrikOrnegi,
    SistemMetrikAyarlari,
    SistemMetrikleriWidget,
    metrik_ornekle,
    metrik_satirlari,
)


def test_metrik_ornekle() -> None:
    ornek = metrik_ornekle(cpu_aralik=0.05)
    assert isinstance(ornek, MetrikOrnegi)
    assert 0.0 <= ornek.cpu_yuzde <= 100.0
    assert 0.0 <= ornek.ram_yuzde <= 100.0
    assert ornek.ram_toplam_gb > 0
    assert ornek.kaynak in {"psutil", "sahte", "karisik"}
    assert "cpu_percent" in ornek.to_dict()


def test_metrik_satirlari_bayraklar() -> None:
    ornek = MetrikOrnegi(
        cpu_yuzde=10.0,
        ram_yuzde=50.0,
        ram_kullanilan_gb=8.0,
        ram_toplam_gb=16.0,
        gpu_yuzde=None,
        ag_aktif=True,
        sistem="Windows 11",
    )
    satirlar = metrik_satirlari(
        ornek, cpu=True, ram=True, gpu=True, ag=False, sistem_bilgi=True, disk=False, batarya=False
    )
    anahtarlar = [a for a, _ in satirlar]
    assert anahtarlar == ["CPU", "RAM", "GPU", "SİSTEM"]
    assert any("N/A" in d for _, d in satirlar)


def test_ayarlar_config() -> None:
    ayar = SistemMetrikAyarlari.from_config(
        {"widgets": {"show_cpu": True, "show_gpu": False, "show_network": True}}
    )
    assert ayar.show_cpu is True
    assert ayar.show_gpu is False
    from config.ayarlar import Ayarlar

    a = Ayarlar()
    a.yukle()
    tam = SistemMetrikAyarlari.ayarlardan(a)
    assert tam.show_ram is True


def test_widget_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = SistemMetrikleriWidget(
        SistemMetrikAyarlari(show_gpu=True, guncelleme_ms=800),
        cpu_aralik=0.05,
    )
    try:
        w.yenile()
        metinler = w.metinler()
        assert "CPU" in metinler
        assert "RAM" in metinler
        assert w.objectName() in {"CamPanel", "HudPanel"}
        assert w.son_ornek is not None
        assert hasattr(w.son_ornek, "disk_yuzde")
    finally:
        w.durdur()
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_metrik_ornekle()
    test_metrik_satirlari_bayraklar()
    test_ayarlar_config()
    test_widget_offscreen()
    print("OK test_sistem_metrikleri")

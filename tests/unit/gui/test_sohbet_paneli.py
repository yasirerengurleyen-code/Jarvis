"""gui/widgets/sohbet_paneli.py birim testleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.widgets.sohbet_paneli import MesajRol, SohbetMesaji, SohbetModel, SohbetPaneli


def test_model_mesajlar() -> None:
    m = SohbetModel(asistan_adi="J.A.R.V.I.S.")
    m.kullanici("Merhaba")
    m.asistan("Sistemler çevrimiçi.")
    m.sistem("Hazır")
    assert len(m.mesajlar) == 3
    assert "Siz" in m.metin()
    assert "J.A.R.V.I.S." in m.metin()
    assert m.to_list()[0]["role"] == "kullanici"
    try:
        m.ekle(MesajRol.KULLANICI, "  ")
        raise AssertionError("ValueError bekleniyordu")
    except ValueError:
        pass
    m.temizle()
    assert m.mesajlar == []


def test_model_ayarlardan() -> None:
    from config.ayarlar import Ayarlar

    a = Ayarlar()
    a.yukle()
    m = SohbetModel.ayarlardan(a)
    assert m.asistan_adi == "J.A.R.V.I.S."


def test_max_mesaj() -> None:
    m = SohbetModel(max_mesaj=3)
    for i in range(5):
        m.kullanici(f"m{i}")
    assert len(m.mesajlar) == 3
    assert m.mesajlar[0].icerik == "m2"


def test_widget_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    alinan: list[str] = []

    w = SohbetPaneli(SohbetModel(asistan_adi="J.A.R.V.I.S."), gonder_callback=alinan.append)
    try:
        w.sistem_mesaji_ekle("Sistemler çevrimiçi.")
        w.giris_ayarla("Merhaba Jarvis")
        w.gonder()
        assert w.mesaj_sayisi() == 2
        assert alinan == ["Merhaba Jarvis"]
        assert w.giris_metni() == ""
        w.asistan_mesaji_ekle("Size nasıl yardımcı olabilirim?")
        assert w.mesaj_sayisi() == 3
        w.beklemede(True)
        w.giris_ayarla("ikinci")
        w.gonder()  # busy — eklenmez
        assert w.mesaj_sayisi() == 3
        w.beklemede(False)
        assert w.objectName() == "CamPanel"
        assert isinstance(w.model.mesajlar[0], SohbetMesaji)
    finally:
        w.deleteLater()
    assert app is not None


if __name__ == "__main__":
    test_model_mesajlar()
    test_model_ayarlardan()
    test_max_mesaj()
    test_widget_offscreen()
    print("OK test_sohbet_paneli")

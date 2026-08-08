"""plugins/modeller.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from core.exceptions import PluginError
from plugins.modeller import (
    PLUGIN_MODEL_SURUM,
    VARSAYILAN_PLUGIN_DIZINI,
    PluginDurumu,
    PluginKaynak,
    PluginKayit,
    PluginManifesto,
    PluginSonucu,
    durum_coz,
    eklenti_adi_dogrula,
    kayit_olustur,
    kaynak_coz,
    manifesto_olustur,
)


def test_durum_ve_kaynak_coz() -> None:
    assert durum_coz("discovered") is PluginDurumu.KESFEDILDI
    assert durum_coz("hazir") is PluginDurumu.HAZIR
    assert durum_coz("loading") is PluginDurumu.YUKLENIYOR
    assert kaynak_coz("file") is PluginKaynak.DOSYA
    assert kaynak_coz("ornek") is PluginKaynak.ORNEK
    assert kaynak_coz("memory") is PluginKaynak.BELLEK
    try:
        durum_coz("bilinmeyen_durum")
        raise AssertionError("PluginError beklenirdi")
    except PluginError as exc:
        assert exc.kod == "PLG_0020"


def test_eklenti_adi_dogrula() -> None:
    assert eklenti_adi_dogrula("Merhaba Plugin") == "merhaba_plugin"
    assert eklenti_adi_dogrula("hava-durumu") == "hava-durumu"
    try:
        eklenti_adi_dogrula("")
        raise AssertionError("PluginError beklenirdi")
    except PluginError as exc:
        assert exc.kod == "PLG_0022"
    try:
        eklenti_adi_dogrula("modeller")
        raise AssertionError("PluginError beklenirdi")
    except PluginError as exc:
        assert exc.kod == "PLG_0024"
    try:
        eklenti_adi_dogrula("kötü!")
        raise AssertionError("PluginError beklenirdi")
    except PluginError as exc:
        assert exc.kod == "PLG_0023"


def test_manifesto_roundtrip() -> None:
    man = manifesto_olustur(
        "merhaba",
        surum="0.2.0",
        aciklama="Ornek eklenti",
        tehlikeli=False,
        kaynak="example",
        yol="plugins/ornek/merhaba.py",
        anahtarlar=("selam", "hello"),
    )
    assert man.ad == "merhaba"
    assert man.kaynak is PluginKaynak.ORNEK
    d = man.to_dict()
    assert d["name"] == "merhaba"
    assert d["version"] == "0.2.0"
    assert d["entry"] == "merhaba"
    assert d["source"] == "example"
    assert d["model_version"] == PLUGIN_MODEL_SURUM
    assert "selam" in d["keywords"]

    geri = PluginManifesto.from_dict(d)
    assert geri.ad == "merhaba"
    assert geri.surum == "0.2.0"
    assert geri.kaynak is PluginKaynak.ORNEK

    try:
        PluginManifesto.from_dict({"version": "1.0"})
        raise AssertionError("PluginError beklenirdi")
    except PluginError as exc:
        assert exc.kod == "PLG_0026"


def test_kayit_hazir_ve_hata() -> None:
    kayit = kayit_olustur("demo", dry_run=True, kaynak=PluginKaynak.BELLEK)
    assert kayit.durum is PluginDurumu.KESFEDILDI
    assert kayit.dry_run is True
    assert not kayit.hazir_mi

    kayit.hazir_isaretle()
    assert kayit.hazir_mi
    assert kayit.yuklenme_zamani is not None

    d = kayit.to_dict()
    assert d["status"] == "ready"
    assert d["dry_run"] is True
    geri = PluginKayit.from_dict(d)
    assert geri.ad == "demo"
    assert geri.durum is PluginDurumu.HAZIR

    kayit.hata_isaretle("yukleme basarisiz")
    assert kayit.durum is PluginDurumu.HATA
    assert kayit.hata == "yukleme basarisiz"


def test_plugin_sonucu_ve_yetenek_kopru() -> None:
    ok = PluginSonucu.ok("tamam", eklenti="merhaba", veri={"x": 1}, sure_ms=12.5)
    assert ok.basarili_mi
    d = ok.to_dict()
    assert d["ok"] is True
    assert d["plugin"] == "merhaba"
    assert d["duration_ms"] == 12.5

    geri = PluginSonucu.from_dict(d)
    assert geri.durum is YetenekDurumu.BASARILI
    ys = geri.to_yetenek_sonucu()
    assert ys.durum is YetenekDurumu.BASARILI
    assert ys.yetenek == "merhaba"
    assert ys.veri["x"] == 1

    hata = PluginSonucu.hata("patladi", eklenti="merhaba")
    assert not hata.basarili_mi
    assert hata.to_dict()["status"] == YetenekDurumu.BASARISIZ.value


def test_varsayilan_dizin_sabiti() -> None:
    assert VARSAYILAN_PLUGIN_DIZINI == "plugins"

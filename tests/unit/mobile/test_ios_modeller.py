"""mobile/ios/modeller.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import MobileBridgeError
from mobile.ios.modeller import (
    IOS_MODEL_SURUM,
    VARSAYILAN_YETENEKLER,
    IosCihaz,
    IosOturum,
    IosOturumDurumu,
    IosPilBilgisi,
    baglanti_durumu_coz,
    ios_cihaz_olustur,
    ios_oturum_olustur,
    oturum_durumu_coz,
)
from network.device.modeller import BaglantiDurumu, BagliCihaz, PlatformTuru


def test_oturum_ve_baglanti_coz() -> None:
    assert oturum_durumu_coz("connected") is IosOturumDurumu.BAGLI
    assert baglanti_durumu_coz("online") is BaglantiDurumu.CEVRIMICI
    try:
        oturum_durumu_coz("bilinmeyen")
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0020"


def test_pil_roundtrip_ve_sinir() -> None:
    pil = IosPilBilgisi(yuzde=82, sarj_oluyor=False, dusuk_guc=True)
    d = pil.to_dict()
    assert d["percent"] == 82
    assert d["low_power"] is True
    geri = IosPilBilgisi.from_dict(d)
    assert geri.yuzde == 82
    assert geri.dusuk_guc is True
    try:
        IosPilBilgisi.from_dict({"percent": 150})
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0024"


def test_ios_cihaz_wire_ve_bagli_cihaz() -> None:
    cihaz = ios_cihaz_olustur("iphone-1", ad="Yasir iPhone", model="iPhone 15")
    cihaz.durum = BaglantiDurumu.CEVRIMICI
    cihaz.pil_guncelle(91, sarj_oluyor=True)
    cihaz.oturum_id = "sess-1"
    assert cihaz.cevrimici_mi()
    assert cihaz.yetenek_var_mi("find_phone")
    assert "find_phone" in VARSAYILAN_YETENEKLER

    d = cihaz.to_dict()
    assert d["v"] == IOS_MODEL_SURUM
    assert d["device_id"] == "iphone-1"
    assert d["platform"] == "ios"
    assert d["battery"]["percent"] == 91
    assert d["session_id"] == "sess-1"
    assert "find_phone" in d["capabilities"]

    geri = IosCihaz.from_dict(d)
    assert geri.cihaz_id == "iphone-1"
    assert geri.pil is not None and geri.pil.yuzde == 91

    bagli = geri.bagli_cihaza()
    assert isinstance(bagli, BagliCihaz)
    assert bagli.platform is PlatformTuru.IOS
    assert bagli.pil_yuzde == 91
    assert bagli.meta["session_id"] == "sess-1"

    tekrar = IosCihaz.bagli_cihazdan(bagli)
    assert tekrar.cihaz_id == "iphone-1"
    assert tekrar.model == "iPhone 15"


def test_bagli_cihazdan_yanlis_platform() -> None:
    web = BagliCihaz(
        cihaz_id="web-1",
        ad="Web",
        platform=PlatformTuru.WEB,
    )
    try:
        IosCihaz.bagli_cihazdan(web)
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0025"


def test_ios_oturum_baglan_kopar() -> None:
    oturum = ios_oturum_olustur(host="192.168.1.10", cihaz_id="iphone-2")
    assert oturum.durum is IosOturumDurumu.BAGLANIYOR
    assert not oturum.bagli_mi()

    oturum.baglan("iphone-2", token_parmak_izi="abc123", shortcuts_aktif=True)
    assert oturum.bagli_mi()
    assert oturum.shortcuts_aktif is True

    d = oturum.to_dict()
    assert d["session_id"] == oturum.oturum_id
    assert d["device_id"] == "iphone-2"
    assert d["authenticated"] is True
    assert d["shortcuts_enabled"] is True
    assert d["host"] == "192.168.1.10"

    geri = IosOturum.from_dict(d)
    assert geri.oturum_id == oturum.oturum_id
    assert geri.bagli_mi()

    oturum.kopar()
    assert oturum.durum is IosOturumDurumu.KOPUK
    assert not oturum.bagli_mi()


def test_cihaz_device_id_zorunlu() -> None:
    try:
        IosCihaz.from_dict({"name": "x"})
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0027"


if __name__ == "__main__":
    test_oturum_ve_baglanti_coz()
    test_pil_roundtrip_ve_sinir()
    test_ios_cihaz_wire_ve_bagli_cihaz()
    test_bagli_cihazdan_yanlis_platform()
    test_ios_oturum_baglan_kopar()
    test_cihaz_device_id_zorunlu()
    print("OK test_ios_modeller")

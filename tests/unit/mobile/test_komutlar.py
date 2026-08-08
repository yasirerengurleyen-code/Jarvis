"""mobile/bridge/komutlar.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import MobileBridgeError
from mobile.bridge.komutlar import (
    KOMUT_SOZLESME_SURUM,
    KomutDurum,
    KomutYon,
    MobilKomut,
    MobilKomutIstegi,
    MobilKomutSozlesmesi,
    MobilKomutYaniti,
    istek_olustur,
    komut_coz,
    komut_yonu,
    tehlikeli_mi,
    yon_coz,
)


def test_komut_coz_ve_bilinmeyen() -> None:
    assert komut_coz("find_phone") is MobilKomut.FIND_PHONE
    assert komut_coz(MobilKomut.BATTERY_STATUS) is MobilKomut.BATTERY_STATUS
    try:
        komut_coz("bilinmeyen_komut")
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0010"


def test_yon_ve_tehlikeli() -> None:
    assert yon_coz("pc_to_phone") is KomutYon.PC_TO_PHONE
    assert komut_yonu(MobilKomut.FIND_PHONE) is KomutYon.PC_TO_PHONE
    assert komut_yonu("shutdown_pc") is KomutYon.PHONE_TO_PC
    assert tehlikeli_mi(MobilKomut.SHUTDOWN_PC) is True
    assert tehlikeli_mi(MobilKomut.FIND_PHONE) is False


def test_istek_roundtrip_wire_keys() -> None:
    istek = istek_olustur(
        "find_phone",
        cihaz_id="iphone-1",
        args={"vibrate": True},
    )
    assert istek.komut is MobilKomut.FIND_PHONE
    assert istek.yon is KomutYon.PC_TO_PHONE
    assert istek.onay_gerekli is False
    assert istek.surum == KOMUT_SOZLESME_SURUM

    d = istek.to_dict()
    assert d["command"] == "find_phone"
    assert d["direction"] == "pc_to_phone"
    assert d["device_id"] == "iphone-1"
    assert d["args"]["vibrate"] is True
    assert d["require_confirm"] is False
    assert "id" in d and "ts" in d and "v" in d

    geri = MobilKomutIstegi.from_dict(d)
    assert geri.komut is MobilKomut.FIND_PHONE
    assert geri.cihaz_id == "iphone-1"
    assert geri.args["vibrate"] is True
    assert geri.istek_id == istek.istek_id


def test_shutdown_onay_gerekli() -> None:
    istek = istek_olustur("shutdown_pc", cihaz_id="iphone-2")
    assert istek.onay_gerekli is True
    assert istek.yon is KomutYon.PHONE_TO_PC


def test_sozlesme_izin_ve_yanit() -> None:
    soz = MobilKomutSozlesmesi()
    assert soz.izinli_mi(MobilKomut.SEND_NOTIFICATION) is True
    assert soz.izinli_mi(MobilKomut.FIND_PHONE, KomutYon.PHONE_TO_PC) is False
    assert "find_phone" in soz.pc_to_phone_listesi()
    assert "shutdown_pc" in soz.phone_to_pc_listesi()

    ok = soz.yanit_ok(
        MobilKomut.BATTERY_STATUS,
        mesaj="Pil alindi",
        veri={"percent": 82, "charging": False},
        cihaz_id="iphone-1",
        istek_id="abc",
    )
    assert ok.basarili_mi
    assert ok.to_dict()["status"] == "ok"
    assert ok.to_dict()["data"]["percent"] == 82

    hata = soz.yanit_hata(
        "open_camera",
        "Cihaz cevrimdisi",
        durum=KomutDurum.HATA,
        cihaz_id="iphone-1",
    )
    assert not hata.basarili_mi
    geri = MobilKomutYaniti.from_dict(hata.to_dict())
    assert geri.durum is KomutDurum.HATA
    assert geri.komut is MobilKomut.OPEN_CAMERA


def test_izinli_degil_hata() -> None:
    # dogrula=False ile bilinmeyen yön kombinasyonu üretilebilir; bilinmeyen komut yine patlar
    try:
        komut_coz("hack_device")
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0010"


if __name__ == "__main__":
    test_komut_coz_ve_bilinmeyen()
    test_yon_ve_tehlikeli()
    test_istek_roundtrip_wire_keys()
    test_shutdown_onay_gerekli()
    test_sozlesme_izin_ve_yanit()
    test_izinli_degil_hata()
    print("OK test_komutlar")

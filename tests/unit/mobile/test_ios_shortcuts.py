"""mobile/ios/shortcuts.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import MobileBridgeError
from mobile.bridge.komutlar import KomutDurum, KomutYon, MobilKomut, istek_olustur
from mobile.ios.kopru import ios_kopru_olustur
from mobile.ios.shortcuts import (
    APPLE_SHORTCUTS_SCHEME,
    SHORTCUTS_SOZLESME_SURUM,
    VARSAYILAN_SCHEME,
    IosShortcuts,
    ShortcutAksiyon,
    ShortcutYuk,
    aksiyon_coz,
    ios_shortcuts_olustur,
    kisayol_adi,
    mobil_komuta,
)


def test_aksiyon_coz_ve_kisayol_adi() -> None:
    assert aksiyon_coz("find_phone") is ShortcutAksiyon.FIND_PHONE
    assert aksiyon_coz(MobilKomut.BATTERY_STATUS) is ShortcutAksiyon.BATTERY_STATUS
    assert aksiyon_coz(ShortcutAksiyon.PING) is ShortcutAksiyon.PING
    assert kisayol_adi("find_phone") == "WhiteCore Find Phone"
    assert mobil_komuta(ShortcutAksiyon.FIND_PHONE) is MobilKomut.FIND_PHONE
    assert mobil_komuta(ShortcutAksiyon.PAIR) is None
    try:
        aksiyon_coz("bilinmeyen")
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0050"


def test_yuk_roundtrip_wire_keys() -> None:
    sc = ios_shortcuts_olustur(dry_run=True)
    yuk = sc.yuk_olustur(
        "send_notification",
        cihaz_id="iphone-s1",
        args={"title": "Merhaba", "body": "Test"},
        token="tok-demo",
        x_success="shortcuts://",
    )
    assert yuk.aksiyon is ShortcutAksiyon.SEND_NOTIFICATION
    assert yuk.surum == SHORTCUTS_SOZLESME_SURUM

    d = yuk.to_dict()
    assert d["action"] == "send_notification"
    assert d["device_id"] == "iphone-s1"
    assert d["args"]["title"] == "Merhaba"
    assert d["token"] == "tok-demo"
    assert d["x_success"] == "shortcuts://"
    assert "id" in d and "ts" in d and "v" in d

    geri = ShortcutYuk.from_dict(d)
    assert geri.aksiyon is ShortcutAksiyon.SEND_NOTIFICATION
    assert geri.cihaz_id == "iphone-s1"
    assert geri.args["body"] == "Test"


def test_yuk_to_istek_ve_tersi() -> None:
    sc = ios_shortcuts_olustur(dry_run=True)
    yuk = sc.yuk_olustur("find_phone", cihaz_id="iphone-s2", args={"vibrate": True})
    istek = sc.yuk_to_istek(yuk)
    assert istek.komut is MobilKomut.FIND_PHONE
    assert istek.yon is KomutYon.PC_TO_PHONE
    assert istek.cihaz_id == "iphone-s2"
    assert istek.args["vibrate"] is True
    assert istek.corr_id == yuk.istek_id

    geri_yuk = sc.istek_to_yuk(istek)
    assert geri_yuk.aksiyon is ShortcutAksiyon.FIND_PHONE
    assert geri_yuk.cihaz_id == "iphone-s2"

    try:
        sc.yuk_to_istek(sc.yuk_olustur("pair"))
        raise AssertionError("MobileBridgeError beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0054"


def test_companion_ve_x_callback_url() -> None:
    sc = ios_shortcuts_olustur(dry_run=True)
    url = sc.companion_url(
        "find_phone",
        cihaz_id="iphone-s3",
        args={"vibrate": True, "sound": False},
        token="abc",
        istek_id="req-1",
    )
    assert url.startswith(f"{VARSAYILAN_SCHEME}://v1/command?")
    parca = urlparse(url)
    q = parse_qs(parca.query)
    assert q["action"] == ["find_phone"]
    assert q["device_id"] == ["iphone-s3"]
    assert q["id"] == ["req-1"]
    assert q["token"] == ["abc"]
    assert q["arg_vibrate"] == ["true"]
    assert q["arg_sound"] == ["false"]

    xurl = sc.x_callback_url(
        "battery_status",
        cihaz_id="iphone-s3",
        x_success="shortcuts://callback-ok",
        x_error="shortcuts://callback-err",
    )
    assert "x-callback-url/command" in xurl
    assert "x-success=" in xurl
    assert "action=battery_status" in xurl


def test_url_ayristir_companion() -> None:
    sc = ios_shortcuts_olustur(dry_run=True)
    url = sc.companion_url(
        "open_camera",
        cihaz_id="iphone-s4",
        args={"front": True},
        istek_id="cam-1",
        x_success="shortcuts://ok",
    )
    yuk = sc.url_ayristir(url)
    assert yuk.aksiyon is ShortcutAksiyon.OPEN_CAMERA
    assert yuk.cihaz_id == "iphone-s4"
    assert yuk.istek_id == "cam-1"
    assert yuk.args["front"] is True
    assert yuk.x_success == "shortcuts://ok"
    assert yuk.kaynak == "url"


def test_shortcuts_calistir_url_ve_ayristir() -> None:
    sc = ios_shortcuts_olustur(dry_run=True)
    url = sc.shortcuts_calistir_url(
        "battery_status",
        cihaz_id="iphone-s5",
        args={"percent": 42},
    )
    assert url.startswith(f"{APPLE_SHORTCUTS_SCHEME}://run-shortcut?")
    q = parse_qs(urlparse(url).query)
    assert unquote(q["name"][0]) == "WhiteCore Battery"
    assert q["input"] == ["text"]

    yuk = sc.url_ayristir(url)
    assert yuk.aksiyon is ShortcutAksiyon.BATTERY_STATUS
    assert yuk.cihaz_id == "iphone-s5"
    assert yuk.args.get("percent") == 42
    assert yuk.kaynak == "apple_shortcuts"

    ac = sc.shortcuts_ac_url("find_phone")
    assert ac.startswith(f"{APPLE_SHORTCUTS_SCHEME}://open-shortcut?")
    assert "WhiteCore%20Find%20Phone" in ac or "Find" in unquote(ac)


def test_url_ayristir_hatalar() -> None:
    sc = ios_shortcuts_olustur(dry_run=True)
    try:
        sc.url_ayristir("")
        raise AssertionError("beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0055"

    try:
        sc.url_ayristir("http://example.com/x")
        raise AssertionError("beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0056"

    try:
        sc.url_ayristir("whitecore://v1/command?id=1")
        raise AssertionError("beklenirdi")
    except MobileBridgeError as exc:
        assert exc.kod == "MOB_0052"


def test_isle_dry_run_find_phone_ve_ping() -> None:
    async def _run() -> None:
        sc = ios_shortcuts_olustur(dry_run=True)
        assert sc.motor == "dry_run"
        assert sc.durum()["scheme"] == VARSAYILAN_SCHEME

        url = sc.companion_url("find_phone", cihaz_id="iphone-s6")
        sonuc = await sc.isle(url)
        assert sonuc["ok"] is True
        assert sonuc["action"] == "find_phone"
        assert sonuc["status"] == KomutDurum.OK.value
        assert sonuc["data"]["played"] is True
        assert sonuc["via"] == "shortcuts"

        ping = await sc.isle(sc.yuk_olustur("ping", cihaz_id="iphone-s6"))
        assert ping["ok"] is True
        assert ping["action"] == "ping"
        assert ping["data"]["pong"] is True

        pair = await sc.isle(
            sc.yuk_olustur("pair", cihaz_id="iphone-s6", token="t1")
        )
        assert pair["ok"] is True
        assert pair["data"]["paired"] is True
        assert pair["data"]["token_accepted"] is True

        kayitlar = sc.islenenleri_cek()
        assert len(kayitlar) == 3
        assert kayitlar[0]["action"] == "find_phone"

    asyncio.run(_run())


def test_isle_phone_to_pc_ve_katalog() -> None:
    async def _run() -> None:
        sc = ios_shortcuts_olustur(dry_run=True)
        katalog = sc.katalog()
        assert len(katalog) == len(ShortcutAksiyon)
        adlar = {x["action"] for x in katalog}
        assert "shutdown_pc" in adlar
        assert "pair" in adlar

        istek = istek_olustur("open_vscode", cihaz_id="iphone-s7")
        sonuc = await sc.isle(istek)
        assert sonuc["ok"] is True
        assert sonuc["data"]["queued"] is True
        assert sonuc["data"]["command"] == "open_vscode"

        # shutdown dry_run'da onay beklemeden ok (queued)
        sd = await sc.isle(sc.yuk_olustur("shutdown_pc", cihaz_id="iphone-s7"))
        assert sd["ok"] is True
        assert sd["data"]["queued"] is True

    asyncio.run(_run())


def test_isle_kopru_ile() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        try:
            await kopru.cihaz_bagla("iphone-s8", ad="Shortcuts Phone")
            sc = ios_shortcuts_olustur(dry_run=True, kopru=kopru)
            assert sc.motor == "dry_run"  # dry_run öncelikli

            # dry_run True olsa bile kopru calisiyor + bagli → köprü yolu
            # motor dry_run kalır ama _isle_komut köprüye gider
            sonuc = await sc.isle(
                sc.companion_url("battery_status", cihaz_id="iphone-s8")
            )
            assert sonuc["ok"] is True
            assert "percent" in sonuc["data"]
            assert sonuc["action"] == "battery_status"
        finally:
            await kopru.durdur()

    asyncio.run(_run())


def test_factory_ve_ozel_scheme() -> None:
    sc = IosShortcuts(dry_run=False, zorla_sahte=True, scheme="wcai")
    assert sc.motor == "sahte"
    assert sc.scheme == "wcai"
    url = sc.companion_url("ping")
    assert url.startswith("wcai://v1/command?")
    sc2 = ios_shortcuts_olustur(dry_run=True)
    assert isinstance(sc2, IosShortcuts)

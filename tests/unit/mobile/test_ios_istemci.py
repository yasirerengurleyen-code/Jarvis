"""mobile/ios/istemci.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import PlatformIstemciTabani
from core.events import (
    OLAY_IPHONE_BAGLANDI,
    OLAY_IPHONE_KOPTU,
    olay_yolu,
)
from core.exceptions import MobileBridgeError
from mobile.bridge.komutlar import KomutDurum, KomutYon, MobilKomut
from mobile.ios.istemci import ios_istemci_olustur, pc_komut_istegi
from mobile.ios.modeller import IosOturumDurumu
from network.device.modeller import BaglantiDurumu
from network.websocket.sunucu import WsSunucu


def test_platform_tabani_ve_motor() -> None:
    istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-t1")
    assert isinstance(istemci, PlatformIstemciTabani)
    assert istemci.platform == "ios"
    assert istemci.motor == "dry_run"
    assert not istemci.bagli_mi


def test_baglan_kopar_dry_run() -> None:
    async def _run() -> None:
        olaylar: list[str] = []

        async def _kaydet(event: object) -> None:
            olaylar.append(getattr(event, "ad", ""))

        olay_yolu.subscribe(OLAY_IPHONE_BAGLANDI, _kaydet)
        olay_yolu.subscribe(OLAY_IPHONE_KOPTU, _kaydet)
        try:
            istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-t2")
            ok = await istemci.baglan("127.0.0.1", "test-token-abc")
            assert ok is True
            assert istemci.bagli_mi
            assert istemci.oturum.durum is IosOturumDurumu.BAGLI
            assert istemci.cihaz.durum is BaglantiDurumu.CEVRIMICI

            ozet = await istemci.durum()
            assert ozet["connected"] is True
            assert ozet["engine"] == "dry_run"
            assert ozet["device"]["device_id"] == "iphone-t2"

            await istemci.baglantiyi_kes()
            assert not istemci.bagli_mi
            assert OLAY_IPHONE_BAGLANDI in olaylar
            assert OLAY_IPHONE_KOPTU in olaylar
        finally:
            olay_yolu.unsubscribe(OLAY_IPHONE_BAGLANDI)
            olay_yolu.unsubscribe(OLAY_IPHONE_KOPTU)

    asyncio.run(_run())


def test_bos_token_hata() -> None:
    async def _run() -> None:
        istemci = ios_istemci_olustur(dry_run=True)
        try:
            await istemci.baglan("127.0.0.1", "")
            raise AssertionError("MobileBridgeError beklenirdi")
        except MobileBridgeError as exc:
            assert exc.kod == "MOB_0030"

    asyncio.run(_run())


def test_komut_al_find_battery_notification() -> None:
    async def _run() -> None:
        istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-t3")
        await istemci.baglan("192.168.1.5", "tok-1")
        istemci.pil_ayarla(64, sarj_oluyor=True)

        find = await istemci.komut_al("find_phone", args={"vibrate": True})
        assert find.basarili_mi
        assert find.durum is KomutDurum.OK
        assert find.veri["played"] is True

        pil = await istemci.komut_al(MobilKomut.BATTERY_STATUS)
        assert pil.veri["percent"] == 64
        assert pil.veri["charging"] is True

        bild = await istemci.komut_al(
            "send_notification",
            args={"title": "Merhaba", "body": "Test"},
        )
        assert bild.veri["delivered"] is True
        assert bild.veri["title"] == "Merhaba"

        gelen = istemci.gelen_cek()
        assert len(gelen) == 3
        assert gelen[0].komut is MobilKomut.FIND_PHONE

        yanitlar = istemci.yanit_cek()
        assert len(yanitlar) == 3

        await istemci.baglantiyi_kes()

    asyncio.run(_run())


def test_bagli_degilken_komut_hata() -> None:
    async def _run() -> None:
        istemci = ios_istemci_olustur(dry_run=True)
        try:
            await istemci.komut_al("find_phone")
            raise AssertionError("MobileBridgeError beklenirdi")
        except MobileBridgeError as exc:
            assert exc.kod == "MOB_0032"

    asyncio.run(_run())


def test_komut_gonder_phone_to_pc() -> None:
    async def _run() -> None:
        istemci = ios_istemci_olustur(
            dry_run=False, zorla_sahte=True, cihaz_id="iphone-t4"
        )
        assert istemci.motor == "sahte"
        await istemci.baglan("10.0.0.1", "sahte-token")

        istek = await istemci.komut_gonder("open_vscode", args={"path": "."})
        assert istek.yon is KomutYon.PHONE_TO_PC
        assert istek.komut is MobilKomut.OPEN_VSCODE
        assert istek.cihaz_id == "iphone-t4"

        kuyruk = istemci.pc_komut_cek()
        assert len(kuyruk) == 1
        assert kuyruk[0].istek_id == istek.istek_id

        # pc_to_phone komut_gonder ile reddedilmeli
        try:
            await istemci.komut_gonder("find_phone")
            raise AssertionError("MobileBridgeError beklenirdi")
        except MobileBridgeError as exc:
            assert exc.kod == "MOB_0034"

        await istemci.baglantiyi_kes()

    asyncio.run(_run())


def test_pc_komut_istegi_ve_istek_nesnesi() -> None:
    async def _run() -> None:
        istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-t5")
        await istemci.baglan("127.0.0.1", "tok")
        istek = pc_komut_istegi(
            "open_camera", cihaz_id="iphone-t5", args={"mode": "photo"}
        )
        yanit = await istemci.komut_al(istek)
        assert yanit.basarili_mi
        assert yanit.veri["opened"] is True
        assert yanit.istek_id == istek.istek_id
        await istemci.baglantiyi_kes()

    asyncio.run(_run())


def test_memory_ws_auth() -> None:
    async def _run() -> None:
        srv = WsSunucu(dry_run=True, asistan_adi="J.A.R.V.I.S.")
        await srv.baslat()
        try:
            istemci = ios_istemci_olustur(
                dry_run=False,
                cihaz_id="iphone-ws",
                ws_sunucu=srv,
            )
            assert istemci.motor == "memory"
            ok = await istemci.baglan("127.0.0.1", "ws-token")
            assert ok is True
            assert istemci.bagli_mi

            # WS oturumu kimlikli olmalı
            oturumlar = srv.oturum_listele(sadece_kimlikli=True)
            assert len(oturumlar) == 1
            assert oturumlar[0].cihaz_id == "iphone-ws"

            find = await istemci.komut_al("find_phone")
            assert find.basarili_mi

            await istemci.baglantiyi_kes()
            assert srv.oturum_listele() == []
        finally:
            await srv.durdur()

    asyncio.run(_run())


def test_komut_al_phone_to_pc_red() -> None:
    async def _run() -> None:
        istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-t6")
        await istemci.baglan("127.0.0.1", "tok")
        try:
            await istemci.komut_al("shutdown_pc")
            raise AssertionError("MobileBridgeError beklenirdi")
        except MobileBridgeError as exc:
            assert exc.kod == "MOB_0033"
        await istemci.baglantiyi_kes()

    asyncio.run(_run())


if __name__ == "__main__":
    test_platform_tabani_ve_motor()
    test_baglan_kopar_dry_run()
    test_bos_token_hata()
    test_komut_al_find_battery_notification()
    test_bagli_degilken_komut_hata()
    test_komut_gonder_phone_to_pc()
    test_pc_komut_istegi_ve_istek_nesnesi()
    test_memory_ws_auth()
    test_komut_al_phone_to_pc_red()
    print("OK test_ios_istemci")

"""mobile/yoneticisi.py birim testleri (dry_run / ağsız)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import MobileBridgeError
from mobile.bridge.komutlar import KomutDurum, MobilKomut
from mobile.ios.kopru import IosKopru
from mobile.ios.shortcuts import IosShortcuts
from mobile.yoneticisi import MobilYoneticisi, mobil_yoneticisi_olustur
from network.device.modeller import BaglantiDurumu, PlatformTuru
from network.yoneticisi import NetworkYoneticisi


def _yonetici() -> MobilYoneticisi:
    bus = EventBus(ad="test.mobile")
    return MobilYoneticisi(bus=bus, dry_run=True, olustur=True)


def test_modul_tabani_ve_fabrika() -> None:
    m = mobil_yoneticisi_olustur(dry_run=True)
    assert isinstance(m, MobilYoneticisi)
    assert isinstance(m, ModulTabani)
    assert m.ad == "mobile"
    assert m.motor == "dry_run"
    assert isinstance(m.kopru, IosKopru)
    assert isinstance(m.shortcuts, IosShortcuts)
    assert m.shortcuts.kopru is m.kopru


def test_dry_run_baslat_durdur_ozet() -> None:
    async def _run() -> None:
        m = _yonetici()
        assert m.motor == "dry_run"
        assert m.kopru is not None
        assert m.shortcuts is not None

        await m.baslat()
        assert m.calisiyor
        assert m.kopru.calisiyor

        ozet = m.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["bridge"]["engine"] == "dry_run"
        assert ozet["bridge"]["running"] is True
        assert ozet["shortcuts"]["module"] == "mobile.ios.shortcuts"
        assert ozet["primary_mobile"] == "ios"

        await m.durdur()
        assert not m.calisiyor
        assert not m.kopru.calisiyor

    asyncio.run(_run())


def test_baslamadan_komut_hata() -> None:
    async def _run() -> None:
        m = _yonetici()
        try:
            await m.telefonumu_bul("iphone-x")
            raise AssertionError("MobileBridgeError beklenirdi")
        except MobileBridgeError as exc:
            assert exc.kod == "MOB_0061"

    asyncio.run(_run())


def test_telefonumu_bul_pil_bildirim() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            istemci = await m.cihaz_bagla("iphone-m1", ad="Manager iPhone")
            assert istemci.bagli_mi
            istemci.pil_ayarla(72, sarj_oluyor=False)

            find = await m.telefonumu_bul("iphone-m1")
            assert find["ok"] is True
            assert find["status"] == KomutDurum.OK.value
            assert find["data"]["played"] is True

            pil = await m.pil_durumu("iphone-m1")
            assert pil["ok"] is True
            assert pil["data"]["percent"] == 72

            bild = await m.bildirim_gonder(
                "iphone-m1", "Merhaba", "Manager test", veri={"n": 1}
            )
            assert bild["ok"] is True
            assert bild["data"]["delivered"] is True

            durum = await m.baglanti_durumu("iphone-m1")
            assert durum is BaglantiDurumu.CEVRIMICI

            cihazlar = await m.bagli_cihazlar()
            assert len(cihazlar) == 1
            assert cihazlar[0].cihaz_id == "iphone-m1"
            assert cihazlar[0].platform is PlatformTuru.IOS
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_komut_gonder_ve_shortcut() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            await m.cihaz_bagla("iphone-sc")

            yanit = await m.komut_gonder(
                "iphone-sc",
                MobilKomut.FIND_PHONE,
                args={"vibrate": True},
            )
            assert yanit.basarili_mi
            assert yanit.durum is KomutDurum.OK

            katalog = m.shortcut_katalog()
            assert any(k["action"] == "find_phone" for k in katalog)

            url = m.shortcut_url("find_phone", cihaz_id="iphone-sc")
            assert url.startswith("whitecore://")
            assert "action=find_phone" in url

            sonuc = await m.shortcut_isle(url, cihaz_id="iphone-sc")
            assert sonuc["ok"] is True
            assert sonuc["via"] == "shortcuts"
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_agdan_network_kancasi() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        bus = EventBus(ad="test.mobile.net")
        net = NetworkYoneticisi(
            bus=bus,
            dry_run=True,
            kayit_yolu=tmp / "devices.json",
            sync_depo_kok=tmp / "sync",
            sync_olustur=True,
        )
        await net.baslat()
        try:
            m = MobilYoneticisi.agdan(net, bus=bus)
            assert m.motor == "dry_run"
            assert m._network is net
            assert m.kopru is not None
            assert m.kopru.cihaz_yoneticisi is net.cihazlar
            assert m.kopru.ws_sunucu is net.ws

            await m.baslat()
            assert m.calisiyor
            assert m.ozet()["network_bound"] is True

            istemci = await m.cihaz_bagla("iphone-net", ad="Net iPhone")
            assert istemci.bagli_mi
            # Cihaz yöneticisinde ios kaydı oluşmalı
            kayitlar = net.cihazlar.listele(platform="ios")
            assert any(c.cihaz_id == "iphone-net" for c in kayitlar)

            await m.durdur()
        finally:
            await net.durdur()

    asyncio.run(_run())


def test_istemci_olustur_kaydet() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            istemci = m.istemci_olustur(cihaz_id="iphone-create", ad="Create")
            assert m.kopru.istemci_var_mi("iphone-create")
            # Henüz bağlı değil — bagla ile bağlanır
            assert not istemci.bagli_mi
            bagli = await m.cihaz_bagla("iphone-create")
            assert bagli.bagli_mi
            await m.cihaz_kopar("iphone-create")
            assert not bagli.bagli_mi
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_idempotent_baslat_durdur() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        await m.baslat()  # ikinci çağrı no-op
        assert m.calisiyor
        await m.durdur()
        await m.durdur()  # ikinci çağrı no-op
        assert not m.calisiyor

    asyncio.run(_run())


if __name__ == "__main__":
    test_modul_tabani_ve_fabrika()
    test_dry_run_baslat_durdur_ozet()
    test_baslamadan_komut_hata()
    test_telefonumu_bul_pil_bildirim()
    test_komut_gonder_ve_shortcut()
    test_agdan_network_kancasi()
    test_istemci_olustur_kaydet()
    test_idempotent_baslat_durdur()
    print("OK test_yoneticisi")

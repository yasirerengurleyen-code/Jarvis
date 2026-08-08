"""mobile/ios/kopru.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.exceptions import MobileBridgeError
from mobile.bridge.arayuzler import MobilKopru
from mobile.bridge.komutlar import KomutDurum, MobilKomut
from mobile.ios.istemci import ios_istemci_olustur
from mobile.ios.kopru import IosKopru, ios_kopru_olustur
from network.device.modeller import BaglantiDurumu, PlatformTuru
from network.device.yonetici import CihazYoneticisi


def test_mobil_kopru_ve_modul_tabani() -> None:
    kopru = ios_kopru_olustur(dry_run=True)
    assert isinstance(kopru, MobilKopru)
    assert isinstance(kopru, ModulTabani)
    assert kopru.motor == "dry_run"
    assert kopru.ad == "mobile.ios.kopru"


def test_baslat_durdur_durum() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        assert kopru.calisiyor
        ozet = await kopru.durum()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        await kopru.durdur()
        assert not kopru.calisiyor

    asyncio.run(_run())


def test_baslamadan_komut_hata() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        try:
            await kopru.telefonumu_bul("iphone-x")
            raise AssertionError("MobileBridgeError beklenirdi")
        except MobileBridgeError as exc:
            assert exc.kod == "MOB_0044"

    asyncio.run(_run())


def test_telefonumu_bul_pil_bildirim() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        try:
            istemci = await kopru.cihaz_bagla("iphone-k1", ad="Test iPhone")
            assert istemci.bagli_mi
            istemci.pil_ayarla(55, sarj_oluyor=True)

            find = await kopru.telefonumu_bul("iphone-k1")
            assert find["ok"] is True
            assert find["status"] == KomutDurum.OK.value
            assert find["data"]["played"] is True

            pil = await kopru.pil_durumu("iphone-k1")
            assert pil["ok"] is True
            assert pil["data"]["percent"] == 55
            assert pil["data"]["charging"] is True

            bild = await kopru.bildirim_gonder(
                "iphone-k1", "Merhaba", "Kopru test", veri={"x": 1}
            )
            assert bild["ok"] is True
            assert bild["data"]["delivered"] is True
            assert bild["data"]["title"] == "Merhaba"

            durum = await kopru.baglanti_durumu("iphone-k1")
            assert durum is BaglantiDurumu.CEVRIMICI

            cihazlar = await kopru.bagli_cihazlar()
            assert len(cihazlar) == 1
            assert cihazlar[0].cihaz_id == "iphone-k1"
            assert cihazlar[0].platform is PlatformTuru.IOS
        finally:
            await kopru.durdur()

    asyncio.run(_run())


def test_otomatik_bagla_dry_run() -> None:
    async def _run() -> None:
        """Kayıtsız cihaz_id ile find_phone — dry_run otomatik bağlar."""
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        try:
            find = await kopru.telefonumu_bul("iphone-auto")
            assert find["ok"] is True
            assert kopru.istemci_var_mi("iphone-auto")
            assert kopru.istemci_al("iphone-auto").bagli_mi
        finally:
            await kopru.durdur()

    asyncio.run(_run())


def test_istemci_ekle_ve_komut_gonder() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        try:
            istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-k2")
            kopru.istemci_ekle(istemci)
            await istemci.baglan("127.0.0.1", "tok")

            yanit = await kopru.komut_gonder(
                "iphone-k2", "open_camera", args={"mode": "photo"}
            )
            assert yanit.basarili_mi
            assert yanit.komut is MobilKomut.OPEN_CAMERA
            assert yanit.veri["opened"] is True
        finally:
            await kopru.durdur()

    asyncio.run(_run())


def test_cihaz_yoneticisi_senkron() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            yonetici = CihazYoneticisi(kayit_yolu=Path(tmp) / "devices.json")
            await yonetici.baslat()
            try:
                kopru = ios_kopru_olustur(
                    dry_run=True, cihaz_yoneticisi=yonetici
                )
                await kopru.baslat()
                try:
                    await kopru.cihaz_bagla("iphone-net", ad="Net iPhone")
                    kayit = yonetici.al("iphone-net")
                    assert kayit.platform is PlatformTuru.IOS
                    assert kayit.durum is BaglantiDurumu.CEVRIMICI

                    kopru.istemci_al("iphone-net").pil_ayarla(42)
                    pil = await kopru.pil_durumu("iphone-net")
                    assert pil["data"]["percent"] == 42
                    assert yonetici.al("iphone-net").pil_yuzde == 42
                finally:
                    await kopru.durdur()
            finally:
                await yonetici.durdur()

    asyncio.run(_run())


def test_bagli_degil_bagla_false() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        try:
            istemci = ios_istemci_olustur(dry_run=True, cihaz_id="iphone-k3")
            kopru.istemci_ekle(istemci)
            assert not istemci.bagli_mi
            try:
                await kopru.komut_gonder(
                    "iphone-k3", "find_phone", bagla=False
                )
                raise AssertionError("MobileBridgeError beklenirdi")
            except MobileBridgeError as exc:
                assert exc.kod == "MOB_0043"
        finally:
            await kopru.durdur()

    asyncio.run(_run())


def test_bulunamayan_cihaz_baglanti() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=True)
        await kopru.baslat()
        try:
            try:
                await kopru.baglanti_durumu("yok-cihaz")
                raise AssertionError("MobileBridgeError beklenirdi")
            except MobileBridgeError as exc:
                assert exc.kod == "MOB_0042"
        finally:
            await kopru.durdur()

    asyncio.run(_run())


def test_sahte_motor() -> None:
    async def _run() -> None:
        kopru = ios_kopru_olustur(dry_run=False, zorla_sahte=True)
        assert kopru.motor == "sahte"
        await kopru.baslat()
        try:
            find = await kopru.telefonumu_bul("iphone-sahte")
            assert find["ok"] is True
            assert find["engine"] == "sahte"
        finally:
            await kopru.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_mobil_kopru_ve_modul_tabani()
    test_baslat_durdur_durum()
    test_baslamadan_komut_hata()
    test_telefonumu_bul_pil_bildirim()
    test_otomatik_bagla_dry_run()
    test_istemci_ekle_ve_komut_gonder()
    test_cihaz_yoneticisi_senkron()
    test_bagli_degil_bagla_false()
    test_bulunamayan_cihaz_baglanti()
    test_sahte_motor()
    print("OK test_ios_kopru")

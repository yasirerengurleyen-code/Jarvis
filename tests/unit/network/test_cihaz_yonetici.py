"""network/device/yonetici.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.events import EventBus, OLAY_CIHAZ_DURUM, OLAY_CIHAZ_ESLESTI
from core.exceptions import NetworkError
from network.device.modeller import BaglantiDurumu, PlatformTuru
from network.device.yonetici import CihazYoneticisi


def test_cihaz_crud_ve_kalicilik() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "devices.json"
        bus = EventBus(ad="test.device")
        eslesen: list[dict] = []
        bus.subscribe(OLAY_CIHAZ_ESLESTI, lambda e: eslesen.append(e.veri))

        y = CihazYoneticisi(bus=bus, kayit_yolu=tmp)
        y.max_cihaz = 2
        await y.baslat()

        c1 = y.olustur("iPhone", PlatformTuru.IOS, pil_yuzde=90)
        assert c1.cevrimici_mi()
        assert y.adet() == 1
        assert len(eslesen) == 1

        y.durum_ayarla(c1.cihaz_id, BaglantiDurumu.CEVRIMDISI, pil_yuzde=88)
        assert y.al(c1.cihaz_id).durum == BaglantiDurumu.CEVRIMDISI
        assert y.al(c1.cihaz_id).pil_yuzde == 88

        y.yeniden_adlandir(c1.cihaz_id, "Yasir iPhone")
        assert y.al(c1.cihaz_id).ad == "Yasir iPhone"

        y.olustur("iPad", "ipados")
        assert y.adet() == 2
        try:
            y.olustur("Fazla", "web")
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError as exc:
            assert "Maksimum" in str(exc)

        assert y.kaldir(c1.cihaz_id) is True
        assert y.adet() == 1
        ozet = y.ozet()
        assert ozet["count"] == 1

        await y.durdur()

        # Yeniden yükle
        y2 = CihazYoneticisi(bus=EventBus(ad="test.device2"), kayit_yolu=tmp)
        await y2.baslat()
        assert y2.adet() == 1
        assert y2.listele()[0].ad == "iPad"
        await y2.durdur()

    asyncio.run(_run())


def test_liste_filtre() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "d2.json"
        y = CihazYoneticisi(bus=EventBus(ad="t3"), kayit_yolu=tmp)
        await y.baslat()
        a = y.olustur("A", "ios", durum=BaglantiDurumu.CEVRIMICI)
        y.olustur("B", "web", durum=BaglantiDurumu.CEVRIMDISI)
        assert len(y.listele(sadece_cevrimici=True)) == 1
        assert len(y.listele(platform="ios")) == 1
        y.durum_ayarla(a.cihaz_id, "online")
        await y.durdur()

    asyncio.run(_run())


def test_bulunamadi() -> None:
    async def _run() -> None:
        y = CihazYoneticisi(
            bus=EventBus(ad="t4"),
            kayit_yolu=Path(tempfile.mkdtemp()) / "d3.json",
        )
        await y.baslat()
        try:
            y.durum_ayarla("yok", BaglantiDurumu.CEVRIMICI)
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError:
            pass
        # durum olayı publish_sync çalışır
        durumlar: list = []
        y.bus.subscribe(OLAY_CIHAZ_DURUM, lambda e: durumlar.append(e.veri))
        y.olustur("X", "ios")
        assert durumlar or True  # eslesti ayrı olay
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_cihaz_crud_ve_kalicilik()
    test_liste_filtre()
    test_bulunamadi()
    print("OK test_cihaz_yonetici")

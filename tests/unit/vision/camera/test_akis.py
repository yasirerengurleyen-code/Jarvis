"""vision/camera/akis.py birim testleri (dry_run / sahte / mock opencv)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.events import EventBus
from core.exceptions import VisionError
from vision.camera.akis import (
    OLAY_AKIS_BASLADI,
    OLAY_AKIS_DURDU,
    OLAY_AKIS_KARE,
    VideoAkis,
    video_akis_olustur,
)
from vision.camera.kamera import KameraYoneticisi
from vision.modeller import Kare, VisionMotoru


class _SahteCap:
    def __init__(self, acik: bool = True, kare: Any = None) -> None:
        self._acik = acik
        self._kare = kare
        self.released = False
        self.read_count = 0

    def isOpened(self) -> bool:
        return self._acik

    def read(self):
        self.read_count += 1
        return True, self._kare

    def set(self, prop: int, val: float) -> bool:  # noqa: ARG002
        return True

    def release(self) -> None:
        self.released = True
        self._acik = False


class _Kare:
    shape = (48, 64, 3)


class _SahteCv2:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5

    def __init__(self, *, acik: bool = True) -> None:
        self.acik = acik
        self.son_cap: _SahteCap | None = None

    def VideoCapture(self, idx: int) -> _SahteCap:  # noqa: ARG002
        self.son_cap = _SahteCap(acik=self.acik, kare=_Kare())
        return self.son_cap


def test_fabrika_ve_ozellikler() -> None:
    a = video_akis_olustur(dry_run=True, olay_yayinla=False, fps=12)
    assert isinstance(a, VideoAkis)
    assert a.ad == "vision.camera.stream"
    assert a.akiyor is False
    assert a.fps == 12
    assert a.uretilen == 0
    ozet = a.ozet()
    assert ozet["streaming"] is False
    assert ozet["fps"] == 12
    assert ozet["dry_run"] is True


def test_dry_run_akis_max_kare_ve_olaylar() -> None:
    async def _run() -> None:
        bus = EventBus(ad="test.akis.dry")
        olaylar: list[str] = []
        bus.subscribe(OLAY_AKIS_BASLADI, lambda e: olaylar.append(e.ad))
        bus.subscribe(OLAY_AKIS_DURDU, lambda e: olaylar.append(e.ad))
        bus.subscribe(OLAY_AKIS_KARE, lambda e: olaylar.append(e.ad))

        a = video_akis_olustur(dry_run=True, bus=bus, olay_yayinla=True, fps=30)
        kareler: list[Kare] = []
        async for k in a.akis(max_kare=3):
            kareler.append(k)

        assert len(kareler) == 3
        assert all(k.dry_run for k in kareler)
        assert all(k.motor == VisionMotoru.DRY_RUN for k in kareler)
        assert a.uretilen == 3
        assert a.son_kare is not None
        assert OLAY_AKIS_BASLADI in olaylar
        assert olaylar.count(OLAY_AKIS_KARE) == 3

        await a.durdur()
        assert a.akiyor is False
        assert OLAY_AKIS_DURDU in olaylar
        assert a.kamera.calisiyor is False

    asyncio.run(_run())


def test_sahte_akis_ve_kare_al() -> None:
    async def _run() -> None:
        a = video_akis_olustur(
            dry_run=False,
            zorla_sahte=True,
            olay_yayinla=False,
            fps=20,
        )
        await a.baslat()
        assert a.akiyor
        assert a.motor == "sahte"

        k = await a.kare_al()
        assert isinstance(k, Kare)
        assert k.motor == VisionMotoru.SAHTE
        assert k.dry_run is False
        assert k.ham is not None
        assert k.bayt_sayisi > 0
        assert k.genislik == 64
        assert k.yukseklik == 48

        await a.durdur()
        assert not a.akiyor

    asyncio.run(_run())


def test_fps_ayarla_ve_hata() -> None:
    a = video_akis_olustur(dry_run=True, olay_yayinla=False, fps=10)
    assert a.fps_ayarla(25) == 25
    assert a.fps == 25
    try:
        a.fps_ayarla(0)
        assert False, "VisionError beklenirdi"
    except VisionError as e:
        assert e.kod == "VIS_0102"


def test_durdur_donguyu_keser() -> None:
    async def _run() -> None:
        a = video_akis_olustur(dry_run=True, olay_yayinla=False, fps=50)
        await a.baslat()

        async def _tuket() -> int:
            n = 0
            async for _ in a.akis():
                n += 1
                if n >= 2:
                    # Döngüyü dışarıdan kes
                    await a.durdur()
            return n

        n = await asyncio.wait_for(_tuket(), timeout=5.0)
        assert n >= 2
        assert a.akiyor is False

    asyncio.run(_run())


def test_fps_throttle_yaklasik() -> None:
    async def _run() -> None:
        a = video_akis_olustur(dry_run=True, olay_yayinla=False, fps=10)
        t0 = time.perf_counter()
        kareler = [k async for k in a.akis(max_kare=3)]
        gecen = time.perf_counter() - t0
        assert len(kareler) == 3
        # 3 kare @ 10 FPS ≈ 0.2s aralık toplamı; gevşek alt sınır
        assert gecen >= 0.12
        await a.durdur()

    asyncio.run(_run())


def test_mevcut_kamera_ile_opencv_akis() -> None:
    async def _run() -> None:
        stub = _SahteCv2(acik=True)
        bus = EventBus(ad="test.akis.cv")
        kam = KameraYoneticisi(
            bus=bus,
            dry_run=False,
            zorla_sahte=False,
            cv2_modul=stub,
            olay_yayinla=False,
            cihaz=0,
            fps=30,
        )
        await kam.baslat()
        assert kam.motor == "opencv"
        assert kam.cap is not None

        a = VideoAkis(
            kam,
            bus=bus,
            olay_yayinla=True,
            kamera_yonet=False,  # dış kamera oturumunu kapatma
        )
        kareler = [k async for k in a.akis(max_kare=2)]
        assert len(kareler) == 2
        assert all(k.motor == VisionMotoru.OPENCV for k in kareler)
        assert all(k.genislik == 64 and k.yukseklik == 48 for k in kareler)
        assert stub.son_cap is not None
        assert stub.son_cap.read_count >= 2

        await a.durdur()
        # kamera_yonet=False → kamera hâlâ açık
        assert kam.calisiyor is True
        assert kam.cap is not None
        await kam.durdur()
        assert stub.son_cap.released is True

    asyncio.run(_run())


def test_max_kare_negatif_hata() -> None:
    async def _run() -> None:
        a = video_akis_olustur(dry_run=True, olay_yayinla=False)
        try:
            async for _ in a.akis(max_kare=-1):
                pass
            assert False, "VisionError beklenirdi"
        except VisionError as e:
            assert e.kod == "VIS_0103"

    asyncio.run(_run())

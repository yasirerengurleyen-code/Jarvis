"""vision/camera/kamera.py birim testleri (dry_run / sahte / mock opencv)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.camera.kamera import (
    OLAY_KAMERA_BASLADI,
    OLAY_KAMERA_CIHAZ,
    OLAY_KAMERA_DURDU,
    OLAY_KAMERA_FOTO,
    OLAY_KAMERA_FPS,
    KameraYoneticisi,
    kamera_yoneticisi_olustur,
)
from vision.modeller import KameraAyarlari, VisionMotoru, YakalamaSonucu


class _SahteCap:
    def __init__(self, acik: bool = True, kare: Any = None) -> None:
        self._acik = acik
        self._kare = kare
        self.released = False
        self.props: dict[int, float] = {}

    def isOpened(self) -> bool:
        return self._acik

    def read(self):
        return True, self._kare

    def set(self, prop: int, val: float) -> bool:
        self.props[int(prop)] = float(val)
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

    def imencode(self, ext: str, kare: Any):  # noqa: ANN001, ARG002
        class _Buf:
            def tobytes(self) -> bytes:
                return b"\x89PNG\r\n\x1a\nfake-frame"

        return True, _Buf()


def _yonetici(**kwargs: Any) -> KameraYoneticisi:
    bus = kwargs.pop("bus", EventBus(ad="test.vision.camera"))
    return KameraYoneticisi(
        bus=bus,
        dry_run=kwargs.pop("dry_run", True),
        zorla_sahte=kwargs.pop("zorla_sahte", False),
        olay_yayinla=kwargs.pop("olay_yayinla", True),
        **kwargs,
    )


def test_fabrika_ve_modul_tabani() -> None:
    m = kamera_yoneticisi_olustur(dry_run=True, olay_yayinla=False)
    assert isinstance(m, KameraYoneticisi)
    assert isinstance(m, ModulTabani)
    assert m.ad == "vision.camera"
    assert m.motor == VisionMotoru.DRY_RUN.value
    assert m.calisiyor is False
    assert m.fps >= 1


def test_dry_run_baslat_durdur_ozet() -> None:
    async def _run() -> None:
        bus = EventBus(ad="test.cam.dry")
        olaylar: list[str] = []
        bus.subscribe(OLAY_KAMERA_BASLADI, lambda e: olaylar.append(e.ad))
        bus.subscribe(OLAY_KAMERA_DURDU, lambda e: olaylar.append(e.ad))

        m = _yonetici(bus=bus, dry_run=True)
        await m.baslat()
        assert m.calisiyor
        assert m.motor == "dry_run"
        assert m.cap is None

        ozet = m.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["dry_run"] is True
        assert "device" in ozet
        assert "fps" in ozet

        await m.durdur()
        assert not m.calisiyor
        assert OLAY_KAMERA_BASLADI in olaylar
        assert OLAY_KAMERA_DURDU in olaylar

    asyncio.run(_run())


def test_cihaz_sec_ve_fps() -> None:
    async def _run() -> None:
        bus = EventBus(ad="test.cam.cfg")
        olaylar: list[str] = []
        bus.subscribe(OLAY_KAMERA_CIHAZ, lambda e: olaylar.append(e.ad))
        bus.subscribe(OLAY_KAMERA_FPS, lambda e: olaylar.append(e.ad))

        m = _yonetici(bus=bus, dry_run=True, cihaz=0, fps=15)
        await m.baslat()

        ayar = m.cihaz_sec(1)
        assert isinstance(ayar, KameraAyarlari)
        assert m.cihaz == 1
        assert ayar.cihaz == 1

        ayar2 = m.fps_ayarla(24)
        assert ayar2.fps == 24
        assert m.fps == 24

        assert OLAY_KAMERA_CIHAZ in olaylar
        assert OLAY_KAMERA_FPS in olaylar

        await m.durdur()

    asyncio.run(_run())


def test_fps_ve_cihaz_hatalari() -> None:
    m = _yonetici(dry_run=True, olay_yayinla=False)
    try:
        m.cihaz_sec(-1)
        assert False, "VisionError beklenirdi"
    except VisionError as e:
        assert e.kod == "VIS_0101"

    try:
        m.fps_ayarla(0)
        assert False, "VisionError beklenirdi"
    except VisionError as e:
        assert e.kod == "VIS_0102"


def test_fotograf_dry_run_ve_sahte() -> None:
    async def _run() -> None:
        bus = EventBus(ad="test.cam.foto")
        foto_olay: list[dict] = []
        bus.subscribe(OLAY_KAMERA_FOTO, lambda e: foto_olay.append(e.veri))

        m = _yonetici(bus=bus, dry_run=True)
        await m.baslat()

        tmp = Path(tempfile.mkdtemp()) / "plan.png"
        sonuc = m.fotograf_cek(yol=tmp)
        assert isinstance(sonuc, YakalamaSonucu)
        assert sonuc.kare.dry_run is True
        assert sonuc.kare.motor == VisionMotoru.DRY_RUN
        assert not tmp.exists()
        assert m.son_yakalama is not None
        assert foto_olay

        await m.durdur()

        m2 = _yonetici(dry_run=False, zorla_sahte=True, olay_yayinla=False)
        await m2.baslat()
        assert m2.motor == "sahte"
        tmp2 = Path(tempfile.mkdtemp()) / "sahte.png"
        s2 = m2.fotograf_cek(yol=tmp2)
        assert s2.kare.motor == VisionMotoru.SAHTE
        assert tmp2.is_file()
        assert tmp2.stat().st_size > 0
        await m2.durdur()

    asyncio.run(_run())


def test_cihazlari_listele_dry_run() -> None:
    m = _yonetici(dry_run=True, olay_yayinla=False)
    liste = m.cihazlari_listele()
    assert len(liste) >= 1
    assert liste[0].erisilebilir is True
    assert liste[0].indeks == 0


def test_mock_opencv_oturum_ve_foto() -> None:
    async def _run() -> None:
        stub = _SahteCv2(acik=True)
        bus = EventBus(ad="test.cam.cv")
        m = KameraYoneticisi(
            bus=bus,
            dry_run=False,
            zorla_sahte=False,
            cv2_modul=stub,
            olay_yayinla=True,
            cihaz=0,
            fps=20,
        )
        await m.baslat()
        assert m.calisiyor
        assert m.motor == "opencv"
        assert m.cap is not None
        assert stub.son_cap is not None
        assert stub.son_cap.props.get(stub.CAP_PROP_FPS) == 20.0

        tmp = Path(tempfile.mkdtemp()) / "cv.png"
        sonuc = m.fotograf_cek(yol=tmp)
        assert sonuc.kare.motor == VisionMotoru.OPENCV
        assert sonuc.acik is True
        assert sonuc.kare.genislik == 64
        assert sonuc.kare.yukseklik == 48
        assert tmp.is_file()

        m.fps_ayarla(10)
        assert stub.son_cap.props.get(stub.CAP_PROP_FPS) == 10.0

        await m.durdur()
        assert stub.son_cap.released is True
        assert m.cap is None

    asyncio.run(_run())


def test_opencv_acilamazsa_sahte_oturum() -> None:
    async def _run() -> None:
        stub = _SahteCv2(acik=False)
        m = KameraYoneticisi(
            dry_run=False,
            zorla_sahte=False,
            cv2_modul=stub,
            olay_yayinla=False,
        )
        await m.baslat()
        assert m.calisiyor
        assert m.motor == "sahte"
        assert m.cap is None
        await m.durdur()

    asyncio.run(_run())

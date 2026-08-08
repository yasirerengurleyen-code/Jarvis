"""vision/ocr/ekran.py birim testleri (dry_run / sahte / mock ImageGrab)."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import OcrSonucu, VisionMotoru
from vision.ocr.ekran import (
    OLAY_EKRAN_BASLADI,
    OLAY_EKRAN_DURDU,
    OLAY_EKRAN_OKUNDU,
    OLAY_EKRAN_YAKALANDI,
    EkranBolgesi,
    EkranOcr,
    bolge_coz,
    ekran_ocr_oku,
    ekran_ocr_olustur,
    imagegrab_var_mi,
    pillow_var_mi,
)
from vision.ocr.motor import OcrYoneticisi

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _SahteImg:
    def __init__(self, size: tuple[int, int] = (100, 50), ham: bytes = _MINI_PNG) -> None:
        self.size = size
        self._ham = ham

    def save(self, buf: Any, format: str = "PNG") -> None:  # noqa: A003
        buf.write(self._ham)


class _SahteImageGrab:
    def __init__(self) -> None:
        self.cagrilar: list[Optional[tuple[int, int, int, int]]] = []

    def grab(self, bbox: Any = None) -> _SahteImg:
        self.cagrilar.append(bbox)
        if bbox is None:
            return _SahteImg(size=(1920, 1080))
        sol, ust, sag, alt = bbox
        return _SahteImg(size=(max(1, sag - sol), max(1, alt - ust)))


class _SahtePytesseract:
    def __init__(self, metin: str = "Ekran metni") -> None:
        self.metin = metin
        self.cagrilar: list[tuple[Any, str]] = []

    def image_to_string(self, image: Any, lang: str = "eng") -> str:
        self.cagrilar.append((image, lang))
        return self.metin


class _SahtePillowImage:
    @staticmethod
    def open(yol: str):  # noqa: ANN001
        class _Ctx:
            def __enter__(self):
                return {"path": yol}

            def __exit__(self, *args):  # noqa: ANN002
                return None

        return _Ctx()


def test_fabrika_ve_bolge() -> None:
    e = ekran_ocr_olustur(dry_run=True)
    assert isinstance(e, EkranOcr)
    assert isinstance(e, ModulTabani)
    assert e.ad == "vision.ocr.screen"
    assert e.motor == "dry_run"
    ozet = e.ozet()
    assert ozet["dry_run"] is True
    assert isinstance(imagegrab_var_mi(), bool)
    assert isinstance(pillow_var_mi(), bool)

    b = bolge_coz((10, 20, 100, 50))
    assert isinstance(b, EkranBolgesi)
    assert b.bbox() == (10, 20, 110, 70)
    assert not b.tam_ekran_mi()
    assert bolge_coz(None).tam_ekran_mi()
    d = b.to_dict()
    assert EkranBolgesi.from_dict(d).w == 100


def test_dry_run_yakala_ve_oku() -> None:
    bus = EventBus(ad="test.vision.ocr.ekran")
    alinan: list[str] = []
    bus.subscribe(OLAY_EKRAN_YAKALANDI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_EKRAN_OKUNDU, lambda ev: alinan.append(ev.ad))

    e = EkranOcr(dry_run=True, bus=bus, olay_yayinla=True)
    kare = e.yakala()
    assert kare.dry_run is True
    assert kare.motor == VisionMotoru.DRY_RUN
    assert e.son_kare is kare

    sonuc = e.oku()
    assert isinstance(sonuc, OcrSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.metin == ""
    assert sonuc.kaynak_yol == "screen://dry_run"
    assert OLAY_EKRAN_YAKALANDI in alinan
    assert OLAY_EKRAN_OKUNDU in alinan


def test_zorla_sahte_ve_bolge() -> None:
    e = ekran_ocr_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert e.motor == "sahte"
    kare = e.yakala((0, 0, 200, 100))
    assert kare.motor == VisionMotoru.SAHTE
    assert kare.ham is not None
    assert kare.genislik == 200
    assert kare.yukseklik == 100

    s = e.oku((5, 5, 80, 40), sahte_metin="Jarvis Ekran")
    assert s.motor == VisionMotoru.SAHTE
    assert s.metin == "Jarvis Ekran"
    assert e.metin_oku()  # sahte varsayılan metin dolu


def test_mock_imagegrab_ve_ocr() -> None:
    grab = _SahteImageGrab()
    stub = _SahtePytesseract(metin="WhiteCore Ekran OK")
    ocr = OcrYoneticisi(
        dry_run=False,
        zorla_sahte=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )
    e = EkranOcr(
        ocr=ocr,
        dry_run=False,
        zorla_sahte=False,
        imagegrab_modul=grab,
        olay_yayinla=False,
        ocr_yonet=False,
    )
    assert e.motor == "pillow"

    # Tam ekran
    kare = e.yakala()
    assert kare.motor == VisionMotoru.PILLOW
    assert kare.genislik == 1920
    assert kare.yukseklik == 1080
    assert grab.cagrilar[-1] is None

    # Bölge
    sonuc = e.oku((100, 50, 300, 200), dil="tur")
    assert sonuc.motor == VisionMotoru.TESSERACT
    assert "WhiteCore" in sonuc.metin
    assert sonuc.dil == "tur"
    assert grab.cagrilar[-1] == (100, 50, 400, 250)
    assert stub.cagrilar


def test_gecersiz_bolge() -> None:
    e = ekran_ocr_olustur(dry_run=True, olay_yayinla=False)
    try:
        bolge_coz((1, 2, 3))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0401"

    try:
        e.yakala((-1, 0, -10, 20))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0401"


def test_yardimci_ve_yasam_dongusu() -> None:
    bil = ekran_ocr_oku(dry_run=True, dil="tur+eng")
    assert bil.dry_run is True
    assert bil.motor == VisionMotoru.DRY_RUN

    async def _run() -> None:
        bus = EventBus(ad="test.ekran.life")
        e = ekran_ocr_olustur(dry_run=True, bus=bus, olay_yayinla=True)
        await e.baslat()
        assert e.calisiyor is True
        e.oku()
        await e.durdur()
        assert e.calisiyor is False

    asyncio.run(_run())
    assert OLAY_EKRAN_BASLADI.startswith("vision.ocr.screen")
    assert OLAY_EKRAN_DURDU.startswith("vision.ocr.screen")


def test_yakalama_hata_sahte_fallback() -> None:
    class _BozukGrab:
        def grab(self, bbox=None):  # noqa: ANN001
            raise RuntimeError("headless")

    e = EkranOcr(
        dry_run=False,
        zorla_sahte=False,
        imagegrab_modul=_BozukGrab(),
        olay_yayinla=False,
    )
    # ocr da sahte olacak (pytesseract olmayabilir) — yakalama fallback sahte kare
    kare = e.yakala()
    assert kare.motor == VisionMotoru.SAHTE
    assert kare.ham is not None

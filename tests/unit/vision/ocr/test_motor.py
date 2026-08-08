"""vision/ocr/motor.py birim testleri (dry_run / sahte / mock pytesseract)."""

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
from vision.modeller import Kare, OcrSonucu, VisionMotoru, kare_olustur
from vision.ocr.motor import (
    OLAY_OCR_BASLADI,
    OLAY_OCR_DURDU,
    OLAY_OCR_OKUNDU,
    OcrYoneticisi,
    ocr_oku,
    ocr_yoneticisi_olustur,
    pillow_var_mi,
    pytesseract_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _SahtePytesseract:
    def __init__(self, metin: str = "Merhaba OCR") -> None:
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


def test_fabrika_ve_ozellikler() -> None:
    y = ocr_yoneticisi_olustur(dry_run=True)
    assert isinstance(y, OcrYoneticisi)
    assert isinstance(y, ModulTabani)
    assert y.ad == "vision.ocr"
    assert y.motor == "dry_run"
    assert y.dil == "tur+eng"
    ozet = y.ozet()
    assert ozet["dry_run"] is True
    assert ozet["lang"] == "tur+eng"
    assert isinstance(pytesseract_var_mi(), bool)
    assert isinstance(pillow_var_mi(), bool)


def test_dry_run_ve_sonuc_dict() -> None:
    bus = EventBus(ad="test.vision.ocr")
    alinan: list[str] = []
    bus.subscribe(OLAY_OCR_OKUNDU, lambda e: alinan.append(e.ad))
    y = OcrYoneticisi(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = y.oku("ornek.png", dil="tur+eng")
    assert isinstance(sonuc, OcrSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.metin == ""
    assert sonuc.dil == "tur+eng"
    assert sonuc.kaynak_yol == "ornek.png"
    d = sonuc.to_dict()
    assert d["engine"] == "dry_run"
    assert d["text"] == ""
    geri = OcrSonucu.from_dict(d)
    assert geri.motor == VisionMotoru.DRY_RUN
    assert y.son_sonuc is sonuc
    assert OLAY_OCR_OKUNDU in alinan


def test_zorla_sahte_ve_sahte_metin() -> None:
    y = ocr_yoneticisi_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert y.motor == "sahte"
    s1 = y.oku(_MINI_PNG)
    assert s1.motor == VisionMotoru.SAHTE
    assert s1.neden == "zorla_sahte"
    assert "Sahte OCR" in s1.metin

    s2 = y.oku(_MINI_PNG, sahte_metin="Jarvis OCR")
    assert s2.motor == VisionMotoru.SAHTE
    assert s2.metin == "Jarvis OCR"
    assert s2.neden == "sahte_metin"


def test_mock_pytesseract_yol_ve_bayt() -> None:
    stub = _SahtePytesseract(metin="WhiteCore OCR OK")
    y = OcrYoneticisi(
        dry_run=False,
        zorla_sahte=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )
    assert y.motor == "tesseract"

    with tempfile.TemporaryDirectory() as tmp:
        yol = Path(tmp) / "doc.png"
        yol.write_bytes(_MINI_PNG)
        sonuc = y.oku(str(yol), dil="tur")
        assert sonuc.motor == VisionMotoru.TESSERACT
        assert "WhiteCore" in sonuc.metin
        assert sonuc.dil == "tur"
        assert stub.cagrilar
        assert stub.cagrilar[-1][1] == "tur"

    # Bayt girdisi → geçici dosya
    stub2 = _SahtePytesseract(metin="bayt-metin")
    y2 = OcrYoneticisi(
        dry_run=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub2,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )
    s2 = y2.oku(_MINI_PNG, dil="eng")
    assert s2.motor == VisionMotoru.TESSERACT
    assert s2.metin == "bayt-metin"
    assert s2.dil == "eng"


def test_kare_ham_ve_metin_oku() -> None:
    stub = _SahtePytesseract(metin="kare OCR")
    y = OcrYoneticisi(
        dry_run=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )
    kare = kare_olustur(
        genislik=1,
        yukseklik=1,
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        ham=_MINI_PNG,
        bayt_sayisi=len(_MINI_PNG),
    )
    assert y.metin_oku(kare) == "kare OCR"


def test_dosya_yok_ve_bos_kare() -> None:
    stub = _SahtePytesseract()
    y = OcrYoneticisi(
        dry_run=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        olay_yayinla=False,
    )
    try:
        y.oku("C:/olmayan_whitecore_ocr_xyz.png")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0302"

    bos = Kare(yol=None, ham=None)
    try:
        y.oku(bos)
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0301"


def test_yardimci_ocr_oku_ve_yasam_dongusu() -> None:
    bil = ocr_oku("plan.png", dry_run=True, dil="tur+eng")
    assert bil.dry_run is True
    assert bil.motor == VisionMotoru.DRY_RUN

    async def _run() -> None:
        bus = EventBus(ad="test.ocr.life")
        y = ocr_yoneticisi_olustur(
            dry_run=True,
            bus=bus,
            olay_yayinla=True,
        )
        await y.baslat()
        assert y.calisiyor is True
        y.oku("a.png")
        await y.durdur()
        assert y.calisiyor is False

    asyncio.run(_run())


def test_on_isleme_kapali_ve_desteklenmeyen() -> None:
    stub = _SahtePytesseract(metin="x")
    y = OcrYoneticisi(
        dry_run=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )
    assert y.on_isleme_aktif is False
    try:
        y.oku(object())  # type: ignore[arg-type]
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0301"

    # olay sabitleri export
    assert OLAY_OCR_OKUNDU.startswith("vision.ocr")
    assert OLAY_OCR_BASLADI.startswith("vision.ocr")
    assert OLAY_OCR_DURDU.startswith("vision.ocr")

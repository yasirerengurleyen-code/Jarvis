"""vision/ocr/pdf.py birim testleri (dry_run / sahte / mock PyPDF2 / pdf2image)."""

from __future__ import annotations

import asyncio
import io
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import OcrSonucu, VisionMotoru
from vision.ocr.motor import OcrYoneticisi
from vision.ocr.pdf import (
    OLAY_PDF_BASLADI,
    OLAY_PDF_DURDU,
    OLAY_PDF_OKUNDU,
    PdfOcr,
    pdf2image_var_mi,
    pdf_ocr_oku,
    pdf_ocr_olustur,
    pillow_var_mi,
    pypdf_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _SahteSayfa:
    def __init__(self, metin: str = "") -> None:
        self._metin = metin

    def extract_text(self) -> str:
        return self._metin


class _SahtePdfReader:
    def __init__(self, sayfalar: list[str]) -> None:
        self.pages = [_SahteSayfa(m) for m in sayfalar]


class _SahteImg:
    def __init__(self, ham: bytes = _MINI_PNG) -> None:
        self.size = (100, 50)
        self._ham = ham

    def save(self, buf: Any, format: str = "PNG") -> None:  # noqa: A003
        buf.write(self._ham)


class _SahtePytesseract:
    def __init__(self, metin: str = "PDF OCR metni") -> None:
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


def _bos_pdf(yol: Path) -> None:
    """Mümkünse gerçek boş PDF; değilse minimal bayt dosyası."""
    try:
        from PyPDF2 import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=300, height=144)
        with yol.open("wb") as f:
            writer.write(f)
    except ImportError:
        yol.write_bytes(b"%PDF-1.4\n%%EOF\n")


def test_fabrika_ve_ozellikler() -> None:
    p = pdf_ocr_olustur(dry_run=True)
    assert isinstance(p, PdfOcr)
    assert isinstance(p, ModulTabani)
    assert p.ad == "vision.ocr.pdf"
    assert p.motor == "dry_run"
    ozet = p.ozet()
    assert ozet["dry_run"] is True
    assert ozet["lang"] == "tur+eng"
    assert isinstance(pypdf_var_mi(), bool)
    assert isinstance(pdf2image_var_mi(), bool)
    assert isinstance(pillow_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.ocr.pdf")
    alinan: list[str] = []
    bus.subscribe(OLAY_PDF_OKUNDU, lambda e: alinan.append(e.ad))

    tmp = Path(tempfile.mkdtemp()) / "dry.pdf"
    _bos_pdf(tmp)

    p = PdfOcr(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = p.oku(tmp)
    assert isinstance(sonuc, OcrSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.metin == ""
    assert sonuc.kaynak_yol == str(tmp)
    assert OLAY_PDF_OKUNDU in alinan
    assert p.son_sonuc is sonuc


def test_zorla_sahte_ve_sahte_metin() -> None:
    tmp = Path(tempfile.mkdtemp()) / "s.pdf"
    _bos_pdf(tmp)

    p = pdf_ocr_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert p.motor == "sahte"
    s1 = p.oku(tmp)
    assert s1.motor == VisionMotoru.SAHTE
    assert "Sahte PDF" in s1.metin
    assert s1.neden == "zorla_sahte"

    s2 = p.oku(tmp, sahte_metin="Jarvis PDF")
    assert s2.metin == "Jarvis PDF"
    assert s2.neden == "sahte_metin"
    assert "Sahte" in p.metin_oku(tmp)


def test_metin_mod_mock_pypdf() -> None:
    tmp = Path(tempfile.mkdtemp()) / "metin.pdf"
    _bos_pdf(tmp)

    def _reader(yol: str) -> _SahtePdfReader:  # noqa: ARG001
        return _SahtePdfReader(
            [
                "Birinci sayfa metni WhiteCore",
                "Ikinci sayfa devam",
            ]
        )

    p = PdfOcr(
        dry_run=False,
        zorla_sahte=False,
        pypdf_modul=_reader,
        olay_yayinla=False,
    )
    sonuc = p.oku(tmp, mod="metin")
    assert sonuc.motor == VisionMotoru.YEREL
    assert "WhiteCore" in sonuc.metin
    assert "Ikinci" in sonuc.metin
    assert sonuc.neden == "pypdf"
    assert p.son_sayfa_sayisi == 2

    # Tek sayfa
    s2 = p.oku(tmp, mod="metin", sayfa=2)
    assert "Ikinci" in s2.metin
    assert "Birinci" not in s2.metin
    assert s2.sayfa == 2


def test_ocr_mod_mock_pdf2image() -> None:
    tmp = Path(tempfile.mkdtemp()) / "scan.pdf"
    _bos_pdf(tmp)

    cagrilar: list[dict[str, Any]] = []

    def _convert(yol: str, **kwargs: Any) -> list[_SahteImg]:  # noqa: ARG001
        cagrilar.append(kwargs)
        return [_SahteImg(), _SahteImg()]

    stub = _SahtePytesseract(metin="Taranmis sayfa OK")
    ocr = OcrYoneticisi(
        dry_run=False,
        zorla_sahte=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )
    p = PdfOcr(
        ocr=ocr,
        dry_run=False,
        zorla_sahte=False,
        pdf2image_modul=_convert,
        pypdf_modul=lambda yol: _SahtePdfReader(["", ""]),  # noqa: ARG005
        olay_yayinla=False,
        ocr_yonet=False,
    )
    sonuc = p.oku(tmp, mod="ocr", dil="tur+eng")
    assert stub.cagrilar  # OCR çağrıldı
    assert "Taranmis" in sonuc.metin
    assert sonuc.neden == "pdf2image+ocr"
    assert sonuc.motor == VisionMotoru.TESSERACT


def test_auto_metin_yeterli() -> None:
    """auto: yeterli metin → OCR çağrılmaz."""
    tmp = Path(tempfile.mkdtemp()) / "auto.pdf"
    _bos_pdf(tmp)

    convert_cagrildi = {"v": False}

    def _convert(yol: str, **kwargs: Any) -> list[_SahteImg]:  # noqa: ARG001
        convert_cagrildi["v"] = True
        return [_SahteImg()]

    p = PdfOcr(
        dry_run=False,
        zorla_sahte=False,
        pypdf_modul=lambda yol: _SahtePdfReader(  # noqa: ARG005
            ["Bu yeterince uzun bir metin katmani WhiteCore PDF"]
        ),
        pdf2image_modul=_convert,
        olay_yayinla=False,
    )
    sonuc = p.oku(tmp, mod="auto")
    assert "WhiteCore" in sonuc.metin
    assert sonuc.neden == "pypdf"
    assert convert_cagrildi["v"] is False


def test_auto_metin_yetersiz_ocr() -> None:
    """auto: kısa metin → OCR'a düşer."""
    tmp = Path(tempfile.mkdtemp()) / "zayif.pdf"
    _bos_pdf(tmp)

    stub = _SahtePytesseract(metin="OCR kurtardi")
    ocr = OcrYoneticisi(
        dry_run=False,
        zorla_sahte=False,
        on_isleme_aktif=False,
        pytesseract_modul=stub,
        pillow_modul=_SahtePillowImage,
        olay_yayinla=False,
    )

    def _convert(yol: str, **kwargs: Any) -> list[_SahteImg]:  # noqa: ARG001
        return [_SahteImg()]

    p = PdfOcr(
        ocr=ocr,
        dry_run=False,
        zorla_sahte=False,
        pypdf_modul=lambda yol: _SahtePdfReader(["x"]),  # noqa: ARG005
        pdf2image_modul=_convert,
        olay_yayinla=False,
        ocr_yonet=False,
        metin_esik=20,
    )
    sonuc = p.oku(tmp, mod="auto")
    assert "kurtardi" in sonuc.metin
    assert sonuc.neden == "pdf2image+ocr"


def test_dosya_yok_ve_gecersiz_sayfa() -> None:
    p = pdf_ocr_olustur(dry_run=False, zorla_sahte=False, olay_yayinla=False)
    # motor sahte olabilir (deps yok) — dosya yok yine VIS_0502 olmalı
    # zorla_sahte False + dry_run False → yol doğrulanır (sahte motorda
    # zorla_sahte değilse yol doğrulanır; motor_sahte yolunda da doğrulanır)
    try:
        # pypdf yoksa motor=sahte → yol doğrulanır
        PdfOcr(
            dry_run=False,
            zorla_sahte=False,
            pypdf_modul=lambda yol: _SahtePdfReader(["a"]),  # noqa: ARG005
            olay_yayinla=False,
        ).oku(r"C:\olmayan_whitecore_pdf_xyz.pdf", mod="metin")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0502"

    tmp = Path(tempfile.mkdtemp()) / "sayfa.pdf"
    _bos_pdf(tmp)
    p2 = PdfOcr(
        dry_run=False,
        zorla_sahte=False,
        pypdf_modul=lambda yol: _SahtePdfReader(["a", "b"]),  # noqa: ARG005
        olay_yayinla=False,
    )
    try:
        p2.oku(tmp, mod="metin", sayfa=9)
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0501"

    try:
        p2.oku(tmp, mod="gecersiz")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0501"


def test_yardimci_ve_yasam_dongusu() -> None:
    tmp = Path(tempfile.mkdtemp()) / "life.pdf"
    _bos_pdf(tmp)
    bil = pdf_ocr_oku(tmp, dry_run=True, dil="tur+eng")
    assert bil.dry_run is True
    assert bil.motor == VisionMotoru.DRY_RUN

    async def _run() -> None:
        bus = EventBus(ad="test.pdf.life")
        p = pdf_ocr_olustur(dry_run=True, bus=bus, olay_yayinla=True)
        await p.baslat()
        assert p.calisiyor is True
        p.oku(tmp)
        await p.durdur()
        assert p.calisiyor is False

    asyncio.run(_run())
    assert OLAY_PDF_BASLADI.startswith("vision.ocr.pdf")
    assert OLAY_PDF_DURDU.startswith("vision.ocr.pdf")


def test_ocr_mod_pdf2image_yok_sahte() -> None:
    """ocr modunda pdf2image yok → sahte fallback."""
    tmp = Path(tempfile.mkdtemp()) / "noscan.pdf"
    _bos_pdf(tmp)

    # pypdf var gibi ama pdf2image yok — özel: pdf2image_modul vermeden
    # ve pdf2image gerçekten yoksa sahte; inject ile pdf2image'i kapatamayız
    # ama convert yokken _pdf2image_var_mi False kalsın diye None bırakıp
    # gerçek ortamda pdf2image olmayabilir. Zorla: PdfOcr alt sınıfı.
    class _YokPdf(PdfOcr):
        def _pdf2image_var_mi(self) -> bool:
            return False

        def _pypdf_var_mi(self) -> bool:
            return True

    p = _YokPdf(
        dry_run=False,
        zorla_sahte=False,
        pypdf_modul=lambda yol: _SahtePdfReader([""]),  # noqa: ARG005
        olay_yayinla=False,
    )
    sonuc = p.oku(tmp, mod="ocr")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.neden == "pdf2image_yok"

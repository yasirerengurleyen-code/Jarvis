"""skills/media/ocr.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.media.ocr import (
    OcrSkill,
    dil_ayikla,
    gorsel_yolu_ayikla,
    ocr_oku,
    pytesseract_var_mi,
)
from skills.yoneticisi import SkillYoneticisi

# 1x1 PNG — gerçek görüntü dosyası (OCR motor stub ile okunur)
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _SahtePytesseract:
    """Tesseract olmadan test için enjekte edilen stub."""

    def __init__(self, metin: str = "Merhaba OCR") -> None:
        self.metin = metin
        self.cagrilar: list[tuple[Any, str]] = []

    def image_to_string(self, image, lang: str = "eng"):  # noqa: ANN001
        self.cagrilar.append((image, lang))
        return self.metin


class _SahtePillowImage:
    """Pillow.open stub'u."""

    @staticmethod
    def open(yol: str):  # noqa: ANN001
        class _Ctx:
            def __enter__(self):
                return {"path": yol}

            def __exit__(self, *args):  # noqa: ANN002
                return None

        return _Ctx()


def test_yol_ve_dil_ayikla() -> None:
    assert gorsel_yolu_ayikla('ocr oku "C:/tmp/a.png"') == "C:/tmp/a.png"
    assert gorsel_yolu_ayikla("metin oku foto.JPG").lower().endswith("foto.jpg")
    assert gorsel_yolu_ayikla("ocr yok") is None
    assert dil_ayikla("ocr dil:tur ekran.png") == "tur"
    assert dil_ayikla("read text lang eng") == "eng"
    assert dil_ayikla("türkçe ocr") == "tur"
    assert dil_ayikla("english ocr") == "eng"


def test_dry_run_ve_sahte() -> None:
    tmp = Path(tempfile.mkdtemp()) / "snap.png"
    tmp.write_bytes(_MINI_PNG)

    bil = ocr_oku(tmp, dry_run=True)
    assert bil["dry_run"] is True
    assert bil["engine"] == "dry_run"
    assert bil["text"] == ""

    bil2 = ocr_oku(tmp, zorla_sahte=True)
    assert bil2["engine"] == "sahte"
    assert bil2["chars"] > 0

    bil3 = ocr_oku(tmp, sahte_metin="Jarvis OCR")
    assert bil3["engine"] == "sahte"
    assert bil3["text"] == "Jarvis OCR"


def test_mock_pytesseract_ve_skill() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "mock.png"
        tmp.write_bytes(_MINI_PNG)

        stub = _SahtePytesseract(metin="WhiteCore OCR OK")
        bil = ocr_oku(
            tmp,
            dil="tur",
            pytesseract_modul=stub,
            pillow_modul=_SahtePillowImage,
        )
        assert bil["engine"] == "pytesseract"
        assert "WhiteCore" in bil["text"]
        assert bil["lang"] == "tur"
        assert stub.cagrilar

        # Pillow yok → yol string ile
        stub2 = _SahtePytesseract(metin="yol-ile")
        bil_b = ocr_oku(tmp, pytesseract_modul=stub2, pillow_modul=None)
        assert bil_b["engine"] == "pytesseract"
        assert bil_b["text"] == "yol-ile"

        s = OcrSkill()
        assert s.eslesir_mi("ocr oku test.png")
        assert s.eslesir_mi("görüntüden metin al")
        assert s.eslesir_mi("metin oku")

        r = await s.calistir(f'ocr oku "{tmp}"', dry_run=True)
        assert r.basarili
        assert r.veri["dry_run"] is True

        r2 = await s.calistir(
            f'görüntüden metin "{tmp}"',
            zorla_sahte=True,
        )
        assert r2.basarili
        assert r2.veri["engine"] == "sahte"

        r3 = await s.calistir(
            f'ocr "{tmp}" dil:eng',
            pytesseract_modul=stub,
            pillow_modul=_SahtePillowImage,
        )
        assert r3.basarili
        assert r3.veri["engine"] == "pytesseract"

        r4 = await s.calistir("ocr oku")
        assert not r4.basarili

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r5 = await y.calistir(f'ocr "{tmp}"', dry_run=True)
        assert r5.basarili
        await y.durdur()

        # motor yok bilgisi erişilebilir
        assert isinstance(pytesseract_var_mi(), bool)

    asyncio.run(_run())


def test_dosya_yok_gercek_motor() -> None:
    """Gerçek motor stub ile olmayan dosya FileNotFoundError → skill hata."""

    async def _run() -> None:
        s = OcrSkill()
        stub = _SahtePytesseract()
        r = await s.calistir(
            'ocr oku "C:/olmayan_whitecore_ocr_xyz.png"',
            pytesseract_modul=stub,
        )
        assert not r.basarili

    asyncio.run(_run())


if __name__ == "__main__":
    test_yol_ve_dil_ayikla()
    test_dry_run_ve_sahte()
    test_mock_pytesseract_ve_skill()
    test_dosya_yok_gercek_motor()
    print("OK test_ocr")

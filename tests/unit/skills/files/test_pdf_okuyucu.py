"""skills/files/pdf_okuyucu.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.files.pdf_okuyucu import (
    PdfOkuyucuSkill,
    pdf_metin_oku,
    pdf_yolu_ayikla,
)
from skills.yoneticisi import SkillYoneticisi


def _mini_pdf(yol: Path, metin: str = "WhiteCore PDF Test") -> None:
    """PyPDF2 ile tek sayfalık basit PDF yazar."""
    from PyPDF2 import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=144)
    with yol.open("wb") as f:
        writer.write(f)


def test_yol_ayikla() -> None:
    assert pdf_yolu_ayikla('pdf oku "C:/tmp/a.pdf"') == "C:/tmp/a.pdf"
    assert pdf_yolu_ayikla("oku rapor.PDF lütfen").lower().endswith("rapor.pdf")
    assert pdf_yolu_ayikla("pdf yok") is None


def test_sahte_ve_skill() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "t.pdf"
        _mini_pdf(tmp)

        bil = pdf_metin_oku(tmp, sahte_metin="Merhaba PDF")
        assert bil["engine"] == "sahte"
        assert "Merhaba" in bil["text"]

        # Gerçek PyPDF2 okuma (boş sayfa → text boş olabilir ama hata olmamalı)
        bil2 = pdf_metin_oku(tmp)
        assert bil2["engine"] == "PyPDF2"
        assert bil2["pages"] >= 1

        s = PdfOkuyucuSkill()
        assert s.eslesir_mi("pdf oku test.pdf")
        r = await s.calistir(f'pdf oku "{tmp}"', sahte_metin="Jarvis PDF")
        assert r.basarili
        assert "Jarvis" in r.veri["text"]

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r2 = await y.calistir(f'pdf oku "{tmp}"', sahte_metin="OK")
        assert r2.basarili
        await y.durdur()

    asyncio.run(_run())


def test_dosya_yok() -> None:
    async def _run() -> None:
        s = PdfOkuyucuSkill()
        r = await s.calistir('pdf oku "C:/olmayan_whitecore_xyz.pdf"')
        assert not r.basarili

    asyncio.run(_run())


if __name__ == "__main__":
    test_yol_ayikla()
    test_sahte_ve_skill()
    test_dosya_yok()
    print("OK test_pdf_okuyucu")

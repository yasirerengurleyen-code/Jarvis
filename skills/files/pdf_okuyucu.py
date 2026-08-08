"""
skills/files/pdf_okuyucu.py
---------------------------
PDF metin okuma skill'i.

Görev:
- PDF dosyasından sayfa metinlerini çıkarmak (PyPDF2)
- Paket yoksa anlaşılır hata / sahte mod (test)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from skills.taban import SkillTabani

try:
    from PyPDF2 import PdfReader

    _PYPDF_VAR = True
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[misc, assignment]
    _PYPDF_VAR = False


def pdf_yolu_ayikla(komut: str) -> Optional[str]:
    """Komuttan .pdf yolunu veya tırnaklı yolu alır."""
    yollar = re.findall(r'"([^"]+\.pdf)"|\'([^\']+\.pdf)\'', komut or "", flags=re.I)
    duz = [a or b for a, b in yollar]
    if duz:
        return duz[0]
    m = re.search(r"(\S+\.pdf)\b", komut or "", flags=re.I)
    return m.group(1) if m else None


def pdf_metin_oku(
    yol: str | Path,
    *,
    max_sayfa: Optional[int] = None,
    sahte_metin: Optional[str] = None,
) -> dict[str, Any]:
    """
    PDF metnini okur.

    sahte_metin verilirse PyPDF2 kullanılmaz (birim test).
    """
    p = Path(yol).expanduser().resolve()
    if sahte_metin is not None:
        return {
            "path": str(p),
            "pages": 1,
            "text": sahte_metin,
            "engine": "sahte",
        }

    if not p.is_file():
        raise FileNotFoundError(f"PDF yok: {p}")

    if not _PYPDF_VAR:
        raise RuntimeError(
            "PyPDF2 yüklü değil. Kurulum: pip install PyPDF2"
        )

    assert PdfReader is not None
    okuyucu = PdfReader(str(p))
    sayfalar: list[str] = []
    toplam = len(okuyucu.pages)
    limit = toplam if max_sayfa is None else min(toplam, max(1, int(max_sayfa)))
    for i in range(limit):
        try:
            sayfalar.append(okuyucu.pages[i].extract_text() or "")
        except Exception:
            sayfalar.append("")

    metin = "\n\n".join(sayfalar).strip()
    return {
        "path": str(p),
        "pages": toplam,
        "pages_read": limit,
        "text": metin,
        "engine": "PyPDF2",
    }


class PdfOkuyucuSkill(SkillTabani):
    """PDF dosyasından metin okur."""

    ad = "pdf_okuyucu"
    aciklama = "PDF dosyalarından metin çıkarır"
    kategori = "files"
    tehlikeli = False
    anahtarlar = (
        "pdf",
        "pdf oku",
        "pdf okuyucu",
        "pdf metin",
        "read pdf",
    )
    ornekler = (
        'pdf oku "rapor.pdf"',
        "PDF dosyasını oku",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        yol = kwargs.get("yol") or pdf_yolu_ayikla(komut)
        if not yol:
            return self.hata(
                'PDF yolu gerekli. Örnek: pdf oku "dosya.pdf"',
                veri={"komut": komut},
            )

        max_sayfa = kwargs.get("max_sayfa")
        sahte = kwargs.get("sahte_metin")
        try:
            bil = pdf_metin_oku(
                str(yol),
                max_sayfa=int(max_sayfa) if max_sayfa is not None else None,
                sahte_metin=sahte,
            )
        except Exception as exc:
            return self.hata(str(exc), veri={"path": str(yol)})

        ozet = (bil.get("text") or "")[:500]
        return self.ok(
            f"PDF okundu ({bil.get('pages', 0)} sayfa)",
            veri={**bil, "preview": ozet},
        )


pdf_okuyucu_skill = PdfOkuyucuSkill()

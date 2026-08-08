"""
skills/media/ocr.py
-------------------
OCR skill'i.

Görev:
- Görüntü dosyasından metin çıkarmak (pytesseract + isteğe bağlı Pillow)
- Tesseract / paket yoksa dry_run veya sahte fallback
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from skills.taban import SkillTabani

try:
    import pytesseract as _pytesseract

    _PYTESSERACT_VAR = True
except ImportError:  # pragma: no cover
    _pytesseract = None  # type: ignore[assignment]
    _PYTESSERACT_VAR = False

try:
    from PIL import Image as _PILImage

    _PILLOW_VAR = True
except ImportError:  # pragma: no cover
    _PILImage = None  # type: ignore[misc, assignment]
    _PILLOW_VAR = False

_GORSEL_UZANTILAR = ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "gif")
_SAHTE_METIN = "[Sahte OCR] WhiteCore test metni"


def pytesseract_var_mi() -> bool:
    return bool(_PYTESSERACT_VAR)


def pillow_var_mi() -> bool:
    return bool(_PILLOW_VAR)


def gorsel_yolu_ayikla(komut: str) -> Optional[str]:
    """Komuttan görüntü yolunu (tırnaklı veya uzantılı) alır."""
    uz = "|".join(_GORSEL_UZANTILAR)
    yollar = re.findall(
        rf'"([^"]+\.(?:{uz}))"|'
        rf"'([^']+\.(?:{uz}))'",
        komut or "",
        flags=re.I,
    )
    duz = [a or b for a, b in yollar]
    if duz:
        return duz[0]
    m = re.search(rf"(\S+\.(?:{uz}))\b", komut or "", flags=re.I)
    return m.group(1) if m else None


def dil_ayikla(komut: str) -> Optional[str]:
    """'dil:tur', 'lang eng', 'türkçe' vb."""
    n = (komut or "").strip().lower()
    m = re.search(r"(?i)\b(?:dil|lang|language)\s*[:=]?\s*([a-z+]{2,12})\b", n)
    if m:
        return m.group(1).replace(" ", "")
    if re.search(r"(?i)\b(türkçe|turkce|turkish)\b", n):
        return "tur"
    if re.search(r"(?i)\b(english|ingilizce)\b", n):
        return "eng"
    return None


def ocr_oku(
    yol: str | Path,
    *,
    dil: str = "tur+eng",
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_metin: Optional[str] = None,
    pytesseract_modul: Any = None,
    pillow_modul: Any = None,
) -> dict[str, Any]:
    """
    Görüntüden metin okur.

    dry_run / zorla_sahte / sahte_metin / motor yok → dosya yazmaz, sahte/dry sonuç.
    """
    p = Path(yol).expanduser()
    dil_kod = (dil or "tur+eng").strip() or "tur+eng"

    if dry_run:
        return {
            "path": str(p),
            "text": "",
            "lang": dil_kod,
            "engine": "dry_run",
            "dry_run": True,
            "chars": 0,
        }

    if sahte_metin is not None:
        metin = str(sahte_metin)
        return {
            "path": str(p.resolve()) if p.exists() else str(p),
            "text": metin,
            "lang": dil_kod,
            "engine": "sahte",
            "dry_run": False,
            "reason": "sahte_metin",
            "chars": len(metin),
        }

    if zorla_sahte or (pytesseract_modul is None and not _PYTESSERACT_VAR):
        metin = _SAHTE_METIN
        return {
            "path": str(p.resolve()) if p.exists() else str(p),
            "text": metin,
            "lang": dil_kod,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte" if zorla_sahte else "pytesseract_yok",
            "chars": len(metin),
        }

    if not p.is_file():
        raise FileNotFoundError(f"Görüntü yok: {p}")

    pt = pytesseract_modul if pytesseract_modul is not None else _pytesseract
    pil = pillow_modul if pillow_modul is not None else (_PILImage if _PILLOW_VAR else None)

    try:
        if pil is not None:
            with pil.open(str(p)) as img:
                metin = pt.image_to_string(img, lang=dil_kod) or ""
        else:
            metin = pt.image_to_string(str(p), lang=dil_kod) or ""
        metin = metin.strip()
        return {
            "path": str(p.resolve()),
            "text": metin,
            "lang": dil_kod,
            "engine": "pytesseract",
            "dry_run": False,
            "chars": len(metin),
        }
    except Exception as exc:
        # Tesseract binary yok / okuma hatası → sahte fallback
        metin = _SAHTE_METIN
        return {
            "path": str(p.resolve()),
            "text": metin,
            "lang": dil_kod,
            "engine": "sahte",
            "dry_run": False,
            "reason": f"hata:{exc}",
            "error": str(exc),
            "chars": len(metin),
        }


class OcrSkill(SkillTabani):
    """Görüntü dosyasından OCR ile metin çıkarır."""

    ad = "ocr"
    aciklama = "Görüntülerden metin okur (pytesseract / Tesseract)"
    kategori = "media"
    tehlikeli = False
    anahtarlar = (
        "ocr",
        "metin oku",
        "yazı oku",
        "yazi oku",
        "görüntüden metin",
        "goruntuden metin",
        "tesseract",
        "read text",
        "image to text",
    )
    ornekler = (
        'ocr oku "ekran.png"',
        'görüntüden metin "foto.jpg" dil:tur',
        "ocr dry_run test.png",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        yol = kwargs.get("yol") or gorsel_yolu_ayikla(komut)
        dry_run = bool(kwargs.get("dry_run", False))
        zorla_sahte = bool(kwargs.get("zorla_sahte", False))
        sahte = kwargs.get("sahte_metin")
        dil = kwargs.get("dil") or dil_ayikla(komut) or "tur+eng"

        if not yol:
            if dry_run or zorla_sahte or sahte is not None:
                yol = "sahte_ocr.png"
            else:
                return self.hata(
                    'Görüntü yolu gerekli. Örnek: ocr oku "ekran.png"',
                    veri={"komut": komut},
                )

        try:
            bil = ocr_oku(
                str(yol),
                dil=str(dil),
                dry_run=dry_run,
                zorla_sahte=zorla_sahte,
                sahte_metin=sahte,
                pytesseract_modul=kwargs.get("pytesseract_modul"),
                pillow_modul=kwargs.get("pillow_modul"),
            )
        except Exception as exc:
            return self.hata(str(exc), veri={"path": str(yol)})

        if bil.get("dry_run"):
            mesaj = f"OCR planlandı (dry_run): {bil.get('path')}"
        elif bil.get("engine") == "sahte":
            mesaj = f"Sahte OCR tamamlandı ({bil.get('chars', 0)} karakter)"
        else:
            mesaj = f"OCR tamamlandı ({bil.get('chars', 0)} karakter)"

        ozet = (bil.get("text") or "")[:500]
        return self.ok(mesaj, veri={**bil, "preview": ozet})


ocr_skill = OcrSkill()

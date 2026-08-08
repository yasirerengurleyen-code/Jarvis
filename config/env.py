"""
config/env.py
-------------
Proje kökündeki .env dosyasını ortama yükler.

Görev:
- OPENAI_API_KEY vb. anahtarları güvenli şekilde okumak
- Mevcut ortam değişkenlerini ezmemek
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJE_KOKU = Path(__file__).resolve().parent.parent


def env_yukle(yol: Path | None = None) -> Path | None:
    """
    .env satırlarını os.environ'a yazar (yalnızca boş olanlar).

    Dönüş: yüklenen dosya yolu veya None.
    """
    dosya = Path(yol) if yol is not None else _PROJE_KOKU / ".env"
    if not dosya.is_file():
        return None
    try:
        metin = dosya.read_text(encoding="utf-8")
    except OSError:
        return None

    for ham in metin.splitlines():
        satir = ham.strip()
        if not satir or satir.startswith("#"):
            continue
        if satir.lower().startswith("export "):
            satir = satir[7:].strip()
        if "=" not in satir:
            continue
        anahtar, deger = satir.split("=", 1)
        anahtar = anahtar.strip()
        deger = deger.strip()
        if len(deger) >= 2 and deger[0] == deger[-1] and deger[0] in {'"', "'"}:
            deger = deger[1:-1]
        if not anahtar:
            continue
        # Mevcut ortamı ezme
        if os.environ.get(anahtar, "").strip():
            continue
        os.environ[anahtar] = deger
    return dosya


def env_anahtar_yaz(
    anahtar: str,
    deger: str,
    *,
    yol: Path | None = None,
) -> Path:
    """
    .env içinde anahtarı günceller veya ekler; os.environ'a da yazar.
    """
    dosya = Path(yol) if yol is not None else _PROJE_KOKU / ".env"
    anahtar = (anahtar or "").strip()
    deger = (deger or "").strip()
    if not anahtar:
        raise ValueError("Boş ortam anahtarı")

    satirlar: list[str] = []
    if dosya.is_file():
        try:
            satirlar = dosya.read_text(encoding="utf-8").splitlines()
        except OSError:
            satirlar = []

    yeni = f"{anahtar}={deger}"
    bulundu = False
    cikti: list[str] = []
    for ham in satirlar:
        strip = ham.strip()
        if not strip or strip.startswith("#") or "=" not in strip:
            cikti.append(ham)
            continue
        k = strip.split("=", 1)[0].strip()
        if k.lower().startswith("export "):
            k = k[7:].strip()
        if k == anahtar:
            cikti.append(yeni)
            bulundu = True
        else:
            cikti.append(ham)
    if not bulundu:
        if cikti and cikti[-1].strip():
            cikti.append("")
        cikti.append(yeni)

    dosya.parent.mkdir(parents=True, exist_ok=True)
    dosya.write_text("\n".join(cikti) + "\n", encoding="utf-8")
    os.environ[anahtar] = deger
    return dosya


__all__ = ["env_yukle", "env_anahtar_yaz"]

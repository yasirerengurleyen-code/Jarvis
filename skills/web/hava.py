"""
skills/web/hava.py
------------------
Hava durumu skill'i.

Görev:
- Komuttan şehir adını ayıklamak
- Open-Meteo üzerinden hava almak (gui.widgets.hava_durumu ile paylaşır)
- Offline / test için sahte sonuç
"""

from __future__ import annotations

import re
from typing import Any, Optional

from gui.widgets.hava_durumu import (
    HavaAyarlari,
    hava_getir,
    sahte_hava,
)
from skills.taban import SkillTabani

# Bilinen şehirler → lat/lon (genişletilebilir)
_SEHIRLER: dict[str, tuple[float, float]] = {
    "istanbul": (41.0082, 28.9784),
    "ankara": (39.9334, 32.8597),
    "izmir": (38.4237, 27.1428),
    "bursa": (40.1885, 29.0610),
    "antalya": (36.8969, 30.7133),
    "adana": (37.0000, 35.3213),
    "trabzon": (41.0027, 39.7168),
    "gaziantep": (37.0662, 37.3833),
}


def sehir_ayikla(komut: str) -> Optional[str]:
    """'hava istanbul', 'hava durumu ankara' vb."""
    n = (komut or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    if not n:
        return None

    # bilinen şehir
    for ad in sorted(_SEHIRLER.keys(), key=len, reverse=True):
        if ad in n:
            return ad.capitalize() if ad != "istanbul" else "İstanbul"

    kaliplar = [
        r"(?i)hava(?:\s+durumu)?\s+(?:için\s+)?(.+)$",
        r"(?i)(.+?)\s+hava(?:\s+durumu)?$",
        r"(?i)weather\s+(?:in\s+)?(.+)$",
    ]
    for k in kaliplar:
        m = re.search(k, n)
        if m:
            aday = m.group(1).strip(" .\"'")
            aday = re.sub(
                r"(?i)^(lütfen|please|bugün|yarın|durumu|nasıl|nasil)\s+",
                "",
                aday,
            ).strip()
            if aday and aday not in {"hava", "durumu", "weather"}:
                return aday.title()
    return None


def sehir_koordinat(sehir: str) -> Optional[tuple[float, float]]:
    return _SEHIRLER.get((sehir or "").strip().lower())


class HavaSkill(SkillTabani):
    """Şehir için hava durumu sorar."""

    ad = "hava"
    aciklama = "Hava durumu sorgular (Open-Meteo)"
    kategori = "web"
    tehlikeli = False
    anahtarlar = (
        "hava",
        "hava durumu",
        "hava nasıl",
        "weather",
        "sıcaklık",
        "sicaklik",
    )
    ornekler = (
        "hava istanbul",
        "Ankara hava durumu",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        sehir = kwargs.get("sehir") or sehir_ayikla(komut) or "İstanbul"
        zorla_sahte = bool(kwargs.get("zorla_sahte", False))

        lat = kwargs.get("latitude")
        lon = kwargs.get("longitude")
        if lat is None or lon is None:
            koordinat = sehir_koordinat(str(sehir))
            if koordinat:
                lat, lon = koordinat
            else:
                # bilinmeyen şehir → varsayılan İstanbul koordinatı + isim korunur
                ayar_v = HavaAyarlari.ayarlardan()
                lat = float(lat if lat is not None else ayar_v.latitude)
                lon = float(lon if lon is not None else ayar_v.longitude)

        ayar = HavaAyarlari(
            sehir=str(sehir),
            latitude=float(lat),
            longitude=float(lon),
        )

        try:
            if zorla_sahte:
                hava = sahte_hava(str(sehir), neden="zorla_sahte")
            else:
                hava = hava_getir(
                    ayar,
                    zorla_sahte=False,
                    urlac=kwargs.get("urlac"),
                )
        except Exception as exc:
            return self.hata(str(exc), veri={"city": sehir})

        return self.ok(hava.ozet, veri=hava.to_dict())


hava_skill = HavaSkill()

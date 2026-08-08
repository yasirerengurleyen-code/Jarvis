"""
skills/taban.py
---------------
Skills (yetenek) ortak taban ve yardımcılar.

Görev:
- core.base.YetenekTabani üzerinde skill sözleşmesini netleştirmek
- Anahtar kelime eşleştirme / meta bilgi
- Tehlikeli işlemler için onay bayrağı kontrolü
"""

from __future__ import annotations

import re
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from core.base import YetenekDurumu, YetenekSonucu, YetenekTabani
from core.logger import logger_al

log = logger_al("skills.taban")


@dataclass(frozen=True)
class SkillMeta:
    """Skill kimlik / keşif kartı."""

    ad: str
    aciklama: str = ""
    kategori: str = "genel"
    tehlikeli: bool = False
    anahtarlar: tuple[str, ...] = ()
    ornekler: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "description": self.aciklama,
            "category": self.kategori,
            "dangerous": self.tehlikeli,
            "keywords": list(self.anahtarlar),
            "examples": list(self.ornekler),
        }


def komut_normalize(komut: str) -> str:
    """Komutu küçük harf + sıkıştırılmış boşluklara indirger."""
    metin = (komut or "").strip().lower()
    metin = re.sub(r"\s+", " ", metin)
    return metin


def anahtar_eslesir(komut: str, anahtarlar: Iterable[str]) -> bool:
    """
    Komut içinde herhangi bir anahtar geçerse True.

    Çok kelimeli anahtarlar alt dize olarak aranır.
    """
    n = komut_normalize(komut)
    if not n:
        return False
    for a in anahtarlar:
        anahtar = komut_normalize(str(a))
        if not anahtar:
            continue
        if " " in anahtar:
            if anahtar in n:
                return True
        else:
            # kelime sınırı (Türkçe basit)
            if re.search(rf"(^|\W){re.escape(anahtar)}(\W|$)", n):
                return True
    return False


def tehlikeli_onay_gerekli(
    ayar_yonetici: Any = None,
    *,
    eylem: Optional[str] = None,
) -> bool:
    """
    config.security.require_confirmation_for_dangerous değerini okur.

    eylem verilirse dangerous_actions listesinde olup olmadığına da bakar.
    """
    if ayar_yonetici is None:
        try:
            from config.ayarlar import ayarlar as global_ayarlar

            ayar_yonetici = global_ayarlar
        except Exception:
            return True

    try:
        if not getattr(ayar_yonetici, "yuklendi", False):
            ayar_yonetici.yukle()
        zorunlu = bool(
            ayar_yonetici.al("security.require_confirmation_for_dangerous", True)
        )
        if not zorunlu:
            return False
        if eylem is None:
            return True
        liste = ayar_yonetici.al("security.dangerous_actions", []) or []
        return str(eylem) in {str(x) for x in liste}
    except Exception:
        return True


class SkillTabani(YetenekTabani, ABC):
    """
    Tüm WhiteCore skill'lerinin tabanı.

    Alt sınıflar:
    - ad / aciklama / tehlikeli / kategori / anahtarlar tanımlar
    - calistir() uygular
    """

    kategori: str = "genel"
    anahtarlar: Sequence[str] = ()
    ornekler: Sequence[str] = ()
    # config.security.dangerous_actions ile eşleşecek kimlik (opsiyonel)
    tehlike_eylemi: Optional[str] = None

    def meta(self) -> SkillMeta:
        return SkillMeta(
            ad=self.ad,
            aciklama=self.aciklama,
            kategori=self.kategori,
            tehlikeli=bool(self.tehlikeli),
            anahtarlar=tuple(self.anahtarlar) if self.anahtarlar else (self.ad,),
            ornekler=tuple(self.ornekler),
        )

    def eslesir_mi(self, komut: str) -> bool:
        anahtarlar = list(self.anahtarlar) if self.anahtarlar else [self.ad]
        if anahtar_eslesir(komut, anahtarlar):
            return True
        return super().eslesir_mi(komut)

    def onay_kontrol(
        self,
        *,
        onaylandi: bool = False,
        ayar_yonetici: Any = None,
    ) -> Optional[YetenekSonucu]:
        """
        Tehlikeli skill için onay yoksa YetenekSonucu.onay_gerekli döner.
        Güvenliyse None (devam et).
        """
        if not self.tehlikeli:
            return None
        if onaylandi:
            return None
        if not tehlikeli_onay_gerekli(
            ayar_yonetici, eylem=self.tehlike_eylemi or self.ad
        ):
            return None
        return YetenekSonucu.onay_gerekli(
            f"'{self.ad}' tehlikeli bir işlem; kullanıcı onayı gerekli.",
            yetenek=self.ad,
            veri={"action": self.tehlike_eylemi or self.ad},
        )

    def ok(
        self,
        mesaj: str = "Tamam",
        *,
        veri: Optional[dict[str, Any]] = None,
    ) -> YetenekSonucu:
        return YetenekSonucu.ok(mesaj, yetenek=self.ad, veri=veri)

    def hata(
        self,
        mesaj: str,
        *,
        veri: Optional[dict[str, Any]] = None,
    ) -> YetenekSonucu:
        return YetenekSonucu.hata(mesaj, yetenek=self.ad, veri=veri)

    def desteklenmiyor(self, mesaj: str = "Bu işlem desteklenmiyor") -> YetenekSonucu:
        return YetenekSonucu(
            durum=YetenekDurumu.DESTEKLENMIYOR,
            mesaj=mesaj,
            yetenek=self.ad,
        )


@dataclass
class SkillBaglam:
    """Skill çalıştırma bağlamı (yönetici / ajan iletir)."""

    kullanici_id: Optional[str] = None
    onaylandi: bool = False
    ayar_yonetici: Any = None
    ekstra: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "SkillMeta",
    "SkillTabani",
    "SkillBaglam",
    "komut_normalize",
    "anahtar_eslesir",
    "tehlikeli_onay_gerekli",
    "YetenekSonucu",
    "YetenekDurumu",
]

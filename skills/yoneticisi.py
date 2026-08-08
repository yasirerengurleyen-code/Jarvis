"""
skills/yoneticisi.py
--------------------
Skill Manager — yetenek kaydı, eşleştirme ve çalıştırma.

Görev:
- SkillTabani örneklerini kaydetmek
- Komuttan uygun skill seçmek
- Tehlikeli işlem onayını uygulamak
- Sonuçları EventBus ile duyurmak (opsiyonel)
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani, YetenekDurumu, YetenekSonucu
from core.events import (
    OLAY_SKILL_CALISTI,
    OLAY_SKILL_HATA,
    OLAY_SKILL_ONAY,
    EventBus,
    olay_yolu,
)
from core.logger import audit_yaz, logger_al
from skills.taban import SkillBaglam, SkillMeta, SkillTabani

# Geriye dönük: testler / dış kod skills.yoneticisi üzerinden import edebilir
__all__ = [
    "SkillYoneticisi",
    "OLAY_SKILL_CALISTI",
    "OLAY_SKILL_HATA",
    "OLAY_SKILL_ONAY",
]

log = logger_al("skills.yoneticisi")


class SkillYoneticisi(ModulTabani):
    """J.A.R.V.I.S. skill / yetenek yöneticisi."""

    ad = "skills"
    surum = "0.1.0"
    aciklama = "Skill Manager — yetenek orkestrasyonu"

    def __init__(
        self,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        skilller: Optional[Sequence[SkillTabani]] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.bus = bus or olay_yolu
        self._skilller: dict[str, SkillTabani] = {}
        if skilller:
            for s in skilller:
                self.kaydet(s)

    async def baslat(self) -> None:
        if not self.ayarlar.yuklendi:
            self.ayarlar.yukle()
        self._isaret_basladi()
        log.info("Skill Manager hazır (%s skill)", len(self._skilller))

    async def durdur(self) -> None:
        self._skilller.clear()
        self._isaret_durdu()

    def kaydet(self, skill: SkillTabani) -> None:
        """Skill kaydeder; aynı ad varsa üzerine yazar."""
        if not isinstance(skill, SkillTabani):
            raise TypeError("skill SkillTabani örneği olmalıdır")
        self._skilller[skill.ad] = skill
        log.debug("Skill kaydedildi: %s", skill.ad)

    def kaldir(self, ad: str) -> bool:
        return self._skilller.pop(ad, None) is not None

    def al(self, ad: str) -> Optional[SkillTabani]:
        return self._skilller.get(ad)

    def listele(self, *, kategori: Optional[str] = None) -> list[SkillMeta]:
        metas = [s.meta() for s in self._skilller.values()]
        if kategori:
            metas = [m for m in metas if m.kategori == kategori]
        return sorted(metas, key=lambda m: (m.kategori, m.ad))

    def adlar(self) -> list[str]:
        return sorted(self._skilller.keys())

    @property
    def adet(self) -> int:
        return len(self._skilller)

    def eslesenleri_bul(self, komut: str) -> list[SkillTabani]:
        """Komutla eşleşen tüm skill'ler (kayıt sırasına yakın)."""
        return [s for s in self._skilller.values() if s.eslesir_mi(komut)]

    def sec(self, komut: str) -> Optional[SkillTabani]:
        """
        En uygun tek skill.

        Birden fazla eşleşmede daha uzun anahtar setine / ada öncelik.
        """
        adaylar = self.eslesenleri_bul(komut)
        if not adaylar:
            return None
        if len(adaylar) == 1:
            return adaylar[0]

        def skor(s: SkillTabani) -> tuple[int, int]:
            anahtarlar = list(s.anahtarlar) if s.anahtarlar else [s.ad]
            en_uzun = max((len(a) for a in anahtarlar), default=0)
            return (en_uzun, len(s.ad))

        adaylar.sort(key=skor, reverse=True)
        return adaylar[0]

    async def calistir(
        self,
        komut: str,
        *,
        skill_adi: Optional[str] = None,
        baglam: Optional[SkillBaglam] = None,
        **kwargs: Any,
    ) -> YetenekSonucu:
        """
        Komutu (veya açık skill adını) çalıştırır.

        Skill bulunamazsa DESTEKLENMIYOR döner.
        """
        baglam = baglam or SkillBaglam(ayar_yonetici=self.ayarlar)
        if baglam.ayar_yonetici is None:
            baglam.ayar_yonetici = self.ayarlar

        skill: Optional[SkillTabani]
        if skill_adi:
            skill = self.al(skill_adi)
        else:
            skill = self.sec(komut)

        if skill is None:
            sonuc = YetenekSonucu(
                durum=YetenekDurumu.DESTEKLENMIYOR,
                mesaj="Uygun skill bulunamadı",
                veri={"komut": komut, "skill": skill_adi},
            )
            await self._yayin(OLAY_SKILL_HATA, sonuc)
            return sonuc

        onaylandi = baglam.onaylandi or bool(kwargs.pop("onaylandi", False))
        onay = skill.onay_kontrol(
            onaylandi=onaylandi,
            ayar_yonetici=baglam.ayar_yonetici,
        )
        if onay is not None:
            await self._yayin(OLAY_SKILL_ONAY, onay)
            return onay

        try:
            sonuc = await skill.calistir(
                komut,
                onaylandi=True,
                baglam=baglam,
                **kwargs,
            )
        except Exception as exc:
            log.exception("Skill hata: %s", skill.ad)
            sonuc = YetenekSonucu.hata(
                str(exc),
                yetenek=skill.ad,
                veri={"komut": komut},
            )
            await self._yayin(OLAY_SKILL_HATA, sonuc)
            return sonuc

        if sonuc.yetenek is None:
            sonuc.yetenek = skill.ad

        if skill.tehlikeli:
            audit_yaz(
                "skill_calisti",
                modul="skills",
                detay={
                    "skill": skill.ad,
                    "ok": sonuc.basarili,
                    "komut": komut[:200],
                },
            )

        olay = OLAY_SKILL_CALISTI if sonuc.basarili else OLAY_SKILL_HATA
        await self._yayin(olay, sonuc)
        return sonuc

    async def _yayin(self, olay: str, sonuc: YetenekSonucu) -> None:
        try:
            await self.bus.publish(
                olay,
                sonuc.to_dict(),
                kaynak=self.ad,
            )
        except Exception:
            log.debug("Skill olay yayınlanamadı: %s", olay)

    def ozet(self) -> dict[str, Any]:
        return {
            "count": self.adet,
            "skills": [m.to_dict() for m in self.listele()],
            "running": self.calisiyor,
        }

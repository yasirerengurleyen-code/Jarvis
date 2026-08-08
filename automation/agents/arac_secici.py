"""
automation/agents/arac_secici.py
--------------------------------
Araç / skill seçici — plan adımlarına uygun yetenek atar.

Görev:
- PlanAdimi / GorevPlani için skill veya yerleşik araç seçmek
- SkillYoneticisi varsa eşleştirme; yoksa offline heuristik harita
- dry_run / ağsız birim testlere uygun (zorunlu bağımlılık yok)
- Mevcut arac_adi korunur; needs_tool_select veya boş ad doldurulur

Not: Yürütme `yurutucu.py` içinde; bu modül yalnızca seçim / zenginleştirme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence, Union

from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    AracTuru,
    GorevPlani,
    PlanAdimi,
    arac_turu_coz,
)
from automation.agents.planlayici import hedef_normalize
from core.logger import logger_al

log = logger_al("automation.agents.arac_secici")

# Bilinen varsayılan skill adları (skills/kayit ile uyumlu; import zorunlu değil)
VARSAYILAN_SKILL_ADLARI: frozenset[str] = frozenset(
    {
        "program_ac",
        "terminal",
        "dosya_islemleri",
        "pdf_okuyucu",
        "web_arama",
        "hava",
        "kamera",
        "ocr",
        "qr_okuyucu",
        "takvim",
        "hatirlatici",
    }
)

# Skill → varsayılan tehlikeli bayrağı (yönetici yokken)
_SKILL_TEHLIKELI: dict[str, bool] = {
    "terminal": True,
    "dosya_islemleri": False,
    "program_ac": False,
    "pdf_okuyucu": False,
    "web_arama": False,
    "hava": False,
    "kamera": False,
    "ocr": False,
    "qr_okuyucu": False,
    "takvim": False,
    "hatirlatici": False,
}

# Plan meta.role → skill (planlayici şablonları ile hizalı)
_ROLE_SKILL: dict[str, str] = {
    "mkdir": "dosya_islemleri",
    "readme": "dosya_islemleri",
    "git_init": "terminal",
    "venv": "terminal",
    "editor": "program_ac",
    "shell": "terminal",
    "file": "dosya_islemleri",
}

# (anahtarlar, skill_adi) — ilk eşleşen kazanır; uzun / spesifik önce
_HEURISTIK_HARITA: list[tuple[tuple[str, ...], str]] = [
    (("hava durumu", "hava nasil", "hava nasıl", "weather", "sicaklik", "sıcaklık"), "hava"),
    (("web ara", "internet ara", "google", "duckduckgo", "search"), "web_arama"),
    (("pdf oku", "pdf okuyucu", "pdf"), "pdf_okuyucu"),
    (("qr oku", "qr kod", "barkod"), "qr_okuyucu"),
    (("ocr", "metin oku", "goruntu metin", "görüntü metin"), "ocr"),
    (("kamera", "fotocek", "foto çek", "webcam"), "kamera"),
    (("hatirlatici", "hatırlatıcı", "reminder", "alarm kur"), "hatirlatici"),
    (("takvim", "calendar", "etkinlik", "randevu"), "takvim"),
    (
        (
            "klasor olustur",
            "klasör oluştur",
            "mkdir",
            "dosya yaz",
            "dosya oku",
            "dosya sil",
            "dosya_islemleri",
            "readme",
            "listele",
        ),
        "dosya_islemleri",
    ),
    (
        (
            "git init",
            "git baslat",
            "git başlat",
            "venv",
            "terminal",
            "shell",
            "powershell",
            "komut calistir",
            "komut çalıştır",
            "python -m",
        ),
        "terminal",
    ),
    (
        (
            "vscode",
            "vs code",
            "program ac",
            "program aç",
            "uygulama ac",
            "uygulama aç",
            "notepad",
            "chrome ac",
            "code ac",
        ),
        "program_ac",
    ),
]


class SecimKaynagi(str, Enum):
    """Araç seçiminin nereden geldiği."""

    PRESET = "preset"  # adımda zaten arac_adi vardı
    ROLE = "role"  # meta.role eşlemesi
    SKILL_MANAGER = "skill_manager"
    HEURISTIC = "heuristic"
    BUILTIN = "builtin"
    FORCED = "forced"


SecimKaynagiGirdi = Union[SecimKaynagi, str]


def secim_kaynagi_coz(deger: SecimKaynagiGirdi) -> SecimKaynagi:
    """str / Enum → SecimKaynagi."""
    if isinstance(deger, SecimKaynagi):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "preset": SecimKaynagi.PRESET,
        "onceden": SecimKaynagi.PRESET,
        "role": SecimKaynagi.ROLE,
        "rol": SecimKaynagi.ROLE,
        "skill_manager": SecimKaynagi.SKILL_MANAGER,
        "yonetici": SecimKaynagi.SKILL_MANAGER,
        "heuristic": SecimKaynagi.HEURISTIC,
        "heuristik": SecimKaynagi.HEURISTIC,
        "builtin": SecimKaynagi.BUILTIN,
        "yerlesik": SecimKaynagi.BUILTIN,
        "forced": SecimKaynagi.FORCED,
        "zorla": SecimKaynagi.FORCED,
    }
    if metin in esleme:
        return esleme[metin]
    raise AjanHata(
        f"Bilinmeyen secim kaynagi: {deger!r}",
        kod="AUT_0036",
        modul="automation.agents",
    )


@dataclass
class AracSecim:
    """
    Tek adım için araç seçim sonucu.

    Wire: tool_name, tool_type, dangerous, confidence, source, reason?, meta?
    """

    arac_adi: str
    arac_turu: AracTuru = AracTuru.SKILL
    tehlikeli: bool = False
    guven: float = 1.0
    kaynak: SecimKaynagi = SecimKaynagi.HEURISTIC
    neden: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.arac_adi,
            "tool_type": self.arac_turu.value,
            "dangerous": bool(self.tehlikeli),
            "confidence": float(self.guven),
            "source": self.kaynak.value,
            "reason": self.neden,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "AracSecim":
        if not isinstance(veri, dict):
            raise AjanHata(
                "Arac secim dict olmali",
                kod="AUT_0037",
                modul="automation.agents",
            )
        return cls(
            arac_adi=str(veri.get("tool_name") or veri.get("arac_adi") or ""),
            arac_turu=arac_turu_coz(
                veri.get("tool_type") or veri.get("arac_turu") or "skill"
            ),
            tehlikeli=bool(veri.get("dangerous", veri.get("tehlikeli", False))),
            guven=float(veri.get("confidence", veri.get("guven", 1.0))),
            kaynak=secim_kaynagi_coz(
                veri.get("source") or veri.get("kaynak") or "heuristic"
            ),
            neden=str(veri.get("reason") or veri.get("neden") or ""),
            meta=dict(veri.get("meta") or {}),
        )


def _metin_birlestir(*parcalar: Any) -> str:
    """Başlık / komut / args parçalarını tek arama metnine çevirir."""
    parca: list[str] = []
    for p in parcalar:
        if p is None:
            continue
        if isinstance(p, dict):
            for k, v in p.items():
                if v is None:
                    continue
                parca.append(f"{k} {v}")
        else:
            s = str(p).strip()
            if s:
                parca.append(s)
    return " ".join(parca)


def heuristik_skill_sec(metin: str) -> Optional[tuple[str, float, str]]:
    """
    Offline anahtar → skill eşlemesi.

    Dönüş: (skill_adi, guven, eslesen_anahtar) veya None.
    """
    n = hedef_normalize(metin)
    if not n:
        return None
    for anahtarlar, skill in _HEURISTIK_HARITA:
        for a in anahtarlar:
            ana = hedef_normalize(a)
            if ana and ana in n:
                # daha uzun anahtar → biraz daha yüksek güven
                guven = min(0.95, 0.55 + min(len(ana), 24) * 0.015)
                return skill, guven, a
    return None


def role_skill_sec(role: Any) -> Optional[str]:
    """meta.role → bilinen skill adı."""
    if role is None:
        return None
    anahtar = str(role).strip().lower()
    return _ROLE_SKILL.get(anahtar)


def skill_tehlikeli_mi(arac_adi: str, *, skill_yoneticisi: Any = None) -> bool:
    """Skill adına göre tehlikeli bayrağı (yönetici veya yerel tablo)."""
    ad = str(arac_adi or "").strip()
    if not ad:
        return False
    if skill_yoneticisi is not None:
        try:
            skill = skill_yoneticisi.al(ad) if hasattr(skill_yoneticisi, "al") else None
            if skill is not None:
                return bool(getattr(skill, "tehlikeli", False))
        except Exception:
            pass
    return bool(_SKILL_TEHLIKELI.get(ad, False))


def adim_arac_gerekli_mi(adim: PlanAdimi) -> bool:
    """Boş araç veya needs_tool_select ise seçim gerekir."""
    if bool(adim.meta.get("needs_tool_select")):
        return True
    if not str(adim.arac_adi or "").strip():
        return True
    return False


class AracSecici:
    """
    Plan adımları için araç / skill seçici.

    SkillYoneticisi enjekte edilebilir; yoksa yalnızca heuristik çalışır.
    """

    def __init__(
        self,
        *,
        skill_yoneticisi: Any = None,
        ayar_yonetici: Any = None,
        bilinen_skilller: Optional[Sequence[str]] = None,
    ) -> None:
        self.skills = skill_yoneticisi
        self.ayarlar = ayar_yonetici
        self.bilinen = frozenset(
            bilinen_skilller if bilinen_skilller is not None else VARSAYILAN_SKILL_ADLARI
        )

    def _yonetici_sec(self, metin: str) -> Optional[tuple[str, float]]:
        """SkillYoneticisi.sec → (ad, guven)."""
        if self.skills is None or not metin.strip():
            return None
        try:
            skill = self.skills.sec(metin) if hasattr(self.skills, "sec") else None
        except Exception as hata:
            log.debug("SkillYoneticisi.sec basarisiz: %s", hata)
            return None
        if skill is None:
            return None
        ad = str(getattr(skill, "ad", "") or "").strip()
        if not ad:
            return None
        return ad, 0.9

    def _arac_dogrula(self, arac_adi: str) -> bool:
        """Adın bilinen / kayıtlı skill olup olmadığı."""
        ad = str(arac_adi or "").strip()
        if not ad:
            return False
        if self.skills is not None and hasattr(self.skills, "al"):
            try:
                if self.skills.al(ad) is not None:
                    return True
            except Exception:
                pass
        return ad in self.bilinen

    def sec(
        self,
        adim: PlanAdimi,
        *,
        hedef: Optional[str] = None,
        baglam: Optional[AjanBaglam] = None,
        zorla: bool = False,
    ) -> AracSecim:
        """
        Tek adım için AracSecim üretir (adımı değiştirmez).

        Args:
            adim: Plan adımı
            hedef: Görev hedefi (ek bağlam metni)
            baglam: dry_run vb. (şimdilik meta için)
            zorla: True ise mevcut arac_adi yok sayılır
        """
        _ = baglam
        arama = _metin_birlestir(adim.baslik, adim.komut, adim.args, hedef)
        role = adim.meta.get("role")

        # 1) Mevcut araç korunur
        mevcut = str(adim.arac_adi or "").strip()
        if mevcut and not zorla and not bool(adim.meta.get("needs_tool_select")):
            tur = adim.arac_turu
            tehlike = adim.tehlikeli or skill_tehlikeli_mi(
                mevcut, skill_yoneticisi=self.skills
            )
            if tur is AracTuru.SKILL and not self._arac_dogrula(mevcut):
                log.debug("Onceden atanmis arac dogrulanamadi: %s", mevcut)
            return AracSecim(
                arac_adi=mevcut,
                arac_turu=tur,
                tehlikeli=bool(tehlike),
                guven=1.0 if self._arac_dogrula(mevcut) or tur is not AracTuru.SKILL else 0.7,
                kaynak=SecimKaynagi.PRESET,
                neden="adimda arac_adi mevcut",
                meta={"validated": self._arac_dogrula(mevcut)},
            )

        # 2) meta.role
        role_skill = role_skill_sec(role)
        if role_skill:
            return AracSecim(
                arac_adi=role_skill,
                arac_turu=AracTuru.SKILL,
                tehlikeli=skill_tehlikeli_mi(role_skill, skill_yoneticisi=self.skills),
                guven=0.92,
                kaynak=SecimKaynagi.ROLE,
                neden=f"meta.role={role}",
                meta={"role": role},
            )

        # 3) Skill yöneticisi
        yonetici = self._yonetici_sec(arama)
        if yonetici is not None:
            ad, guven = yonetici
            return AracSecim(
                arac_adi=ad,
                arac_turu=AracTuru.SKILL,
                tehlikeli=skill_tehlikeli_mi(ad, skill_yoneticisi=self.skills),
                guven=guven,
                kaynak=SecimKaynagi.SKILL_MANAGER,
                neden="SkillYoneticisi.sec",
                meta={},
            )

        # 4) Heuristik
        heur = heuristik_skill_sec(arama)
        if heur is not None:
            ad, guven, anahtar = heur
            return AracSecim(
                arac_adi=ad,
                arac_turu=AracTuru.SKILL,
                tehlikeli=skill_tehlikeli_mi(ad, skill_yoneticisi=self.skills),
                guven=guven,
                kaynak=SecimKaynagi.HEURISTIC,
                neden=f"anahtar={anahtar!r}",
                meta={"matched_key": anahtar},
            )

        # 5) Yerleşik / seçilemedi
        return AracSecim(
            arac_adi="",
            arac_turu=AracTuru.BUILTIN,
            tehlikeli=False,
            guven=0.2,
            kaynak=SecimKaynagi.BUILTIN,
            neden="uygun skill bulunamadi",
            meta={"query": arama[:200]},
        )

    def adima_uygula(
        self,
        adim: PlanAdimi,
        *,
        hedef: Optional[str] = None,
        baglam: Optional[AjanBaglam] = None,
        zorla: bool = False,
        sadece_gerekliyse: bool = True,
    ) -> AracSecim:
        """
        Seçimi PlanAdimi üzerine yazar.

        sadece_gerekliyse=True ve araç zaten doluysa yalnızca meta zenginleşir.
        """
        if sadece_gerekliyse and not zorla and not adim_arac_gerekli_mi(adim):
            secim = self.sec(adim, hedef=hedef, baglam=baglam, zorla=False)
            # tehlikeli bayrağını skill tablosundan güçlendir
            if secim.tehlikeli and not adim.tehlikeli:
                adim.tehlikeli = True
            adim.meta.setdefault("tool_select", secim.to_dict())
            return secim

        secim = self.sec(adim, hedef=hedef, baglam=baglam, zorla=zorla)
        if secim.arac_adi:
            adim.arac_adi = secim.arac_adi
            adim.arac_turu = secim.arac_turu
        elif secim.arac_turu is AracTuru.BUILTIN:
            adim.arac_turu = AracTuru.BUILTIN
        if secim.tehlikeli:
            adim.tehlikeli = True
        adim.meta["needs_tool_select"] = False
        adim.meta["tool_select"] = secim.to_dict()
        if zorla:
            adim.meta["tool_select_forced"] = True
        return secim

    def plana_uygula(
        self,
        plan: GorevPlani,
        *,
        zorla: bool = False,
        sadece_gerekliyse: bool = True,
    ) -> GorevPlani:
        """
        Planın tüm adımlarına araç seçimi uygular.

        dry_run bağlamında da güvenle çağrılabilir (yan etki: adım alanları).
        """
        if not isinstance(plan, GorevPlani):
            raise AjanHata(
                "GorevPlani bekleniyor",
                kod="AUT_0038",
                modul="automation.agents",
            )

        ozet: list[dict[str, Any]] = []
        for adim in plan.adimlar:
            secim = self.adima_uygula(
                adim,
                hedef=plan.hedef,
                baglam=plan.baglam,
                zorla=zorla,
                sadece_gerekliyse=sadece_gerekliyse,
            )
            ozet.append(
                {
                    "index": adim.indeks,
                    "tool_name": secim.arac_adi,
                    "source": secim.kaynak.value,
                    "confidence": secim.guven,
                }
            )

        plan.meta["tool_selector"] = {
            "steps": ozet,
            "dry_run": bool(plan.baglam.dry_run),
            "forced": bool(zorla),
        }
        plan.dokun()
        log.info(
            "Arac secimi: plan=%s steps=%s dry_run=%s",
            plan.plan_id,
            len(ozet),
            plan.baglam.dry_run,
        )
        return plan


def arac_secici_olustur(
    *,
    skill_yoneticisi: Any = None,
    ayar_yonetici: Any = None,
    bilinen_skilller: Optional[Sequence[str]] = None,
) -> AracSecici:
    """AracSecici fabrikası."""
    return AracSecici(
        skill_yoneticisi=skill_yoneticisi,
        ayar_yonetici=ayar_yonetici,
        bilinen_skilller=bilinen_skilller,
    )


__all__ = [
    "VARSAYILAN_SKILL_ADLARI",
    "SecimKaynagi",
    "SecimKaynagiGirdi",
    "AracSecim",
    "AracSecici",
    "secim_kaynagi_coz",
    "heuristik_skill_sec",
    "role_skill_sec",
    "skill_tehlikeli_mi",
    "adim_arac_gerekli_mi",
    "arac_secici_olustur",
]

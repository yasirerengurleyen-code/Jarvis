"""
automation/agents/planlayici.py
-------------------------------
Görev planlayıcı — hedef metninden GorevPlani / PlanAdimi üretir.

Görev:
- Heuristik şablonlarla çok adımlı plan (offline / dry_run dostu)
- İsteğe bağlı LLM plan fonksiyonu (enjekte; yoksa ağ çağrısı yok)
- config.automation.max_plan_steps / confirm_multi_step ile uyum
- OLAY_AJAN_PLAN yayınlama (opsiyonel EventBus)

Not: Araç seçimi `arac_secici.py`, yürütme `yurutucu.py` içinde;
bu modül yalnızca plan üretimidir.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from automation.agents.modeller import (
    VARSAYILAN_MAX_ADIM,
    AjanBaglam,
    AjanHata,
    AracTuru,
    GorevDurumu,
    GorevPlani,
    PlanAdimi,
    gorev_plani_olustur,
    max_adim_siniri,
    plan_adimi_olustur,
)
from core.events import OLAY_AJAN_PLAN, EventBus, olay_yolu
from core.logger import audit_yaz, logger_al

log = logger_al("automation.agents.planlayici")

# LLM / harici plancı: hedef + bağlam → plan, adım listesi veya wire dict
LlmPlanci = Callable[
    [str, AjanBaglam],
    Union[GorevPlani, Sequence[PlanAdimi], Sequence[dict[str, Any]], dict[str, Any]],
]


class PlanModu(str, Enum):
    """Plan üretim stratejisi."""

    HEURISTIC = "heuristic"
    LLM = "llm"
    HYBRID = "hybrid"  # önce heuristik; eşleşme yoksa LLM


PlanModuGirdi = Union[PlanModu, str]


def plan_modu_coz(deger: PlanModuGirdi) -> PlanModu:
    """str / Enum → PlanModu."""
    if isinstance(deger, PlanModu):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "heuristic": PlanModu.HEURISTIC,
        "heuristik": PlanModu.HEURISTIC,
        "llm": PlanModu.LLM,
        "hybrid": PlanModu.HYBRID,
        "hibrit": PlanModu.HYBRID,
    }
    if metin in esleme:
        return esleme[metin]
    raise AjanHata(
        f"Bilinmeyen plan modu: {deger!r}",
        kod="AUT_0033",
        modul="automation.agents",
    )


def hedef_normalize(hedef: str) -> str:
    """Hedefi küçük harf + sıkıştırılmış boşluklara indirger."""
    metin = (hedef or "").strip().lower()
    metin = re.sub(r"\s+", " ", metin)
    # Türkçe basit normalizasyon
    for eski, yeni in (
        ("ı", "i"),
        ("İ", "i"),
        ("ğ", "g"),
        ("ü", "u"),
        ("ş", "s"),
        ("ö", "o"),
        ("ç", "c"),
    ):
        metin = metin.replace(eski, yeni)
    return metin


def _proje_adi_ayikla(hedef: str, *, varsayilan: str = "proje") -> str:
    """
    Hedef metninden olası proje / klasör adını çıkarır.

    Örnek: 'yeni python projesi olustur myapp' → myapp
    """
    n = (hedef or "").strip()
    # tırnaklı ad
    m = re.search(r'["\']([^"\']+)["\']', n)
    if m:
        ad = m.group(1).strip()
        if ad:
            return ad
    # 'adı X' / 'named X' / son token
    m = re.search(
        r"(?i)(?:adi|ad[iı]|named|name|klasor|klasör)\s*[:=]?\s*([A-Za-z0-9_.\-]+)",
        n,
    )
    if m:
        return m.group(1).strip()
    parcalar = n.split()
    atla = {
        "yeni",
        "python",
        "projesi",
        "proje",
        "olustur",
        "oluştur",
        "create",
        "a",
        "bir",
        "git",
        "repo",
        "baslat",
        "başlat",
        "init",
        "readme",
        "yaz",
        "olustur.",
    }
    for p in reversed(parcalar):
        temiz = p.strip(".,;:!?\"'")
        if temiz and temiz.lower() not in atla and len(temiz) >= 2:
            # fiil gibi durmasın
            if temiz.lower() in {"olustur", "oluştur", "create", "make", "yap"}:
                continue
            if re.match(r"^[A-Za-z_][A-Za-z0-9_.\-]*$", temiz):
                return temiz
    return varsayilan


def _sablon_python_projesi(hedef: str, baglam: AjanBaglam) -> list[PlanAdimi]:
    """ASAMA8 örnek senaryosu: klasör → git → venv → README → editör."""
    ad = _proje_adi_ayikla(hedef, varsayilan="yeni_proje")
    if baglam.proje_kok:
        yol = str(Path(baglam.proje_kok) / ad)
    else:
        yol = ad
    readme = str(Path(yol) / "README.md")
    venv_yol = str(Path(yol) / ".venv")

    return [
        plan_adimi_olustur(
            "Klasör oluştur",
            arac_adi="dosya_islemleri",
            komut=f'mkdir "{yol}"',
            args={"islem": "klasor", "path": yol},
            meta={"template": "python_project", "role": "mkdir"},
        ),
        plan_adimi_olustur(
            "Git başlat",
            arac_adi="terminal",
            komut=f'git -C "{yol}" init',
            tehlikeli=True,
            args={"cwd": yol, "shell": "git init"},
            meta={"template": "python_project", "role": "git_init"},
        ),
        plan_adimi_olustur(
            "venv oluştur",
            arac_adi="terminal",
            komut=f'python -m venv "{venv_yol}"',
            args={"cwd": yol, "shell": "python -m venv .venv"},
            meta={"template": "python_project", "role": "venv"},
        ),
        plan_adimi_olustur(
            "README oluştur",
            arac_adi="dosya_islemleri",
            komut=f'yaz "{readme}"',
            args={
                "islem": "yaz",
                "path": readme,
                "icerik": f"# {ad}\n\nWhiteCore AI ile oluşturuldu.\n",
            },
            meta={"template": "python_project", "role": "readme"},
        ),
        plan_adimi_olustur(
            "VS Code aç",
            arac_adi="program_ac",
            komut=f'code "{yol}"',
            args={"hedef": "code", "path": yol},
            meta={"template": "python_project", "role": "editor"},
        ),
    ]


def _sablon_git_baslat(hedef: str, baglam: AjanBaglam) -> list[PlanAdimi]:
    kok = baglam.proje_kok or "."
    return [
        plan_adimi_olustur(
            "Git deposu başlat",
            arac_adi="terminal",
            komut=f'git -C "{kok}" init',
            tehlikeli=True,
            args={"cwd": kok, "shell": "git init"},
            meta={"template": "git_init"},
        ),
    ]


def _sablon_genel(hedef: str, baglam: AjanBaglam) -> list[PlanAdimi]:
    """
    Bilinmeyen hedefler için tek adımlık genel plan.

    Araç seçici sonraki aşamada zenginleştirebilir.
    """
    _ = baglam
    return [
        plan_adimi_olustur(
            "Hedefi incele",
            arac_adi="",
            komut=hedef.strip(),
            arac_turu=AracTuru.BUILTIN,
            args={"goal": hedef.strip()},
            meta={"template": "generic", "needs_tool_select": True},
        ),
    ]


# (anahtarlar, şablon üretici) — ilk eşleşen kazanır
_HEURISTIK_SABLONLAR: list[tuple[tuple[str, ...], Callable[[str, AjanBaglam], list[PlanAdimi]]]] = [
    (
        (
            "python proje",
            "python projesi",
            "yeni python",
            "create python",
            "python project",
            "py proje",
        ),
        _sablon_python_projesi,
    ),
    (
        ("git baslat", "git init", "git deposu", "repo baslat", "repository init"),
        _sablon_git_baslat,
    ),
]


def heuristik_sablon_eslestir(hedef: str) -> Optional[str]:
    """Eşleşen şablon adını döner; yoksa None."""
    n = hedef_normalize(hedef)
    if not n:
        return None
    for anahtarlar, uretici in _HEURISTIK_SABLONLAR:
        for a in anahtarlar:
            if hedef_normalize(a) in n:
                return uretici.__name__.replace("_sablon_", "")
    return None


def heuristik_adimlar(hedef: str, baglam: AjanBaglam) -> tuple[list[PlanAdimi], str]:
    """
    Heuristik adım listesi + şablon kimliği.

    Dönüş: (adımlar, template_id)
    """
    n = hedef_normalize(hedef)
    for anahtarlar, uretici in _HEURISTIK_SABLONLAR:
        for a in anahtarlar:
            if hedef_normalize(a) in n:
                adimlar = uretici(hedef, baglam)
                sablon = uretici.__name__.replace("_sablon_", "")
                return adimlar, sablon
    return _sablon_genel(hedef, baglam), "generic"


def _adimlari_kirp(adimlar: Sequence[PlanAdimi], max_adim: int) -> list[PlanAdimi]:
    """max_plan_steps sınırına göre kırpar."""
    sinir = max_adim_siniri(max_adim)
    liste = list(adimlar)
    if len(liste) > sinir:
        log.warning("Plan adımları kırpıldı: %s → %s", len(liste), sinir)
        liste = liste[:sinir]
    return liste


def _llm_yanitini_adimlara(
    yanit: Union[GorevPlani, Sequence[Any], dict[str, Any]],
    *,
    hedef: str,
    baglam: AjanBaglam,
) -> list[PlanAdimi]:
    """LLM / harici plancının çıktısını PlanAdimi listesine çevirir."""
    if isinstance(yanit, GorevPlani):
        return list(yanit.adimlar)

    if isinstance(yanit, dict):
        if "steps" in yanit or "adimlar" in yanit or "goal" in yanit or "hedef" in yanit:
            plan = GorevPlani.from_dict(
                {
                    "goal": yanit.get("goal") or yanit.get("hedef") or hedef,
                    "steps": yanit.get("steps") or yanit.get("adimlar") or [],
                    "context": baglam.to_dict(),
                    **{k: v for k, v in yanit.items() if k not in {"steps", "adimlar"}},
                }
            )
            return list(plan.adimlar)
        raise AjanHata(
            "LLM plan yaniti steps/goal icermeli",
            kod="AUT_0035",
            modul="automation.agents",
        )

    if isinstance(yanit, (list, tuple)):
        adimlar: list[PlanAdimi] = []
        for oge in yanit:
            if isinstance(oge, PlanAdimi):
                adimlar.append(oge)
            elif isinstance(oge, dict):
                adimlar.append(PlanAdimi.from_dict(oge))
            else:
                raise AjanHata(
                    f"LLM adim gecersiz tip: {type(oge).__name__}",
                    kod="AUT_0035",
                    modul="automation.agents",
                )
        return adimlar

    raise AjanHata(
        f"LLM plan yaniti cozulemedi: {type(yanit).__name__}",
        kod="AUT_0035",
        modul="automation.agents",
    )


class GorevPlanlayici:
    """
    Hedef metninden GorevPlani üreten planlayıcı.

    Varsayılan mod: heuristic (ağ / LLM gerekmez).
    """

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        llm_planci: Optional[LlmPlanci] = None,
        ayar_yonetici: Any = None,
        olay_yayinla: bool = True,
        varsayilan_mod: PlanModuGirdi = PlanModu.HEURISTIC,
    ) -> None:
        self.bus = bus
        self.llm_planci = llm_planci
        self.ayarlar = ayar_yonetici
        self.olay_yayinla = bool(olay_yayinla)
        self.varsayilan_mod = plan_modu_coz(varsayilan_mod)

    def _ayar_al(self, anahtar: str, varsayilan: Any = None) -> Any:
        if self.ayarlar is None:
            return varsayilan
        try:
            if hasattr(self.ayarlar, "al"):
                return self.ayarlar.al(anahtar, varsayilan)
        except Exception:
            return varsayilan
        return varsayilan

    def baglam_hazirla(
        self,
        baglam: Optional[AjanBaglam] = None,
        *,
        dry_run: Optional[bool] = None,
        max_adim: Optional[int] = None,
        onay_coklu: Optional[bool] = None,
        proje_kok: Optional[str] = None,
        kullanici_id: Optional[str] = None,
        ekstra: Optional[dict[str, Any]] = None,
    ) -> AjanBaglam:
        """Config + argümanlardan AjanBaglam üretir / birleştirir."""
        cfg_max = self._ayar_al("automation.max_plan_steps", VARSAYILAN_MAX_ADIM)
        cfg_onay = self._ayar_al("automation.confirm_multi_step", True)
        cfg_kok = self._ayar_al("automation.default_project_root", None)

        if baglam is None:
            baglam = AjanBaglam(
                dry_run=True if dry_run is None else bool(dry_run),
                onay_coklu=bool(cfg_onay) if onay_coklu is None else bool(onay_coklu),
                max_adim=max_adim_siniri(
                    cfg_max if max_adim is None else max_adim,
                    varsayilan=VARSAYILAN_MAX_ADIM,
                ),
                proje_kok=(
                    None
                    if (proje_kok if proje_kok is not None else cfg_kok) is None
                    else str(proje_kok if proje_kok is not None else cfg_kok)
                ),
                kullanici_id=kullanici_id,
                ekstra=dict(ekstra or {}),
            )
            return baglam

        # Mevcut bağlamı kopyala / override
        return AjanBaglam(
            kullanici_id=kullanici_id if kullanici_id is not None else baglam.kullanici_id,
            proje_kok=proje_kok if proje_kok is not None else baglam.proje_kok,
            dry_run=baglam.dry_run if dry_run is None else bool(dry_run),
            onay_coklu=baglam.onay_coklu if onay_coklu is None else bool(onay_coklu),
            max_adim=max_adim_siniri(
                baglam.max_adim if max_adim is None else max_adim,
                varsayilan=VARSAYILAN_MAX_ADIM,
            ),
            ekstra={**dict(baglam.ekstra), **dict(ekstra or {})},
        )

    def _yayinla(self, plan: GorevPlani) -> None:
        if not self.olay_yayinla:
            return
        bus = self.bus or olay_yolu
        try:
            bus.publish_sync(
                OLAY_AJAN_PLAN,
                plan.to_dict(),
                kaynak="automation.planlayici",
            )
        except Exception as hata:  # yayın hatası planı bozmasın
            log.debug("OLAY_AJAN_PLAN yayinlanamadi: %s", hata)

    def _audit(self, plan: GorevPlani, *, mod: PlanModu, sablon: str) -> None:
        if plan.adim_sayisi > 1 or plan.tehlikeli_mi:
            try:
                audit_yaz(
                    "ajan_plan",
                    modul="automation.agents.planlayici",
                    kullanici=plan.baglam.kullanici_id,
                    detay={
                        "plan_id": plan.plan_id,
                        "goal": plan.hedef,
                        "steps": plan.adim_sayisi,
                        "dangerous": plan.tehlikeli_mi,
                        "needs_confirmation": plan.onay_gerekli_mi,
                        "dry_run": plan.baglam.dry_run,
                        "mode": mod.value,
                        "template": sablon,
                    },
                )
            except Exception as hata:
                log.debug("audit yazilamadi: %s", hata)

    def _heuristik_plan(
        self,
        hedef: str,
        baglam: AjanBaglam,
        *,
        meta: Optional[dict[str, Any]] = None,
    ) -> GorevPlani:
        adimlar, sablon = heuristik_adimlar(hedef, baglam)
        adimlar = _adimlari_kirp(adimlar, baglam.max_adim)
        plan = gorev_plani_olustur(
            hedef.strip(),
            adimlar=adimlar,
            baglam=baglam,
            meta={
                "planner": "heuristic",
                "template": sablon,
                **dict(meta or {}),
            },
        )
        return plan

    def _llm_plan(
        self,
        hedef: str,
        baglam: AjanBaglam,
        *,
        meta: Optional[dict[str, Any]] = None,
    ) -> GorevPlani:
        if self.llm_planci is None:
            raise AjanHata(
                "LLM planci tanimli degil",
                kod="AUT_0034",
                modul="automation.agents",
            )
        yanit = self.llm_planci(hedef.strip(), baglam)
        adimlar = _llm_yanitini_adimlara(yanit, hedef=hedef, baglam=baglam)
        if not adimlar:
            raise AjanHata(
                "LLM plani bos adim listesi dondu",
                kod="AUT_0035",
                modul="automation.agents",
            )
        adimlar = _adimlari_kirp(adimlar, baglam.max_adim)
        return gorev_plani_olustur(
            hedef.strip(),
            adimlar=adimlar,
            baglam=baglam,
            meta={
                "planner": "llm",
                "template": "llm",
                **dict(meta or {}),
            },
        )

    def planla(
        self,
        hedef: str,
        *,
        baglam: Optional[AjanBaglam] = None,
        mod: Optional[PlanModuGirdi] = None,
        dry_run: Optional[bool] = None,
        meta: Optional[dict[str, Any]] = None,
        yayinla: Optional[bool] = None,
    ) -> GorevPlani:
        """
        Hedef için GorevPlani üretir.

        Args:
            hedef: Kullanıcı görevi (örn. 'Yeni Python projesi oluştur')
            baglam: AjanBaglam; None ise config varsayılanları
            mod: heuristic | llm | hybrid
            dry_run: Bağlam dry_run override
            meta: plan.meta ek alanları
            yayinla: OLAY_AJAN_PLAN; None → self.olay_yayinla
        """
        hedef_temiz = str(hedef or "").strip()
        if not hedef_temiz:
            raise AjanHata(
                "Gorev plani hedefi gerekli",
                kod="AUT_0031",
                modul="automation.agents",
            )

        bag = self.baglam_hazirla(baglam, dry_run=dry_run)
        kullanilan_mod = plan_modu_coz(mod if mod is not None else self.varsayilan_mod)
        sablon = "unknown"

        if kullanilan_mod is PlanModu.HEURISTIC:
            plan = self._heuristik_plan(hedef_temiz, bag, meta=meta)
            sablon = str(plan.meta.get("template") or "heuristic")
        elif kullanilan_mod is PlanModu.LLM:
            plan = self._llm_plan(hedef_temiz, bag, meta=meta)
            sablon = "llm"
        else:
            # hybrid: özel şablon varsa heuristic; generic ise LLM dene
            eslesen = heuristik_sablon_eslestir(hedef_temiz)
            if eslesen:
                plan = self._heuristik_plan(hedef_temiz, bag, meta=meta)
                sablon = str(plan.meta.get("template") or eslesen)
            elif self.llm_planci is not None:
                plan = self._llm_plan(hedef_temiz, bag, meta=meta)
                sablon = "llm"
            else:
                plan = self._heuristik_plan(hedef_temiz, bag, meta=meta)
                sablon = str(plan.meta.get("template") or "generic")

        plan.meta["mode"] = kullanilan_mod.value
        plan.meta["dry_run"] = bool(bag.dry_run)
        if plan.adimlar and plan.durum is GorevDurumu.TASLAK:
            plan.durum = GorevDurumu.HAZIR

        self._audit(plan, mod=kullanilan_mod, sablon=sablon)

        if yayinla if yayinla is not None else self.olay_yayinla:
            self._yayinla(plan)

        log.info(
            "Plan hazir: id=%s steps=%s mode=%s template=%s dry_run=%s",
            plan.plan_id,
            plan.adim_sayisi,
            kullanilan_mod.value,
            sablon,
            bag.dry_run,
        )
        return plan


def gorev_planlayici_olustur(
    *,
    bus: Optional[EventBus] = None,
    llm_planci: Optional[LlmPlanci] = None,
    ayar_yonetici: Any = None,
    olay_yayinla: bool = True,
    varsayilan_mod: PlanModuGirdi = PlanModu.HEURISTIC,
) -> GorevPlanlayici:
    """GorevPlanlayici fabrikası."""
    return GorevPlanlayici(
        bus=bus,
        llm_planci=llm_planci,
        ayar_yonetici=ayar_yonetici,
        olay_yayinla=olay_yayinla,
        varsayilan_mod=varsayilan_mod,
    )


__all__ = [
    "LlmPlanci",
    "PlanModu",
    "PlanModuGirdi",
    "GorevPlanlayici",
    "plan_modu_coz",
    "hedef_normalize",
    "heuristik_sablon_eslestir",
    "heuristik_adimlar",
    "gorev_planlayici_olustur",
]

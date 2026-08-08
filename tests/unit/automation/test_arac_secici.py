"""automation/agents/arac_secici.py birim testleri (offline)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.arac_secici import (
    AracSecici,
    AracSecim,
    SecimKaynagi,
    adim_arac_gerekli_mi,
    arac_secici_olustur,
    heuristik_skill_sec,
    role_skill_sec,
    secim_kaynagi_coz,
    skill_tehlikeli_mi,
)
from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    AracTuru,
    PlanAdimi,
    gorev_plani_olustur,
    plan_adimi_olustur,
)
from automation.agents.planlayici import GorevPlanlayici


class _SahteSkill:
    def __init__(self, ad: str, *, tehlikeli: bool = False) -> None:
        self.ad = ad
        self.tehlikeli = tehlikeli


class _SahteYoneticisi:
    def __init__(self, skilller: dict[str, _SahteSkill], *, sec_map: Optional[dict[str, str]] = None) -> None:
        self._skilller = skilller
        self._sec_map = sec_map or {}

    def al(self, ad: str) -> Optional[_SahteSkill]:
        return self._skilller.get(ad)

    def sec(self, komut: str) -> Optional[_SahteSkill]:
        for anahtar, ad in self._sec_map.items():
            if anahtar in (komut or "").lower():
                return self._skilller.get(ad)
        return None


def test_secim_kaynagi_ve_heuristik() -> None:
    assert secim_kaynagi_coz("heuristik") is SecimKaynagi.HEURISTIC
    assert secim_kaynagi_coz("yonetici") is SecimKaynagi.SKILL_MANAGER
    try:
        secim_kaynagi_coz("bilinmeyen")
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0036"

    hit = heuristik_skill_sec("İstanbul hava durumu")
    assert hit is not None
    assert hit[0] == "hava"
    assert role_skill_sec("git_init") == "terminal"
    assert skill_tehlikeli_mi("terminal") is True
    assert skill_tehlikeli_mi("hava") is False


def test_python_plan_preset_korunur() -> None:
    planci = GorevPlanlayici(olay_yayinla=False)
    plan = planci.planla(
        "Yeni Python projesi oluştur demo_app",
        baglam=AjanBaglam(dry_run=True, max_adim=12),
    )
    secici = arac_secici_olustur()
    secici.plana_uygula(plan)

    assert plan.adimlar[0].arac_adi == "dosya_islemleri"
    assert plan.adimlar[1].arac_adi == "terminal"
    assert plan.adimlar[1].tehlikeli is True
    assert plan.adimlar[4].arac_adi == "program_ac"
    assert plan.meta["tool_selector"]["dry_run"] is True
    # preset kaynağı
    assert plan.adimlar[0].meta["tool_select"]["source"] == "preset"


def test_generic_needs_tool_select_heuristik() -> None:
    planci = GorevPlanlayici(olay_yayinla=False)
    plan = planci.planla("hava durumu istanbul", dry_run=True)
    assert plan.adimlar[0].arac_adi == ""
    assert adim_arac_gerekli_mi(plan.adimlar[0]) is True

    secici = AracSecici()
    secici.plana_uygula(plan)

    assert plan.adimlar[0].arac_adi == "hava"
    assert plan.adimlar[0].arac_turu is AracTuru.SKILL
    assert plan.adimlar[0].meta.get("needs_tool_select") is False
    assert plan.adimlar[0].meta["tool_select"]["source"] == "heuristic"


def test_role_ve_skill_manager() -> None:
    adim = plan_adimi_olustur(
        "Git başlat",
        arac_adi="",
        komut="git init",
        meta={"role": "git_init", "needs_tool_select": True},
    )
    secici = AracSecici()
    secim = secici.adima_uygula(adim)
    assert secim.kaynak is SecimKaynagi.ROLE
    assert adim.arac_adi == "terminal"
    assert adim.tehlikeli is True

    yonetici = _SahteYoneticisi(
        {
            "web_arama": _SahteSkill("web_arama"),
            "terminal": _SahteSkill("terminal", tehlikeli=True),
        },
        sec_map={"python nedir": "web_arama"},
    )
    adim2 = plan_adimi_olustur(
        "Ara",
        arac_adi="",
        komut="python nedir diye bak",
        meta={"needs_tool_select": True},
    )
    secici2 = arac_secici_olustur(skill_yoneticisi=yonetici)
    secim2 = secici2.adima_uygula(adim2)
    assert secim2.kaynak is SecimKaynagi.SKILL_MANAGER
    assert adim2.arac_adi == "web_arama"


def test_builtin_fallback_ve_serilestirme() -> None:
    adim = plan_adimi_olustur(
        "Bilinmeyen",
        arac_adi="",
        komut="xyzzy quux 42",
        arac_turu=AracTuru.BUILTIN,
        meta={"needs_tool_select": True},
    )
    secici = AracSecici()
    secim = secici.adima_uygula(adim)
    assert secim.kaynak is SecimKaynagi.BUILTIN
    assert adim.arac_turu is AracTuru.BUILTIN
    assert adim.arac_adi == ""

    wire = secim.to_dict()
    geri = AracSecim.from_dict(wire)
    assert geri.arac_turu is AracTuru.BUILTIN
    assert geri.kaynak is SecimKaynagi.BUILTIN

    try:
        AracSecim.from_dict("x")  # type: ignore[arg-type]
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0037"


def test_zorla_yeniden_secim() -> None:
    plan = gorev_plani_olustur(
        "terminal dir",
        adimlar=[
            PlanAdimi(
                baslik="Komut",
                arac_adi="hava",
                komut="terminal dir",
                arac_turu=AracTuru.SKILL,
                meta={"needs_tool_select": False},
            )
        ],
        baglam=AjanBaglam(dry_run=True),
    )
    secici = AracSecici()
    # zorla=False → hava korunur
    secici.plana_uygula(plan, zorla=False)
    assert plan.adimlar[0].arac_adi == "hava"

    # zorla=True → terminal heuristik / metin
    secici.plana_uygula(plan, zorla=True, sadece_gerekliyse=False)
    assert plan.adimlar[0].arac_adi == "terminal"
    assert plan.adimlar[0].meta.get("tool_select_forced") is True

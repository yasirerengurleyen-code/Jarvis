"""automation/agents/planlayici.py birim testleri (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    AracTuru,
    GorevDurumu,
    plan_adimi_olustur,
)
from automation.agents.planlayici import (
    GorevPlanlayici,
    PlanModu,
    gorev_planlayici_olustur,
    hedef_normalize,
    heuristik_sablon_eslestir,
    plan_modu_coz,
)
from core.events import OLAY_AJAN_PLAN, EventBus


def test_plan_modu_ve_normalize() -> None:
    assert plan_modu_coz("heuristik") is PlanModu.HEURISTIC
    assert plan_modu_coz("hibrit") is PlanModu.HYBRID
    assert "python" in hedef_normalize("Yeni Python Projesi Oluştur")
    try:
        plan_modu_coz("bilinmeyen")
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0033"


def test_python_projesi_heuristik_dry_run() -> None:
    planci = gorev_planlayici_olustur(olay_yayinla=False)
    plan = planci.planla(
        "Yeni Python projesi oluştur demo_app",
        baglam=AjanBaglam(dry_run=True, onay_coklu=True, max_adim=12),
        mod=PlanModu.HEURISTIC,
    )
    assert plan.adim_sayisi == 5
    assert plan.durum is GorevDurumu.HAZIR
    assert plan.baglam.dry_run is True
    assert plan.tehlikeli_mi is True
    assert plan.onay_gerekli_mi is True
    assert plan.meta["planner"] == "heuristic"
    assert plan.meta["template"] == "python_projesi"
    assert plan.adimlar[0].arac_adi == "dosya_islemleri"
    assert plan.adimlar[1].arac_adi == "terminal"
    assert plan.adimlar[1].tehlikeli is True
    assert plan.adimlar[4].arac_adi == "program_ac"
    assert "demo_app" in (plan.adimlar[0].args.get("path") or "")


def test_max_adim_kirpma() -> None:
    planci = GorevPlanlayici(olay_yayinla=False)
    plan = planci.planla(
        "Yeni Python projesi oluştur",
        baglam=AjanBaglam(dry_run=True, max_adim=3),
    )
    assert plan.adim_sayisi == 3


def test_bos_hedef_hata() -> None:
    planci = GorevPlanlayici(olay_yayinla=False)
    try:
        planci.planla("   ")
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0031"


def test_llm_opsiyonel_ve_hybrid() -> None:
    def sahte_llm(hedef: str, baglam: AjanBaglam):
        assert baglam.dry_run is True
        return [
            {
                "title": "LLM adım 1",
                "tool_name": "dosya_islemleri",
                "command": "listele .",
                "tool_type": "skill",
            },
            plan_adimi_olustur("LLM adım 2", arac_adi="terminal", komut="echo ok"),
        ]

    planci = gorev_planlayici_olustur(llm_planci=sahte_llm, olay_yayinla=False)

    # LLM modu
    plan = planci.planla("özel görev xyz", mod=PlanModu.LLM, dry_run=True)
    assert plan.adim_sayisi == 2
    assert plan.meta["planner"] == "llm"
    assert plan.adimlar[0].baslik == "LLM adım 1"

    # Hybrid: bilinen şablon → heuristic (LLM çağrılmaz)
    plan2 = planci.planla("git init yap", mod=PlanModu.HYBRID)
    assert plan2.meta["template"] == "git_baslat"
    assert plan2.adimlar[0].tehlikeli is True

    # Hybrid: bilinmeyen + LLM var → LLM
    plan3 = planci.planla("garip bir istek 42", mod="hybrid")
    assert plan3.meta["planner"] == "llm"

    # LLM yokken LLM modu hata
    bos = GorevPlanlayici(olay_yayinla=False)
    try:
        bos.planla("x", mod=PlanModu.LLM)
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0034"


def test_genel_sablon_ve_olay() -> None:
    assert heuristik_sablon_eslestir("hava durumu istanbul") is None
    bus = EventBus()
    yakalanan: list[dict] = []

    def dinle(event) -> None:
        yakalanan.append(dict(event.veri))

    bus.subscribe(OLAY_AJAN_PLAN, dinle)
    planci = GorevPlanlayici(bus=bus, olay_yayinla=True)
    plan = planci.planla("hava durumu istanbul", dry_run=True)
    assert plan.adim_sayisi == 1
    assert plan.adimlar[0].arac_turu is AracTuru.BUILTIN
    assert plan.meta["template"] == "generic"
    assert len(yakalanan) == 1
    assert yakalanan[0]["goal"] == "hava durumu istanbul"
    assert yakalanan[0]["step_count"] == 1


def test_config_baglam_hazirla() -> None:
    class SahteAyar:
        def al(self, anahtar: str, varsayilan=None):
            veri = {
                "automation.max_plan_steps": 8,
                "automation.confirm_multi_step": False,
                "automation.default_project_root": "C:/tmp/wc",
            }
            return veri.get(anahtar, varsayilan)

    planci = GorevPlanlayici(ayar_yonetici=SahteAyar(), olay_yayinla=False)
    bag = planci.baglam_hazirla()
    assert bag.max_adim == 8
    assert bag.onay_coklu is False
    assert bag.proje_kok == "C:/tmp/wc"

    plan = planci.planla("Yeni Python projesi oluştur", baglam=bag)
    assert plan.adim_sayisi == 5
    assert "C:" in (plan.adimlar[0].args.get("path") or "") or "tmp" in (
        plan.adimlar[0].args.get("path") or ""
    ).replace("\\", "/")

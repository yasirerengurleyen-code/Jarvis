"""automation/agents/modeller.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.modeller import (
    AJAN_MODEL_SURUM,
    VARSAYILAN_MAX_ADIM,
    AjanBaglam,
    AjanHata,
    AracTuru,
    GorevDurumu,
    GorevPlani,
    PlanAdimDurumu,
    PlanAdimi,
    adim_durumu_coz,
    arac_turu_coz,
    gorev_durumu_coz,
    gorev_plani_olustur,
    max_adim_siniri,
    plan_adimi_olustur,
)
from core.base import YetenekSonucu


def test_durum_ve_arac_coz() -> None:
    assert adim_durumu_coz("pending") is PlanAdimDurumu.BEKLIYOR
    assert adim_durumu_coz("basarili") is PlanAdimDurumu.BASARILI
    assert gorev_durumu_coz("ready") is GorevDurumu.HAZIR
    assert gorev_durumu_coz("taslak") is GorevDurumu.TASLAK
    assert arac_turu_coz("skill") is AracTuru.SKILL
    assert arac_turu_coz("yetenek") is AracTuru.SKILL
    try:
        adim_durumu_coz("bilinmeyen")
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0020"


def test_max_adim_siniri() -> None:
    assert max_adim_siniri(None) == VARSAYILAN_MAX_ADIM
    assert max_adim_siniri(8) == 8
    try:
        max_adim_siniri(0)
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0024"


def test_plan_adimi_roundtrip_ve_sonuc() -> None:
    adim = plan_adimi_olustur(
        "Klasör oluştur",
        arac_adi="dosya_islemleri",
        komut="mkdir proje",
        tehlikeli=False,
    )
    assert adim.durum is PlanAdimDurumu.BEKLIYOR
    d = adim.to_dict()
    assert d["title"] == "Klasör oluştur"
    assert d["tool_name"] == "dosya_islemleri"
    assert d["status"] == "pending"

    geri = PlanAdimi.from_dict(d)
    assert geri.baslik == "Klasör oluştur"
    assert geri.arac_turu is AracTuru.SKILL

    adim.sonucu_uygula(YetenekSonucu.ok("olusturuldu", yetenek="dosya_islemleri"))
    assert adim.basarili_mi
    assert adim.sonuc is not None and adim.sonuc["ok"] is True


def test_gorev_plani_python_projesi_ornegi() -> None:
    baglam = AjanBaglam(dry_run=True, onay_coklu=True, max_adim=12)
    plan = gorev_plani_olustur(
        "Yeni Python projesi oluştur",
        baglam=baglam,
        adimlar=[
            plan_adimi_olustur("Klasör oluştur", arac_adi="dosya_islemleri", komut="mkdir"),
            plan_adimi_olustur("Git başlat", arac_adi="terminal", komut="git init", tehlikeli=True),
            plan_adimi_olustur("venv oluştur", arac_adi="terminal", komut="python -m venv .venv"),
            plan_adimi_olustur("README oluştur", arac_adi="dosya_islemleri", komut="write README"),
            plan_adimi_olustur("VS Code aç", arac_adi="program_ac", komut="code ."),
        ],
    )
    assert plan.adim_sayisi == 5
    assert plan.durum is GorevDurumu.HAZIR
    assert plan.tehlikeli_mi is True
    assert plan.onay_gerekli_mi is True
    assert plan.sonraki_bekleyen() is plan.adimlar[0]

    d = plan.to_dict()
    assert d["v"] == AJAN_MODEL_SURUM
    assert d["goal"] == "Yeni Python projesi oluştur"
    assert d["step_count"] == 5
    assert d["needs_confirmation"] is True
    assert len(d["steps"]) == 5

    geri = GorevPlani.from_dict(d)
    assert geri.hedef == plan.hedef
    assert geri.adim_sayisi == 5
    assert geri.baglam.dry_run is True


def test_adim_siniri_asimi() -> None:
    plan = gorev_plani_olustur(
        "sinir testi",
        baglam=AjanBaglam(max_adim=2),
        adimlar=[
            plan_adimi_olustur("a"),
            plan_adimi_olustur("b"),
        ],
    )
    try:
        plan.adim_ekle(plan_adimi_olustur("c"))
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0029"


def test_ozet_yenile_tamamlandi() -> None:
    plan = gorev_plani_olustur(
        "iki adim",
        adimlar=[plan_adimi_olustur("bir"), plan_adimi_olustur("iki")],
    )
    for adim in plan.adimlar:
        adim.sonucu_uygula(YetenekSonucu.ok("ok"))
    assert plan.ozet_yenile() is GorevDurumu.TAMAMLANDI
    assert plan.sonraki_bekleyen() is None

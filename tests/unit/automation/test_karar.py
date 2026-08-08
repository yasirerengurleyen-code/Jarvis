"""automation/agents/karar.py birim testleri (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.karar import (
    KararAksiyonu,
    KararMotoru,
    KararSonucu,
    hata_gecici_mi,
    karar_aksiyonu_coz,
    karar_motoru_olustur,
    max_retry_siniri,
)
from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    GorevDurumu,
    PlanAdimDurumu,
    gorev_plani_olustur,
    plan_adimi_olustur,
)
from core.base import YetenekDurumu, YetenekSonucu


def test_aksiyon_coz_ve_max_retry() -> None:
    assert karar_aksiyonu_coz("continue") is KararAksiyonu.DEVAM
    assert karar_aksiyonu_coz("yeniden_dene") is KararAksiyonu.YENIDEN_DENE
    assert karar_aksiyonu_coz("abort") is KararAksiyonu.IPTAL
    assert karar_aksiyonu_coz("kullaniciya_sor") is KararAksiyonu.KULLANICIYA_SOR
    assert max_retry_siniri(None) == 2
    assert max_retry_siniri(0) == 0
    try:
        karar_aksiyonu_coz("bilinmeyen")
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0043"
    try:
        max_retry_siniri(99)
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0044"


def test_hata_gecici_ve_kalici() -> None:
    assert hata_gecici_mi("Connection timeout") is True
    assert hata_gecici_mi("rate limit exceeded") is True
    assert hata_gecici_mi("SkillYoneticisi yok", veri={"code": "AUT_0041"}) is False
    assert hata_gecici_mi("desteklenmiyor") is False
    assert hata_gecici_mi("bilinmeyen hata") is False


def test_devam_ve_tamamlandi() -> None:
    plan = gorev_plani_olustur(
        "iki adim",
        adimlar=[
            plan_adimi_olustur("A", arac_adi="hava", komut="hava"),
            plan_adimi_olustur("B", arac_adi="hava", komut="hava"),
        ],
        baglam=AjanBaglam(dry_run=True, onay_coklu=True),
    )
    motor = karar_motoru_olustur()
    karar = motor.degerlendir(plan)
    assert karar.aksiyon is KararAksiyonu.DEVAM
    assert karar.bitti is False

    plan.adimlar[0].durum = PlanAdimDurumu.BASARILI
    plan.adimlar[1].durum = PlanAdimDurumu.BASARILI
    plan.durum = GorevDurumu.TAMAMLANDI
    karar2 = motor.degerlendir(plan)
    assert karar2.aksiyon is KararAksiyonu.DEVAM
    assert karar2.bitti is True


def test_onay_ask_user_ve_onaylandi_devam() -> None:
    plan = gorev_plani_olustur(
        "tehlikeli",
        adimlar=[
            plan_adimi_olustur(
                "Git",
                arac_adi="terminal",
                komut="git init",
                tehlikeli=True,
            ),
            plan_adimi_olustur("README", arac_adi="dosya_islemleri", komut="yaz"),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=True),
    )
    motor = KararMotoru()
    karar = motor.degerlendir(plan, onaylandi=False)
    assert karar.aksiyon is KararAksiyonu.KULLANICIYA_SOR
    assert karar.onay_gerekli is True

    plan2, karar2 = motor.degerlendir_ve_uygula(plan, onaylandi=False)
    assert plan2.durum is GorevDurumu.ONAY_BEKLIYOR
    assert karar2.aksiyon is KararAksiyonu.KULLANICIYA_SOR

    karar3 = motor.degerlendir(plan2, onaylandi=True)
    assert karar3.aksiyon is KararAksiyonu.DEVAM
    motor.uygula(plan2, karar3, onaylandi=True)
    assert plan2.durum is GorevDurumu.HAZIR
    assert all(
        a.durum is not PlanAdimDurumu.ONAY_BEKLIYOR for a in plan2.adimlar
    )


def test_retry_gecici_hata() -> None:
    plan = gorev_plani_olustur(
        "retry",
        adimlar=[
            plan_adimi_olustur("A", arac_adi="web_arama", komut="ara"),
            plan_adimi_olustur("B", arac_adi="hava", komut="hava"),
        ],
        baglam=AjanBaglam(dry_run=True),
    )
    adim = plan.adimlar[0]
    adim.durum = PlanAdimDurumu.BASARISIZ
    adim.hata = "timeout while connecting"
    plan.durum = GorevDurumu.BASARISIZ

    motor = karar_motoru_olustur(max_retry=2)
    karar = motor.degerlendir(
        plan,
        adim=adim,
        sonuc=YetenekSonucu.hata("temporary timeout", veri={"code": "TMP"}),
    )
    assert karar.aksiyon is KararAksiyonu.YENIDEN_DENE
    assert karar.deneme == 0

    motor.uygula(plan, karar)
    assert adim.durum is PlanAdimDurumu.BEKLIYOR
    assert adim.meta["retry_count"] == 1
    assert plan.durum is GorevDurumu.HAZIR


def test_retry_siniri_abort() -> None:
    plan = gorev_plani_olustur(
        "abort",
        adimlar=[plan_adimi_olustur("A", arac_adi="web_arama", komut="ara")],
        baglam=AjanBaglam(dry_run=True),
    )
    adim = plan.adimlar[0]
    adim.durum = PlanAdimDurumu.BASARISIZ
    adim.meta["retry_count"] = 2
    adim.hata = "timeout"
    plan.durum = GorevDurumu.BASARISIZ

    motor = KararMotoru(max_retry=2)
    karar = motor.degerlendir(plan, adim=adim)
    assert karar.aksiyon is KararAksiyonu.IPTAL
    assert karar.bitti is True

    motor.uygula(plan, karar)
    assert plan.durum is GorevDurumu.IPTAL
    assert adim.durum is PlanAdimDurumu.IPTAL


def test_kalici_hata_ve_desteklenmiyor() -> None:
    plan = gorev_plani_olustur(
        "kalici",
        adimlar=[
            plan_adimi_olustur("A", arac_adi="hava", komut="hava"),
            plan_adimi_olustur("B", arac_adi="hava", komut="hava"),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=False),
    )
    adim = plan.adimlar[0]
    adim.durum = PlanAdimDurumu.BASARISIZ
    plan.durum = GorevDurumu.BASARISIZ

    motor = KararMotoru(max_retry=3)
    karar = motor.degerlendir(
        plan,
        adim=adim,
        sonuc=YetenekSonucu.hata(
            "SkillYoneticisi yok",
            veri={"code": "AUT_0041"},
        ),
    )
    assert karar.aksiyon is KararAksiyonu.IPTAL

    adim2 = plan.adimlar[1]
    adim2.durum = PlanAdimDurumu.BASARISIZ
    karar2 = motor.degerlendir(
        plan,
        adim=adim2,
        sonuc=YetenekSonucu(
            durum=YetenekDurumu.DESTEKLENMIYOR,
            mesaj="plugin yok",
        ),
    )
    assert karar2.aksiyon is KararAksiyonu.IPTAL


def test_karar_sonucu_serilestirme_ve_gecersiz_plan() -> None:
    ks = KararSonucu(
        aksiyon=KararAksiyonu.DEVAM,
        neden="ok",
        adim_indeks=0,
        bitti=False,
    )
    geri = KararSonucu.from_dict(ks.to_dict())
    assert geri.aksiyon is KararAksiyonu.DEVAM
    assert geri.adim_indeks == 0

    motor = KararMotoru()
    try:
        motor.degerlendir("x")  # type: ignore[arg-type]
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0046"

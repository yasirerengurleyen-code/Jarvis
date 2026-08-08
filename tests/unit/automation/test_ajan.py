"""automation/agents/ajan.py birim testleri (offline / dry_run)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.ajan import (
    AjanSonucu,
    AkilliAjan,
    akilli_ajan_olustur,
)
from automation.agents.karar import KararAksiyonu
from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    GorevDurumu,
    PlanAdimDurumu,
    gorev_plani_olustur,
    plan_adimi_olustur,
)
from core.base import YetenekSonucu
from core.events import OLAY_AJAN_PLAN, EventBus


class _SahteSkillYoneticisi:
    """Async skill yöneticisi stub (offline)."""

    def __init__(self, *, basarisiz: Optional[str] = None, gecici: bool = False) -> None:
        self.basarisiz = basarisiz
        self.gecici = gecici
        self.cagrilar: list[dict[str, Any]] = []

    async def calistir(
        self,
        komut: str,
        *,
        skill_adi: Optional[str] = None,
        baglam: Any = None,
        **kwargs: Any,
    ) -> YetenekSonucu:
        self.cagrilar.append(
            {
                "komut": komut,
                "skill_adi": skill_adi,
                "onaylandi": bool(
                    getattr(baglam, "onaylandi", False) or kwargs.get("onaylandi")
                ),
            }
        )
        if self.basarisiz and skill_adi == self.basarisiz:
            if self.gecici:
                return YetenekSonucu.hata(
                    "connection timeout",
                    yetenek=skill_adi,
                    veri={"code": "TMP_001"},
                )
            return YetenekSonucu.hata("kalici hata", yetenek=skill_adi)
        return YetenekSonucu.ok(f"ok:{skill_adi}", yetenek=skill_adi)


def test_dry_run_python_projesi_tamamlanir() -> None:
    ajan = akilli_ajan_olustur(olay_yayinla=False)
    sonuc = ajan.calistir_senkron(
        "Yeni Python projesi oluştur demo_app",
        baglam=AjanBaglam(dry_run=True, onay_coklu=True, max_adim=12),
    )

    assert isinstance(sonuc, AjanSonucu)
    assert sonuc.dry_run is True
    assert sonuc.bitti is True
    assert sonuc.plan.durum is GorevDurumu.TAMAMLANDI
    assert all(a.durum is PlanAdimDurumu.BASARILI for a in sonuc.plan.adimlar)
    assert sonuc.plan.adim_sayisi == 5
    assert sonuc.karar is not None
    assert sonuc.karar.aksiyon is KararAksiyonu.DEVAM
    assert sonuc.karar.bitti is True
    assert sonuc.to_dict()["done"] is True
    # Araç seçimi uygulanmış olmalı
    assert all(str(a.arac_adi).strip() for a in sonuc.plan.adimlar)


def test_bos_hedef_hata() -> None:
    ajan = AkilliAjan(olay_yayinla=False)
    try:
        ajan.calistir_senkron("   ")
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0048"


def test_planla_sadece_arac_secer() -> None:
    ajan = akilli_ajan_olustur(olay_yayinla=False)
    plan = ajan.planla(
        "hava durumu istanbul",
        baglam=AjanBaglam(dry_run=True),
        arac_sec=True,
    )
    assert plan.durum is GorevDurumu.HAZIR
    assert plan.adimlar
    # generic şablon + araç seçimi → hava
    assert plan.adimlar[0].arac_adi == "hava"
    assert plan.meta.get("tool_selector") is not None


def test_onay_kapisi_dry_run_degil() -> None:
    ajan = akilli_ajan_olustur(olay_yayinla=False)
    sonuc = ajan.calistir_senkron(
        "Yeni Python projesi oluştur onay_test",
        baglam=AjanBaglam(dry_run=False, onay_coklu=True),
        onaylandi=False,
    )
    assert sonuc.onay_bekliyor is True
    assert sonuc.plan.durum is GorevDurumu.ONAY_BEKLIYOR
    assert sonuc.karar is not None
    assert sonuc.karar.aksiyon is KararAksiyonu.KULLANICIYA_SOR


def test_devam_et_onay_sonrasi() -> None:
    skills = _SahteSkillYoneticisi()
    ajan = akilli_ajan_olustur(skill_yoneticisi=skills, olay_yayinla=False)
    sonuc = ajan.calistir_senkron(
        "Yeni Python projesi oluştur onay_devam",
        baglam=AjanBaglam(dry_run=False, onay_coklu=True),
        onaylandi=False,
    )
    assert sonuc.plan.durum is GorevDurumu.ONAY_BEKLIYOR

    import asyncio

    sonuc2 = asyncio.run(
        ajan.devam_et(sonuc.plan, onaylandi=True, dry_run=False)
    )
    assert sonuc2.plan.durum is GorevDurumu.TAMAMLANDI
    assert sonuc2.bitti is True
    assert len(skills.cagrilar) >= 1


def test_retry_gecici_hata() -> None:
    skills = _SahteSkillYoneticisi(basarisiz="web_arama", gecici=True)
    # İlk çağrıda fail; retry sonrası da fail olacak ama retry aksiyonu görülmeli
    # retry_count artınca abort — max_retry=1 ile tek retry
    plan = gorev_plani_olustur(
        "web ara",
        adimlar=[
            plan_adimi_olustur("Ara", arac_adi="web_arama", komut="python ara"),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=False),
    )
    ajan = akilli_ajan_olustur(
        skill_yoneticisi=skills,
        olay_yayinla=False,
        max_retry=1,
    )
    sonuc = ajan.plan_calistir_senkron(plan, onaylandi=True, dry_run=False)
    # Geçici hata → en az bir retry denemesi
    assert any(k.aksiyon is KararAksiyonu.YENIDEN_DENE for k in sonuc.kararlar)
    assert sonuc.plan.durum in {GorevDurumu.IPTAL, GorevDurumu.BASARISIZ}
    assert len(skills.cagrilar) >= 2


def test_olay_yayinlanir() -> None:
    bus = EventBus(ad="test-ajan")
    olaylar: list[str] = []

    def _dinle(event: Any) -> None:
        olaylar.append(str(event.veri.get("agent_phase") or event.veri.get("status")))

    bus.subscribe(OLAY_AJAN_PLAN, _dinle)
    ajan = akilli_ajan_olustur(bus=bus, olay_yayinla=True)
    ajan.calistir_senkron(
        "git init",
        baglam=AjanBaglam(dry_run=True, onay_coklu=False),
    )
    assert olaylar  # en az bir yayın

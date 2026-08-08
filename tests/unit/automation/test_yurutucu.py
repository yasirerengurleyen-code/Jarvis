"""automation/agents/yurutucu.py birim testleri (offline / dry_run)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.arac_secici import arac_secici_olustur
from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    AracTuru,
    GorevDurumu,
    PlanAdimDurumu,
    gorev_plani_olustur,
    plan_adimi_olustur,
)
from automation.agents.planlayici import GorevPlanlayici
from automation.agents.yurutucu import GorevYurutucu, gorev_yurutucu_olustur
from core.base import YetenekDurumu, YetenekSonucu
from core.events import OLAY_AJAN_PLAN, EventBus


class _SahteSkillYoneticisi:
    """Async skill yöneticisi stub (offline)."""

    def __init__(self, *, basarisiz: Optional[str] = None) -> None:
        self.basarisiz = basarisiz
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
                "kwargs": dict(kwargs),
                "onaylandi": bool(
                    getattr(baglam, "onaylandi", False) or kwargs.get("onaylandi")
                ),
            }
        )
        if self.basarisiz and skill_adi == self.basarisiz:
            return YetenekSonucu.hata("sahte hata", yetenek=skill_adi)
        return YetenekSonucu.ok(
            f"ok:{skill_adi}",
            yetenek=skill_adi,
            veri={"komut": komut},
        )


def test_dry_run_python_plani_tamamlanir() -> None:
    planci = GorevPlanlayici(olay_yayinla=False)
    plan = planci.planla(
        "Yeni Python projesi oluştur demo_app",
        baglam=AjanBaglam(dry_run=True, onay_coklu=True, max_adim=12),
    )
    yurutucu = gorev_yurutucu_olustur(
        arac_secici=arac_secici_olustur(),
        olay_yayinla=False,
    )
    sonuc = yurutucu.yurut_senkron(plan)

    assert sonuc.durum is GorevDurumu.TAMAMLANDI
    assert all(a.durum is PlanAdimDurumu.BASARILI for a in sonuc.adimlar)
    assert sonuc.meta["executor"]["dry_run"] is True
    assert sonuc.meta["executor"]["succeeded"] == 5
    assert sonuc.adimlar[0].sonuc is not None
    assert sonuc.adimlar[0].sonuc.get("data", {}).get("dry_run") is True


def test_onay_kapisi_dry_run_degil() -> None:
    plan = gorev_plani_olustur(
        "git init",
        adimlar=[
            plan_adimi_olustur(
                "Git başlat",
                arac_adi="terminal",
                komut="git init",
                tehlikeli=True,
            ),
            plan_adimi_olustur(
                "README",
                arac_adi="dosya_islemleri",
                komut="yaz README",
            ),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=True),
    )
    yurutucu = GorevYurutucu(olay_yayinla=False)
    sonuc = yurutucu.yurut_senkron(plan, onaylandi=False)

    assert sonuc.durum is GorevDurumu.ONAY_BEKLIYOR
    assert sonuc.meta["executor"]["phase"] == "awaiting_confirmation"
    assert any(a.durum is PlanAdimDurumu.ONAY_BEKLIYOR for a in sonuc.adimlar)


def test_devam_et_onay_sonrasi() -> None:
    plan = gorev_plani_olustur(
        "iki adim",
        adimlar=[
            plan_adimi_olustur("A", arac_adi="hava", komut="hava"),
            plan_adimi_olustur(
                "B",
                arac_adi="terminal",
                komut="dir",
                tehlikeli=True,
            ),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=True),
    )
    skills = _SahteSkillYoneticisi()
    yurutucu = GorevYurutucu(skill_yoneticisi=skills, olay_yayinla=False)

    bekleyen = yurutucu.yurut_senkron(plan, onaylandi=False)
    assert bekleyen.durum is GorevDurumu.ONAY_BEKLIYOR

    async def _devam() -> None:
        biten = await yurutucu.devam_et(bekleyen, onaylandi=True)
        assert biten.durum is GorevDurumu.TAMAMLANDI
        assert len(skills.cagrilar) == 2

    asyncio.run(_devam())


def test_skill_yoneticisi_ile_gercek_yurutme() -> None:
    plan = gorev_plani_olustur(
        "hava",
        adimlar=[
            plan_adimi_olustur(
                "Hava sor",
                arac_adi="hava",
                komut="istanbul hava",
                args={"sehir": "istanbul"},
            )
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=False),
    )
    skills = _SahteSkillYoneticisi()
    yurutucu = gorev_yurutucu_olustur(skill_yoneticisi=skills, olay_yayinla=False)
    sonuc = yurutucu.yurut_senkron(plan, onaylandi=True)

    assert sonuc.durum is GorevDurumu.TAMAMLANDI
    assert len(skills.cagrilar) == 1
    assert skills.cagrilar[0]["skill_adi"] == "hava"


def test_skill_yok_hatasi_ve_dur_hatada() -> None:
    plan = gorev_plani_olustur(
        "x",
        adimlar=[
            plan_adimi_olustur("A", arac_adi="hava", komut="hava"),
            plan_adimi_olustur("B", arac_adi="terminal", komut="dir"),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=False),
    )
    yurutucu = GorevYurutucu(skill_yoneticisi=None, olay_yayinla=False)
    sonuc = yurutucu.yurut_senkron(plan, onaylandi=True, dur_hatada=True)

    assert sonuc.durum is GorevDurumu.BASARISIZ
    assert sonuc.adimlar[0].durum is PlanAdimDurumu.BASARISIZ
    assert "AUT_0041" in str(sonuc.adimlar[0].sonuc)
    assert sonuc.adimlar[1].durum is PlanAdimDurumu.BEKLIYOR


def test_plugin_ve_builtin() -> None:
    plan = gorev_plani_olustur(
        "karisik",
        adimlar=[
            plan_adimi_olustur(
                "Builtin",
                arac_turu=AracTuru.BUILTIN,
                komut="noop",
            ),
            plan_adimi_olustur(
                "Plugin",
                arac_adi="demo",
                arac_turu=AracTuru.PLUGIN,
                komut="demo.run",
            ),
        ],
        baglam=AjanBaglam(dry_run=False, onay_coklu=False),
    )
    yurutucu = GorevYurutucu(olay_yayinla=False)
    # dur_hatada=False → plugin DESTEKLENMIYOR sonrası devam (builtin OK, plugin fail)
    sonuc = yurutucu.yurut_senkron(plan, onaylandi=True, dur_hatada=False)

    assert sonuc.adimlar[0].durum is PlanAdimDurumu.BASARILI
    assert sonuc.adimlar[1].durum is PlanAdimDurumu.BASARISIZ
    assert sonuc.adimlar[1].sonuc is not None
    assert sonuc.adimlar[1].sonuc.get("status") == YetenekDurumu.DESTEKLENMIYOR.value


def test_olay_yayini_ve_gecersiz_plan() -> None:
    bus = EventBus()
    alinan: list[dict[str, Any]] = []

    def _dinle(event: Any) -> None:
        alinan.append(dict(event.veri or {}))

    bus.subscribe(OLAY_AJAN_PLAN, _dinle)

    planci = GorevPlanlayici(olay_yayinla=False)
    plan = planci.planla("hava durumu", dry_run=True)
    yurutucu = GorevYurutucu(bus=bus, olay_yayinla=True)
    yurutucu.yurut_senkron(plan)

    assert any(x.get("executor_phase") == "completed" for x in alinan)

    try:
        yurutucu.yurut_senkron("x")  # type: ignore[arg-type]
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0039"

    bitmis = gorev_plani_olustur(
        "bitmis",
        adimlar=[plan_adimi_olustur("A", arac_adi="hava")],
        baglam=AjanBaglam(dry_run=True),
    )
    bitmis.durum = GorevDurumu.TAMAMLANDI
    try:
        yurutucu.yurut_senkron(bitmis)
        raise AssertionError("AjanHata beklenirdi")
    except AjanHata as exc:
        assert exc.kod == "AUT_0040"

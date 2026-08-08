"""automation/yoneticisi.py birim testleri (offline / dry_run)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from automation.agents.ajan import AkilliAjan, AjanSonucu
from automation.agents.karar import KararAksiyonu
from automation.agents.modeller import AjanHata, GorevDurumu, PlanAdimDurumu
from automation.yoneticisi import (
    AutomationYoneticisi,
    automation_yoneticisi_olustur,
)
from core.base import ModulTabani, YetenekSonucu
from core.events import EventBus


class _SahteSkillYoneticisi:
    """Async skill yöneticisi stub (offline)."""

    def __init__(self) -> None:
        self.cagrilar: list[dict[str, Any]] = []
        self.adet = 1

    def al(self, ad: str) -> Any:
        return object() if ad else None

    def sec(self, komut: str) -> Any:
        return None

    def ozet(self) -> dict[str, Any]:
        return {"count": self.adet, "skills": []}

    async def calistir(
        self,
        komut: str,
        *,
        skill_adi: Optional[str] = None,
        baglam: Any = None,
        **kwargs: Any,
    ) -> YetenekSonucu:
        self.cagrilar.append(
            {"komut": komut, "skill_adi": skill_adi, "onaylandi": kwargs.get("onaylandi")}
        )
        return YetenekSonucu.ok(f"ok:{skill_adi}", yetenek=skill_adi)


def _yonetici(*, skills: Any = None) -> AutomationYoneticisi:
    bus = EventBus(ad="test.automation")
    return AutomationYoneticisi(
        bus=bus,
        dry_run=True,
        skill_yoneticisi=skills,
        olustur=True,
        olay_yayinla=False,
    )


def test_modul_tabani_ve_fabrika() -> None:
    m = automation_yoneticisi_olustur(dry_run=True, olay_yayinla=False)
    assert isinstance(m, AutomationYoneticisi)
    assert isinstance(m, ModulTabani)
    assert m.ad == "automation"
    assert m.motor == "dry_run"
    assert isinstance(m.ajan, AkilliAjan)
    assert m.calisiyor is False


def test_dry_run_baslat_durdur_ozet() -> None:
    async def _run() -> None:
        m = _yonetici()
        assert m.motor == "dry_run"
        assert m.ajan is not None

        await m.baslat()
        assert m.calisiyor

        ozet = m.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["agent_bound"] is True
        assert ozet["enabled"] is True
        assert ozet["smart_agent"] is True
        assert ozet["max_plan_steps"] >= 1
        assert ozet["confirm_multi_step"] is True
        assert ozet["skills"]["bound"] is False
        assert ozet["last_result"] is None

        await m.durdur()
        assert not m.calisiyor

    asyncio.run(_run())


def test_baslamadan_calistir_hata() -> None:
    async def _run() -> None:
        m = _yonetici()
        try:
            await m.calistir("Yeni Python projesi oluştur")
            raise AssertionError("AjanHata beklenirdi")
        except AjanHata as exc:
            assert exc.kod == "AUT_0051"

    asyncio.run(_run())


def test_dry_run_python_projesi_calistir() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            sonuc = await m.calistir(
                "Yeni Python projesi oluştur demo_app",
                onaylandi=False,
            )
            assert isinstance(sonuc, AjanSonucu)
            assert sonuc.dry_run is True
            assert sonuc.bitti is True
            assert sonuc.plan.durum is GorevDurumu.TAMAMLANDI
            assert all(a.durum is PlanAdimDurumu.BASARILI for a in sonuc.plan.adimlar)
            assert sonuc.plan.adim_sayisi == 5
            assert sonuc.karar is not None
            assert sonuc.karar.aksiyon is KararAksiyonu.DEVAM

            ozet = m.ozet()
            assert ozet["last_result"] is not None
            assert ozet["last_result"]["done"] is True
            assert ozet["last_result"]["steps"] == 5
            assert m.son_sonuc is sonuc
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_planla_ve_senkron() -> None:
    async def _planla() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            plan = m.planla("hava durumu istanbul")
            assert plan.adim_sayisi >= 1
            assert all(str(a.arac_adi).strip() for a in plan.adimlar)
            sonuc = await m.calistir("hava durumu ankara")
            assert sonuc.bitti is True
            assert sonuc.dry_run is True
        finally:
            await m.durdur()

    asyncio.run(_planla())

    # Senkron API ayrı event loop'ta (iç içe asyncio.run yok)
    m2 = _yonetici()

    async def _baslat() -> None:
        await m2.baslat()

    asyncio.run(_baslat())
    try:
        sonuc = m2.calistir_senkron("hava durumu izmir")
        assert sonuc.bitti is True
        assert sonuc.dry_run is True
    finally:
        asyncio.run(m2.durdur())


def test_skills_bagla_kancasi() -> None:
    async def _run() -> None:
        skills = _SahteSkillYoneticisi()
        m = _yonetici(skills=skills)
        await m.baslat()
        try:
            assert m.skills is skills
            assert m.ajan is not None
            assert m.ajan.skills is skills
            assert m.ajan.arac_secici.skills is skills
            assert m.ajan.yurutucu.skills is skills

            ozet = m.ozet()
            assert ozet["skills"]["bound"] is True
            assert ozet["skills"]["count"] == 1

            # Yeniden bağlama
            skills2 = _SahteSkillYoneticisi()
            skills2.adet = 3
            m.skills_bagla(skills2)
            assert m.ajan.skills is skills2
            assert m.ozet()["skills"]["count"] == 3
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_skilllerden_fabrika() -> None:
    skills = _SahteSkillYoneticisi()
    m = AutomationYoneticisi.skilllerden(
        skills,
        dry_run=True,
        olay_yayinla=False,
    )
    assert m.skills is skills
    assert m.motor == "dry_run"
    assert isinstance(m.ajan, AkilliAjan)
    assert m.ajan.skills is skills


def test_kapali_config_dry_run_izin() -> None:
    """enabled=false olsa bile dry_run ile başlayabilmeli."""

    class _KapaliAyar:
        yuklendi = True

        def al(self, anahtar: str, varsayilan: Any = None) -> Any:
            if anahtar == "automation.enabled":
                return False
            if anahtar == "automation.smart_agent":
                return True
            if anahtar == "automation.max_plan_steps":
                return 8
            if anahtar == "automation.confirm_multi_step":
                return True
            return varsayilan

        def yukle(self) -> None:
            return None

    async def _run() -> None:
        m = AutomationYoneticisi(
            ayarlar=_KapaliAyar(),  # type: ignore[arg-type]
            dry_run=True,
            olay_yayinla=False,
        )
        await m.baslat()
        assert m.calisiyor
        assert m.enabled is False
        assert m.max_plan_steps == 8
        await m.durdur()

        m2 = AutomationYoneticisi(
            ayarlar=_KapaliAyar(),  # type: ignore[arg-type]
            dry_run=False,
            zorla_sahte=False,
            olay_yayinla=False,
        )
        try:
            await m2.baslat()
            raise AssertionError("AjanHata beklenirdi")
        except AjanHata as exc:
            assert exc.kod == "AUT_0050"

    asyncio.run(_run())


if __name__ == "__main__":
    test_modul_tabani_ve_fabrika()
    test_dry_run_baslat_durdur_ozet()
    test_baslamadan_calistir_hata()
    test_dry_run_python_projesi_calistir()
    test_planla_ve_senkron()
    test_skills_bagla_kancasi()
    test_skilllerden_fabrika()
    test_kapali_config_dry_run_izin()
    print("TEST_OK")

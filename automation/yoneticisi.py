"""
automation/yoneticisi.py
------------------------
Automation Manager — akıllı ajan orkestrasyon facade'ı.

Görev:
- AkilliAjan yaşam döngüsünü (start/stop) yönetmek
- planla / calistir / devam_et API'sini dışarıya açmak
- dry_run / sahte modda ağ veya LLM olmadan test edilebilmek
- İsteğe bağlı SkillYoneticisi kancası (skills_bagla)

Not: Engine yaşam döngüsü `core/engine.py` üzerinden bağlanır
(`engine.automation`); bu sınıf Automation runtime facade'ıdır.
"""

from __future__ import annotations

from typing import Any, Optional

from automation.agents.ajan import (
    AjanSonucu,
    AkilliAjan,
    akilli_ajan_olustur,
)
from automation.agents.modeller import (
    VARSAYILAN_MAX_ADIM,
    AjanBaglam,
    AjanHata,
    GorevPlani,
    max_adim_siniri,
)
from automation.agents.planlayici import PlanModuGirdi
from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.logger import audit_yaz, logger_al

log = logger_al("automation.yoneticisi")


class AutomationYoneticisi(ModulTabani):
    """
    J.A.R.V.I.S. otomasyon yöneticisi (host tarafı facade).

    Alt bileşen:
      ajan (AkilliAjan) ← isteğe bağlı skills (SkillYoneticisi)
    """

    ad = "automation"
    surum = "0.1.0"
    aciklama = "Automation Manager — akıllı ajan / görev orkestrasyonu"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        ajan: Optional[AkilliAjan] = None,
        skill_yoneticisi: Any = None,
        olustur: bool = True,
        olay_yayinla: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)

        self.enabled = bool(self.ayarlar.al("automation.enabled", True))
        self.smart_agent = bool(self.ayarlar.al("automation.smart_agent", True))
        self.max_plan_steps = max_adim_siniri(
            self.ayarlar.al("automation.max_plan_steps", VARSAYILAN_MAX_ADIM),
            varsayilan=VARSAYILAN_MAX_ADIM,
        )
        self.confirm_multi_step = bool(
            self.ayarlar.al("automation.confirm_multi_step", True)
        )

        self.skills = skill_yoneticisi
        self.ajan = ajan

        if olustur and self.ajan is None:
            self.ajan = akilli_ajan_olustur(
                skill_yoneticisi=self.skills,
                bus=self.bus,
                ayar_yonetici=self.ayarlar,
                olay_yayinla=self.olay_yayinla,
            )
        elif self.ajan is not None and self.skills is not None:
            self.skills_bagla(self.skills)

        self._motor = self._motor_sec()
        self._son_sonuc: Optional[AjanSonucu] = None

    # ------------------------------------------------------------------ fabrika

    @classmethod
    def skilllerden(
        cls,
        skill_yoneticisi: Any,
        *,
        bus: Optional[EventBus] = None,
        dry_run: Optional[bool] = None,
        zorla_sahte: Optional[bool] = None,
        ayarlar: Optional[Ayarlar] = None,
        olay_yayinla: bool = True,
    ) -> AutomationYoneticisi:
        """
        SkillYoneticisi üzerinden AutomationYoneticisi üretir.

        dry_run verilmezse True (güvenli varsayılan).
        """
        dry = True if dry_run is None else bool(dry_run)
        sahte = bool(zorla_sahte) if zorla_sahte is not None else False
        ayar = ayarlar or getattr(skill_yoneticisi, "ayarlar", None)
        return cls(
            ayarlar=ayar,
            bus=bus or getattr(skill_yoneticisi, "bus", None),
            dry_run=dry,
            zorla_sahte=sahte,
            skill_yoneticisi=skill_yoneticisi,
            olustur=True,
            olay_yayinla=olay_yayinla,
        )

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — test / bellek ayarları
                pass

        # Config yenile (yükleme sonrası)
        self.enabled = bool(self.ayarlar.al("automation.enabled", True))
        self.smart_agent = bool(self.ayarlar.al("automation.smart_agent", True))
        self.max_plan_steps = max_adim_siniri(
            self.ayarlar.al("automation.max_plan_steps", VARSAYILAN_MAX_ADIM),
            varsayilan=VARSAYILAN_MAX_ADIM,
        )
        self.confirm_multi_step = bool(
            self.ayarlar.al("automation.confirm_multi_step", True)
        )

        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise AjanHata(
                "Automation config ile kapali (automation.enabled=false)",
                kod="AUT_0050",
                modul=self.ad,
            )

        if self.ajan is None:
            raise AjanHata(
                "Akilli ajan bagli degil",
                kod="AUT_0052",
                modul=self.ad,
            )

        self._motor = self._motor_sec()

        # Skills yaşam döngüsü Engine'e aittir; burada yalnızca kanca
        if self.skills is not None:
            self.skills_bagla(self.skills)

        self._isaret_basladi()
        audit_yaz(
            "automation.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "smart_agent": self.smart_agent,
                "max_plan_steps": self.max_plan_steps,
                "confirm_multi_step": self.confirm_multi_step,
                "skills_bound": self.skills is not None,
                "dry_run": self.dry_run,
            },
        )
        log.info(
            "Automation Manager hazir (motor=%s, smart=%s, max_steps=%s)",
            self._motor,
            self.smart_agent,
            self.max_plan_steps,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return

        self._isaret_durdu()
        audit_yaz(
            "automation.stopped",
            modul=self.ad,
            detay={"engine": self._motor},
        )
        log.info("Automation Manager durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ özellikler

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def son_sonuc(self) -> Optional[AjanSonucu]:
        """Son çalıştırma özeti (yoksa None)."""
        return self._son_sonuc

    def skills_bagla(self, skill_yoneticisi: Any) -> None:
        """
        SkillYoneticisi kancasını ajan alt bileşenlerine bağlar.

        Döngüsel import yok: duck-typing (al / sec / calistir).
        """
        self.skills = skill_yoneticisi
        ajan = self.ajan
        if ajan is None:
            return
        ajan.skills = skill_yoneticisi
        if getattr(ajan, "arac_secici", None) is not None:
            ajan.arac_secici.skills = skill_yoneticisi
        if getattr(ajan, "yurutucu", None) is not None:
            ajan.yurutucu.skills = skill_yoneticisi
        log.debug("Automation kancalari Skill Manager'a baglandi")

    def ajan_bagla(self, ajan: AkilliAjan) -> None:
        """Dışarıdan AkilliAjan örneği bağlar / değiştirir."""
        self.ajan = ajan
        if self.skills is not None:
            self.skills_bagla(self.skills)

    # ------------------------------------------------------------------ ajan facade

    def varsayilan_baglam(
        self,
        *,
        dry_run: Optional[bool] = None,
        onay_coklu: Optional[bool] = None,
        max_adim: Optional[int] = None,
        kullanici_id: Optional[str] = None,
        proje_kok: Optional[str] = None,
        ekstra: Optional[dict[str, Any]] = None,
    ) -> AjanBaglam:
        """Config + manager bayraklarından AjanBaglam üretir."""
        dry = self.dry_run if dry_run is None else bool(dry_run)
        # dry_run / sahte motor: güvenli varsayılan True
        if dry_run is None and self._motor in {"dry_run", "sahte"}:
            dry = True
        return AjanBaglam(
            kullanici_id=kullanici_id,
            proje_kok=proje_kok
            or self.ayarlar.al("automation.default_project_root", None),
            dry_run=dry,
            onay_coklu=(
                self.confirm_multi_step if onay_coklu is None else bool(onay_coklu)
            ),
            max_adim=max_adim_siniri(
                self.max_plan_steps if max_adim is None else max_adim,
                varsayilan=self.max_plan_steps,
            ),
            ekstra=dict(ekstra or {}),
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
        arac_sec: bool = True,
    ) -> GorevPlani:
        """Hedef için plan üretir (yürütmez)."""
        self._calisiyor_mi()
        ajan = self._ajan_gerekli()
        return ajan.planla(
            hedef,
            baglam=baglam or self.varsayilan_baglam(dry_run=dry_run),
            mod=mod,
            dry_run=dry_run if dry_run is not None else None,
            meta=meta,
            yayinla=yayinla,
            arac_sec=arac_sec,
        )

    async def calistir(
        self,
        hedef: str,
        *,
        baglam: Optional[AjanBaglam] = None,
        mod: Optional[PlanModuGirdi] = None,
        dry_run: Optional[bool] = None,
        onaylandi: bool = False,
        arac_sec: bool = True,
        dur_hatada: bool = True,
        max_retry: Optional[int] = None,
        meta: Optional[dict[str, Any]] = None,
        yayinla: Optional[bool] = None,
    ) -> AjanSonucu:
        """Tam ajan döngüsü: planla → araç seç → yürüt → karar."""
        self._calisiyor_mi()
        ajan = self._ajan_gerekli()
        kullanilan_dry = self._dry_run_coz(dry_run)
        sonuc = await ajan.calistir(
            hedef,
            baglam=baglam or self.varsayilan_baglam(dry_run=kullanilan_dry),
            mod=mod,
            dry_run=kullanilan_dry,
            onaylandi=onaylandi,
            arac_sec=arac_sec,
            dur_hatada=dur_hatada,
            max_retry=max_retry,
            meta=meta,
            yayinla=yayinla,
        )
        self._son_sonuc = sonuc
        return sonuc

    async def plan_calistir(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool = False,
        dry_run: Optional[bool] = None,
        arac_sec: bool = True,
        dur_hatada: bool = True,
        max_retry: Optional[int] = None,
        yayinla: Optional[bool] = None,
    ) -> AjanSonucu:
        """Mevcut GorevPlani üzerinde yürüt → karar döngüsü."""
        self._calisiyor_mi()
        ajan = self._ajan_gerekli()
        sonuc = await ajan.plan_calistir(
            plan,
            onaylandi=onaylandi,
            dry_run=self._dry_run_coz(dry_run),
            arac_sec=arac_sec,
            dur_hatada=dur_hatada,
            max_retry=max_retry,
            yayinla=yayinla,
        )
        self._son_sonuc = sonuc
        return sonuc

    async def devam_et(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool = True,
        dry_run: Optional[bool] = None,
        dur_hatada: bool = True,
        max_retry: Optional[int] = None,
        yayinla: Optional[bool] = None,
    ) -> AjanSonucu:
        """ONAY_BEKLIYOR durumundan onay ile devam eder."""
        self._calisiyor_mi()
        ajan = self._ajan_gerekli()
        sonuc = await ajan.devam_et(
            plan,
            onaylandi=onaylandi,
            dry_run=self._dry_run_coz(dry_run),
            dur_hatada=dur_hatada,
            max_retry=max_retry,
            yayinla=yayinla,
        )
        self._son_sonuc = sonuc
        return sonuc

    def calistir_senkron(
        self,
        hedef: str,
        *,
        baglam: Optional[AjanBaglam] = None,
        mod: Optional[PlanModuGirdi] = None,
        dry_run: Optional[bool] = None,
        onaylandi: bool = False,
        arac_sec: bool = True,
        dur_hatada: bool = True,
        max_retry: Optional[int] = None,
        meta: Optional[dict[str, Any]] = None,
        yayinla: Optional[bool] = None,
    ) -> AjanSonucu:
        """asyncio.run sarmalayıcısı (senkron test / CLI)."""
        import asyncio

        return asyncio.run(
            self.calistir(
                hedef,
                baglam=baglam,
                mod=mod,
                dry_run=dry_run,
                onaylandi=onaylandi,
                arac_sec=arac_sec,
                dur_hatada=dur_hatada,
                max_retry=max_retry,
                meta=meta,
                yayinla=yayinla,
            )
        )

    def plan_calistir_senkron(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool = False,
        dry_run: Optional[bool] = None,
        arac_sec: bool = True,
        dur_hatada: bool = True,
        max_retry: Optional[int] = None,
        yayinla: Optional[bool] = None,
    ) -> AjanSonucu:
        """Mevcut plan için senkron yürütme."""
        import asyncio

        return asyncio.run(
            self.plan_calistir(
                plan,
                onaylandi=onaylandi,
                dry_run=dry_run,
                arac_sec=arac_sec,
                dur_hatada=dur_hatada,
                max_retry=max_retry,
                yayinla=yayinla,
            )
        )

    # ------------------------------------------------------------------ özet

    def ozet(self) -> dict[str, Any]:
        skills_ozet: dict[str, Any] = {"bound": False}
        if self.skills is not None:
            try:
                if hasattr(self.skills, "ozet"):
                    skills_ozet = dict(self.skills.ozet())
                    skills_ozet["bound"] = True
                else:
                    skills_ozet = {
                        "bound": True,
                        "count": getattr(self.skills, "adet", None),
                    }
            except Exception as exc:  # noqa: BLE001
                skills_ozet = {"bound": True, "error": str(exc)}

        son: Optional[dict[str, Any]] = None
        if self._son_sonuc is not None:
            try:
                son = {
                    "done": self._son_sonuc.bitti,
                    "dry_run": self._son_sonuc.dry_run,
                    "status": self._son_sonuc.plan.durum.value,
                    "steps": self._son_sonuc.plan.adim_sayisi,
                    "plan_id": self._son_sonuc.plan.plan_id,
                }
            except Exception as exc:  # noqa: BLE001
                son = {"error": str(exc)}

        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "smart_agent": self.smart_agent,
            "max_plan_steps": self.max_plan_steps,
            "confirm_multi_step": self.confirm_multi_step,
            "dry_run": self.dry_run,
            "agent_bound": self.ajan is not None,
            "skills": skills_ozet,
            "last_result": son,
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "live"

    def _dry_run_coz(self, dry_run: Optional[bool]) -> bool:
        if dry_run is not None:
            return bool(dry_run)
        if self._motor in {"dry_run", "sahte"}:
            return True
        return bool(self.dry_run)

    def _calisiyor_mi(self) -> None:
        if not self._calisiyor:
            raise AjanHata(
                "Automation Manager calismiyor; once baslat() cagirin",
                kod="AUT_0051",
                modul=self.ad,
            )

    def _ajan_gerekli(self) -> AkilliAjan:
        if self.ajan is None:
            raise AjanHata(
                "Akilli ajan bagli degil",
                kod="AUT_0052",
                modul=self.ad,
            )
        return self.ajan


def automation_yoneticisi_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    skill_yoneticisi: Any = None,
    olay_yayinla: bool = False,
) -> AutomationYoneticisi:
    """Test / demo için hazır AutomationYoneticisi üretir (henüz başlatılmaz)."""
    if skill_yoneticisi is not None:
        return AutomationYoneticisi.skilllerden(
            skill_yoneticisi,
            bus=bus,
            dry_run=dry_run,
            zorla_sahte=zorla_sahte,
            ayarlar=ayarlar,
            olay_yayinla=olay_yayinla,
        )
    return AutomationYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        skill_yoneticisi=None,
        olustur=True,
        olay_yayinla=olay_yayinla,
    )


__all__ = [
    "AutomationYoneticisi",
    "automation_yoneticisi_olustur",
]

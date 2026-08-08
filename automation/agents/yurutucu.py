"""
automation/agents/yurutucu.py
-----------------------------
Görev yürütücü — GorevPlani adımlarını sırayla çalıştırır.

Görev:
- Plan adımlarını sırayla yürütmek (skill / builtin / plugin iskelet)
- dry_run: gerçek yan etki yok; simüle YetenekSonucu
- Tehlikeli adım ve confirm_multi_step için onay kapısı
- SkillYoneticisi entegrasyonu (opsiyonel; yoksa dry_run / builtin)
- Offline birim testlere uygun

Not: Karar / hata düzeltme `karar.py` içinde; bu modül yalnızca yürütme.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from automation.agents.modeller import (
    AjanHata,
    AracTuru,
    GorevDurumu,
    GorevPlani,
    PlanAdimDurumu,
    PlanAdimi,
)
from core.base import YetenekDurumu, YetenekSonucu
from core.events import OLAY_AJAN_PLAN, EventBus, olay_yolu
from core.logger import audit_yaz, logger_al

log = logger_al("automation.agents.yurutucu")


class GorevYurutucu:
    """
    GorevPlani yürütücüsü.

    Varsayılan: dry_run dostu; SkillYoneticisi enjekte edilirse gerçek skill çağrılır.
    """

    def __init__(
        self,
        *,
        skill_yoneticisi: Any = None,
        arac_secici: Any = None,
        bus: Optional[EventBus] = None,
        ayar_yonetici: Any = None,
        olay_yayinla: bool = True,
    ) -> None:
        self.skills = skill_yoneticisi
        self.arac_secici = arac_secici
        self.bus = bus
        self.ayarlar = ayar_yonetici
        self.olay_yayinla = bool(olay_yayinla)

    def _yayinla(self, plan: GorevPlani, *, asamasi: str) -> None:
        if not self.olay_yayinla:
            return
        bus = self.bus or olay_yolu
        try:
            veri = plan.to_dict()
            veri["executor_phase"] = asamasi
            bus.publish_sync(
                OLAY_AJAN_PLAN,
                veri,
                kaynak="automation.yurutucu",
            )
        except Exception as hata:
            log.debug("OLAY_AJAN_PLAN yayinlanamadi: %s", hata)

    def _audit(
        self,
        plan: GorevPlani,
        *,
        asamasi: str,
        onaylandi: bool,
    ) -> None:
        if plan.adim_sayisi > 1 or plan.tehlikeli_mi:
            try:
                audit_yaz(
                    "ajan_yurut",
                    modul="automation.agents.yurutucu",
                    kullanici=plan.baglam.kullanici_id,
                    detay={
                        "plan_id": plan.plan_id,
                        "goal": plan.hedef,
                        "steps": plan.adim_sayisi,
                        "status": plan.durum.value,
                        "dangerous": plan.tehlikeli_mi,
                        "needs_confirmation": plan.onay_gerekli_mi,
                        "dry_run": plan.baglam.dry_run,
                        "approved": bool(onaylandi),
                        "phase": asamasi,
                    },
                )
            except Exception as hata:
                log.debug("audit yazilamadi: %s", hata)

    def _plan_dogrula(self, plan: Any) -> GorevPlani:
        if not isinstance(plan, GorevPlani):
            raise AjanHata(
                "GorevPlani bekleniyor",
                kod="AUT_0039",
                modul="automation.agents",
            )
        if plan.durum in {GorevDurumu.IPTAL, GorevDurumu.TAMAMLANDI}:
            raise AjanHata(
                f"Plan yurutulemez durumda: {plan.durum.value}",
                kod="AUT_0040",
                modul="automation.agents",
                detay={"plan_id": plan.plan_id, "status": plan.durum.value},
            )
        return plan

    def _onay_kapisi(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool,
        adim: Optional[PlanAdimi] = None,
    ) -> Optional[YetenekSonucu]:
        """
        Onay gerekliyse YetenekSonucu.onay_gerekli döner; aksi halde None.

        dry_run: ios/skill kalıbı — tehlikeli adımlar simüle edilir, onay beklenmez.
        """
        if onaylandi:
            return None
        if plan.baglam.dry_run:
            return None

        if adim is not None and adim.tehlikeli:
            return YetenekSonucu.onay_gerekli(
                f"Tehlikeli adim onay bekliyor: {adim.baslik}",
                yetenek=adim.arac_adi or "automation",
                veri={
                    "plan_id": plan.plan_id,
                    "step_id": adim.adim_id,
                    "index": adim.indeks,
                    "dangerous": True,
                    "confirm_multi_step": plan.baglam.onay_coklu,
                },
            )

        # Plan seviyesi: çok adımlı onay veya tehlikeli plan
        if adim is None and plan.onay_gerekli_mi:
            return YetenekSonucu.onay_gerekli(
                "Cok adimli / tehlikeli plan kullanici onayi gerektirir",
                yetenek="automation",
                veri={
                    "plan_id": plan.plan_id,
                    "steps": plan.adim_sayisi,
                    "dangerous": plan.tehlikeli_mi,
                    "confirm_multi_step": plan.baglam.onay_coklu,
                },
            )
        return None

    def _arac_sec_uygula(self, plan: GorevPlani) -> None:
        """İsteğe bağlı AracSecici ile boş araçları doldurur."""
        if self.arac_secici is None:
            return
        try:
            if hasattr(self.arac_secici, "plana_uygula"):
                self.arac_secici.plana_uygula(plan)
        except Exception as hata:
            log.debug("Arac secici uygulanamadi: %s", hata)

    async def _skill_calistir(
        self,
        adim: PlanAdimi,
        plan: GorevPlani,
        *,
        onaylandi: bool,
    ) -> YetenekSonucu:
        """SkillYoneticisi üzerinden adımı çalıştırır."""
        if self.skills is None:
            return YetenekSonucu.hata(
                "SkillYoneticisi yok; gercek yurutme icin enjekte edin veya dry_run kullanin",
                yetenek=adim.arac_adi or None,
                veri={
                    "plan_id": plan.plan_id,
                    "step_id": adim.adim_id,
                    "code": "AUT_0041",
                },
            )

        komut = str(adim.komut or adim.baslik or "").strip()
        kwargs = dict(adim.args or {})
        # SkillBaglam varsa kullan; yoksa kwargs ile onay ilet
        baglam = None
        try:
            from skills.taban import SkillBaglam

            baglam = SkillBaglam(
                kullanici_id=plan.baglam.kullanici_id,
                onaylandi=bool(onaylandi),
                ayar_yonetici=self.ayarlar,
                ekstra={
                    "plan_id": plan.plan_id,
                    "step_id": adim.adim_id,
                    "project_root": plan.baglam.proje_kok,
                    **dict(plan.baglam.ekstra),
                },
            )
        except Exception:
            kwargs["onaylandi"] = bool(onaylandi)

        try:
            return await self.skills.calistir(
                komut,
                skill_adi=adim.arac_adi or None,
                baglam=baglam,
                **kwargs,
            )
        except TypeError:
            # baglam desteklemeyen sahte yöneticiler
            return await self.skills.calistir(
                komut,
                skill_adi=adim.arac_adi or None,
                onaylandi=bool(onaylandi),
                **dict(adim.args or {}),
            )

    def _dry_run_sonuc(self, adim: PlanAdimi, plan: GorevPlani) -> YetenekSonucu:
        """Yan etkisiz simüle sonuç."""
        return YetenekSonucu.ok(
            f"[dry_run] {adim.baslik}",
            yetenek=adim.arac_adi or adim.arac_turu.value,
            veri={
                "dry_run": True,
                "plan_id": plan.plan_id,
                "step_id": adim.adim_id,
                "index": adim.indeks,
                "tool_type": adim.arac_turu.value,
                "tool_name": adim.arac_adi,
                "command": adim.komut,
                "args": dict(adim.args),
            },
        )

    async def adim_calistir(
        self,
        adim: PlanAdimi,
        plan: GorevPlani,
        *,
        onaylandi: bool = False,
    ) -> YetenekSonucu:
        """
        Tek plan adımını çalıştırır (plan durumunu güncellemez; çağıran yönetir).

        dry_run bağlamında skill çağrılmaz.
        """
        if not isinstance(adim, PlanAdimi):
            raise AjanHata(
                "PlanAdimi bekleniyor",
                kod="AUT_0042",
                modul="automation.agents",
            )

        kapı = self._onay_kapisi(plan, onaylandi=onaylandi, adim=adim)
        if kapı is not None:
            return kapı

        if plan.baglam.dry_run:
            return self._dry_run_sonuc(adim, plan)

        if adim.arac_turu is AracTuru.SKILL:
            return await self._skill_calistir(adim, plan, onaylandi=onaylandi)

        if adim.arac_turu is AracTuru.BUILTIN:
            return YetenekSonucu.ok(
                f"Builtin adim: {adim.baslik}",
                yetenek="builtin",
                veri={
                    "plan_id": plan.plan_id,
                    "step_id": adim.adim_id,
                    "command": adim.komut,
                    "args": dict(adim.args),
                },
            )

        if adim.arac_turu is AracTuru.PLUGIN:
            # Plugin köprüsü sonraki dosyalarda; iskelet
            return YetenekSonucu(
                durum=YetenekDurumu.DESTEKLENMIYOR,
                mesaj="Plugin yurutme henuz bagli degil",
                yetenek=adim.arac_adi or "plugin",
                veri={
                    "plan_id": plan.plan_id,
                    "step_id": adim.adim_id,
                    "tool_type": "plugin",
                },
            )

        if adim.arac_turu is AracTuru.AGENT:
            return YetenekSonucu(
                durum=YetenekDurumu.DESTEKLENMIYOR,
                mesaj="Alt ajan yurutme henuz bagli degil",
                yetenek=adim.arac_adi or "agent",
                veri={"plan_id": plan.plan_id, "step_id": adim.adim_id},
            )

        return YetenekSonucu.hata(
            f"Bilinmeyen arac turu: {adim.arac_turu}",
            yetenek=adim.arac_adi or None,
        )

    async def yurut(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool = False,
        dry_run: Optional[bool] = None,
        arac_sec: bool = True,
        dur_hatada: bool = True,
        yayinla: Optional[bool] = None,
    ) -> GorevPlani:
        """
        Plan adımlarını sırayla yürütür.

        Args:
            plan: GorevPlani
            onaylandi: Tehlikeli / çok adımlı onay verildi mi
            dry_run: None → plan.baglam.dry_run; True/False override
            arac_sec: AracSecici varsa önce uygula
            dur_hatada: Başarısız adımda dur
            yayinla: OLAY_AJAN_PLAN; None → self.olay_yayinla
        """
        plan = self._plan_dogrula(plan)

        if dry_run is not None:
            plan.baglam.dry_run = bool(dry_run)

        if arac_sec:
            self._arac_sec_uygula(plan)

        # Plan seviyesi onay (dry_run değilse)
        plan_kapı = self._onay_kapisi(plan, onaylandi=onaylandi, adim=None)
        if plan_kapı is not None:
            plan.durum = GorevDurumu.ONAY_BEKLIYOR
            sonraki = plan.sonraki_bekleyen()
            if sonraki is not None:
                sonraki.durum = PlanAdimDurumu.ONAY_BEKLIYOR
                sonraki.sonuc = plan_kapı.to_dict()
            plan.meta["executor"] = {
                "phase": "awaiting_confirmation",
                "dry_run": bool(plan.baglam.dry_run),
                "approved": False,
                "message": plan_kapı.mesaj,
            }
            plan.dokun()
            self._audit(plan, asamasi="awaiting_confirmation", onaylandi=False)
            if yayinla if yayinla is not None else self.olay_yayinla:
                self._yayinla(plan, asamasi="awaiting_confirmation")
            log.info(
                "Plan onay bekliyor: id=%s steps=%s",
                plan.plan_id,
                plan.adim_sayisi,
            )
            return plan

        plan.durum = GorevDurumu.CALISIYOR
        plan.meta["executor"] = {
            "phase": "running",
            "dry_run": bool(plan.baglam.dry_run),
            "approved": bool(onaylandi),
        }
        plan.dokun()
        if yayinla if yayinla is not None else self.olay_yayinla:
            self._yayinla(plan, asamasi="start")

        for adim in plan.adimlar:
            if adim.durum in {
                PlanAdimDurumu.BASARILI,
                PlanAdimDurumu.ATLANDI,
                PlanAdimDurumu.IPTAL,
            }:
                continue

            # Önceki onay bekleyen → yeniden denenebilir
            if adim.durum is PlanAdimDurumu.ONAY_BEKLIYOR and onaylandi:
                adim.durum = PlanAdimDurumu.BEKLIYOR
                adim.hata = None

            if adim.durum not in {
                PlanAdimDurumu.BEKLIYOR,
                PlanAdimDurumu.ONAY_BEKLIYOR,
                PlanAdimDurumu.BASARISIZ,
            }:
                continue

            adim.durum = PlanAdimDurumu.CALISIYOR
            plan.dokun()

            sonuc = await self.adim_calistir(adim, plan, onaylandi=onaylandi)
            adim.sonucu_uygula(sonuc)

            if adim.durum is PlanAdimDurumu.ONAY_BEKLIYOR:
                plan.ozet_yenile()
                plan.meta["executor"] = {
                    "phase": "awaiting_confirmation",
                    "dry_run": bool(plan.baglam.dry_run),
                    "approved": False,
                    "step_index": adim.indeks,
                    "message": sonuc.mesaj,
                }
                self._audit(plan, asamasi="awaiting_confirmation", onaylandi=False)
                if yayinla if yayinla is not None else self.olay_yayinla:
                    self._yayinla(plan, asamasi="awaiting_confirmation")
                log.info(
                    "Adim onay bekliyor: plan=%s step=%s",
                    plan.plan_id,
                    adim.indeks,
                )
                return plan

            if adim.durum is PlanAdimDurumu.BASARISIZ and dur_hatada:
                plan.ozet_yenile()
                plan.meta["executor"] = {
                    "phase": "failed",
                    "dry_run": bool(plan.baglam.dry_run),
                    "approved": bool(onaylandi),
                    "step_index": adim.indeks,
                    "message": adim.hata or sonuc.mesaj,
                }
                self._audit(plan, asamasi="failed", onaylandi=onaylandi)
                if yayinla if yayinla is not None else self.olay_yayinla:
                    self._yayinla(plan, asamasi="failed")
                log.warning(
                    "Plan adiminda duruldu: plan=%s step=%s hata=%s",
                    plan.plan_id,
                    adim.indeks,
                    adim.hata,
                )
                return plan

        plan.ozet_yenile()
        plan.meta["executor"] = {
            "phase": "completed" if plan.durum is GorevDurumu.TAMAMLANDI else plan.durum.value,
            "dry_run": bool(plan.baglam.dry_run),
            "approved": bool(onaylandi),
            "succeeded": sum(1 for a in plan.adimlar if a.basarili_mi),
            "total": plan.adim_sayisi,
        }
        self._audit(plan, asamasi="completed", onaylandi=onaylandi)
        if yayinla if yayinla is not None else self.olay_yayinla:
            self._yayinla(plan, asamasi="completed")
        log.info(
            "Plan yurutme bitti: id=%s status=%s dry_run=%s",
            plan.plan_id,
            plan.durum.value,
            plan.baglam.dry_run,
        )
        return plan

    async def devam_et(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool = True,
        dry_run: Optional[bool] = None,
        dur_hatada: bool = True,
        yayinla: Optional[bool] = None,
    ) -> GorevPlani:
        """ONAY_BEKLIYOR durumundan onay ile devam eder."""
        plan = self._plan_dogrula(plan)
        for adim in plan.adimlar:
            if adim.durum is PlanAdimDurumu.ONAY_BEKLIYOR:
                adim.durum = PlanAdimDurumu.BEKLIYOR
                adim.hata = None
                adim.sonuc = None
        if plan.durum is GorevDurumu.ONAY_BEKLIYOR:
            plan.durum = GorevDurumu.HAZIR
        return await self.yurut(
            plan,
            onaylandi=onaylandi,
            dry_run=dry_run,
            arac_sec=False,
            dur_hatada=dur_hatada,
            yayinla=yayinla,
        )

    def yurut_senkron(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool = False,
        dry_run: Optional[bool] = None,
        arac_sec: bool = True,
        dur_hatada: bool = True,
        yayinla: Optional[bool] = None,
    ) -> GorevPlani:
        """asyncio.run sarmalayıcısı (senkron test / CLI)."""
        return asyncio.run(
            self.yurut(
                plan,
                onaylandi=onaylandi,
                dry_run=dry_run,
                arac_sec=arac_sec,
                dur_hatada=dur_hatada,
                yayinla=yayinla,
            )
        )


def gorev_yurutucu_olustur(
    *,
    skill_yoneticisi: Any = None,
    arac_secici: Any = None,
    bus: Optional[EventBus] = None,
    ayar_yonetici: Any = None,
    olay_yayinla: bool = True,
) -> GorevYurutucu:
    """GorevYurutucu fabrikası."""
    return GorevYurutucu(
        skill_yoneticisi=skill_yoneticisi,
        arac_secici=arac_secici,
        bus=bus,
        ayar_yonetici=ayar_yonetici,
        olay_yayinla=olay_yayinla,
    )


__all__ = [
    "GorevYurutucu",
    "gorev_yurutucu_olustur",
]

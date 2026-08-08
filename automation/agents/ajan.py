"""
automation/agents/ajan.py
-------------------------
Akıllı ajan orkestratörü — plan → araç seç → yürüt → karar döngüsü.

Görev:
- GorevPlanlayici, AracSecici, GorevYurutucu, KararMotoru'nu birleştirmek
- Hedef metninden çok adımlı görevi dry_run dostu şekilde çalıştırmak
- Retry / onay / iptal politikasını karar motoru ile uygulamak
- Offline birim testlere uygun (ağ / LLM zorunlu değil)

Not: Engine / yoneticisi köprüsü sonraki dosyalarda; bu modül ajan döngüsü.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from automation.agents.arac_secici import AracSecici, arac_secici_olustur
from automation.agents.karar import (
    VARSAYILAN_MAX_RETRY,
    KararAksiyonu,
    KararMotoru,
    KararSonucu,
    karar_motoru_olustur,
)
from automation.agents.modeller import (
    AjanBaglam,
    AjanHata,
    GorevDurumu,
    GorevPlani,
    PlanAdimDurumu,
)
from automation.agents.planlayici import (
    GorevPlanlayici,
    LlmPlanci,
    PlanModuGirdi,
    gorev_planlayici_olustur,
)
from automation.agents.yurutucu import GorevYurutucu, gorev_yurutucu_olustur
from core.events import OLAY_AJAN_PLAN, EventBus, olay_yolu
from core.logger import audit_yaz, logger_al

log = logger_al("automation.agents.ajan")

# Güvenlik: karar döngüsünün sonsuz dönmesini engeller
VARSAYILAN_MAX_DONGU = 32


@dataclass
class AjanSonucu:
    """
    Akıllı ajan çalıştırma özeti.

    Wire: plan, decision?, decisions, iterations, dry_run, approved, meta?
    """

    plan: GorevPlani
    karar: Optional[KararSonucu] = None
    kararlar: list[KararSonucu] = field(default_factory=list)
    iterasyon: int = 0
    dry_run: bool = True
    onaylandi: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def bitti(self) -> bool:
        if self.karar is not None and self.karar.bitti:
            return True
        return self.plan.durum in {
            GorevDurumu.TAMAMLANDI,
            GorevDurumu.IPTAL,
            GorevDurumu.BASARISIZ,
        }

    @property
    def onay_bekliyor(self) -> bool:
        if self.karar is not None and self.karar.onay_gerekli:
            return True
        return self.plan.durum is GorevDurumu.ONAY_BEKLIYOR

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "decision": None if self.karar is None else self.karar.to_dict(),
            "decisions": [k.to_dict() for k in self.kararlar],
            "iterations": int(self.iterasyon),
            "dry_run": bool(self.dry_run),
            "approved": bool(self.onaylandi),
            "done": bool(self.bitti),
            "needs_confirmation": bool(self.onay_bekliyor),
            "meta": dict(self.meta),
        }


class AkilliAjan:
    """
    Plan → araç seç → yürüt → karar ana döngüsü.

    Varsayılan: dry_run; SkillYoneticisi enjekte edilirse gerçek skill çağrılır.
    """

    def __init__(
        self,
        *,
        planlayici: Optional[GorevPlanlayici] = None,
        arac_secici: Optional[AracSecici] = None,
        yurutucu: Optional[GorevYurutucu] = None,
        karar_motoru: Optional[KararMotoru] = None,
        skill_yoneticisi: Any = None,
        bus: Optional[EventBus] = None,
        ayar_yonetici: Any = None,
        llm_planci: Optional[LlmPlanci] = None,
        olay_yayinla: bool = True,
        max_dongu: int = VARSAYILAN_MAX_DONGU,
        max_retry: int = VARSAYILAN_MAX_RETRY,
    ) -> None:
        self.bus = bus
        self.ayarlar = ayar_yonetici
        self.skills = skill_yoneticisi
        self.olay_yayinla = bool(olay_yayinla)
        self.max_dongu = max(1, int(max_dongu))

        self.planlayici = planlayici or gorev_planlayici_olustur(
            bus=bus,
            llm_planci=llm_planci,
            ayar_yonetici=ayar_yonetici,
            olay_yayinla=olay_yayinla,
        )
        self.arac_secici = arac_secici or arac_secici_olustur(
            skill_yoneticisi=skill_yoneticisi,
            ayar_yonetici=ayar_yonetici,
        )
        self.yurutucu = yurutucu or gorev_yurutucu_olustur(
            skill_yoneticisi=skill_yoneticisi,
            arac_secici=self.arac_secici,
            bus=bus,
            ayar_yonetici=ayar_yonetici,
            olay_yayinla=olay_yayinla,
        )
        # Yürütücüye enjekte edilmemişse aynı seçiciyi bağla
        if getattr(self.yurutucu, "arac_secici", None) is None:
            self.yurutucu.arac_secici = self.arac_secici
        self.karar = karar_motoru or karar_motoru_olustur(
            max_retry=max_retry,
            ayar_yonetici=ayar_yonetici,
        )

    def _ayar_al(self, anahtar: str, varsayilan: Any = None) -> Any:
        if self.ayarlar is None:
            return varsayilan
        try:
            if hasattr(self.ayarlar, "al"):
                return self.ayarlar.al(anahtar, varsayilan)
        except Exception:
            return varsayilan
        return varsayilan

    def _yayinla(self, plan: GorevPlani, *, asamasi: str) -> None:
        if not self.olay_yayinla:
            return
        bus = self.bus or olay_yolu
        try:
            veri = plan.to_dict()
            veri["agent_phase"] = asamasi
            bus.publish_sync(
                OLAY_AJAN_PLAN,
                veri,
                kaynak="automation.ajan",
            )
        except Exception as hata:
            log.debug("OLAY_AJAN_PLAN yayinlanamadi: %s", hata)

    def _audit(
        self,
        plan: GorevPlani,
        *,
        asamasi: str,
        onaylandi: bool,
        karar: Optional[KararSonucu] = None,
    ) -> None:
        if plan.adim_sayisi > 1 or plan.tehlikeli_mi:
            try:
                audit_yaz(
                    "ajan_calistir",
                    modul="automation.agents.ajan",
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
                        "action": None if karar is None else karar.aksiyon.value,
                    },
                )
            except Exception as hata:
                log.debug("audit yazilamadi: %s", hata)

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
        """
        Hedef için plan üretir; isteğe bağlı araç seçimi uygular.

        Yürütmez — yalnızca plan (+ araç) hazırlar.
        """
        plan = self.planlayici.planla(
            hedef,
            baglam=baglam,
            mod=mod,
            dry_run=dry_run,
            meta=meta,
            yayinla=yayinla,
        )
        if arac_sec:
            self.arac_secici.plana_uygula(plan)
            plan.meta.setdefault("agent", {})
            if isinstance(plan.meta["agent"], dict):
                plan.meta["agent"]["phase"] = "tools_selected"
            plan.dokun()
        return plan

    async def _dongu(
        self,
        plan: GorevPlani,
        *,
        onaylandi: bool,
        dry_run: Optional[bool],
        dur_hatada: bool,
        yayinla: Optional[bool],
        arac_sec: bool,
        max_retry: Optional[int],
    ) -> AjanSonucu:
        """Yürüt → karar → (retry ise tekrarla) döngüsü."""
        if dry_run is not None:
            plan.baglam.dry_run = bool(dry_run)

        kararlar: list[KararSonucu] = []
        son_karar: Optional[KararSonucu] = None
        iterasyon = 0
        yayin = self.olay_yayinla if yayinla is None else bool(yayinla)

        plan.meta.setdefault("agent", {})
        if isinstance(plan.meta["agent"], dict):
            plan.meta["agent"].update(
                {
                    "phase": "running",
                    "dry_run": bool(plan.baglam.dry_run),
                    "approved": bool(onaylandi),
                }
            )

        if yayin:
            self._yayinla(plan, asamasi="start")

        while iterasyon < self.max_dongu:
            iterasyon += 1

            # İlk turda araç seçimi yurutucu içinde de yapılabilir; açıkça kontrol
            plan = await self.yurutucu.yurut(
                plan,
                onaylandi=onaylandi,
                dry_run=None,  # baglam zaten ayarlı
                arac_sec=arac_sec and iterasyon == 1,
                dur_hatada=dur_hatada,
                yayinla=yayinla,
            )

            karar = self.karar.degerlendir(
                plan,
                max_retry=max_retry,
                onaylandi=onaylandi,
            )
            kararlar.append(karar)
            son_karar = karar
            plan = self.karar.uygula(plan, karar, onaylandi=onaylandi)

            if isinstance(plan.meta.get("agent"), dict):
                plan.meta["agent"]["last_action"] = karar.aksiyon.value
                plan.meta["agent"]["iterations"] = iterasyon

            log.info(
                "Ajan karar: plan=%s action=%s done=%s iter=%s",
                plan.plan_id,
                karar.aksiyon.value,
                karar.bitti,
                iterasyon,
            )

            if karar.aksiyon is KararAksiyonu.YENIDEN_DENE:
                # Adım sıfırlandı; yeniden yürüt
                continue

            if karar.aksiyon is KararAksiyonu.KULLANICIYA_SOR:
                break

            if karar.aksiyon is KararAksiyonu.IPTAL or karar.bitti:
                break

            # continue + henüz bitmedi: bekleyen adım kaldıysa döngüye devam
            if plan.sonraki_bekleyen() is not None and plan.durum not in {
                GorevDurumu.ONAY_BEKLIYOR,
                GorevDurumu.IPTAL,
                GorevDurumu.TAMAMLANDI,
                GorevDurumu.BASARISIZ,
            }:
                continue
            break

        if iterasyon >= self.max_dongu and son_karar is not None and not son_karar.bitti:
            log.warning(
                "Ajan max_dongu asildi: plan=%s limit=%s",
                plan.plan_id,
                self.max_dongu,
            )
            if plan.durum not in {
                GorevDurumu.TAMAMLANDI,
                GorevDurumu.IPTAL,
                GorevDurumu.ONAY_BEKLIYOR,
            }:
                plan.durum = GorevDurumu.BASARISIZ
                plan.meta.setdefault("agent", {})
                if isinstance(plan.meta["agent"], dict):
                    plan.meta["agent"]["phase"] = "max_loop_exceeded"
                plan.dokun()

        if isinstance(plan.meta.get("agent"), dict):
            plan.meta["agent"]["phase"] = (
                "awaiting_confirmation"
                if plan.durum is GorevDurumu.ONAY_BEKLIYOR
                else plan.durum.value
            )
            plan.meta["agent"]["iterations"] = iterasyon

        self._audit(
            plan,
            asamasi=str(plan.meta.get("agent", {}).get("phase") or "done"),
            onaylandi=onaylandi,
            karar=son_karar,
        )
        if yayin:
            self._yayinla(plan, asamasi="done")

        return AjanSonucu(
            plan=plan,
            karar=son_karar,
            kararlar=kararlar,
            iterasyon=iterasyon,
            dry_run=bool(plan.baglam.dry_run),
            onaylandi=bool(onaylandi),
            meta={
                "goal": plan.hedef,
                "status": plan.durum.value,
                "steps": plan.adim_sayisi,
            },
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
        """
        Tam ajan döngüsü: planla → araç seç → yürüt → karar.

        dry_run varsayılanı bağlam / config üzerinden (True önerilir).
        """
        hedef_temiz = str(hedef or "").strip()
        if not hedef_temiz:
            raise AjanHata(
                "Ajan hedefi gerekli",
                kod="AUT_0048",
                modul="automation.agents",
            )

        # smart_agent kapalıysa yine de çalışır; uyarı loglanır
        smart = self._ayar_al("automation.smart_agent", True)
        if smart is False:
            log.warning("automation.smart_agent=false; ajan yine de calisiyor")

        plan = self.planla(
            hedef_temiz,
            baglam=baglam,
            mod=mod,
            dry_run=dry_run,
            meta=meta,
            yayinla=yayinla,
            arac_sec=arac_sec,
        )

        return await self._dongu(
            plan,
            onaylandi=onaylandi,
            dry_run=dry_run,
            dur_hatada=dur_hatada,
            yayinla=yayinla,
            arac_sec=False,  # planla zaten seçti
            max_retry=max_retry,
        )

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
        if not isinstance(plan, GorevPlani):
            raise AjanHata(
                "GorevPlani bekleniyor",
                kod="AUT_0049",
                modul="automation.agents",
            )
        if arac_sec:
            self.arac_secici.plana_uygula(plan)
        return await self._dongu(
            plan,
            onaylandi=onaylandi,
            dry_run=dry_run,
            dur_hatada=dur_hatada,
            yayinla=yayinla,
            arac_sec=False,
            max_retry=max_retry,
        )

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
        if not isinstance(plan, GorevPlani):
            raise AjanHata(
                "GorevPlani bekleniyor",
                kod="AUT_0049",
                modul="automation.agents",
            )
        # Onay bayraklarını temizle (yurutucu.devam_et ile uyumlu)
        for adim in plan.adimlar:
            if adim.durum is PlanAdimDurumu.ONAY_BEKLIYOR:
                adim.durum = PlanAdimDurumu.BEKLIYOR
                adim.hata = None
                adim.sonuc = None
        if plan.durum is GorevDurumu.ONAY_BEKLIYOR:
            plan.durum = GorevDurumu.HAZIR

        return await self._dongu(
            plan,
            onaylandi=onaylandi,
            dry_run=dry_run,
            dur_hatada=dur_hatada,
            yayinla=yayinla,
            arac_sec=False,
            max_retry=max_retry,
        )

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


def akilli_ajan_olustur(
    *,
    planlayici: Optional[GorevPlanlayici] = None,
    arac_secici: Optional[AracSecici] = None,
    yurutucu: Optional[GorevYurutucu] = None,
    karar_motoru: Optional[KararMotoru] = None,
    skill_yoneticisi: Any = None,
    bus: Optional[EventBus] = None,
    ayar_yonetici: Any = None,
    llm_planci: Optional[LlmPlanci] = None,
    olay_yayinla: bool = True,
    max_dongu: int = VARSAYILAN_MAX_DONGU,
    max_retry: int = VARSAYILAN_MAX_RETRY,
) -> AkilliAjan:
    """AkilliAjan fabrikası."""
    return AkilliAjan(
        planlayici=planlayici,
        arac_secici=arac_secici,
        yurutucu=yurutucu,
        karar_motoru=karar_motoru,
        skill_yoneticisi=skill_yoneticisi,
        bus=bus,
        ayar_yonetici=ayar_yonetici,
        llm_planci=llm_planci,
        olay_yayinla=olay_yayinla,
        max_dongu=max_dongu,
        max_retry=max_retry,
    )


__all__ = [
    "VARSAYILAN_MAX_DONGU",
    "AjanSonucu",
    "AkilliAjan",
    "akilli_ajan_olustur",
]

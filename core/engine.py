"""
core/engine.py
--------------
WhiteCore AI ana orkestrasyon motoru.

Görev:
- config.json yüklemek
- Logger ve EventBus'ı başlatmak
- Çekirdek modül yaşam döngüsünü yönetmek
- Hata yönetimini merkezileştirmek
- Sistem durumunu EventBus üzerinden yayınlamak
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani, SistemDurumu
from core.events import (
    OLAY_AJAN_PLAN,
    OLAY_DURUM_DEGISTI,
    OLAY_HATA,
    OLAY_SISTEM_HAZIR,
    OLAY_SISTEM_KAPANIYOR,
    EventBus,
    olay_yolu,
)
from core.exceptions import ConfigurationError, WhiteCoreError
from core.logger import audit_yaz, logger_al, logger_yapilandir

log = logger_al("core.engine")


@dataclass
class ModulDurum:
    """Başlatma sırasında modül durumu kaydı."""

    ad: str
    aktif: bool
    notu: str = ""


@dataclass
class BaslatmaRaporu:
    """Engine başlatma özeti."""

    basarili: bool
    sure_saniye: float
    adimlar: list[str] = field(default_factory=list)
    aktif_moduller: list[str] = field(default_factory=list)
    bekleyen_moduller: list[str] = field(default_factory=list)
    hata: Optional[str] = None


class Engine(ModulTabani):
    """
    J.A.R.V.I.S. çekirdek motoru.

    Aşama 9: çekirdek + Memory + Brain + Voice + Skills + Network + Sync
    + Mobile + Automation + Vision + (isteğe bağlı) GUI.
    """

    ad = "engine"
    surum = "0.1.0"
    aciklama = "WhiteCore AI ana orkestrasyon motoru"

    # Henüz geliştirilmemiş (iskelet) modüller — plugins sonraki aşama
    # Not: "gui" yalnızca baslat(gui=False) iken bekleyen listesine eklenir.
    BEKLEYEN_MODULLER = [
        "plugins",
    ]

    def __init__(
        self,
        ayar_yonetici: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.bus = bus or olay_yolu
        self.durum = SistemDurumu.KAPALI
        self.modul_durumlari: list[ModulDurum] = []
        self.rapor: Optional[BaslatmaRaporu] = None
        self._baslangic_zamani = 0.0
        self.hafiza: Any = None
        self.beyin: Any = None
        self.ses: Any = None
        self.skills: Any = None
        self.network: Any = None
        self.sync: Any = None
        self.mobile: Any = None
        self.automation: Any = None
        self.vision: Any = None
        self.gui: Any = None
        self._gui_istendi = False

    async def baslat(
        self,
        *,
        gui: bool = False,
        gui_goster: bool = True,
        gui_hava_sahte: bool = False,
    ) -> BaslatmaRaporu:
        """
        Tüm çekirdek bileşenleri sırayla başlatır.

        Args:
            gui: True ise PySide6 GUI yöneticisini de başlatır
            gui_goster: Ana pencereyi göster (demo/test için False)
            gui_hava_sahte: Hava paneli ağ çağrısı yapmasın
        """
        self._baslangic_zamani = time.perf_counter()
        adimlar: list[str] = []
        self.durum = SistemDurumu.BASLIYOR
        self.modul_durumlari.clear()
        self._gui_istendi = bool(gui)

        try:
            # 1) Config
            self.ayarlar.yukle()
            adimlar.append("config")
            self.modul_durumlari.append(
                ModulDurum("config", True, "config.json yüklendi")
            )

            # 2) Logger (açılışta konsol sessiz; dosya aktif — banner sonrası açılır)
            logger_yapilandir(zorla=True)
            self._konsol_seviyesi_ayarla("WARNING")
            adimlar.append("logger")
            self.modul_durumlari.append(
                ModulDurum("logger", True, "logs/app.log aktif")
            )

            # 3) EventBus
            self.bus.clear()
            self._cekirdek_abonelikleri()
            adimlar.append("eventbus")
            self.modul_durumlari.append(
                ModulDurum("eventbus", True, f"bus={self.bus.ad}")
            )

            # 4) Exceptions / hata yönetimi hazır (import ile aktif)
            adimlar.append("exceptions")
            self.modul_durumlari.append(
                ModulDurum("exceptions", True, "WhiteCoreError ailesi")
            )

            # 5) Base sözleşmeler
            adimlar.append("base")
            self.modul_durumlari.append(
                ModulDurum("base", True, "ModulTabani / Mesaj / YetenekSonucu")
            )

            # 6) Memory (Aşama 2)
            await self._hafiza_baslat()
            adimlar.append("memory")

            # 7) Brain / AI Manager (Aşama 2)
            await self._beyin_baslat()
            adimlar.append("brain")

            # 8) Voice (Aşama 3)
            await self._ses_baslat()
            adimlar.append("voice")

            # 9) Skills (Aşama 5)
            await self._skills_baslat()
            adimlar.append("skills")

            # 10) Network + Sync (Aşama 6 — GUI köprüsünden önce)
            await self._network_baslat()
            adimlar.append("network")
            await self._sync_baslat()
            adimlar.append("sync")

            # 11) Mobile / iPhone köprüsü (Aşama 7 — network üzerine)
            await self._mobile_baslat()
            adimlar.append("mobile")

            # 12) Automation / akıllı ajan (Aşama 8 — skills + EventBus)
            await self._automation_baslat()
            adimlar.append("automation")

            # 13) Vision (Aşama 9 — kamera / OCR / analiz / yüz / Vision AI)
            await self._vision_baslat()
            adimlar.append("vision")

            # 14) GUI (Aşama 4 — isteğe bağlı; network/sync/mobile bağlanır)
            if self._gui_istendi:
                await self._gui_baslat(
                    goster=gui_goster,
                    hava_zorla_sahte=gui_hava_sahte,
                )
                adimlar.append("gui")

            # 15) Platform iskeletleri (kod yüklenebilir, runtime kapalı)
            self._iskelet_modulleri_kaydet()
            adimlar.append("platform_iskelet")

            await self.bus.publish(
                OLAY_DURUM_DEGISTI,
                {"durum": SistemDurumu.HAZIR.value},
                kaynak="engine",
            )
            await self.bus.publish(
                OLAY_SISTEM_HAZIR,
                {
                    "assistant": self.ayarlar.al("assistant.name", "J.A.R.V.I.S."),
                    "version": self.ayarlar.al("project.version", self.surum),
                },
                kaynak="engine",
            )

            self.durum = SistemDurumu.HAZIR
            self._isaret_basladi()
            sure = time.perf_counter() - self._baslangic_zamani

            aktif = [m.ad for m in self.modul_durumlari if m.aktif]
            bekleyen = [m.ad for m in self.modul_durumlari if not m.aktif]
            self.rapor = BaslatmaRaporu(
                basarili=True,
                sure_saniye=sure,
                adimlar=adimlar,
                aktif_moduller=aktif,
                bekleyen_moduller=bekleyen,
            )

            audit_yaz(
                "engine_baslatildi",
                modul="core.engine",
                detay={
                    "sure_saniye": round(sure, 4),
                    "aktif": aktif,
                },
            )
            log.info("Engine hazır (%.3fs)", sure)
            return self.rapor

        except Exception as exc:
            self.durum = SistemDurumu.HATA
            sure = time.perf_counter() - self._baslangic_zamani
            mesaj = str(exc)
            log.exception("Engine başlatılamadı: %s", mesaj)
            try:
                await self.bus.publish(
                    OLAY_HATA,
                    {"hata": mesaj, "trace": traceback.format_exc()},
                    kaynak="engine",
                )
            except Exception:
                pass

            if not isinstance(exc, WhiteCoreError):
                # ConfigurationError zaten loglanmış olabilir
                pass

            self.rapor = BaslatmaRaporu(
                basarili=False,
                sure_saniye=sure,
                adimlar=adimlar,
                aktif_moduller=[m.ad for m in self.modul_durumlari if m.aktif],
                bekleyen_moduller=[m.ad for m in self.modul_durumlari if not m.aktif],
                hata=mesaj,
            )
            return self.rapor

    async def durdur(self) -> None:
        """Sistemi güvenli kapatır."""
        log.info("Engine kapatılıyor...")
        try:
            if self.gui is not None:
                await self.gui.durdur()
                self.gui = None
            if self.ses is not None:
                await self.ses.durdur()
            if self.vision is not None:
                await self.vision.durdur()
                self.vision = None
            if self.automation is not None:
                await self.automation.durdur()
                self.automation = None
            if self.skills is not None:
                await self.skills.durdur()
                self.skills = None
            if self.mobile is not None:
                await self.mobile.durdur()
                self.mobile = None
            if self.sync is not None:
                await self.sync.durdur()
                self.sync = None
            if self.network is not None:
                await self.network.durdur()
                self.network = None
            if self.beyin is not None:
                await self.beyin.durdur()
            if self.hafiza is not None:
                await self.hafiza.durdur()
            await self.bus.publish(
                OLAY_SISTEM_KAPANIYOR,
                {"durum": SistemDurumu.KAPALI.value},
                kaynak="engine",
            )
            await self.bus.publish(
                OLAY_DURUM_DEGISTI,
                {"durum": SistemDurumu.KAPALI.value},
                kaynak="engine",
            )
        except Exception:
            log.exception("Kapanış olayları yayınlanamadı")

        self.durum = SistemDurumu.KAPALI
        self._isaret_durdu()
        audit_yaz("engine_durduruldu", modul="core.engine")

    async def _hafiza_baslat(self) -> None:
        from memory.hafiza import HafizaYoneticisi

        self.hafiza = HafizaYoneticisi(
            ayar_yonetici=self.ayarlar,
            bus=self.bus,
        )
        await self.hafiza.baslat()
        self.modul_durumlari.append(
            ModulDurum(
                "memory",
                True,
                f"sqlite={self.hafiza.depo.db_yolu.name}",
            )
        )

    async def _beyin_baslat(self) -> None:
        from brain.yoneticisi import AIYoneticisi

        self.beyin = AIYoneticisi(
            ayar_yonetici=self.ayarlar,
            bus=self.bus,
        )
        await self.beyin.baslat()
        # Hafıza bağlamını AI'ya bağla
        if self.hafiza is not None:
            self.beyin.baglam_ayarla(self.hafiza.prompt_baglami())
        self.modul_durumlari.append(
            ModulDurum(
                "brain",
                True,
                f"provider={self.beyin.aktif_saglayici}",
            )
        )

    async def _ses_baslat(self) -> None:
        from voice.yoneticisi import VoiceYoneticisi

        if not bool(self.ayarlar.al("voice.enabled", True)):
            self.modul_durumlari.append(
                ModulDurum("voice", False, "config.voice.enabled=false")
            )
            return

        self.ses = VoiceYoneticisi(
            ayar_yonetici=self.ayarlar,
            bus=self.bus,
        )

        async def _brain_cb(metin: str) -> str:
            yanit = await self.dusun(metin)
            return yanit.icerik

        self.ses.brain_bagla(_brain_cb)
        await self.ses.baslat()
        stt_ad = getattr(self.ses.stt, "ad", "?")
        tts_ad = getattr(self.ses.tts, "ad", "?")
        self.modul_durumlari.append(
            ModulDurum(
                "voice",
                True,
                f"wake=Jarvis stt={stt_ad} tts={tts_ad}",
            )
        )

    async def _skills_baslat(self) -> None:
        """Skill Manager + tüm Aşama 5 skill'lerini kaydeder."""
        from skills.kayit import skill_yoneticisi_olustur

        if self.ayarlar.al("skills.enabled", True) is False:
            self.modul_durumlari.append(
                ModulDurum("skills", False, "config.skills.enabled=false")
            )
            return

        self.skills = skill_yoneticisi_olustur(
            ayar_yonetici=self.ayarlar,
            bus=self.bus,
        )
        await self.skills.baslat()
        self.modul_durumlari.append(
            ModulDurum(
                "skills",
                True,
                f"{self.skills.adet} skill kayıtlı",
            )
        )

    async def _network_baslat(self) -> None:
        """Network Manager (eşleştirme / keşif / WS) yaşam döngüsü."""
        from network.yoneticisi import NetworkYoneticisi

        dry_run = bool(self.ayarlar.al("network.dry_run", False))
        if self.ayarlar.al("network.enabled", True) is False and not dry_run:
            self.modul_durumlari.append(
                ModulDurum(
                    "network.runtime",
                    False,
                    "config.network.enabled=false",
                )
            )
            return

        self.network = NetworkYoneticisi(
            ayarlar=self.ayarlar,
            bus=self.bus,
            dry_run=dry_run,
            sync_olustur=True,
        )
        await self.network.baslat()
        self.modul_durumlari.append(
            ModulDurum(
                "network.runtime",
                True,
                f"motor={self.network.motor} ws={self.network.ws.motor}",
            )
        )

    async def _sync_baslat(self) -> None:
        """Sync Manager — Network kancaları üzerinden bağlanır."""
        from sync.yoneticisi import SyncYoneticisi

        dry_run = bool(
            self.ayarlar.al("sync.dry_run", False)
            or self.ayarlar.al("network.dry_run", False)
        )
        if self.ayarlar.al("sync.enabled", True) is False and not dry_run:
            self.modul_durumlari.append(
                ModulDurum(
                    "sync.runtime",
                    False,
                    "config.sync.enabled=false",
                )
            )
            return

        if self.network is not None:
            self.sync = SyncYoneticisi.agdan(self.network, bus=self.bus)
        else:
            self.sync = SyncYoneticisi(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=dry_run,
            )
        await self.sync.baslat()
        self.modul_durumlari.append(
            ModulDurum(
                "sync.runtime",
                True,
                f"motor={self.sync.motor} "
                f"moduller={len(self.sync.ozet().get('modules', {}))}",
            )
        )

    async def _mobile_baslat(self) -> None:
        """Mobile Manager (iPhone köprüsü) — Network kancaları üzerinden."""
        from mobile.yoneticisi import MobilYoneticisi

        mobile_dry = bool(self.ayarlar.al("mobile.dry_run", False))
        # Motor dry_run: mobile veya network dry_run (ağsız test)
        dry_run = bool(
            mobile_dry or self.ayarlar.al("network.dry_run", False)
        )
        enabled = bool(self.ayarlar.al("mobile.enabled", False))
        bridge_on = bool(self.ayarlar.al("mobile.bridge_enabled", False))
        # Varsayılan kapalı: yalnızca enabled/bridge veya mobile.dry_run açar
        # (network.dry_run tek başına mobile runtime'ı başlatmaz)
        if not enabled and not bridge_on and not mobile_dry:
            self.modul_durumlari.append(
                ModulDurum(
                    "mobile.iphone_bridge",
                    False,
                    "config.mobile.enabled/bridge_enabled=false",
                )
            )
            return

        if self.network is not None:
            self.mobile = MobilYoneticisi.agdan(
                self.network,
                bus=self.bus,
                dry_run=dry_run,
            )
        else:
            self.mobile = MobilYoneticisi(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=dry_run,
            )
        await self.mobile.baslat()
        self.modul_durumlari.append(
            ModulDurum(
                "mobile.iphone_bridge",
                True,
                f"motor={self.mobile.motor} "
                f"primary={self.mobile.primary_mobile}",
            )
        )

    async def _automation_baslat(self) -> None:
        """Automation Manager (akıllı ajan) — Skills + EventBus kancaları."""
        from automation.yoneticisi import AutomationYoneticisi

        dry_run = bool(self.ayarlar.al("automation.dry_run", False))
        if self.ayarlar.al("automation.enabled", True) is False and not dry_run:
            self.modul_durumlari.append(
                ModulDurum(
                    "automation",
                    False,
                    "config.automation.enabled=false",
                )
            )
            return

        if self.skills is not None:
            self.automation = AutomationYoneticisi.skilllerden(
                self.skills,
                bus=self.bus,
                dry_run=dry_run,
                ayarlar=self.ayarlar,
                olay_yayinla=True,
            )
        else:
            self.automation = AutomationYoneticisi(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=dry_run,
                skill_yoneticisi=None,
                olustur=True,
                olay_yayinla=True,
            )
        await self.automation.baslat()
        skills_bagli = self.automation.skills is not None
        self.modul_durumlari.append(
            ModulDurum(
                "automation",
                True,
                f"motor={self.automation.motor} "
                f"smart={self.automation.smart_agent} "
                f"skills={skills_bagli}",
            )
        )

    async def _vision_baslat(self) -> None:
        """Vision Manager — EventBus + Config + Logger/audit + VisionError."""
        from vision.yoneticisi import VisionYoneticisi

        dry_run = bool(self.ayarlar.al("vision.dry_run", False))
        if self.ayarlar.al("vision.enabled", True) is False and not dry_run:
            self.modul_durumlari.append(
                ModulDurum(
                    "vision",
                    False,
                    "config.vision.enabled=false",
                )
            )
            return

        self.vision = VisionYoneticisi(
            ayarlar=self.ayarlar,
            bus=self.bus,
            dry_run=dry_run,
            olustur=True,
            olay_yayinla=True,
        )
        await self.vision.baslat()
        yuz_aktif = False
        try:
            yuz_aktif = bool(self.vision.yuz_tanima_aktif_mi())
        except Exception:  # noqa: BLE001
            yuz_aktif = False
        self.modul_durumlari.append(
            ModulDurum(
                "vision",
                True,
                f"motor={self.vision.motor} face={yuz_aktif}",
            )
        )

    async def skill_calistir(
        self,
        komut: str,
        *,
        skill_adi: Optional[str] = None,
        onaylandi: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Doğrudan Skill Manager üzerinden komut çalıştırır."""
        if self.skills is None:
            raise ConfigurationError("Skills başlatılmamış")
        from skills.taban import SkillBaglam

        baglam = SkillBaglam(
            onaylandi=onaylandi,
            ayar_yonetici=self.ayarlar,
        )
        return await self.skills.calistir(
            komut,
            skill_adi=skill_adi,
            baglam=baglam,
            onaylandi=onaylandi,
            **kwargs,
        )

    async def dusun(
        self,
        metin: str,
        *,
        onaylandi: bool = False,
        beyne_zorla: bool = False,
        skill_adi: Optional[str] = None,
        **skill_kwargs: Any,
    ) -> Any:
        """
        Kullanıcı metnini işler: önce Skills, eşleşme yoksa Brain + Memory.

        Args:
            metin: Kullanıcı komutu / sorusu
            onaylandi: Tehlikeli skill onayı
            beyne_zorla: True ise skill eşleşmesini atla
            skill_adi: Belirli skill zorla (eşleştirmeyi atlar)
            **skill_kwargs: Skill.calistir'a iletilen ek argümanlar (ör. dry_run)
        """
        from brain.providers.taban import SaglayiciYaniti

        metin_temiz = (metin or "").strip()
        if not metin_temiz:
            raise ConfigurationError("Boş kullanıcı mesajı")

        # 1) Skill eşleşmesi (doğal komut → yetenek)
        if (
            not beyne_zorla
            and self.skills is not None
            and self.skills.calisiyor
        ):
            skill = (
                self.skills.al(skill_adi)
                if skill_adi
                else self.skills.sec(metin_temiz)
            )
            if skill is not None:
                sonuc = await self.skill_calistir(
                    metin_temiz,
                    skill_adi=skill.ad,
                    onaylandi=onaylandi,
                    **skill_kwargs,
                )
                yanit = SaglayiciYaniti(
                    icerik=sonuc.mesaj or "(skill yanıtı boş)",
                    model="skills",
                    saglayici="skills",
                    ham=sonuc.to_dict() if hasattr(sonuc, "to_dict") else {},
                )
                if self.hafiza is not None:
                    self.hafiza.konusma_kaydet(metin_temiz, yanit.icerik)
                return yanit

        # 2) Brain + Memory
        if self.beyin is None:
            raise ConfigurationError("Brain başlatılmamış")
        if self.hafiza is not None:
            self.beyin.baglam_ayarla(
                self.hafiza.prompt_baglami(arama_sorgusu=metin_temiz)
            )
            gecmis = self.hafiza.sohbet_gecmisi()
        else:
            gecmis = []
        yanit = await self.beyin.dusun(metin_temiz, gecmis=gecmis)
        if self.hafiza is not None:
            self.hafiza.konusma_kaydet(metin_temiz, yanit.icerik)
        return yanit

    def _cekirdek_abonelikleri(self) -> None:
        """Temel sistem olaylarını loglayan abonelikler."""

        def _durum_log(event: Any) -> None:
            log.info("Durum değişti: %s", event.veri.get("durum"))

        def _hazir_log(event: Any) -> None:
            log.info(
                "Sistem hazır — %s v%s",
                event.veri.get("assistant"),
                event.veri.get("version"),
            )

        def _ajan_plan_log(event: Any) -> None:
            veri = event.veri if isinstance(event.veri, dict) else {}
            log.info(
                "Ajan plan olayı: plan_id=%s durum=%s adim=%s kaynak=%s",
                veri.get("id") or veri.get("plan_id"),
                veri.get("status") or veri.get("durum"),
                veri.get("step_count")
                or (
                    len(veri["steps"])
                    if isinstance(veri.get("steps"), list)
                    else veri.get("steps")
                ),
                getattr(event, "kaynak", "?"),
            )

        def _vision_log(event: Any) -> None:
            veri = event.veri if isinstance(event.veri, dict) else {}
            log.info(
                "Vision olayı: motor=%s face=%s dry_run=%s kaynak=%s",
                veri.get("engine"),
                veri.get("face_enabled"),
                veri.get("dry_run"),
                getattr(event, "kaynak", "?"),
            )

        self.bus.subscribe(OLAY_DURUM_DEGISTI, _durum_log, priority=1)
        self.bus.subscribe(OLAY_SISTEM_HAZIR, _hazir_log, priority=1)
        self.bus.subscribe(OLAY_AJAN_PLAN, _ajan_plan_log, priority=1)
        # Vision Manager olayları (vision/yoneticisi.py)
        self.bus.subscribe("vision.started", _vision_log, priority=1)
        self.bus.subscribe("vision.stopped", _vision_log, priority=1)

    async def _gui_baslat(
        self,
        *,
        goster: bool = True,
        hava_zorla_sahte: bool = False,
    ) -> None:
        from gui.yoneticisi import GuiYoneticisi, pyside_var_mi

        if not pyside_var_mi():
            self.modul_durumlari.append(
                ModulDurum("gui", False, "PySide6 yüklü değil")
            )
            return

        self.gui = GuiYoneticisi(
            ayarlar=self.ayarlar,
            bus=self.bus,
            engine=self,
            goster=goster,
            hava_zorla_sahte=hava_zorla_sahte,
        )
        await self.gui.baslat()
        tema = str(self.ayarlar.al("gui.theme", "tony_stark"))
        self.modul_durumlari.append(
            ModulDurum(
                "gui",
                True,
                f"PySide6 / {tema} / goster={goster}",
            )
        )

    def _iskelet_modulleri_kaydet(self) -> None:
        """Geliştirilmemiş modülleri rapora işler (aktif=False)."""
        bekleyen = list(self.BEKLEYEN_MODULLER)
        gui_kayitli = any(m.ad == "gui" for m in self.modul_durumlari)
        if not gui_kayitli:
            bekleyen.insert(0, "gui")
        for ad in bekleyen:
            self.modul_durumlari.append(
                ModulDurum(ad, False, "iskelet / sonraki aşama")
            )

    def konsol_loglarini_ac(self) -> None:
        """Banner sonrası konsol log seviyesini INFO yapar."""
        self._konsol_seviyesi_ayarla("INFO")

    def _konsol_seviyesi_ayarla(self, seviye: str) -> None:
        import logging
        from logging.handlers import TimedRotatingFileHandler

        seviye_no = getattr(logging, seviye.upper(), logging.INFO)
        kok = logger_al()
        for handler in kok.handlers:
            # Yalnızca konsol; dosya handler'ına dokunma
            if isinstance(handler, TimedRotatingFileHandler):
                continue
            if isinstance(handler, logging.StreamHandler):
                handler.setLevel(seviye_no)

    def banner_satirlari(self) -> list[str]:
        """Konsol karşılama metni."""
        proje = self.ayarlar.al("project.name", "WhiteCore AI")
        asistan = self.ayarlar.al("assistant.name", "J.A.R.V.I.S.")
        surum = self.ayarlar.al("project.version", self.surum)
        return [
            "=========================================",
            proje,
            asistan,
            f"Version {surum}",
            "=========================================",
        ]

    def basari_satirlari(self) -> list[str]:
        """Başarılı açılış kontrol listesi."""
        provider = ""
        if self.beyin is not None:
            provider = f" ({self.beyin.aktif_saglayici})"
        voice_not = ""
        if self.ses is not None:
            stt_ad = getattr(self.ses.stt, "ad", "?")
            tts_ad = getattr(self.ses.tts, "ad", "?")
            voice_not = f" (Jarvis / {stt_ad} / {tts_ad})"
        gui_satir = "○ GUI beklemede (python main.py --gui)"
        if self.gui is not None and getattr(self.gui, "calisiyor", False):
            tema = str(self.ayarlar.al("gui.theme", "tony_stark"))
            gui_satir = f"✓ GUI başlatıldı (PySide6 / {tema})"

        skills_satir = "○ Skills beklemede"
        if self.skills is not None and getattr(self.skills, "calisiyor", False):
            skills_satir = f"✓ Skills başlatıldı ({self.skills.adet} yetenek)"

        network_satir = "○ Network beklemede"
        if self.network is not None and getattr(self.network, "calisiyor", False):
            cihaz_adet = 0
            try:
                cihaz_adet = int(self.network.cihazlar.adet())
            except Exception:  # noqa: BLE001
                cihaz_adet = len(self.network.cihaz_listele())
            ws_motor = getattr(getattr(self.network, "ws", None), "motor", "?")
            panel = ""
            try:
                panel = str((self.network.ozet() or {}).get("panel_url") or "")
            except Exception:  # noqa: BLE001
                panel = ""
            panel_not = f", panel={panel}" if panel else ""
            network_satir = (
                f"✓ Network başlatıldı "
                f"(motor={self.network.motor}, {cihaz_adet} cihaz, "
                f"ws={ws_motor}{panel_not})"
            )

        sync_satir = "○ Sync beklemede"
        if self.sync is not None and getattr(self.sync, "calisiyor", False):
            modul_adet = len(self.sync.ozet().get("modules", {}) or {})
            sync_satir = (
                f"✓ Sync başlatıldı "
                f"(motor={self.sync.motor}, {modul_adet} modül)"
            )

        mobile_satir = "○ Mobile / iPhone beklemede"
        if self.mobile is not None and getattr(self.mobile, "calisiyor", False):
            istemci_adet = 0
            try:
                bridge = (self.mobile.ozet() or {}).get("bridge") or {}
                istemci_adet = int(bridge.get("devices", 0) or 0)
            except Exception:  # noqa: BLE001
                istemci_adet = 0
            panel = ""
            try:
                panel = str((self.mobile.ozet() or {}).get("panel_url") or "")
            except Exception:  # noqa: BLE001
                panel = ""
            panel_not = f", telefon={panel}" if panel else ""
            mobile_satir = (
                f"✓ Mobile / iPhone başlatıldı "
                f"(motor={self.mobile.motor}, "
                f"primary={self.mobile.primary_mobile}, "
                f"{istemci_adet} istemci{panel_not})"
            )

        automation_satir = "○ Automation / Akıllı Ajan beklemede"
        if self.automation is not None and getattr(
            self.automation, "calisiyor", False
        ):
            max_adim = getattr(self.automation, "max_plan_steps", "?")
            automation_satir = (
                f"✓ Automation / Akıllı Ajan başlatıldı "
                f"(motor={self.automation.motor}, "
                f"max_steps={max_adim})"
            )

        vision_satir = "○ Vision beklemede"
        if self.vision is not None and getattr(self.vision, "calisiyor", False):
            yuz = False
            try:
                yuz = bool(self.vision.yuz_tanima_aktif_mi())
            except Exception:  # noqa: BLE001
                yuz = False
            vision_satir = (
                f"✓ Vision başlatıldı "
                f"(motor={self.vision.motor}, face={yuz})"
            )

        return [
            "",
            "✓ Config yüklendi",
            "✓ Logger başlatıldı",
            "✓ EventBus hazır",
            "✓ Memory başlatıldı",
            f"✓ Brain başlatıldı{provider}",
            f"✓ Voice başlatıldı{voice_not}",
            skills_satir,
            network_satir,
            sync_satir,
            mobile_satir,
            automation_satir,
            vision_satir,
            gui_satir,
            "✓ Engine başlatıldı",
            "✓ Sistem hazır",
            "",
            "J.A.R.V.I.S. çalışıyor...",
            'Wake word: "Jarvis"',
        ]


__all__ = ["Engine", "BaslatmaRaporu", "ModulDurum"]

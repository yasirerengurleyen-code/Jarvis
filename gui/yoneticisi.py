"""
gui/yoneticisi.py
-----------------
GUI Manager — PySide6 orkestrasyonu.

Görev:
- QApplication + AnaPencere yaşam döngüsü
- Sohbet mesajlarını Engine.dusun / brain callback'e iletmek
- EventBus OLAY_GUI_HAZIR yayını
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from typing import Any, Awaitable, Callable, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import OLAY_GUI_HAZIR, EventBus, olay_yolu
from core.exceptions import WhiteCoreError
from core.logger import logger_al

log = logger_al("gui.yoneticisi")

BrainCallback = Callable[[str], Union[str, Awaitable[str]]]


def pyside_var_mi() -> bool:
    try:
        import PySide6  # noqa: F401

        return True
    except ImportError:
        return False


def qapp_al(argv: Optional[list[str]] = None) -> Any:
    """Mevcut QApplication'ı döner veya yeni oluşturur."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise WhiteCoreError(
            "PySide6 yüklü değil. Kurulum: pip install PySide6",
            kod="GUI_0001",
            modul="gui",
        ) from exc

    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    return app


class GuiYoneticisi(ModulTabani):
    """J.A.R.V.I.S. masaüstü arayüz yöneticisi."""

    ad = "gui"
    surum = "0.1.0"
    aciklama = "PySide6 GUI yöneticisi"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        *,
        engine: Any = None,
        brain_callback: Optional[BrainCallback] = None,
        goster: bool = True,
        hava_zorla_sahte: bool = False,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.engine = engine
        self._brain_callback = brain_callback
        self._goster = goster
        self._hava_zorla_sahte = hava_zorla_sahte
        self.app: Any = None
        self.pencere: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._gorevler: set[asyncio.Task[Any]] = set()

    def brain_bagla(self, callback: Optional[BrainCallback]) -> None:
        self._brain_callback = callback

    def engine_bagla(self, engine: Any) -> None:
        self.engine = engine

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            self.ayarlar.yukle()

        self.app = qapp_al()
        from gui.windows.ana_pencere import AnaPencere

        self.pencere = AnaPencere(
            ayar_yonetici=self.ayarlar,
            bus=self.bus,
            hava_zorla_sahte=self._hava_zorla_sahte,
        )
        self.pencere.mesaj_gonderildi.connect(self._mesaj_sinyali)
        self.pencere.kapanis_istedi.connect(self._kapanis_sinyali)
        if getattr(self.pencere, "ses_notu_istedi", None) is not None:
            self.pencere.ses_notu_istedi.connect(self._ses_notu_sinyali)

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        # Aşama 6–7: Network / Sync / Mobile → CihazPaneli köprüsü
        self._cihaz_kopru_bagla()
        # Medya aç/kapa → Voice / Vision
        self._medya_kopru_bagla()
        self._online_rozet_guncelle()

        if self._goster:
            self.pencere.show()
            if hasattr(self.pencere, "baslangic_gorunumu"):
                self.pencere.baslangic_gorunumu()

        await self.bus.publish(
            OLAY_GUI_HAZIR,
            {
                "framework": "PySide6",
                "theme": self.ayarlar.al("gui.theme", "tony_stark"),
                "shown": self._goster,
            },
            kaynak=self.ad,
        )
        self._isaret_basladi()
        log.info("GUI hazır (goster=%s)", self._goster)

    def _cihaz_kopru_bagla(self) -> None:
        """Engine.network / sync / mobile → AnaPencere.cihazlar."""
        if self.pencere is None or self.engine is None:
            return
        panel = getattr(self.pencere, "cihazlar", None)
        if panel is None:
            return

        network = getattr(self.engine, "network", None)
        sync = getattr(self.engine, "sync", None)
        mobile = getattr(self.engine, "mobile", None)

        if network is not None and hasattr(panel, "network_bagla"):
            panel.network_bagla(
                network,
                async_zamanla=self._gorev_zamanla,
                bus=self.bus,
            )
            log.info("CihazPaneli ← NetworkYoneticisi bağlandı")

        if sync is not None and hasattr(panel, "sync_bagla"):
            panel.sync_bagla(sync)
            log.info("CihazPaneli ← SyncYoneticisi bağlandı")

        if mobile is not None and hasattr(panel, "mobile_bagla"):
            panel.mobile_bagla(mobile)
            log.info("CihazPaneli ← MobilYoneticisi bağlandı")

    def _online_rozet_guncelle(self) -> None:
        """Ana pencere ONLINE rozetini ağ / motor durumuna göre ayarlar."""
        if self.pencere is None or not hasattr(self.pencere, "online_ayarla"):
            return
        network = getattr(self.engine, "network", None) if self.engine else None
        online = True
        detay = "hazır"
        if network is not None:
            try:
                ozet = network.ozet() if hasattr(network, "ozet") else {}
                calisiyor = bool(ozet.get("running", getattr(network, "calisiyor", True)))
                motor = str(ozet.get("engine") or getattr(network, "motor", "live"))
                ws = ""
                if isinstance(ozet.get("modules"), dict):
                    ws = str((ozet["modules"].get("websocket") or {}).get("engine") or "")
                online = calisiyor
                detay = f"net={motor}" + (f" ws={ws}" if ws else "")
            except Exception:
                online = True
                detay = "network"
        self.pencere.online_ayarla(online, detay=detay)

    def _medya_kopru_bagla(self) -> None:
        """AnaPencere.medya → Voice / Vision aç-kapa."""
        if self.pencere is None:
            return
        medya = getattr(self.pencere, "medya", None)
        if medya is None:
            return

        voice = getattr(self.engine, "voice", None) if self.engine else None
        vision = getattr(self.engine, "vision", None) if self.engine else None

        ses = bool(getattr(voice, "ses_acik", True)) if voice else True
        mik = bool(getattr(voice, "mikrofon_acik", True)) if voice else True
        kam = True
        if vision is not None and hasattr(vision, "kamera_izni_var_mi"):
            try:
                kam = bool(vision.kamera_izni_var_mi())
            except Exception:
                kam = True
        medya.durumlari_ayarla(ses=ses, kamera=kam, mikrofon=mik)

        if getattr(medya, "ses_degisti", None) is not None:
            medya.ses_degisti.connect(self._ses_toggle)
        if getattr(medya, "kamera_degisti", None) is not None:
            medya.kamera_degisti.connect(self._kamera_toggle)
        if getattr(medya, "mikrofon_degisti", None) is not None:
            medya.mikrofon_degisti.connect(self._mikrofon_toggle)
        log.info("MedyaKontrolleri ← Voice/Vision bağlandı")

    def _ses_toggle(self, acik: bool) -> None:
        voice = getattr(self.engine, "voice", None) if self.engine else None
        if voice is not None and hasattr(voice, "ses_ayarla"):
            voice.ses_ayarla(bool(acik))
        if self.pencere is not None:
            self.pencere.durum_mesaji(
                "Ses açık" if acik else "Ses kapalı"
            )

    def _kamera_toggle(self, acik: bool) -> None:
        vision = getattr(self.engine, "vision", None) if self.engine else None
        if vision is not None and hasattr(vision, "kamera_izni_ayarla"):
            try:
                vision.kamera_izni_ayarla(bool(acik))
            except Exception as exc:
                log.warning("Kamera toggle: %s", exc)
        if self.pencere is not None:
            self.pencere.durum_mesaji(
                "Kamera açık" if acik else "Kamera kapalı"
            )

    def _mikrofon_toggle(self, acik: bool) -> None:
        voice = getattr(self.engine, "voice", None) if self.engine else None
        if voice is not None and hasattr(voice, "mikrofon_ayarla"):
            voice.mikrofon_ayarla(bool(acik))
        if self.pencere is not None:
            self.pencere.durum_mesaji(
                "Mikrofon açık" if acik else "Mikrofon kapalı"
            )

    async def durdur(self) -> None:
        for t in list(self._gorevler):
            t.cancel()
        self._gorevler.clear()

        if self.pencere is not None:
            try:
                self.pencere.kapat_hazirlik()
                self.pencere.close()
            except Exception as exc:
                log.warning("Pencere kapatma: %s", exc)
            self.pencere = None

        self._loop = None
        self._isaret_durdu()

    def _mesaj_sinyali(self, metin: str) -> None:
        self._gorev_zamanla(self.mesaj_isle(metin))

    def _kapanis_sinyali(self) -> None:
        log.info("Ana pencere kapanış sinyali")

    def _ses_notu_sinyali(self) -> None:
        self._gorev_zamanla(self.ses_notu_isle())

    async def ses_notu_isle(self) -> None:
        """Sohbet 🎙 → kaydet → (isteğe bağlı STT) → beyin."""
        if self.pencere is None:
            return
        sure = 5.0
        stt_acik = True
        try:
            sure = float(self.ayarlar.al("voice.speaking.voice_note_seconds", 5.0) or 5.0)
            stt_acik = bool(self.ayarlar.al("voice.speaking.voice_note_stt", True))
        except Exception:
            pass

        self._ui(lambda: self.pencere.sohbet.ses_notu_durum(True))
        self._ui(lambda: self.pencere.durum_mesaji(f"Ses notu kaydı… {sure:.0f}s"))
        # Dinleme rengi
        try:
            from gui.widgets.ai_animasyon import AiDurum

            self._ui(lambda: self.pencere.ai.durum_ayarla(AiDurum.DINLIYOR))
        except Exception:
            pass

        sonuc: dict[str, Any] = {}
        try:
            from voice.ses_notu import ses_notu_kaydet

            mik = None
            voice = getattr(self.engine, "voice", None) if self.engine else None
            if voice is not None:
                mik = getattr(voice, "mikrofon", None)
            sonuc = await asyncio.to_thread(
                ses_notu_kaydet, sure_saniye=sure, mikrofon=mik
            )
        except Exception as exc:
            log.exception("Ses notu kayıt hatası")
            self._ui(
                lambda: self.pencere.sohbet.sistem_mesaji_ekle(f"Ses notu hatası: {exc}")
            )
            self._ui(lambda: self.pencere.sohbet.ses_notu_durum(False))
            return

        sure_g = float(sonuc.get("duration") or sure)
        yol = str(sonuc.get("path") or "")
        demo = bool(sonuc.get("demo"))
        self._ui(
            lambda: self.pencere.sohbet.ses_notu_mesaji_ekle(
                sure=sure_g, yol=yol, demo=demo
            )
        )
        self._ui(lambda: self.pencere.sohbet.ses_notu_durum(False))
        self._ui(lambda: self.pencere.durum_mesaji("Ses notu kaydedildi"))

        metin = ""
        if stt_acik and self.engine is not None:
            voice = getattr(self.engine, "voice", None)
            if voice is not None and hasattr(voice, "dinle"):
                try:
                    # Kısa dinleme yerine kayıtlı notu STT ile çözmek ideal;
                    # sahte STT için tekrar kısa dinle yerine dosya yolu meta
                    stt = getattr(voice, "stt", None)
                    if stt is not None and hasattr(stt, "pcm_coz"):
                        from pathlib import Path
                        import wave

                        p = Path(yol)
                        if p.is_file():
                            with wave.open(str(p), "rb") as wf:
                                pcm = wf.readframes(wf.getnframes())
                                hz = wf.getframerate()
                            stt_sonuc = await asyncio.to_thread(
                                stt.pcm_coz, pcm, ornek_hizi=hz
                            )
                            metin = str(getattr(stt_sonuc, "metin", "") or "").strip()
                except Exception as exc:
                    log.warning("Ses notu STT: %s", exc)

        if not metin:
            metin = f"[Ses notu {sure_g:.0f}s]"
            if demo:
                metin += " (mikrofon demo)"

        # Kullanıcı satırı zaten ses notu olarak eklendi; beyne ilet
        await self.mesaj_isle(metin)

    def _gorev_zamanla(self, coro: Awaitable[Any]) -> None:
        try:
            loop = self._loop or asyncio.get_running_loop()
        except RuntimeError:
            # Qt sinyalinden, çalışan loop yoksa thread-safe değil — yeni görev atlanır
            log.error("Asyncio loop yok; mesaj işlenemedi")
            return

        if loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                task = loop.create_task(coro)
                self._gorevler.add(task)
                task.add_done_callback(self._gorevler.discard)
            else:
                asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            loop.run_until_complete(coro)

    def _ui(self, fn: Callable[[], None]) -> None:
        """Qt ana iş parçacığında UI güncellemesi."""
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, fn)

    async def mesaj_isle(self, metin: str) -> str:
        """
        Kullanıcı mesajını beyne iletir ve paneli günceller.

        Not: Sohbet paneli mesajı zaten eklemiş olabilir (sinyal yolu).
        """
        metin = (metin or "").strip()
        if not metin:
            return ""

        if self.pencere is not None:
            self._ui(lambda: self._beklemeye_al(True))

        try:
            yanit_metin = await self._beyin_cagir(metin)
        except Exception as exc:
            log.exception("GUI mesaj işleme hatası")
            hata = f"Üzgünüm, bir hata oluştu: {exc}"
            if self.pencere is not None:
                self._ui(lambda: self._hata_goster(hata))
            return hata

        if self.pencere is not None:
            self._ui(lambda: self._yanit_goster(yanit_metin))
        return yanit_metin

    async def _beyin_cagir(self, metin: str) -> str:
        if self.engine is not None and hasattr(self.engine, "dusun"):
            yanit = await self.engine.dusun(metin)
            return str(getattr(yanit, "icerik", yanit))

        if self._brain_callback is not None:
            sonuc = self._brain_callback(metin)
            if inspect.isawaitable(sonuc):
                sonuc = await sonuc
            return str(sonuc)

        return (
            "Beyin henüz GUI'ye bağlanmadı. "
            "Engine entegrasyonu sonraki adımda tamamlanır."
        )

    def _beklemeye_al(self, aktif: bool) -> None:
        if self.pencere is None:
            return
        self.pencere.sohbet.beklemede(aktif)
        if aktif:
            self.pencere.ai.dusunmeye_basla()
            self.pencere.durum_mesaji("Düşünüyor…")

    def _yanit_goster(self, metin: str) -> None:
        if self.pencere is None:
            return
        self.pencere.sohbet.beklemede(False)
        self.pencere.asistan_yaniti_goster(metin)
        self.pencere.ai.yanit_hazir()
        self.pencere.durum_mesaji("Hazır")

    def _hata_goster(self, metin: str) -> None:
        if self.pencere is None:
            return
        from gui.widgets.ai_animasyon import AiDurum

        self.pencere.sohbet.beklemede(False)
        self.pencere.sohbet.sistem_mesaji_ekle(metin)
        self.pencere.ai.durum_ayarla(AiDurum.HATA, mesaj="Hata")
        self.pencere.durum_mesaji("Hata")

    def olay_isle(self) -> None:
        """Tek tur Qt olay döngüsü (test / gömülü kullanım)."""
        if self.app is not None:
            self.app.processEvents()

    def calistir_bloklu(self) -> int:
        """
        Qt olay döngüsünü bloklayarak çalıştırır.

        Not: asyncio ile birlikte kullanmak için main tarafında
        dikkatli entegrasyon gerekir (--gui adımında).
        """
        if self.app is None:
            raise WhiteCoreError("GUI başlatılmamış", kod="GUI_0002", modul="gui")
        return int(self.app.exec())

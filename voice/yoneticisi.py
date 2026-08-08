"""
voice/yoneticisi.py
-------------------
Voice Manager — ses orkestrasyonu.

Akış:
    Wake Word ("Jarvis")
        → Mikrofon dinleme
        → STT (Faster Whisper → OpenAI Whisper → Sahte)
        → (isteğe bağlı) Brain callback
        → TTS (Piper → Coqui → Sahte)
        → EventBus yayınları
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Awaitable, Callable, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import (
    OLAY_DINLEME_BASLADI,
    OLAY_DINLEME_BITTI,
    OLAY_STT_SONUC,
    OLAY_TTS_BASLADI,
    OLAY_TTS_BITTI,
    OLAY_WAKE_WORD,
    EventBus,
    olay_yolu,
)
from core.exceptions import VoiceError
from core.logger import logger_al
from voice.audio.kuyruk import SesKuyrugu
from voice.audio.mikrofon import Mikrofon
from voice.stt.taban import STTMotoru, SahteSTT, SttAyarlari, SttSonucu
from voice.tts.taban import TTSMotoru, SahteTTS, TtsAyarlari, TtsSonucu
from voice.wakeword.dinleyici import WakeWordDinleyici

log = logger_al("voice.yoneticisi")

BrainCallback = Callable[[str], Union[str, Awaitable[str]]]


def _stt_olustur(ayarlar: Ayarlar) -> STTMotoru:
    voice = ayarlar.bolum("voice")
    stt_cfg = dict(voice.get("stt") or {})
    dil = str(voice.get("language") or "tr")
    ayar = SttAyarlari.sozlukten(stt_cfg, dil=dil)

    for ad in (ayar.motor, ayar.fallback):
        try:
            if ad == "faster_whisper":
                from voice.stt.faster_whisper_stt import FasterWhisperSTT

                m = FasterWhisperSTT(ayar)
                m.yukle()
                return m
            if ad == "openai_whisper":
                from voice.stt.openai_whisper_stt import OpenAIWhisperSTT

                m = OpenAIWhisperSTT(ayar)
                m.yukle()
                return m
        except Exception as exc:
            log.warning("STT %s yüklenemedi: %s", ad, exc)
    log.warning("STT sahte moda düşüldü")
    return SahteSTT(ayar, varsayilan_metin="")


def _tts_olustur(ayarlar: Ayarlar) -> TTSMotoru:
    voice = ayarlar.bolum("voice")
    tts_cfg = dict(voice.get("tts") or {})
    ayar = TtsAyarlari.sozlukten(tts_cfg)
    for ad in (ayar.motor, ayar.fallback):
        try:
            if ad == "piper":
                from voice.tts.piper_tts import PiperTTS

                m = PiperTTS(ayar)
                m.yukle()
                return m
            if ad == "coqui":
                from voice.tts.coqui_tts import CoquiTTS

                m = CoquiTTS(ayar)
                m.yukle()
                return m
        except Exception as exc:
            log.warning("TTS %s yüklenemedi: %s", ad, exc)
    log.warning("TTS sahte moda düşüldü")
    return SahteTTS(ayar)


class VoiceYoneticisi(ModulTabani):
    """J.A.R.V.I.S. ses yöneticisi."""

    ad = "voice"
    surum = "0.1.0"
    aciklama = "Wake word + STT + TTS orkestrasyonu"

    def __init__(
        self,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        mikrofon: Optional[Mikrofon] = None,
        stt: Optional[STTMotoru] = None,
        tts: Optional[TTSMotoru] = None,
        wake: Optional[WakeWordDinleyici] = None,
        brain_callback: Optional[BrainCallback] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.bus = bus or olay_yolu
        self.mikrofon = mikrofon
        self.stt = stt
        self.tts = tts
        self.wake = wake
        self.brain_callback = brain_callback
        self.kuyruk = SesKuyrugu()
        self._dinleme_suresi = 3.0
        self._tur_kilit = threading.Lock()
        self._wake_handler_id: Optional[str] = None
        self._ses_acik = True
        self._mikrofon_acik = True

    async def baslat(self) -> None:
        if not self.ayarlar.yuklendi:
            self.ayarlar.yukle()
        if not bool(self.ayarlar.al("voice.enabled", True)):
            raise VoiceError("Voice kapalı (config.voice.enabled=false)")

        if self.mikrofon is None:
            self.mikrofon = Mikrofon(ayar_yonetici=self.ayarlar)
        if not self.mikrofon.calisiyor:
            self.mikrofon.baslat()

        if self.stt is None:
            self.stt = _stt_olustur(self.ayarlar)
        if self.tts is None:
            self.tts = _tts_olustur(self.ayarlar)

        if self.wake is None:
            self.wake = WakeWordDinleyici(
                ayar_yonetici=self.ayarlar,
                bus=self.bus,
                mikrofon=self.mikrofon,
            )
        if not self.wake.calisiyor:
            self.wake.baslat(mikrofonu_ac=False)

        self._wake_handler_id = self.bus.subscribe(
            OLAY_WAKE_WORD,
            self._wake_olay,
            priority=5,
        )
        self._isaret_basladi()
        log.info(
            "Voice hazır (stt=%s tts=%s wake=%s)",
            getattr(self.stt, "ad", "?"),
            getattr(self.tts, "ad", "?"),
            self.wake.phrase,
        )

    async def durdur(self) -> None:
        if self._wake_handler_id:
            self.bus.unsubscribe(OLAY_WAKE_WORD, self._wake_handler_id)
            self._wake_handler_id = None
        if self.wake and self.wake.calisiyor:
            self.wake.durdur()
        if self.mikrofon and self.mikrofon.calisiyor:
            self.mikrofon.durdur()
        self.kuyruk.temizle()
        self._isaret_durdu()

    def brain_bagla(self, callback: BrainCallback) -> None:
        self.brain_callback = callback

    @property
    def ses_acik(self) -> bool:
        return bool(self._ses_acik)

    @property
    def mikrofon_acik(self) -> bool:
        return bool(self._mikrofon_acik)

    def ses_ayarla(self, acik: bool) -> bool:
        """TTS çıkışını runtime'da aç/kapa."""
        self._ses_acik = bool(acik)
        log.info("Ses (TTS) %s", "açık" if self._ses_acik else "kapalı")
        return self._ses_acik

    def mikrofon_ayarla(self, acik: bool) -> bool:
        """Mikrofon + wake dinlemeyi runtime'da aç/kapa."""
        self._mikrofon_acik = bool(acik)
        if self.wake is not None:
            try:
                if self._mikrofon_acik and self._calisiyor and not self.wake.calisiyor:
                    self.wake.baslat(mikrofonu_ac=False)
                elif not self._mikrofon_acik and self.wake.calisiyor:
                    self.wake.durdur()
            except Exception as exc:
                log.warning("Mikrofon/wake ayarı: %s", exc)
        log.info(
            "Mikrofon %s",
            "açık" if self._mikrofon_acik else "kapalı",
        )
        return self._mikrofon_acik

    def _wake_olay(self, event: Any) -> None:
        """EventBus (muhtemel başka thread) → ses turu."""
        if not self._mikrofon_acik:
            log.debug("Mikrofon kapalı — wake atlandı")
            return
        if not self._tur_kilit.acquire(blocking=False):
            log.debug("Ses turu zaten çalışıyor — wake atlandı")
            return

        def _calis() -> None:
            try:
                asyncio.run(self.dinle_ve_yanitla())
            except Exception:
                log.exception("Wake sonrası ses turu başarısız")
            finally:
                self._tur_kilit.release()

        threading.Thread(
            target=_calis, name="whitecore-voice-turn", daemon=True
        ).start()

    async def dinle_ve_yanitla(
        self,
        *,
        dinleme_suresi: Optional[float] = None,
    ) -> dict[str, Any]:
        stt_sonuc = await self.dinle(dinleme_suresi=dinleme_suresi)
        if stt_sonuc.metin.strip():
            yanit = await self._beyne_sor(stt_sonuc.metin)
        else:
            yanit = "Sizi duyamadım, tekrar eder misiniz?"
        tts_sonuc = await self.konus(yanit)
        return {"stt": stt_sonuc, "yanit_metni": yanit, "tts": tts_sonuc}

    async def dinle(
        self,
        *,
        dinleme_suresi: Optional[float] = None,
    ) -> SttSonucu:
        if self.mikrofon is None or self.stt is None:
            raise VoiceError("Voice başlatılmamış")
        if not self._mikrofon_acik:
            return SttSonucu(metin="", motor="muted", ham={"muted": True})
        sure = float(dinleme_suresi or self._dinleme_suresi)

        await self.bus.publish(
            OLAY_DINLEME_BASLADI,
            {"seconds": sure},
            kaynak="voice",
        )
        pcm = await asyncio.to_thread(self.mikrofon.kaydet_saniye, sure)
        await self.bus.publish(
            OLAY_DINLEME_BITTI,
            {"bytes": len(pcm)},
            kaynak="voice",
        )

        sonuc = await asyncio.to_thread(
            self.stt.pcm_coz,
            pcm,
            ornek_hizi=self.mikrofon.ornek_hizi,
        )
        await self.bus.publish(
            OLAY_STT_SONUC,
            {"text": sonuc.metin, "engine": sonuc.motor},
            kaynak="voice",
        )
        return sonuc

    def _tts_yanit_acik_mi(self) -> bool:
        try:
            return bool(self.ayarlar.al("voice.speaking.tts_on_reply", True))
        except Exception:
            return True

    def barge_in_acik_mi(self) -> bool:
        try:
            return bool(self.ayarlar.al("voice.speaking.barge_in", True))
        except Exception:
            return True

    async def konus(self, metin: str) -> TtsSonucu:
        if self.tts is None:
            raise VoiceError("TTS başlatılmamış")
        if not self._ses_acik or not self._tts_yanit_acik_mi():
            sonuc = TtsSonucu(metin=metin, pcm=b"", motor="muted", ham={"muted": True})
            await self.bus.publish(
                OLAY_TTS_BITTI,
                {"text": metin, "bytes": 0, "engine": "muted", "muted": True},
                kaynak="voice",
            )
            return sonuc
        await self.bus.publish(OLAY_TTS_BASLADI, {"text": metin}, kaynak="voice")
        is_ = self.kuyruk.tts_ekle(metin, oncelik=5)
        sonuc = await asyncio.to_thread(self.tts.konus, metin)
        self.kuyruk.tamamla(is_)
        await self.bus.publish(
            OLAY_TTS_BITTI,
            {"text": metin, "bytes": len(sonuc.pcm), "engine": sonuc.motor},
            kaynak="voice",
        )
        return sonuc

    async def _beyne_sor(self, metin: str) -> str:
        if self.brain_callback is None:
            return f"Emriniz dinlendi: {metin}"
        sonuc = self.brain_callback(metin)
        if inspect.isawaitable(sonuc):
            sonuc = await sonuc
        return str(sonuc)

    def simule_wake(self) -> bool:
        if self.wake is None:
            raise VoiceError("Wake dinleyici yok")
        return self.wake.tetikle(kaynak="simulate")


__all__ = ["VoiceYoneticisi"]

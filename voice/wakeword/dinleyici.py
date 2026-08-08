"""
voice/wakeword/dinleyici.py
---------------------------
Wake Word dinleyici — varsayılan ifade: "Jarvis".

Görev:
- Mikrofon akışını dinlemek
- Wake word algılanınca EventBus'a OLAY_WAKE_WORD yayınlamak
- config.json wake_word ayarlarını uygulamak (sensitivity, cooldown)
- Ağır motor yoksa metin/simülasyon tabanlı algılayıcı kullanmak

Not: Porcupine / openWakeWord sonraki iyileştirmede takılabilir;
şu an test edilebilir, EventBus entegreli çekirdek dinleyici sunulur.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Callable, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.events import OLAY_WAKE_WORD, EventBus, olay_yolu
from core.exceptions import WakeWordError
from core.logger import logger_al
from voice.audio.mikrofon import Mikrofon, SesKaresi

log = logger_al("voice.wakeword")


class AnahtarKelimeAlgilayici:
    """
    Metin içinde wake phrase arar (STT ara çıktısı veya simülasyon).

    Örn. "hey jarvis" / "Jarvis," / "JARVIS" eşleşir.
    """

    def __init__(self, phrase: str = "Jarvis", sensitivity: float = 0.6) -> None:
        self.phrase = phrase.strip()
        self.sensitivity = max(0.0, min(1.0, sensitivity))
        # Kelime sınırlı, büyük/küçük harf duyarsız
        self._pattern = re.compile(
            rf"(?<!\w){re.escape(self.phrase)}(?!\w)",
            re.IGNORECASE,
        )

    def eslesir_mi(self, metin: str) -> bool:
        if not metin or not self.phrase:
            return False
        if self._pattern.search(metin):
            return True
        # Düşük sensitivity: yaklaşık yazımlar (jarvs vb.) kabul edilmez —
        # yalnızca normalize eşitlik
        norm = re.sub(r"[^\w]+", "", metin.lower())
        hedef = re.sub(r"[^\w]+", "", self.phrase.lower())
        if self.sensitivity >= 0.5 and hedef in norm:
            return True
        return False


class WakeWordDinleyici:
    """
    Jarvis wake word dinleyicisi.

    Modlar:
    - mikrofon: enerji + isteğe bağlı harici skorlayıcı
    - metin: STT/ara metinden anahtar kelime
    - simülasyon: test için tetikle()
    """

    def __init__(
        self,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        mikrofon: Optional[Mikrofon] = None,
        phrase: Optional[str] = None,
    ) -> None:
        self.ayarlar = ayar_yonetici or global_ayarlar
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:
                pass

        self.bus = bus or olay_yolu
        ww = self.ayarlar.bolum("wake_word")
        self.phrase = phrase or str(ww.get("phrase") or "Jarvis")
        self.enabled = bool(ww.get("enabled", True))
        self.sensitivity = float(ww.get("sensitivity", 0.6))
        self.cooldown = float(ww.get("cooldown_seconds", 1.5))
        self.timeout = float(ww.get("timeout_seconds", 8))

        self.algilayici = AnahtarKelimeAlgilayici(self.phrase, self.sensitivity)
        self.mikrofon = mikrofon
        self._calisiyor = False
        self._thread: Optional[threading.Thread] = None
        self._son_tetik = 0.0
        self._kilit = threading.Lock()
        self._callbacks: list[Callable[[str], None]] = []

    @property
    def calisiyor(self) -> bool:
        return self._calisiyor

    def on_wake(self, callback: Callable[[str], None]) -> None:
        """Wake word callback ekler: callback(phrase)."""
        self._callbacks.append(callback)

    def baslat(self, *, mikrofonu_ac: bool = True) -> None:
        if not self.enabled:
            raise WakeWordError(
                "Wake word kapalı (config.wake_word.enabled=false)",
                detay={"phrase": self.phrase},
            )
        if self._calisiyor:
            return
        if mikrofonu_ac:
            if self.mikrofon is None:
                self.mikrofon = Mikrofon(ayar_yonetici=self.ayarlar)
            if not self.mikrofon.calisiyor:
                self.mikrofon.baslat()
        self._calisiyor = True
        self._thread = threading.Thread(
            target=self._dongu,
            name="whitecore-wakeword",
            daemon=True,
        )
        self._thread.start()
        log.info("Wake word dinleniyor: '%s'", self.phrase)

    def durdur(self) -> None:
        self._calisiyor = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        log.info("Wake word durduruldu")

    def metinden_kontrol(self, metin: str) -> bool:
        """STT metninde wake word var mı? Varsa tetikler."""
        if not self.enabled:
            return False
        if self.algilayici.eslesir_mi(metin):
            self.tetikle(kaynak="text", ham=metin)
            return True
        return False

    def tetikle(self, *, kaynak: str = "manual", ham: str = "") -> bool:
        """
        Wake word olayını yayınlar (cooldown uygular).

        Returns:
            True tetiklendiyse, False cooldown'daysa
        """
        with self._kilit:
            simdi = time.time()
            if simdi - self._son_tetik < self.cooldown:
                log.debug("Wake word cooldown aktif")
                return False
            self._son_tetik = simdi

        veri = {
            "phrase": self.phrase,
            "source": kaynak,
            "raw": ham or self.phrase,
            "timestamp": simdi,
        }
        log.info("Wake word algılandı: %s (kaynak=%s)", self.phrase, kaynak)
        self.bus.publish_sync(OLAY_WAKE_WORD, veri, kaynak="voice.wakeword")
        for cb in list(self._callbacks):
            try:
                cb(self.phrase)
            except Exception:
                log.exception("Wake callback hatası")
        return True

    def _dongu(self) -> None:
        """
        Mikrofon döngüsü.

        Gerçek NN motoru yokken: yüksek enerjili kareleri sayar;
        asıl güvenilir tetik metinden_kontrol / tetikle ile gelir.
        Enerji eşiği aşılırsa opsiyonel 'listening_hot' durumu loglanır.
        """
        esik = 0.15 + (1.0 - self.sensitivity) * 0.25
        while self._calisiyor:
            if self.mikrofon is None:
                time.sleep(0.1)
                continue
            kare = self.mikrofon.kare_oku(timeout=0.2)
            if kare is None:
                continue
            self._kare_isle(kare, esik)

    def _kare_isle(self, kare: SesKaresi, esik: float) -> None:
        # Yer tutucu: harici motor bağlanana kadar yalnızca enerji izlenir.
        # Yanlış pozitif wake üretmez.
        _ = kare.rms() >= esik

    async def bekle(
        self,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Bir sonraki wake word'ü async bekler.

        Testte tetikle() başka task'tan çağrılabilir.
        """
        olay = asyncio.Event()
        sonuc = {"ok": False}

        def _cb(_phrase: str) -> None:
            sonuc["ok"] = True
            olay.set()

        self.on_wake(_cb)
        timeout = self.timeout if timeout is None else timeout
        try:
            await asyncio.wait_for(olay.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return bool(sonuc["ok"])


__all__ = [
    "AnahtarKelimeAlgilayici",
    "WakeWordDinleyici",
]

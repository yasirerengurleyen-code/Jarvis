"""
voice/audio/mikrofon.py
-----------------------
Mikrofon yakalama katmanı.

Görev:
- Ses karelerini (chunk) kaydetmek
- Enerji eşiği ile sessizlik / konuşma tespiti (basit VAD)
- sounddevice yoksa sahte (sessiz) akış üretmek — test için

Wake word ve STT bu sınıfın ürettiği PCM verisini kullanır.
"""

from __future__ import annotations

import asyncio
import math
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import VoiceError
from core.logger import logger_al
from voice.audio.cihazlar import CihazYoneticisi, cihaz_yoneticisi

log = logger_al("voice.audio.mikrofon")


@dataclass
class SesKaresi:
    """Tek bir PCM ses karesi (16-bit mono varsayılan)."""

    veri: bytes
    ornek_hizi: int
    kanallar: int = 1
    zaman: float = 0.0

    @property
    def ornek_sayisi(self) -> int:
        genislik = 2 * self.kanallar  # int16
        if genislik <= 0:
            return 0
        return len(self.veri) // genislik

    def rms(self) -> float:
        """Kök ortalama kare enerji (0–1 yaklaşık)."""
        if not self.veri:
            return 0.0
        n = len(self.veri) // 2
        if n <= 0:
            return 0.0
        ornekler = struct.unpack(f"<{n}h", self.veri[: n * 2])
        toplam = sum(x * x for x in ornekler)
        return math.sqrt(toplam / n) / 32768.0


class Mikrofon:
    """
    Mikrofon yakalayıcı.

    Kullanım:
        mik = Mikrofon()
        mik.baslat()
        kare = mik.kare_oku(timeout=1.0)
        mik.durdur()
    """

    def __init__(
        self,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
        cihazlar: Optional[CihazYoneticisi] = None,
        ornek_hizi: Optional[int] = None,
        chunk_size: Optional[int] = None,
        device_index: Optional[int] = None,
    ) -> None:
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.cihazlar = cihazlar or cihaz_yoneticisi
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:
                pass

        self.ornek_hizi = int(
            ornek_hizi
            or self.ayarlar.al("voice.microphone.sample_rate", 16000)
            or 16000
        )
        self.chunk_size = int(
            chunk_size
            or self.ayarlar.al("voice.microphone.chunk_size", 1024)
            or 1024
        )
        self.kanallar = int(self.ayarlar.al("voice.microphone.channels", 1) or 1)
        self.enerji_esigi = float(
            self.ayarlar.al("voice.microphone.energy_threshold", 300) or 300
        ) / 32768.0
        self.device_index = device_index
        if self.device_index is None:
            cfg_idx = self.ayarlar.al("voice.microphone.device_index", None)
            self.device_index = int(cfg_idx) if cfg_idx is not None else None

        self._kuyruk: deque[SesKaresi] = deque(maxlen=200)
        self._kilit = threading.Lock()
        self._calisiyor = False
        self._stream = None
        self._sahte_mod = False
        self._sahte_thread: Optional[threading.Thread] = None

    @property
    def calisiyor(self) -> bool:
        return self._calisiyor

    @property
    def sahte_mod(self) -> bool:
        return self._sahte_mod

    def baslat(self) -> None:
        """Yakalamayı başlatır."""
        if self._calisiyor:
            return
        try:
            import sounddevice as sd  # noqa: F401

            self._gercek_baslat()
        except ImportError:
            log.warning("sounddevice yok — sahte mikrofon modu")
            self._sahte_baslat()
        except Exception as exc:
            log.warning("Gerçek mikrofon açılamadı (%s) — sahte moda düşülüyor", exc)
            self._sahte_baslat()

        self._calisiyor = True
        log.info(
            "Mikrofon başladı (sr=%s chunk=%s sahte=%s)",
            self.ornek_hizi,
            self.chunk_size,
            self._sahte_mod,
        )

    def durdur(self) -> None:
        """Yakalamayı durdurur."""
        self._calisiyor = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._sahte_thread and self._sahte_thread.is_alive():
            self._sahte_thread.join(timeout=1.0)
        self._sahte_thread = None
        with self._kilit:
            self._kuyruk.clear()
        log.info("Mikrofon durduruldu")

    def kare_oku(self, timeout: float = 1.0) -> Optional[SesKaresi]:
        """Kuyruktan bir kare alır; yoksa None."""
        bitis = time.time() + timeout
        while time.time() < bitis:
            with self._kilit:
                if self._kuyruk:
                    return self._kuyruk.popleft()
            time.sleep(0.01)
        return None

    def kuyruk_boyutu(self) -> int:
        with self._kilit:
            return len(self._kuyruk)

    def konusma_var_mi(self, kare: SesKaresi) -> bool:
        """Basit enerji eşiği VAD."""
        return kare.rms() >= self.enerji_esigi

    async def akis(self) -> AsyncIterator[SesKaresi]:
        """Async kare üreteci."""
        if not self._calisiyor:
            self.baslat()
        while self._calisiyor:
            kare = await asyncio.to_thread(self.kare_oku, 0.2)
            if kare is not None:
                yield kare
            else:
                await asyncio.sleep(0.01)

    def kaydet_saniye(
        self,
        sure: float,
        *,
        sadece_konusma: bool = False,
    ) -> bytes:
        """Belirli süre PCM biriktirir."""
        if not self._calisiyor:
            self.baslat()
        parcalar: list[bytes] = []
        bitis = time.time() + sure
        while time.time() < bitis:
            kare = self.kare_oku(timeout=0.2)
            if kare is None:
                continue
            if sadece_konusma and not self.konusma_var_mi(kare):
                continue
            parcalar.append(kare.veri)
        birlesik = b"".join(parcalar)
        if not birlesik:
            # Hiç kare gelmezse sessiz chunk üret (STT boş PCM hatasına düşmesin)
            birlesik = struct.pack(f"<{self.chunk_size}h", *([0] * self.chunk_size))
        return birlesik

    def _gercek_baslat(self) -> None:
        import sounddevice as sd

        idx = self.device_index
        if idx is None:
            mik = self.cihazlar.varsayilan_mikrofon()
            idx = mik.index if mik else None

        def _callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            if status:
                log.debug("mikrofon status: %s", status)
            # indata: float32 → int16
            try:
                import numpy as np

                clipped = np.clip(indata[:, 0], -1.0, 1.0)
                pcm = (clipped * 32767).astype("<i2").tobytes()
            except ImportError:
                # numpy yoksa ham bytes (beklenmez; sounddevice genelde numpy ister)
                pcm = bytes(indata)
            kare = SesKaresi(
                veri=pcm,
                ornek_hizi=self.ornek_hizi,
                kanallar=self.kanallar,
                zaman=time.time(),
            )
            with self._kilit:
                self._kuyruk.append(kare)

        self._stream = sd.InputStream(
            samplerate=self.ornek_hizi,
            channels=self.kanallar,
            dtype="float32",
            blocksize=self.chunk_size,
            device=idx,
            callback=_callback,
        )
        self._stream.start()
        self._sahte_mod = False

    def _sahte_baslat(self) -> None:
        """Test için sessiz (veya düşük gürültülü) kare üretir."""
        self._sahte_mod = True

        def _dongu() -> None:
            while self._calisiyor:
                # Sessiz int16 kare
                pcm = struct.pack(f"<{self.chunk_size}h", *([0] * self.chunk_size))
                kare = SesKaresi(
                    veri=pcm,
                    ornek_hizi=self.ornek_hizi,
                    kanallar=self.kanallar,
                    zaman=time.time(),
                )
                with self._kilit:
                    self._kuyruk.append(kare)
                time.sleep(self.chunk_size / float(self.ornek_hizi))

        self._calisiyor = True
        self._sahte_thread = threading.Thread(
            target=_dongu, name="whitecore-fake-mic", daemon=True
        )
        self._sahte_thread.start()

    def enjekte_kare(self, kare: SesKaresi) -> None:
        """Test: kuyruğa yapay kare ekler."""
        with self._kilit:
            self._kuyruk.append(kare)


__all__ = ["SesKaresi", "Mikrofon"]

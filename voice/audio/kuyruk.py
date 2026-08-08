"""
voice/audio/kuyruk.py
---------------------
Konuşma ve ses iş kuyruğu.

Görev:
- TTS / STT / wake-word arasında sıralı ses işlerini yönetmek
- Öncelikli kuyruk (priority queue)
- Async bekleyici ve iptal desteği
- Thread-safe yapı

Örnek iş türleri: tts_oynat, stt_bekle, ding, sessizlik
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.logger import logger_al

log = logger_al("voice.audio.kuyruk")


class SesIsTuru(str, Enum):
    """Kuyruktaki iş türleri."""

    TTS = "tts"
    STT = "stt"
    WAKE = "wake"
    EFEKT = "efekt"
    GENEL = "genel"


class SesIsDurumu(str, Enum):
    BEKLIYOR = "bekliyor"
    CALISIYOR = "calisiyor"
    TAMAMLANDI = "tamamlandi"
    IPTAL = "iptal"
    HATA = "hata"


@dataclass(order=True)
class SesIsi:
    """Öncelikli ses işi. Küçük priority değeri = önce (heap uyumu için)."""

    oncelik: int
    olusturma: float = field(compare=True)
    is_id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)
    tur: SesIsTuru = field(default=SesIsTuru.GENEL, compare=False)
    yuku: dict[str, Any] = field(default_factory=dict, compare=False)
    durum: SesIsDurumu = field(default=SesIsDurumu.BEKLIYOR, compare=False)
    hata: Optional[str] = field(default=None, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.is_id,
            "type": self.tur.value,
            "priority": self.oncelik,
            "status": self.durum.value,
            "payload": self.yuku,
            "error": self.hata,
        }


class SesKuyrugu:
    """
    Thread-safe ses iş kuyruğu.

    Öncelik: düşük sayı = yüksek öncelik (0 en yüksek).
    Wake word / acil TTS için 0; normal TTS için 10 önerilir.
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._maxsize = maxsize
        self._kilit = threading.RLock()
        self._kosul = threading.Condition(self._kilit)
        self._heap: list[SesIsi] = []
        self._iptal_set: set[str] = set()
        self._aktif: Optional[SesIsi] = None
        self._sayac = 0

    def __len__(self) -> int:
        with self._kilit:
            return len(self._heap)

    @property
    def aktif_is(self) -> Optional[SesIsi]:
        with self._kilit:
            return self._aktif

    def ekle(
        self,
        tur: SesIsTuru | str,
        yuku: Optional[dict[str, Any]] = None,
        *,
        oncelik: int = 10,
    ) -> SesIsi:
        """Kuyruğa iş ekler."""
        if isinstance(tur, str):
            tur = SesIsTuru(tur)
        with self._kosul:
            if len(self._heap) >= self._maxsize:
                # En düşük öncelikli (en büyük oncelik sayısı) işi at
                self._heap.sort()
                atilan = self._heap.pop()
                log.warning("Kuyruk dolu — iş atıldı: %s", atilan.is_id)
            is_ = SesIsi(
                oncelik=int(oncelik),
                olusturma=time.time(),
                tur=tur,
                yuku=dict(yuku or {}),
            )
            self._heap.append(is_)
            self._heap.sort()
            self._sayac += 1
            self._kosul.notify()
            log.debug("İş eklendi: %s tur=%s oncelik=%s", is_.is_id, tur.value, oncelik)
            return is_

    def al(self, timeout: Optional[float] = None) -> Optional[SesIsi]:
        """Sıradaki işi alır; timeout dolarsa None."""
        with self._kosul:
            bitis = None if timeout is None else time.time() + timeout
            while True:
                # İptal edilenleri temizle
                self._heap = [i for i in self._heap if i.is_id not in self._iptal_set]
                self._heap.sort()
                if self._heap:
                    is_ = self._heap.pop(0)
                    if is_.is_id in self._iptal_set:
                        is_.durum = SesIsDurumu.IPTAL
                        continue
                    is_.durum = SesIsDurumu.CALISIYOR
                    self._aktif = is_
                    return is_
                if timeout is not None:
                    kalan = bitis - time.time()
                    if kalan <= 0:
                        return None
                    self._kosul.wait(timeout=kalan)
                else:
                    self._kosul.wait()

    async def aal(self, timeout: Optional[float] = None) -> Optional[SesIsi]:
        return await asyncio.to_thread(self.al, timeout)

    def tamamla(self, is_: SesIsi, *, hata: Optional[str] = None) -> None:
        with self._kilit:
            if hata:
                is_.durum = SesIsDurumu.HATA
                is_.hata = hata
            elif is_.durum != SesIsDurumu.IPTAL:
                is_.durum = SesIsDurumu.TAMAMLANDI
            if self._aktif and self._aktif.is_id == is_.is_id:
                self._aktif = None

    def iptal(self, is_id: str) -> bool:
        with self._kilit:
            self._iptal_set.add(is_id)
            for i in self._heap:
                if i.is_id == is_id:
                    i.durum = SesIsDurumu.IPTAL
            if self._aktif and self._aktif.is_id == is_id:
                self._aktif.durum = SesIsDurumu.IPTAL
            return True

    def temizle(self) -> int:
        with self._kilit:
            n = len(self._heap)
            self._heap.clear()
            self._iptal_set.clear()
            return n

    def tts_ekle(self, metin: str, *, oncelik: int = 10) -> SesIsi:
        return self.ekle(SesIsTuru.TTS, {"text": metin}, oncelik=oncelik)

    def stt_ekle(self, pcm: bytes, *, oncelik: int = 5) -> SesIsi:
        return self.ekle(SesIsTuru.STT, {"pcm": pcm}, oncelik=oncelik)

    def bekle_bos(self, timeout: float = 5.0) -> bool:
        """Kuyruk ve aktif iş bitene kadar bekler."""
        bitis = time.time() + timeout
        while time.time() < bitis:
            with self._kilit:
                if not self._heap and self._aktif is None:
                    return True
            time.sleep(0.05)
        return False

    def ozet(self) -> dict[str, Any]:
        with self._kilit:
            return {
                "pending": len(self._heap),
                "active": self._aktif.to_dict() if self._aktif else None,
                "total_enqueued": self._sayac,
            }


class SesKuyrukIsleyici:
    """
    Kuyruktan iş çekip handler çalıştıran basit döngü.

    Voice Manager bu sınıfı kullanır.
    """

    def __init__(
        self,
        kuyruk: SesKuyrugu,
        handler: Callable[[SesIsi], Any],
    ) -> None:
        self.kuyruk = kuyruk
        self.handler = handler
        self._calisiyor = False
        self._thread: Optional[threading.Thread] = None

    @property
    def calisiyor(self) -> bool:
        return self._calisiyor

    def baslat(self) -> None:
        if self._calisiyor:
            return
        self._calisiyor = True
        self._thread = threading.Thread(
            target=self._dongu, name="whitecore-voice-queue", daemon=True
        )
        self._thread.start()

    def durdur(self) -> None:
        self._calisiyor = False
        # Bekleyen al() uyandır
        self.kuyruk.ekle(SesIsTuru.GENEL, {"_stop": True}, oncelik=0)
        if self._thread:
            self._thread.join(timeout=2.0)

    def _dongu(self) -> None:
        while self._calisiyor:
            is_ = self.kuyruk.al(timeout=0.5)
            if is_ is None:
                continue
            if is_.yuku.get("_stop"):
                self.kuyruk.tamamla(is_)
                break
            try:
                sonuc = self.handler(is_)
                if asyncio.iscoroutine(sonuc):
                    asyncio.run(sonuc)
                self.kuyruk.tamamla(is_)
            except Exception as exc:
                log.exception("Ses işi hata: %s", is_.is_id)
                self.kuyruk.tamamla(is_, hata=str(exc))


__all__ = [
    "SesIsTuru",
    "SesIsDurumu",
    "SesIsi",
    "SesKuyrugu",
    "SesKuyrukIsleyici",
]

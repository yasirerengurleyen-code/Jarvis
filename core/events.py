"""
core/events.py
--------------
WhiteCore AI olay yolu (EventBus).

Görev:
- Modüller arası gevşek bağlı haberleşme sağlamak
- Senkron ve async aboneleri desteklemek
- Öncelikli (priority) dinleyici sırası
- Thread-safe abonelik / yayın

Kullanım:
    from core.events import olay_yolu, OLAY_DURUM_DEGISTI, Event

    async def dinleyici(event: Event) -> None:
        print(event.veri)

    olay_yolu.subscribe(OLAY_DURUM_DEGISTI, dinleyici, priority=10)
    await olay_yolu.publish(OLAY_DURUM_DEGISTI, {"durum": "hazir"})
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Union
from uuid import uuid4

from core.logger import logger_al

log = logger_al("core.events")

# ---------------------------------------------------------------------------
# Standart olay adları (modüller bu sabitleri kullanır)
# ---------------------------------------------------------------------------

# Sistem / çekirdek
OLAY_SISTEM_HAZIR = "sistem.hazir"
OLAY_SISTEM_KAPANIYOR = "sistem.kapaniyor"
OLAY_DURUM_DEGISTI = "sistem.durum_degisti"
OLAY_HATA = "sistem.hata"

# Voice
OLAY_WAKE_WORD = "voice.wake_word"
OLAY_DINLEME_BASLADI = "voice.dinleme_basladi"
OLAY_DINLEME_BITTI = "voice.dinleme_bitti"
OLAY_STT_SONUC = "voice.stt_sonuc"
OLAY_TTS_BASLADI = "voice.tts_basladi"
OLAY_TTS_BITTI = "voice.tts_bitti"

# Brain
OLAY_DUSUNME_BASLADI = "brain.dusunme_basladi"
OLAY_YANIT_HAZIR = "brain.yanit_hazir"
OLAY_AJAN_PLAN = "brain.ajan_plan"

# GUI
OLAY_GUI_HAZIR = "gui.hazir"
OLAY_GUI_KOMUT = "gui.komut"
OLAY_GUI_BILDIRIM = "gui.bildirim"

# Memory
OLAY_HAFIZA_YAZILDI = "memory.yazildi"
OLAY_HAFIZA_OKUNDU = "memory.okundu"
OLAY_PREFERANS_DEGISTI = "memory.preferans_degisti"

# Network / cihaz
OLAY_AG_BAGLANDI = "network.baglandi"
OLAY_AG_KOPTU = "network.koptu"
OLAY_CIHAZ_ESLESTI = "network.cihaz_eslesti"
OLAY_CIHAZ_DURUM = "network.cihaz_durum"

# iPhone / mobil köprü
OLAY_IPHONE_BAGLANDI = "mobile.iphone_baglandi"
OLAY_IPHONE_KOPTU = "mobile.iphone_koptu"
OLAY_MOBIL_KOMUT = "mobile.komut"
OLAY_MOBIL_BILDIRIM = "mobile.bildirim"
OLAY_MOBIL_PIL = "mobile.pil"

# Plugin
OLAY_PLUGIN_YUKLENDI = "plugin.yuklendi"
OLAY_PLUGIN_KALDIRILDI = "plugin.kaldirildi"
OLAY_PLUGIN_HATA = "plugin.hata"

# Skills
OLAY_SKILL_CALISTI = "skills.calisti"
OLAY_SKILL_HATA = "skills.hata"
OLAY_SKILL_ONAY = "skills.onay_bekliyor"


EventHandler = Callable[["Event"], Any]


@dataclass(order=False)
class Event:
    """Tek bir olay örneği."""

    ad: str
    veri: dict[str, Any] = field(default_factory=dict)
    kaynak: str = "system"
    oncelik: int = 0
    event_id: str = field(default_factory=lambda: str(uuid4()))
    zaman: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    iptal: bool = False

    def iptal_et(self) -> None:
        """Sonraki dinleyicilerin çalışmasını engeller (best-effort)."""
        self.iptal = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "name": self.ad,
            "data": self.veri,
            "source": self.kaynak,
            "priority": self.oncelik,
            "timestamp": self.zaman,
            "cancelled": self.iptal,
        }


@dataclass(order=True)
class _Abone:
    """Öncelikli abone kaydı. Yüksek priority önce çalışır."""

    priority: int
    handler_id: str = field(compare=False)
    handler: EventHandler = field(compare=False)
    bir_kez: bool = field(default=False, compare=False)


class EventBus:
    """
    Thread-safe olay yolu.

    - subscribe / unsubscribe / publish
    - Sync ve async handler desteği
    - Priority: büyük sayı = önce çalışır
    """

    def __init__(self, ad: str = "whitecore.bus") -> None:
        self.ad = ad
        self._aboneler: dict[str, list[_Abone]] = {}
        self._kilit = threading.RLock()
        self._log = logger_al(f"events.{ad}")
        self._yayin_sayaci = 0

    def subscribe(
        self,
        olay_adi: str,
        handler: EventHandler,
        *,
        priority: int = 0,
        bir_kez: bool = False,
    ) -> str:
        """
        Olay dinleyicisi ekler.

        Returns:
            handler_id — unsubscribe için kullanılır
        """
        if not callable(handler):
            raise TypeError("handler çağrılabilir olmalıdır")

        handler_id = str(uuid4())
        abone = _Abone(
            priority=-priority,  # sıralama: küçük order = önce; negatif ile tersine
            handler_id=handler_id,
            handler=handler,
            bir_kez=bir_kez,
        )
        # order=True ile sorted: priority alanı küçük olan önce.
        # Kullanıcı yüksek priority istiyor → saklarken -priority kullanırız.

        with self._kilit:
            liste = self._aboneler.setdefault(olay_adi, [])
            liste.append(abone)
            liste.sort()

        self._log.debug(
            "Abone eklendi: %s -> %s (priority=%s, id=%s)",
            olay_adi,
            getattr(handler, "__name__", repr(handler)),
            priority,
            handler_id,
        )
        return handler_id

    def unsubscribe(
        self,
        olay_adi: str,
        handler: Optional[Union[EventHandler, str]] = None,
    ) -> int:
        """
        Dinleyiciyi kaldırır.

        Args:
            olay_adi: Olay adı
            handler: fonksiyon veya handler_id; None ise o olayın tüm aboneleri silinir

        Returns:
            Kaldırılan abone sayısı
        """
        with self._kilit:
            if olay_adi not in self._aboneler:
                return 0

            if handler is None:
                sayi = len(self._aboneler[olay_adi])
                del self._aboneler[olay_adi]
                self._log.debug("Tüm aboneler kaldırıldı: %s (%s)", olay_adi, sayi)
                return sayi

            onceki = len(self._aboneler[olay_adi])
            if isinstance(handler, str):
                self._aboneler[olay_adi] = [
                    a for a in self._aboneler[olay_adi] if a.handler_id != handler
                ]
            else:
                self._aboneler[olay_adi] = [
                    a for a in self._aboneler[olay_adi] if a.handler is not handler
                ]

            if not self._aboneler[olay_adi]:
                del self._aboneler[olay_adi]

            kalan = len(self._aboneler.get(olay_adi, []))
            silinen = onceki - kalan
            self._log.debug("Abone kaldırıldı: %s (silinen=%s)", olay_adi, silinen)
            return silinen

    def once(
        self,
        olay_adi: str,
        handler: EventHandler,
        *,
        priority: int = 0,
    ) -> str:
        """Yalnızca bir kez tetiklenen abonelik."""
        return self.subscribe(olay_adi, handler, priority=priority, bir_kez=True)

    def clear(self) -> None:
        """Tüm abonelikleri temizler."""
        with self._kilit:
            self._aboneler.clear()
        self._log.info("EventBus temizlendi: %s", self.ad)

    def abone_sayisi(self, olay_adi: Optional[str] = None) -> int:
        """Toplam veya belirli olay için abone sayısı."""
        with self._kilit:
            if olay_adi is None:
                return sum(len(v) for v in self._aboneler.values())
            return len(self._aboneler.get(olay_adi, []))

    def publish_sync(
        self,
        olay_adi: str,
        veri: Optional[dict[str, Any]] = None,
        *,
        kaynak: str = "system",
        oncelik: int = 0,
    ) -> Event:
        """
        Senkron yayın (async handler'lar için yeni event loop yoksa uyarı loglanır).

        Tercihen async ortamlarda ``publish`` kullanın.
        """
        event = Event(
            ad=olay_adi,
            veri=dict(veri or {}),
            kaynak=kaynak,
            oncelik=oncelik,
        )
        aboneler = self._aboneleri_kopyala(olay_adi)
        self._yayin_sayaci += 1
        self._log.info(
            "Yayın (sync): %s kaynak=%s abone=%s",
            olay_adi,
            kaynak,
            len(aboneler),
        )

        silinecek: list[str] = []
        for abone in aboneler:
            if event.iptal:
                break
            try:
                sonuc = abone.handler(event)
                if inspect.isawaitable(sonuc):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(sonuc)
                    except RuntimeError:
                        asyncio.run(sonuc)
            except Exception:
                self._log.exception(
                    "Handler hatası (sync): %s / %s",
                    olay_adi,
                    abone.handler_id,
                )
            if abone.bir_kez:
                silinecek.append(abone.handler_id)

        for hid in silinecek:
            self.unsubscribe(olay_adi, hid)

        return event

    async def publish(
        self,
        olay_adi: str,
        veri: Optional[dict[str, Any]] = None,
        *,
        kaynak: str = "system",
        oncelik: int = 0,
    ) -> Event:
        """Async yayın — sync ve async handler'ları sırayla (önceliğe göre) çalıştırır."""
        event = Event(
            ad=olay_adi,
            veri=dict(veri or {}),
            kaynak=kaynak,
            oncelik=oncelik,
        )
        aboneler = self._aboneleri_kopyala(olay_adi)
        self._yayin_sayaci += 1
        self._log.info(
            "Yayın: %s kaynak=%s abone=%s veri_keys=%s",
            olay_adi,
            kaynak,
            len(aboneler),
            list(event.veri.keys()),
        )

        silinecek: list[str] = []
        for abone in aboneler:
            if event.iptal:
                self._log.debug("Olay iptal edildi, kalan handler'lar atlandı: %s", olay_adi)
                break
            try:
                sonuc = abone.handler(event)
                if inspect.isawaitable(sonuc):
                    await sonuc
            except Exception:
                self._log.exception(
                    "Handler hatası: %s / %s",
                    olay_adi,
                    abone.handler_id,
                )
            if abone.bir_kez:
                silinecek.append(abone.handler_id)

        for hid in silinecek:
            self.unsubscribe(olay_adi, hid)

        return event

    def _aboneleri_kopyala(self, olay_adi: str) -> list[_Abone]:
        with self._kilit:
            return list(self._aboneler.get(olay_adi, []))

    @property
    def yayin_sayisi(self) -> int:
        return self._yayin_sayaci


# Global paylaşılan olay yolu — Voice, Brain, GUI, Memory, Network, iPhone, Plugin
olay_yolu = EventBus(ad="whitecore")

__all__ = [
    "Event",
    "EventBus",
    "olay_yolu",
    "OLAY_SISTEM_HAZIR",
    "OLAY_SISTEM_KAPANIYOR",
    "OLAY_DURUM_DEGISTI",
    "OLAY_HATA",
    "OLAY_WAKE_WORD",
    "OLAY_DINLEME_BASLADI",
    "OLAY_DINLEME_BITTI",
    "OLAY_STT_SONUC",
    "OLAY_TTS_BASLADI",
    "OLAY_TTS_BITTI",
    "OLAY_DUSUNME_BASLADI",
    "OLAY_YANIT_HAZIR",
    "OLAY_AJAN_PLAN",
    "OLAY_GUI_HAZIR",
    "OLAY_GUI_KOMUT",
    "OLAY_GUI_BILDIRIM",
    "OLAY_HAFIZA_YAZILDI",
    "OLAY_HAFIZA_OKUNDU",
    "OLAY_PREFERANS_DEGISTI",
    "OLAY_AG_BAGLANDI",
    "OLAY_AG_KOPTU",
    "OLAY_CIHAZ_ESLESTI",
    "OLAY_CIHAZ_DURUM",
    "OLAY_IPHONE_BAGLANDI",
    "OLAY_IPHONE_KOPTU",
    "OLAY_MOBIL_KOMUT",
    "OLAY_MOBIL_BILDIRIM",
    "OLAY_MOBIL_PIL",
    "OLAY_PLUGIN_YUKLENDI",
    "OLAY_PLUGIN_KALDIRILDI",
    "OLAY_PLUGIN_HATA",
    "OLAY_SKILL_CALISTI",
    "OLAY_SKILL_HATA",
    "OLAY_SKILL_ONAY",
]

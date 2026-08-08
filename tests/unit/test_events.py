"""core/events.py birim testi + örnek olay akışı."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.events import (
    OLAY_DURUM_DEGISTI,
    OLAY_IPHONE_BAGLANDI,
    OLAY_STT_SONUC,
    OLAY_WAKE_WORD,
    OLAY_YANIT_HAZIR,
    Event,
    EventBus,
    olay_yolu,
)
from core.logger import logger_yapilandir


def test_events() -> None:
    logger_yapilandir(zorla=True)
    bus = EventBus(ad="test")

    siralama: list[str] = []

    def dusuk(event: Event) -> None:
        siralama.append("dusuk")

    def yuksek(event: Event) -> None:
        siralama.append("yuksek")

    async def async_gui(event: Event) -> None:
        await asyncio.sleep(0)
        siralama.append("gui")
        event.veri["gui_gordu"] = True

    bus.subscribe(OLAY_WAKE_WORD, dusuk, priority=1)
    bus.subscribe(OLAY_WAKE_WORD, yuksek, priority=100)
    bus.subscribe(OLAY_WAKE_WORD, async_gui, priority=50)

    async def calistir() -> None:
        event = await bus.publish(
            OLAY_WAKE_WORD,
            {"phrase": "Jarvis"},
            kaynak="voice",
        )
        assert event.veri["phrase"] == "Jarvis"
        assert event.veri.get("gui_gordu") is True

    asyncio.run(calistir())
    assert siralama == ["yuksek", "gui", "dusuk"], siralama

    # unsubscribe
    hid = bus.subscribe("x", lambda e: None)
    assert bus.unsubscribe("x", hid) == 1
    assert bus.abone_sayisi("x") == 0

    # once
    sayac = {"n": 0}

    def bir_kez(event: Event) -> None:
        sayac["n"] += 1

    bus.once("tek", bir_kez)

    async def once_test() -> None:
        await bus.publish("tek", {})
        await bus.publish("tek", {})

    asyncio.run(once_test())
    assert sayac["n"] == 1

    # iptal
    iz: list[str] = []

    def ilk(event: Event) -> None:
        iz.append("ilk")
        event.iptal_et()

    def ikinci(event: Event) -> None:
        iz.append("ikinci")

    bus.subscribe("iptal", ilk, priority=10)
    bus.subscribe("iptal", ikinci, priority=1)

    async def iptal_test() -> None:
        await bus.publish("iptal", {})

    asyncio.run(iptal_test())
    assert iz == ["ilk"]

    # thread-safe smoke: publish_sync
    bus.subscribe("sync", lambda e: e.veri.update({"ok": True}))
    e2 = bus.publish_sync("sync", {"a": 1}, kaynak="test")
    assert e2.veri["ok"] is True

    print("TEST_OK")
    print("priority_order:", siralama)
    print("once_count:", sayac["n"])
    print("cancel_trace:", iz)


async def ornek_akis() -> None:
    """
    Gerçekçi mini akış:
    Voice(wake) → STT → Brain → GUI + Memory + iPhone bildirimi
    """
    logger_yapilandir(zorla=True)
    olay_yolu.clear()
    iz: list[str] = []

    async def voice_wake(event: Event) -> None:
        iz.append("1.voice.wake")
        await olay_yolu.publish(
            OLAY_STT_SONUC,
            {"text": "Bugün hava nasıl?"},
            kaynak="voice",
        )

    async def memory_kaydet(event: Event) -> None:
        iz.append("2.memory.stt")

    async def brain_yanit(event: Event) -> None:
        iz.append("3.brain.think")
        await olay_yolu.publish(
            OLAY_YANIT_HAZIR,
            {"text": "İstanbul'da açık ve 24 derece."},
            kaynak="brain",
        )

    async def gui_goster(event: Event) -> None:
        iz.append("4.gui.show")

    async def iphone_bildirim(event: Event) -> None:
        iz.append("5.iphone.notify")

    async def durum(event: Event) -> None:
        iz.append(f"durum:{event.veri.get('durum')}")

    # Öncelikler: memory önce kaydetsin, sonra brain
    olay_yolu.subscribe(OLAY_WAKE_WORD, voice_wake, priority=10)
    olay_yolu.subscribe(OLAY_STT_SONUC, memory_kaydet, priority=20)
    olay_yolu.subscribe(OLAY_STT_SONUC, brain_yanit, priority=10)
    olay_yolu.subscribe(OLAY_YANIT_HAZIR, gui_goster, priority=10)
    olay_yolu.subscribe(OLAY_YANIT_HAZIR, iphone_bildirim, priority=5)
    olay_yolu.subscribe(OLAY_DURUM_DEGISTI, durum, priority=1)
    olay_yolu.subscribe(
        OLAY_IPHONE_BAGLANDI,
        lambda e: iz.append("iphone.online"),
        priority=1,
    )

    await olay_yolu.publish(OLAY_DURUM_DEGISTI, {"durum": "dinliyor"}, kaynak="core")
    await olay_yolu.publish(OLAY_IPHONE_BAGLANDI, {"device": "iPhone"}, kaynak="mobile")
    await olay_yolu.publish(OLAY_WAKE_WORD, {"phrase": "Jarvis"}, kaynak="voice")
    await olay_yolu.publish(OLAY_DURUM_DEGISTI, {"durum": "hazir"}, kaynak="core")

    print("ORNEK_AKIS_OK")
    for adim in iz:
        print(" ->", adim)


if __name__ == "__main__":
    test_events()
    print("---")
    asyncio.run(ornek_akis())

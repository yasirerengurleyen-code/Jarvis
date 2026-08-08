"""gui/yoneticisi.py birim testleri."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.yoneticisi import GuiYoneticisi, pyside_var_mi, qapp_al


def test_pyside_ve_qapp() -> None:
    assert pyside_var_mi() is True
    app = qapp_al([])
    assert app is not None
    assert qapp_al([]) is app


def test_gui_yoneticisi_mesaj() -> None:
    async def _run() -> None:
        from config.ayarlar import Ayarlar
        from core.events import EventBus, OLAY_GUI_HAZIR

        ayar = Ayarlar()
        ayar.yukle()
        bus = EventBus(ad="test.gui")
        hazir: list[bool] = []

        def _on_hazir(_e=None):  # noqa: ANN001
            hazir.append(True)

        bus.subscribe(OLAY_GUI_HAZIR, _on_hazir)

        async def echo(m: str) -> str:
            return f"Yanıt: {m}"

        gui = GuiYoneticisi(
            ayarlar=ayar,
            bus=bus,
            brain_callback=echo,
            goster=False,
            hava_zorla_sahte=True,
        )
        try:
            await gui.baslat()
            assert gui.calisiyor is True
            assert hazir == [True]
            assert gui.pencere is not None

            yanit = await gui.mesaj_isle("merhaba")
            gui.olay_isle()
            await asyncio.sleep(0.05)
            gui.olay_isle()

            assert yanit == "Yanıt: merhaba"
            # UI timer güncellemesi
            assert any(
                "Yanıt: merhaba" in m.icerik for m in gui.pencere.sohbet.model.mesajlar
            )
        finally:
            await gui.durdur()
            assert gui.calisiyor is False

    asyncio.run(_run())


def test_gui_sinyal_yolu() -> None:
    async def _run() -> None:
        from config.ayarlar import Ayarlar
        from core.events import EventBus

        gui = GuiYoneticisi(
            ayarlar=Ayarlar(),
            bus=EventBus(ad="test.gui2"),
            brain_callback=lambda m: f"OK:{m}",
            goster=False,
            hava_zorla_sahte=True,
        )
        gui.ayarlar.yukle()
        try:
            await gui.baslat()
            gui.pencere.sohbet.giris_ayarla("test")
            gui.pencere.sohbet.gonder()
            # sinyal → create_task
            await asyncio.sleep(0.15)
            gui.olay_isle()
            await asyncio.sleep(0.05)
            gui.olay_isle()
            assert any("OK:test" in m.icerik for m in gui.pencere.sohbet.model.mesajlar)
        finally:
            await gui.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_pyside_ve_qapp()
    test_gui_yoneticisi_mesaj()
    test_gui_sinyal_yolu()
    print("OK test_yoneticisi")

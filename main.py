"""
main.py
-------
WhiteCore AI giriş noktası.

J.A.R.V.I.S. çekirdek motorunu (ve isteğe bağlı GUI) başlatır.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Proje kökünü path'e ekle (doğrudan python main.py için)
_KOK = Path(__file__).resolve().parent
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))


def _utf8_konsol() -> None:
    """Windows konsolunda UTF-8 çıktıyı mümkün olduğunca etkinleştirir."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


async def _gui_dongu(engine: object, *, bekle_saniye: float | None) -> None:
    """
    Asyncio ile Qt olaylarını birlikte pompalar.

    bekle_saniye verilirse süre dolunca döner (demo).
    Aksi halde pencere kapanana / Ctrl+C'ye kadar sürer.
    """
    gui = getattr(engine, "gui", None)
    if gui is None:
        if bekle_saniye is not None:
            await asyncio.sleep(max(0.1, bekle_saniye))
        else:
            while True:
                await asyncio.sleep(1.0)
        return

    baslangic = asyncio.get_running_loop().time()
    while True:
        gui.olay_isle()
        pencere = getattr(gui, "pencere", None)
        if pencere is None:
            break
        # Yalnızca kullanıcı kapattıysa çık (isVisible tam ekranda yanıltıcı olabiliyor)
        try:
            if bool(getattr(pencere, "kapandi", False)):
                break
        except Exception:
            break

        if bekle_saniye is not None:
            if asyncio.get_running_loop().time() - baslangic >= bekle_saniye:
                break

        await asyncio.sleep(0.02)


async def _calistir(
    *,
    demo: bool,
    bekle_saniye: float,
    gui: bool,
) -> int:
    from core.engine import Engine
    from core.exceptions import WhiteCoreError
    from core.logger import logger_al

    # GUI demo / CI: offscreen güvenli
    if gui and demo and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Gerçek masaüstü GUI: testlerden kalan offscreen pencereyi görünmez yapar
    if gui and not demo:
        plat = os.environ.get("QT_QPA_PLATFORM", "").lower()
        if plat in {"", "offscreen", "minimal", "null"}:
            if sys.platform.startswith("win"):
                os.environ["QT_QPA_PLATFORM"] = "windows"
            else:
                os.environ.pop("QT_QPA_PLATFORM", None)

    engine = Engine()
    try:
        rapor = await engine.baslat(
            gui=gui,
            gui_goster=bool(gui and not demo),
            gui_hava_sahte=bool(gui and demo),
        )
    except WhiteCoreError as exc:
        print(f"[HATA] {exc}", file=sys.stderr)
        return 1

    if not rapor.basarili:
        engine.konsol_loglarini_ac()
        print("")
        print("[FAIL] Engine başlatılamadı")
        print(f"Hata: {rapor.hata}")
        return 1

    for satir in engine.banner_satirlari():
        print(satir)
    for satir in engine.basari_satirlari():
        print(satir)
    print("")
    print(f"Başlatma süresi: {rapor.sure_saniye:.3f}s")
    print(f"Aktif: {', '.join(rapor.aktif_moduller)}")

    engine.konsol_loglarini_ac()
    log = logger_al("main")
    log.info("main.py — demo=%s gui=%s", demo, gui)

    try:
        if demo:
            await _gui_dongu(engine, bekle_saniye=max(0.1, bekle_saniye))
        elif gui:
            print("(Pencereyi kapatın veya Ctrl+C)")
            await _gui_dongu(engine, bekle_saniye=None)
        else:
            print("(Çıkmak için Ctrl+C)")
            while True:
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    finally:
        await engine.durdur()
        print("")
        print("J.A.R.V.I.S. kapatıldı.")

    return 0 if rapor.basarili else 1


def main(argv: list[str] | None = None) -> int:
    _utf8_konsol()
    # API anahtarları: proje kökü .env (OPENAI_API_KEY=...)
    try:
        from config.env import env_yukle

        env_yukle()
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="WhiteCore AI — J.A.R.V.I.S.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Kısa demo: sistemi başlatır, birkaç saniye bekler, kapatır",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="PySide6 masaüstü arayüzünü başlatır",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1.0,
        help="--demo modunda bekleme süresi (saniye)",
    )
    args = parser.parse_args(argv)

    try:
        return asyncio.run(
            _calistir(demo=args.demo, bekle_saniye=args.wait, gui=args.gui)
        )
    except KeyboardInterrupt:
        print("\nKesildi.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

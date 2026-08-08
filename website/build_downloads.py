"""
website/build_downloads.py
--------------------------
İndirme paketlerini üretir:
  - WhiteCoreAI-Windows-Portable.zip
  - WhiteCoreAI-Setup.exe  (PyInstaller varsa)
  - WhiteCore-iOS.zip / iPadOS / Android
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent
REPO = KOK.parent
PACK = KOK / "packaging"
OUT = KOK / "downloads"


def _zip_dir(kaynak: Path, hedef_zip: Path, *, arc_prefix: str = "") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if hedef_zip.exists():
        hedef_zip.unlink()
    with zipfile.ZipFile(hedef_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for yol in sorted(kaynak.rglob("*")):
            if yol.is_file():
                arc = f"{arc_prefix}/{yol.relative_to(kaynak).as_posix()}" if arc_prefix else yol.relative_to(kaynak).as_posix()
                zf.write(yol, arcname=arc.lstrip("/"))
    print(f"OK {hedef_zip.name} ({hedef_zip.stat().st_size} bayt)")


def windows_portable() -> None:
    """Portable ZIP: başlatıcı + kurulum notu (+ kısa README)."""
    staging = OUT / "_staging_win"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copy2(PACK / "windows" / "KURULUM.txt", staging / "KURULUM.txt")
    shutil.copy2(PACK / "windows" / "start-jarvis.bat", staging / "start-jarvis.bat")
    # Proje köküne taşıyınca çalışsın diye not
    (staging / "README-PORTABLE.txt").write_text(
        "Bu dosyaları WhiteCoreAI proje köküne kopyalayın "
        "(main.py ile aynı klasör), sonra start-jarvis.bat çalıştırın.\n",
        encoding="utf-8",
    )
    _zip_dir(staging, OUT / "WhiteCoreAI-Windows-Portable.zip", arc_prefix="WhiteCoreAI-Portable")
    shutil.rmtree(staging, ignore_errors=True)


def mobil_paketler() -> None:
    _zip_dir(PACK / "ios", OUT / "WhiteCore-iOS.zip", arc_prefix="WhiteCore-iOS")
    _zip_dir(PACK / "ipados", OUT / "WhiteCore-iPadOS.zip", arc_prefix="WhiteCore-iPadOS")
    _zip_dir(PACK / "android", OUT / "WhiteCore-Android.zip", arc_prefix="WhiteCore-Android")


def windows_exe() -> bool:
    """PyInstaller ile Setup.exe üret. Yoksa stub uyarı dosyası yazılmaz — bat wrapper."""
    OUT.mkdir(parents=True, exist_ok=True)
    launcher = PACK / "launcher" / "whitecore_setup.py"
    dist = OUT / "_pyi_dist"
    work = OUT / "_pyi_work"
    exe_hedef = OUT / "WhiteCoreAI-Setup.exe"

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller yok — kuruluyor…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller", "-q"],
        )

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "WhiteCoreAI-Setup",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        str(launcher),
    ]
    print("PyInstaller:", " ".join(cmd))
    subprocess.check_call(cmd)
    uretilen = dist / "WhiteCoreAI-Setup.exe"
    if not uretilen.is_file():
        raise FileNotFoundError(uretilen)
    shutil.copy2(uretilen, exe_hedef)
    print(f"OK {exe_hedef.name} ({exe_hedef.stat().st_size} bayt)")
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    return True


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    windows_portable()
    mobil_paketler()
    try:
        windows_exe()
    except Exception as exc:
        print(f"UYARI: EXE uretilemedi ({exc})")
        # Yedek: bat'ı .cmd olarak kopyala — kullanıcıya exe şartsa tekrar dene
        yedek = OUT / "WhiteCoreAI-Setup.exe"
        if not yedek.exists():
            print("EXE atlandi; ZIP paketleri hazir.")
            return 1
    print("Indirme paketleri hazir:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

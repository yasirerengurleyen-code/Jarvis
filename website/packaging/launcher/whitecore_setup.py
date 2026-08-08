"""
WhiteCore AI — Windows kurulum / başlatıcı (.exe kaynağı).

PyInstaller ile tek dosya EXE üretilir.
Jarvis projesini bulur veya indirme klasörüne yönlendirir.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


def _aday_kokler() -> list[Path]:
    burasi = Path(sys.executable).resolve().parent
    adaylar = [
        burasi,
        burasi.parent,
        Path.cwd(),
        Path.home() / "WhiteCoreAI",
        Path("C:/Users") / os.environ.get("USERNAME", "") / "WhiteCoreAI",
    ]
    # EXE yanında portable ZIP açılmış olabilir
    for p in list(adaylar):
        adaylar.append(p / "WhiteCoreAI")
    uniq: list[Path] = []
    for p in adaylar:
        try:
            r = p.resolve()
        except Exception:
            continue
        if r not in uniq:
            uniq.append(r)
    return uniq


def _proje_bul() -> Path | None:
    for kok in _aday_kokler():
        if (kok / "main.py").is_file():
            return kok
    return None


def _python_bul(kok: Path) -> Path | None:
    venv = kok / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return venv
    return Path(sys.executable) if sys.executable else None


def baslat() -> None:
    kok = _proje_bul()
    root = tk.Tk()
    root.withdraw()
    root.title("WhiteCore AI")

    if kok is None:
        messagebox.showinfo(
            "WhiteCore AI",
            "Proje klasörü bulunamadı.\n\n"
            "1) WhiteCoreAI-Windows-Portable.zip dosyasını indirip açın\n"
            "2) Bu kurulum EXE'sini proje klasörüne koyun\n"
            "3) Tekrar çalıştırın\n\n"
            "veya: python main.py --gui",
        )
        root.destroy()
        return

    py = _python_bul(kok)
    if py is None:
        messagebox.showerror("WhiteCore AI", "Python bulunamadı.")
        root.destroy()
        return

    try:
        subprocess.Popen(
            [str(py), str(kok / "main.py"), "--gui"],
            cwd=str(kok),
            close_fds=True,
        )
        messagebox.showinfo(
            "WhiteCore AI",
            f"J.A.R.V.I.S. başlatılıyor…\n\n{kok}",
        )
    except Exception as exc:
        messagebox.showerror("WhiteCore AI", f"Başlatılamadı:\n{exc}")
    finally:
        root.destroy()


if __name__ == "__main__":
    baslat()

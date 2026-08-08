"""
skills/system/program_ac.py
---------------------------
Program / uygulama açma skill'i.

Görev:
- Komuttan hedef uygulama adını çıkarmak
- Windows'ta os.startfile / PATH üzerinden başlatmak
- Bilinen kısayollar (notepad, calc, chrome, code, …)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Any, Optional

from skills.taban import SkillTabani

# Bilinen uygulama takma adları → çalıştırılabilir / URI
_TAKMA: dict[str, str] = {
    "notepad": "notepad.exe",
    "not defteri": "notepad.exe",
    "hesap makinesi": "calc.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "dosya gezgini": "explorer.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "code": "code",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
}


def hedef_ayikla(komut: str) -> Optional[str]:
    """
    'notepad aç', 'chrome ile aç', 'program aç calc' vb. içinden hedefi çıkarır.
    """
    n = (komut or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    if not n:
        return None

    # Bilinen takmaları uzun olandan kısaya dene
    for takma in sorted(_TAKMA.keys(), key=len, reverse=True):
        if takma in n:
            return takma

    kaliplar = [
        r"(?:program|uygulama|app)\s+aç\s+(.+)$",
        r"aç\s+(.+)$",
        r"open\s+(.+)$",
        r"(.+)\s+aç$",
        r"(.+)\s+aç\s*$",
    ]
    for k in kaliplar:
        m = re.search(k, n)
        if m:
            aday = m.group(1).strip(" .\"'")
            # dolgu kelimeleri temizle
            aday = re.sub(
                r"^(lütfen|please|bir|the)\s+",
                "",
                aday,
            ).strip()
            if aday and aday not in {"program", "uygulama", "app"}:
                return aday
    return None


def hedef_coz(hedef: str) -> str:
    """Takma adı gerçek komuta çevirir."""
    h = (hedef or "").strip().lower()
    if h in _TAKMA:
        return _TAKMA[h]
    return hedef.strip()


def program_baslat(hedef: str, *, dry_run: bool = False) -> dict[str, Any]:
    """
    Programı başlatır.

    dry_run=True ise yalnızca çözümlenmiş komutu döner (test).
    """
    cozulmus = hedef_coz(hedef)
    if dry_run:
        return {
            "target": hedef,
            "resolved": cozulmus,
            "started": False,
            "dry_run": True,
        }

    # PATH'te ara
    yol = shutil.which(cozulmus)
    calistirilacak = yol or cozulmus

    if sys.platform.startswith("win"):
        try:
            # .exe / PATH bulunduysa
            if yol:
                subprocess.Popen(  # noqa: S603
                    [yol],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # startfile: kayıtlı uygulamalar / URI
                os.startfile(calistirilacak)  # type: ignore[attr-defined]  # noqa: S606
            return {
                "target": hedef,
                "resolved": cozulmus,
                "path": yol,
                "started": True,
            }
        except OSError as exc:
            # son çare: cmd start
            try:
                subprocess.Popen(  # noqa: S603, S607
                    ["cmd", "/c", "start", "", calistirilacak],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {
                    "target": hedef,
                    "resolved": cozulmus,
                    "started": True,
                    "fallback": "cmd_start",
                }
            except OSError:
                raise RuntimeError(f"Program açılamadı: {hedef} ({exc})") from exc

    # POSIX
    try:
        subprocess.Popen(  # noqa: S603
            [calistirilacak],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"target": hedef, "resolved": cozulmus, "path": yol, "started": True}
    except OSError as exc:
        raise RuntimeError(f"Program açılamadı: {hedef} ({exc})") from exc


class ProgramAcSkill(SkillTabani):
    """Uygulama / program açar."""

    ad = "program_ac"
    aciklama = "Bilgisayarda program veya uygulama açar"
    kategori = "system"
    tehlikeli = False
    anahtarlar = (
        "program aç",
        "uygulama aç",
        "notepad",
        "hesap makinesi",
        "chrome",
        "vscode",
        "vs code",
        "explorer",
        "aç",
    )
    ornekler = (
        "Notepad aç",
        "Chrome'u aç",
        "Program aç calc",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        dry_run = bool(kwargs.get("dry_run", False))
        hedef = kwargs.get("hedef") or hedef_ayikla(komut)
        if not hedef:
            return self.hata(
                "Açılacak program anlaşılamadı",
                veri={"komut": komut},
            )
        try:
            bilgi = program_baslat(str(hedef), dry_run=dry_run)
        except Exception as exc:
            return self.hata(str(exc), veri={"hedef": hedef})
        return self.ok(
            f"Program başlatıldı: {bilgi.get('resolved', hedef)}",
            veri=bilgi,
        )


# Varsayılan örnek
program_ac_skill = ProgramAcSkill()

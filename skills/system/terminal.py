"""
skills/system/terminal.py
-------------------------
Terminal / kabuk komutu çalıştırma skill'i.

Görev:
- Komuttan shell ifadesini ayıklamak
- config.security.allow_terminal kapalıysa reddetmek
- Tehlikeli işlem: kullanıcı onayı zorunlu
- dry_run ile güvenli test
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any, Optional

from skills.taban import SkillTabani

# Açıkça engellenen kalıplar (onay olsa bile — ekstra güvenlik)
_ENGEL_KALIPLAR = (
    r"rm\s+-rf\s+/",
    r"format\s+[a-z]:",
    r"del\s+/f\s+/s\s+/q\s+[a-z]:\\",
    r"mkfs\.",
    r":\(\)\s*\{\s*:\|:&\s*\};:",  # fork bomb
)


def komut_ayikla(metin: str) -> Optional[str]:
    """
    'terminal dir', 'komut çalıştır echo hi', 'shell: ls' vb.
    """
    n = (metin or "").strip()
    if not n:
        return None

    kaliplar = [
        r"(?i)^(?:terminal|shell|cmd|powershell)\s*[:：]\s*(.+)$",
        r"(?i)^(?:terminal|shell|cmd)\s+(.+)$",
        r"(?i)^(?:komut\s+çalıştır|komut\s+calistir|run\s+command)\s+(.+)$",
        r"(?i)^(?:çalıştır|calistir|run)\s+(.+)$",
    ]
    for k in kaliplar:
        m = re.search(k, n)
        if m:
            return m.group(1).strip()
    # doğrudan komut gibi duruyorsa (tek satır, skill adı yok)
    if not re.search(r"(?i)\b(terminal|shell|komut)\b", n):
        return None
    return None


def komut_engelli_mi(komut: str) -> bool:
    """Sert engel listesi."""
    for k in _ENGEL_KALIPLAR:
        if re.search(k, komut, flags=re.IGNORECASE):
            return True
    return False


def terminal_calistir(
    komut: str,
    *,
    timeout: float = 30.0,
    dry_run: bool = False,
    kabuk: Optional[str] = None,
) -> dict[str, Any]:
    """
    Komutu çalıştırır; stdout/stderr döner.

    Windows varsayılan: cmd /c
    """
    komut = (komut or "").strip()
    if not komut:
        raise ValueError("Boş terminal komutu")

    if komut_engelli_mi(komut):
        raise PermissionError(f"Engellenmiş komut: {komut}")

    if dry_run:
        return {
            "command": komut,
            "dry_run": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }

    if sys.platform.startswith("win"):
        if (kabuk or "").lower() == "powershell":
            args = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                komut,
            ]
        else:
            args = ["cmd", "/c", komut]
    else:
        args = ["sh", "-c", komut]

    tamam = subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return {
        "command": komut,
        "args": args,
        "dry_run": False,
        "returncode": int(tamam.returncode),
        "stdout": (tamam.stdout or "")[:8000],
        "stderr": (tamam.stderr or "")[:4000],
    }


class TerminalSkill(SkillTabani):
    """Kabuk komutu çalıştırır (onay gerekli)."""

    ad = "terminal"
    aciklama = "Terminal / cmd / powershell komutu çalıştırır"
    kategori = "system"
    tehlikeli = True
    tehlike_eylemi = "terminal_command"
    anahtarlar = (
        "terminal",
        "shell",
        "cmd",
        "powershell",
        "komut çalıştır",
        "komut calistir",
        "run command",
    )
    ornekler = (
        "terminal dir",
        "komut çalıştır echo merhaba",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        # Yönetici zaten onayladıysa buraya gelir; yine de çift kontrol
        engel = self.onay_kontrol(
            onaylandi=bool(kwargs.get("onaylandi")),
            ayar_yonetici=kwargs.get("ayar_yonetici")
            or getattr(kwargs.get("baglam"), "ayar_yonetici", None),
        )
        if engel is not None:
            return engel

        # config: allow_terminal
        ayar = kwargs.get("ayar_yonetici")
        if ayar is None and kwargs.get("baglam") is not None:
            ayar = getattr(kwargs["baglam"], "ayar_yonetici", None)
        if ayar is not None:
            try:
                if not getattr(ayar, "yuklendi", False):
                    ayar.yukle()
                if not bool(ayar.al("security.allow_terminal", True)):
                    return self.hata(
                        "Terminal komutları config ile kapalı (security.allow_terminal=false)"
                    )
            except Exception:
                pass

        dry_run = bool(kwargs.get("dry_run", False))
        timeout = float(kwargs.get("timeout", 30.0))
        kabuk = kwargs.get("kabuk")
        shell_komut = kwargs.get("shell_komut") or komut_ayikla(komut)
        if not shell_komut:
            return self.hata(
                "Çalıştırılacak komut anlaşılamadı. Örnek: terminal dir",
                veri={"komut": komut},
            )

        try:
            bilgi = terminal_calistir(
                shell_komut,
                timeout=timeout,
                dry_run=dry_run,
                kabuk=kabuk,
            )
        except subprocess.TimeoutExpired:
            return self.hata(
                f"Komut zaman aşımına uğradı ({timeout}s)",
                veri={"command": shell_komut},
            )
        except Exception as exc:
            return self.hata(str(exc), veri={"command": shell_komut})

        kod = int(bilgi.get("returncode", 0))
        if kod != 0 and not dry_run:
            return self.hata(
                f"Komut hata kodu: {kod}",
                veri=bilgi,
            )
        return self.ok(
            "Komut çalıştırıldı" if not dry_run else "Komut doğrulandı (dry_run)",
            veri=bilgi,
        )


terminal_skill = TerminalSkill()

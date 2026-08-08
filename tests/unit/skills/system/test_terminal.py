"""skills/system/terminal.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from skills.system.terminal import (
    TerminalSkill,
    komut_ayikla,
    komut_engelli_mi,
    terminal_calistir,
)
from skills.yoneticisi import SkillYoneticisi


def test_komut_ayikla() -> None:
    assert komut_ayikla("terminal dir") == "dir"
    assert komut_ayikla("komut çalıştır echo hi") == "echo hi"
    assert komut_ayikla("shell: echo x") == "echo x"
    assert komut_ayikla("merhaba dünya") is None


def test_engel_ve_dry_run() -> None:
    assert komut_engelli_mi("rm -rf /") is True
    assert komut_engelli_mi("echo hello") is False
    bil = terminal_calistir("echo test", dry_run=True)
    assert bil["dry_run"] is True
    assert bil["command"] == "echo test"


def test_skill_onay_ve_dry() -> None:
    async def _run() -> None:
        from config.ayarlar import Ayarlar

        s = TerminalSkill()
        assert s.tehlikeli is True
        r0 = await s.calistir("terminal echo x", onaylandi=False)
        assert r0.durum == YetenekDurumu.ONAY_BEKLIYOR

        r1 = await s.calistir("terminal echo x", onaylandi=True, dry_run=True)
        assert r1.basarili
        assert r1.veri["dry_run"] is True

        ayar = Ayarlar()
        ayar.yukle()
        y = SkillYoneticisi(ayar_yonetici=ayar, skilller=[s])
        await y.baslat()
        r2 = await y.calistir("terminal echo merhaba", onaylandi=True, dry_run=True)
        assert r2.basarili
        await y.durdur()

    asyncio.run(_run())


def test_gercek_echo_windows() -> None:
    """Güvenli, kısa echo — onaylı gerçek çalıştırma."""
    if not sys.platform.startswith("win"):
        return
    bil = terminal_calistir("echo WhiteCore", timeout=10.0, dry_run=False)
    assert bil["returncode"] == 0
    assert "WhiteCore" in (bil["stdout"] + bil["stderr"])


if __name__ == "__main__":
    test_komut_ayikla()
    test_engel_ve_dry_run()
    test_skill_onay_ve_dry()
    test_gercek_echo_windows()
    print("OK test_terminal")

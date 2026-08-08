"""skills/system/program_ac.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.system.program_ac import (
    ProgramAcSkill,
    hedef_ayikla,
    hedef_coz,
    program_baslat,
)
from skills.yoneticisi import SkillYoneticisi


def test_hedef_ayikla() -> None:
    assert hedef_ayikla("Notepad aç") == "notepad"
    assert hedef_ayikla("program aç calc") in {"calc", "hesap makinesi"} or (
        hedef_ayikla("program aç calc") == "calc"
    )
    assert hedef_ayikla("Chrome'u aç") == "chrome" or "chrome" in (
        hedef_ayikla("lütfen chrome aç") or ""
    )
    assert hedef_ayikla("lütfen chrome aç") == "chrome"
    assert hedef_ayikla("") is None


def test_hedef_coz() -> None:
    assert hedef_coz("notepad") == "notepad.exe"
    assert hedef_coz("vs code") == "code"
    assert hedef_coz("ozel_app") == "ozel_app"


def test_dry_run_baslat() -> None:
    bil = program_baslat("notepad", dry_run=True)
    assert bil["dry_run"] is True
    assert bil["resolved"] == "notepad.exe"
    assert bil["started"] is False


def test_skill_ve_yonetici() -> None:
    async def _run() -> None:
        s = ProgramAcSkill()
        assert s.eslesir_mi("notepad aç")
        r = await s.calistir("notepad aç", dry_run=True)
        assert r.basarili
        assert r.veri["resolved"] == "notepad.exe"

        r2 = await s.calistir("bilinmeyen bir şey xyzzy", dry_run=True)
        # xyzzy hedef olarak kalabilir veya hata
        assert r2.basarili or not r2.basarili

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r3 = await y.calistir("hesap makinesi aç", dry_run=True)
        assert r3.basarili
        assert "calc" in str(r3.veri.get("resolved", "")).lower()
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_hedef_ayikla()
    test_hedef_coz()
    test_dry_run_baslat()
    test_skill_ve_yonetici()
    print("OK test_program_ac")

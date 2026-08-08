"""Aşama 8 — Engine Automation (akıllı ajan) köprüsü + demo duman testi."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from config.ayarlar import Ayarlar
from core.engine import Engine
from core.events import OLAY_AJAN_PLAN
from core.logger import logger_yapilandir


def _gecici_config(*, automation_dry: bool = True) -> tuple[Ayarlar, Path]:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e8.db"
    data_dir = tmp / "data"
    cfg_yol = tmp / "config.json"
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek.setdefault("project", {})
    gercek["project"]["data_dir"] = str(data_dir)
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine-asama8"
    gercek.setdefault("network", {})
    gercek["network"]["enabled"] = True
    gercek["network"]["dry_run"] = True
    gercek.setdefault("sync", {})
    gercek["sync"]["enabled"] = True
    gercek["sync"]["dry_run"] = True
    gercek.setdefault("mobile", {})
    gercek["mobile"]["enabled"] = False
    gercek["mobile"]["bridge_enabled"] = False
    gercek["mobile"]["dry_run"] = False
    gercek.setdefault("automation", {})
    gercek["automation"]["enabled"] = True
    gercek["automation"]["dry_run"] = bool(automation_dry)
    gercek["automation"]["smart_agent"] = True
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")
    return Ayarlar(cfg_yol), tmp


def test_engine_automation_kopru() -> None:
    """Engine.automation yaşam döngüsü + skills/EventBus köprüsü (Aşama 8 #8)."""
    logger_yapilandir(zorla=True)
    cfg, tmp = _gecici_config(automation_dry=True)
    engine = Engine(ayar_yonetici=cfg)
    plan_olaylari: list[object] = []

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "automation" in rapor.adimlar
        assert "automation" in rapor.aktif_moduller
        assert "automation" not in rapor.bekleyen_moduller
        assert "automation" not in Engine.BEKLEYEN_MODULLER

        assert engine.automation is not None and engine.automation.calisiyor
        assert engine.automation.motor == "dry_run"
        assert engine.automation.skills is engine.skills
        assert engine.automation.bus is engine.bus
        ozet = engine.automation.ozet()
        assert ozet["running"] is True
        assert ozet["skills"]["bound"] is True
        assert ozet["agent_bound"] is True

        # EventBus: OLAY_AJAN_PLAN ajan/planlayıcıdan Engine bus'ına düşer
        engine.bus.subscribe(OLAY_AJAN_PLAN, plan_olaylari.append, priority=50)
        plan = engine.automation.planla(
            "Yeni Python projesi oluştur",
            dry_run=True,
            yayinla=True,
        )
        assert plan.adim_sayisi >= 1
        assert len(plan_olaylari) >= 1

        satirlar = engine.basari_satirlari()
        assert any("Automation / Akıllı Ajan başlatıldı" in s for s in satirlar)
        assert any("motor=dry_run" in s for s in satirlar if "Automation" in s)

        await engine.durdur()
        assert engine.automation is None

    asyncio.run(_run())
    print("TEST_OK_engine_asama8_automation_kopru")
    print("tmp:", tmp)


def test_engine_automation_kapali() -> None:
    """automation.enabled=false ve dry_run=false → runtime pasif."""
    logger_yapilandir(zorla=True)
    cfg, _tmp = _gecici_config(automation_dry=False)
    cfg.yukle()
    veri = json.loads(cfg.yol.read_text(encoding="utf-8"))
    veri["automation"]["enabled"] = False
    veri["automation"]["dry_run"] = False
    cfg.yol.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    cfg2 = Ayarlar(cfg.yol)
    engine = Engine(ayar_yonetici=cfg2)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert engine.automation is None
        assert "automation" in rapor.bekleyen_moduller
        satirlar = engine.basari_satirlari()
        assert any("Automation / Akıllı Ajan beklemede" in s for s in satirlar)
        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK_engine_automation_kapali")


def test_main_demo_automation_duman() -> None:
    """main.py --demo çıktısında Automation / Akıllı Ajan durumu net görünür (Aşama 8 #9)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    sonuc = subprocess.run(
        [
            sys.executable,
            str(KOK / "main.py"),
            "--demo",
            "--wait",
            "0.3",
        ],
        cwd=str(KOK),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=90,
        check=False,
    )
    birlesik = (sonuc.stdout or "") + "\n" + (sonuc.stderr or "")
    assert sonuc.returncode == 0, birlesik[-2000:]
    assert "Automation / Akıllı Ajan başlatıldı" in birlesik
    assert "max_steps=" in birlesik
    assert "automation" in birlesik
    # Skills / Network / Mobile ile aynı checklist dilinde
    assert "Skills başlatıldı" in birlesik
    assert "Network başlatıldı" in birlesik
    assert "Mobile / iPhone başlatıldı" in birlesik
    print("TEST_OK_demo_automation_duman")


if __name__ == "__main__":
    test_engine_automation_kopru()
    test_engine_automation_kapali()
    test_main_demo_automation_duman()
    print("OK test_engine_asama8")

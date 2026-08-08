"""Aşama 9 — Engine Vision (EventBus / Config / Logger) köprüsü birim testleri."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from config.ayarlar import Ayarlar
from core.engine import Engine
from core.exceptions import VisionError
from core.logger import logger_yapilandir
from vision.yoneticisi import OLAY_VISION_DURDU


def _gecici_config(*, vision_dry: bool = True, vision_enabled: bool = True) -> tuple[Ayarlar, Path]:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e9.db"
    data_dir = tmp / "data"
    faces = tmp / "faces"
    cfg_yol = tmp / "config.json"
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek.setdefault("project", {})
    gercek["project"]["data_dir"] = str(data_dir)
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine-asama9"
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
    gercek["automation"]["dry_run"] = True
    gercek.setdefault("vision", {})
    gercek["vision"]["enabled"] = bool(vision_enabled)
    gercek["vision"]["dry_run"] = bool(vision_dry)
    gercek["vision"].setdefault("face", {})
    gercek["vision"]["face"]["enabled"] = False
    gercek["vision"]["face"]["camera_permission"] = False
    gercek["vision"]["face"]["local_only"] = True
    gercek["vision"]["face"]["storage_root"] = str(faces)
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")
    return Ayarlar(cfg_yol), tmp


def test_engine_vision_kopru() -> None:
    """Engine.vision yaşam döngüsü + bus/config/yüz gizlilik (Aşama 9 #21)."""
    logger_yapilandir(zorla=True)
    cfg, tmp = _gecici_config(vision_dry=True)
    engine = Engine(ayar_yonetici=cfg)
    vision_olaylari: list[object] = []

    async def _run() -> None:
        # baslat() bus.clear() yapar — abonelik sonrası kurulur
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "vision" in rapor.adimlar
        assert "vision" in rapor.aktif_moduller
        assert "vision" not in rapor.bekleyen_moduller
        assert "vision" not in Engine.BEKLEYEN_MODULLER

        assert engine.vision is not None and engine.vision.calisiyor
        assert engine.vision.motor == "dry_run"
        assert engine.vision.bus is engine.bus
        assert engine.vision.ayarlar is engine.ayarlar
        # Yüz tanıma varsayılan kapalı (config.vision.face.enabled=false)
        assert engine.vision.yuz_tanima_aktif_mi() is False
        ozet = engine.vision.ozet()
        assert ozet["running"] is True
        assert ozet["face_enabled"] is False
        assert ozet["local_only"] is True
        assert ozet["cloud_allowed"] is False

        # VisionError köprüsü — tanıma kapalıyken güvenli hata
        try:
            engine.vision.yuz_tanima(embedding=[0.1, 0.2, 0.3], algila=False)
            raise AssertionError("VisionError beklenirdi (yüz kapalı)")
        except VisionError as exc:
            assert exc.kod is not None

        satirlar = engine.basari_satirlari()
        assert any("Vision başlatıldı" in s for s in satirlar)
        assert any("motor=dry_run" in s for s in satirlar if "Vision" in s)
        assert any("face=False" in s for s in satirlar if "Vision" in s)

        # EventBus: durdur → vision.stopped Engine bus'ına düşer
        engine.bus.subscribe(OLAY_VISION_DURDU, vision_olaylari.append, priority=50)
        await engine.durdur()
        assert engine.vision is None
        assert len(vision_olaylari) >= 1

    asyncio.run(_run())
    print("TEST_OK_engine_asama9_vision_kopru")
    print("tmp:", tmp)


def test_engine_vision_kapali() -> None:
    """vision.enabled=false ve dry_run=false → runtime pasif."""
    logger_yapilandir(zorla=True)
    cfg, _tmp = _gecici_config(vision_dry=False, vision_enabled=False)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert engine.vision is None
        assert "vision" in rapor.bekleyen_moduller
        satirlar = engine.basari_satirlari()
        assert any("Vision beklemede" in s for s in satirlar)
        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK_engine_vision_kapali")


if __name__ == "__main__":
    test_engine_vision_kopru()
    test_engine_vision_kapali()
    print("OK test_engine_asama9")

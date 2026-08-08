"""Aşama 7 — Engine Mobile (iPhone) köprüsü birim testleri."""

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
from core.logger import logger_yapilandir


def _gecici_config(*, mobile_dry: bool = True) -> tuple[Ayarlar, Path]:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e7.db"
    data_dir = tmp / "data"
    cfg_yol = tmp / "config.json"
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek.setdefault("project", {})
    gercek["project"]["data_dir"] = str(data_dir)
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine-asama7"
    gercek.setdefault("network", {})
    gercek["network"]["enabled"] = True
    gercek["network"]["dry_run"] = True
    gercek.setdefault("sync", {})
    gercek["sync"]["enabled"] = True
    gercek["sync"]["dry_run"] = True
    gercek.setdefault("mobile", {})
    gercek["mobile"]["enabled"] = False
    gercek["mobile"]["bridge_enabled"] = False
    gercek["mobile"]["dry_run"] = bool(mobile_dry)
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")
    return Ayarlar(cfg_yol), tmp


def test_engine_mobile_kopru() -> None:
    """Engine.mobile yaşam döngüsü + facade (Aşama 7 #8)."""
    logger_yapilandir(zorla=True)
    cfg, tmp = _gecici_config(mobile_dry=True)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "mobile" in rapor.adimlar
        assert "mobile.iphone_bridge" in rapor.aktif_moduller
        assert "mobile.iphone_bridge" not in rapor.bekleyen_moduller
        assert "mobile.iphone_bridge" not in Engine.BEKLEYEN_MODULLER

        assert engine.mobile is not None and engine.mobile.calisiyor
        assert engine.mobile.motor == "dry_run"
        assert engine.mobile.ozet()["network_bound"] is True
        assert engine.mobile.kopru is not None
        assert engine.mobile.kopru.calisiyor
        assert engine.mobile.shortcuts is not None

        # Bellek içi istemci (ağ kayıt dosyasına yazmadan)
        istemci = engine.mobile.istemci_olustur(
            cihaz_id="iphone-engine",
            ad="Engine Test iPhone",
            kaydet=True,
        )
        assert istemci.cihaz.cihaz_id == "iphone-engine"
        assert "iphone-engine" in getattr(engine.mobile.kopru, "_istemciler", {})

        # Telefonumu Bul / pil / bildirim (sahte istemci)
        await engine.mobile.cihaz_bagla("iphone-engine", ad="Engine Test iPhone")
        istemci.pil_ayarla(88, sarj_oluyor=True)
        find = await engine.mobile.telefonumu_bul("iphone-engine")
        assert find["ok"] is True
        pil = await engine.mobile.pil_durumu("iphone-engine")
        assert pil["ok"] is True
        assert pil["data"]["percent"] == 88
        bild = await engine.mobile.bildirim_gonder(
            "iphone-engine", "Demo", "Aşama 7", veri={"src": "asama7"}
        )
        assert bild["ok"] is True

        satirlar = engine.basari_satirlari()
        assert any("Mobile / iPhone başlatıldı" in s for s in satirlar)
        assert any("1 istemci" in s for s in satirlar)

        await engine.durdur()
        assert engine.mobile is None

    asyncio.run(_run())
    print("TEST_OK_engine_asama7_mobile_kopru")
    print("tmp:", tmp)


def test_engine_mobile_kapali() -> None:
    """mobile.enabled/bridge/dry_run kapalı → runtime pasif."""
    logger_yapilandir(zorla=True)
    # Network dry_run açık kalsın; mobile yine de kapalı kalmalı
    cfg, _tmp = _gecici_config(mobile_dry=False)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert engine.mobile is None
        assert "mobile.iphone_bridge" in rapor.bekleyen_moduller
        # Network dry_run açık olsa bile mobile beklemede
        assert engine.network is not None
        satirlar = engine.basari_satirlari()
        assert any("Mobile / iPhone beklemede" in s for s in satirlar)
        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK_engine_mobile_kapali")


def test_main_demo_mobile_duman() -> None:
    """main.py --demo çıktısında Mobile / iPhone durumu net görünür (Aşama 7 #9)."""
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
    assert "Mobile / iPhone başlatıldı" in birlesik
    assert "primary=ios" in birlesik
    assert "istemci" in birlesik
    assert "mobile.iphone_bridge" in birlesik
    # Skills / Network / Sync ile aynı checklist dilinde
    assert "Skills başlatıldı" in birlesik
    assert "Network başlatıldı" in birlesik
    assert "Sync başlatıldı" in birlesik
    print("TEST_OK_demo_mobile_duman")


if __name__ == "__main__":
    test_engine_mobile_kopru()
    test_engine_mobile_kapali()
    test_main_demo_mobile_duman()
    print("OK test_engine_asama7")

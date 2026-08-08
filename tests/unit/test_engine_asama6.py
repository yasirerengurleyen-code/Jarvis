"""Aşama 6 — Engine Network + Sync köprüsü + demo duman testi."""

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
from network.device.modeller import PlatformTuru


def _gecici_config() -> tuple[Ayarlar, Path]:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e6.db"
    data_dir = tmp / "data"
    cfg_yol = tmp / "config.json"
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek.setdefault("project", {})
    gercek["project"]["data_dir"] = str(data_dir)
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine-asama6"
    gercek.setdefault("network", {})
    gercek["network"]["enabled"] = True
    gercek["network"]["dry_run"] = True
    gercek.setdefault("sync", {})
    gercek["sync"]["enabled"] = True
    gercek["sync"]["dry_run"] = True
    # Canlı devices.json ile karışmasın (max_devices dolu olabilir)
    gercek.setdefault("mobile", {})
    gercek["mobile"]["enabled"] = False
    gercek["mobile"]["bridge_enabled"] = False
    gercek["mobile"]["dry_run"] = False
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")
    return Ayarlar(cfg_yol), tmp


def test_engine_network_sync_kopru() -> None:
    logger_yapilandir(zorla=True)
    cfg, tmp = _gecici_config()
    # Cihaz kaydı test dizinine (NetworkYoneticisi varsayılan yolu kullanmasın diye
    # dry_run yeter; kayit_yolu Engine üzerinden enjekte edilmiyor — varsayılan OK)
    engine = Engine(ayar_yonetici=cfg)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "network" in rapor.adimlar
        assert "sync" in rapor.adimlar
        assert "network.runtime" in rapor.aktif_moduller
        assert "sync.runtime" in rapor.aktif_moduller
        assert "network.runtime" not in rapor.bekleyen_moduller
        assert "sync.runtime" not in rapor.bekleyen_moduller

        assert engine.network is not None and engine.network.calisiyor
        assert engine.sync is not None and engine.sync.calisiyor
        assert engine.network.motor == "dry_run"
        assert engine.sync.motor == "dry_run"
        assert engine.sync.ozet()["network_bound"] is True
        assert engine.network.sohbet is engine.sync.sohbet
        assert engine.network.ozet()["running"] is True

        # Eşleştirme API Engine.network üzerinden
        oturum = await engine.network.eslestirme_baslat(PlatformTuru.IOS)
        assert len(oturum.kod) == 6
        cihaz = await engine.network.kod_ile_eslestir(
            oturum.kod,
            "Engine Test Phone",
            PlatformTuru.IOS,
        )
        assert cihaz.ad == "Engine Test Phone"
        assert any(c.cihaz_id == cihaz.cihaz_id for c in engine.network.cihaz_listele())

        # Sync API köprüsü
        mesajlar = await engine.sync.sohbet_cek(cihaz.cihaz_id)
        assert isinstance(mesajlar, list)
        assert engine.sync.ozet()["modules"]

        satirlar = engine.basari_satirlari()
        assert any("Network başlatıldı" in s for s in satirlar)
        assert any("cihaz" in s for s in satirlar if "Network başlatıldı" in s)
        assert any("Sync başlatıldı" in s for s in satirlar)
        assert any("modül" in s for s in satirlar if "Sync başlatıldı" in s)

        await engine.durdur()
        assert engine.network is None
        assert engine.sync is None

    asyncio.run(_run())
    print("TEST_OK_engine_asama6_kopru")
    print("tmp:", tmp)


def test_engine_network_kapali() -> None:
    logger_yapilandir(zorla=True)
    cfg, _tmp = _gecici_config()
    cfg.yukle()
    # dry_run kapalı + enabled false → runtime bekleyen/pasif
    veri = json.loads(cfg.yol.read_text(encoding="utf-8"))
    veri["network"]["enabled"] = False
    veri["network"]["dry_run"] = False
    veri["sync"]["enabled"] = False
    veri["sync"]["dry_run"] = False
    cfg.yol.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    cfg2 = Ayarlar(cfg.yol)
    engine = Engine(ayar_yonetici=cfg2)

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert engine.network is None
        assert engine.sync is None
        assert "network.runtime" in rapor.bekleyen_moduller
        assert "sync.runtime" in rapor.bekleyen_moduller
        await engine.durdur()

    asyncio.run(_run())
    print("TEST_OK_engine_network_kapali")


def test_main_demo_network_sync_duman() -> None:
    """main.py --demo çıktısında Network/Sync durumu net görünür (Aşama 6 #14)."""
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
    assert "Network başlatıldı" in birlesik
    assert "Sync başlatıldı" in birlesik
    assert "cihaz" in birlesik
    assert "modül" in birlesik
    assert "network.runtime" in birlesik
    assert "sync.runtime" in birlesik
    print("TEST_OK_demo_network_sync_duman")


if __name__ == "__main__":
    test_engine_network_sync_kopru()
    test_engine_network_kapali()
    test_main_demo_network_sync_duman()
    print("OK test_engine_asama6")

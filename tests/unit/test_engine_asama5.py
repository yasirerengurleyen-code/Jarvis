"""Aşama 5 — Engine + Skills entegrasyon / demo duman testi."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from brain.providers.taban import SaglayiciYaniti
from config.ayarlar import Ayarlar
from core.base import YetenekDurumu
from core.engine import Engine
from core.events import OLAY_SKILL_CALISTI, OLAY_SKILL_ONAY
from core.logger import logger_yapilandir
from skills.kayit import desteklenen_skill_adlari, varsayilan_skilller


def _gecici_config() -> tuple[Ayarlar, Path]:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "e5.db"
    cfg_yol = tmp / "config.json"
    gercek = json.loads((KOK / "config" / "config.json").read_text(encoding="utf-8"))
    gercek["memory"]["database_path"] = str(db)
    gercek["ai"]["providers"]["openai"]["api_key"] = "sk-test-engine"
    # Takvim / hatırlatıcı depoları test dizinine
    gercek.setdefault("skills", {})
    cfg_yol.write_text(json.dumps(gercek, ensure_ascii=False), encoding="utf-8")
    return Ayarlar(cfg_yol), tmp


def test_kayit_tamamlari() -> None:
    adlar = desteklenen_skill_adlari()
    assert len(adlar) == 11
    assert "program_ac" in adlar
    assert "hatirlatici" in adlar
    assert "web_arama" in adlar
    skilller = varsayilan_skilller()
    assert len(skilller) == 11
    assert {s.ad for s in skilller} == set(adlar)
    print("TEST_OK_kayit")


def test_engine_asama5_skills() -> None:
    logger_yapilandir(zorla=True)
    cfg, _tmp = _gecici_config()
    engine = Engine(ayar_yonetici=cfg)
    olaylar: list[str] = []

    async def _run() -> None:
        rapor = await engine.baslat()
        assert rapor.basarili, rapor.hata
        assert "skills" in rapor.aktif_moduller
        assert "skills" not in rapor.bekleyen_moduller
        assert engine.skills is not None and engine.skills.calisiyor
        assert engine.skills.adet == 11

        engine.bus.subscribe(OLAY_SKILL_CALISTI, lambda e: olaylar.append(e.ad))
        engine.bus.subscribe(OLAY_SKILL_ONAY, lambda e: olaylar.append(e.ad))

        # Doğal komut → program_ac (dry_run: gerçek süreç yok)
        yanit = await engine.dusun("Notepad aç", dry_run=True)
        assert yanit.saglayici == "skills"
        assert "notepad" in yanit.icerik.lower() or "başlat" in yanit.icerik.lower()
        assert OLAY_SKILL_CALISTI in olaylar

        # Tehlikeli skill → onay bekler
        onay = await engine.skill_calistir("terminal komutu çalıştır: echo test")
        assert onay.durum == YetenekDurumu.ONAY_BEKLIYOR
        assert OLAY_SKILL_ONAY in olaylar

        # Eşleşme yok → Brain
        fake = SaglayiciYaniti(
            icerik="Sohbet yanıtı",
            model="test",
            saglayici="openai",
        )
        with patch.object(
            engine.beyin.saglayici, "sohbet", new=AsyncMock(return_value=fake)
        ):
            beyin_yanit = await engine.dusun("Merhaba, nasılsın?")
        assert beyin_yanit.icerik == "Sohbet yanıtı"
        assert beyin_yanit.saglayici == "openai"

        # beyne_zorla skill'i atlar
        with patch.object(
            engine.beyin.saglayici, "sohbet", new=AsyncMock(return_value=fake)
        ):
            zorla = await engine.dusun("Notepad aç", beyne_zorla=True)
        assert zorla.saglayici == "openai"

        satirlar = engine.basari_satirlari()
        assert any("Skills başlatıldı" in s for s in satirlar)

        await engine.durdur()
        assert engine.skills is None

    asyncio.run(_run())
    print("TEST_OK")
    print("aktif:", ", ".join(engine.rapor.aktif_moduller if engine.rapor else []))


def test_main_demo_skills_duman() -> None:
    """main.py --demo çıktısında Skills durumu net görünür (Aşama 5 #15)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # Konsol log gürültüsünü azalt; banner/basarı satırları stdout'ta kalır
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
    assert "Skills başlatıldı" in birlesik
    assert "11 yetenek" in birlesik
    assert "skills" in (sonuc.stdout or "").lower()
    print("TEST_OK_demo_duman")


if __name__ == "__main__":
    test_kayit_tamamlari()
    test_engine_asama5_skills()
    test_main_demo_skills_duman()

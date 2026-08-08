"""vision/ai/multimodal.py birim testleri (dry_run / sahte / mock analyzer / compose)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import VisionAiSonucu, VisionGorevTuru, VisionMotoru, kare_olustur
from vision.ai.multimodal import (
    OLAY_MULTIMODAL,
    OLAY_MULTIMODAL_BASLADI,
    OLAY_MULTIMODAL_DURDU,
    MultimodalAnaliz,
    multimodal_analiz,
    multimodal_analiz_olustur,
    numpy_var_mi,
    opencv_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_analyzer(mat: Any, metin: str) -> dict[str, Any]:
    _ = mat
    return {
        "answer": f"Birleşik analiz: {metin} — ofis masası ve ekran.",
        "confidence": 0.92,
        "engine": "llm",
        "count": 2,
        "count_label": "nesne",
    }


def test_fabrika_ve_ozet() -> None:
    m = multimodal_analiz_olustur(dry_run=True)
    assert isinstance(m, MultimodalAnaliz)
    assert isinstance(m, ModulTabani)
    assert m.ad == "vision.ai.multimodal"
    assert m.motor == "dry_run"
    assert m.backend == "dry_run"
    ozet = m.ozet()
    assert ozet["dry_run"] is True
    assert ozet["compose"] is True
    assert ozet["use_caption"] is True
    assert ozet["use_ocr"] is True
    assert ozet["use_count"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.ai.multimodal")
    alinan: list[str] = []
    bus.subscribe(OLAY_MULTIMODAL, lambda ev: alinan.append(ev.ad))

    m = MultimodalAnaliz(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = m.analiz("image://dry_run", "Bu görüntüde ne var?")
    assert isinstance(sonuc, VisionAiSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.cevap == ""
    assert sonuc.ek_metin == "Bu görüntüde ne var?"
    assert sonuc.neden == "dry_run"
    assert sonuc.gorev is VisionGorevTuru.AI
    assert m.son_sonuc is sonuc
    assert OLAY_MULTIMODAL in alinan

    d = sonuc.to_dict()
    assert d["answer"] == ""
    assert d["prompt_text"] == "Bu görüntüde ne var?"
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"
    assert d["task"] == "vision_ai"


def test_bos_metin_hata() -> None:
    m = multimodal_analiz_olustur(dry_run=True, olay_yayinla=False)
    try:
        m.analiz("image://x", "   ")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0834"


def test_zorla_sahte() -> None:
    m = multimodal_analiz_olustur(
        dry_run=False,
        zorla_sahte=True,
        compose=False,
        olay_yayinla=False,
    )
    assert m.motor == "sahte"
    sonuc = m.analiz("image://sahte", "Özetle")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.ek_metin == "Özetle"
    assert sonuc.cevap
    assert "Özetle" in (sonuc.cevap or "")
    assert sonuc.guven > 0.0

    s2 = m.analiz(
        b"x",
        "Parkı anlat",
        sahte_cevap="Parkta ağaçlar ve bank.",
    )
    assert "Parkta ağaçlar" in (s2.cevap or "")
    assert "Parkı anlat" in (s2.cevap or "")


def test_mock_analyzer_ve_yanitla() -> None:
    m = MultimodalAnaliz(
        dry_run=False,
        zorla_sahte=False,
        analyzer=_sahte_analyzer,
        compose=False,
        olay_yayinla=False,
    )
    assert m.motor == "llm"
    assert m.backend == "injected"

    sonuc = m.analiz(_MINI_PNG, "Masayı tarif et")
    assert sonuc.motor == VisionMotoru.LLM
    assert sonuc.neden == "injected"
    assert sonuc.ek_metin == "Masayı tarif et"
    assert "Masayı tarif et" in (sonuc.cevap or "")
    assert sonuc.guven >= 0.9
    assert sonuc.sayim == 2
    assert sonuc.sayim_etiket == "nesne"

    assert "Masayı tarif et" in m.yanitla(_MINI_PNG, "Masayı tarif et")


def test_kare_ve_serilestirme() -> None:
    kare = kare_olustur(
        yol="mem://test-multimodal",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    m = multimodal_analiz_olustur(
        dry_run=False,
        analyzer=_sahte_analyzer,
        compose=False,
        olay_yayinla=False,
    )
    sonuc = m.analiz(kare, "Wire testi")
    assert sonuc.kaynak_yol == "mem://test-multimodal"
    d = sonuc.to_dict()
    geri = VisionAiSonucu.from_dict(d)
    assert geri.ek_metin == "Wire testi"
    assert d["prompt_text"] == "Wire testi"
    assert d["engine"] == "llm"
    assert d["task"] == "vision_ai"


def test_dosya_yok_hata() -> None:
    m = MultimodalAnaliz(
        dry_run=False,
        zorla_sahte=False,
        analyzer=_sahte_analyzer,
        compose=False,
        olay_yayinla=False,
    )
    try:
        m.analiz(str(_KOK / "yok_olmayan_mm_goruntu_xyz.png"), "var mı?")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0832"


def test_bilinen_yardimci() -> None:
    bil = multimodal_analiz("x://dry", "soru", dry_run=True)
    assert bil.dry_run is True
    assert bil.ek_metin == "soru"
    assert bil.cevap == ""

    sahte = multimodal_analiz(
        "x://sahte",
        "özet",
        zorla_sahte=True,
        compose=False,
        sahte_cevap="Sahte multimodal özet.",
    )
    assert sahte.motor == VisionMotoru.SAHTE
    assert "Sahte multimodal" in (sahte.cevap or "")


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.ai.multimodal.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_MULTIMODAL_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_MULTIMODAL_DURDU, lambda ev: alinan.append(ev.ad))

    m = MultimodalAnaliz(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await m.baslat()
        assert m.calisiyor is True
        await m.durdur()
        assert m.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_MULTIMODAL_BASLADI in alinan
    assert OLAY_MULTIMODAL_DURDU in alinan


def test_compose_kapali_sahte_fallback() -> None:
    """Compose kapalı + analyzer yok → sahte fallback."""
    m = multimodal_analiz_olustur(
        dry_run=False,
        zorla_sahte=False,
        compose=False,
        olay_yayinla=False,
        varsayilan_sahte="Fallback multimodal.",
    )
    assert m.motor == "sahte"
    sonuc = m.analiz(_MINI_PNG, "Ne görüyorsun?")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert "sahte" in (sonuc.neden or "") or "fallback" in (sonuc.neden or "")
    assert "Ne görüyorsun?" in (sonuc.cevap or "")


def test_compose_uri() -> None:
    """URI + compose → caption/OCR/sayma bileşim (dosya yok)."""
    m = multimodal_analiz_olustur(
        dry_run=False,
        zorla_sahte=False,
        compose=True,
        olay_yayinla=False,
    )
    assert m.backend in ("compose", "sahte")
    sonuc = m.analiz("image://multimodal-uri", "Bu sahneyi metinle birlikte özetle")
    assert sonuc.dry_run is False
    assert sonuc.ek_metin == "Bu sahneyi metinle birlikte özetle"
    assert sonuc.cevap
    assert "Bu sahneyi metinle birlikte özetle" in (sonuc.cevap or "")
    assert sonuc.neden is not None
    # Alt motorlar mevcutsa compose; aksi halde sahte
    assert m.backend in ("compose", "sahte")
    if m.backend == "compose":
        assert "compose" in str(sonuc.neden)
        assert sonuc.guven >= 0.5

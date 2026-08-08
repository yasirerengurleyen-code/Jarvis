"""vision/ai/soru_cevap.py birim testleri (dry_run / sahte / mock answerer)."""

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
from vision.ai.soru_cevap import (
    OLAY_VQA,
    OLAY_VQA_BASLADI,
    OLAY_VQA_DURDU,
    GorselSoruCevap,
    gorsel_sor,
    gorsel_soru_cevap_olustur,
    numpy_var_mi,
    opencv_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_answerer(mat: Any, soru: str) -> dict[str, Any]:
    _ = mat
    return {
        "answer": f"Masada bir kupa var. (Soru: {soru})",
        "confidence": 0.92,
        "engine": "llm",
    }


def test_fabrika_ve_ozet() -> None:
    m = gorsel_soru_cevap_olustur(dry_run=True)
    assert isinstance(m, GorselSoruCevap)
    assert isinstance(m, ModulTabani)
    assert m.ad == "vision.ai.soru_cevap"
    assert m.motor == "dry_run"
    assert m.backend == "dry_run"
    ozet = m.ozet()
    assert ozet["dry_run"] is True
    assert ozet["scene_heuristic"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.ai.vqa")
    alinan: list[str] = []
    bus.subscribe(OLAY_VQA, lambda ev: alinan.append(ev.ad))

    m = GorselSoruCevap(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = m.sor("image://dry_run", "Bu görüntüde ne var?")
    assert isinstance(sonuc, VisionAiSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.cevap == ""
    assert sonuc.soru == "Bu görüntüde ne var?"
    assert sonuc.neden == "dry_run"
    assert sonuc.gorev is VisionGorevTuru.AI
    assert m.son_sonuc is sonuc
    assert OLAY_VQA in alinan

    d = sonuc.to_dict()
    assert d["answer"] == ""
    assert d["question"] == "Bu görüntüde ne var?"
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"
    assert d["task"] == "vision_ai"


def test_zorla_sahte() -> None:
    m = gorsel_soru_cevap_olustur(
        dry_run=False,
        zorla_sahte=True,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    assert m.motor == "sahte"
    sonuc = m.sor("image://sahte", "Ekran var mı?")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.cevap
    assert sonuc.soru == "Ekran var mı?"
    assert sonuc.guven > 0.0

    s2 = m.sor(
        b"x",
        "Kaç nesne var?",
        sahte_cevap="Yaklaşık üç masaüstü nesnesi görünüyor.",
    )
    assert "üç" in (s2.cevap or "").lower() or "uc" in (s2.cevap or "").lower()


def test_mock_answerer_ve_cevapla() -> None:
    m = GorselSoruCevap(
        dry_run=False,
        zorla_sahte=False,
        answerer=_sahte_answerer,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    assert m.motor == "llm"
    assert m.backend == "injected"

    sonuc = m.sor(_MINI_PNG, "Masada ne var?")
    assert sonuc.motor == VisionMotoru.LLM
    assert sonuc.neden == "injected"
    assert "kupa" in (sonuc.cevap or "").lower()
    assert sonuc.guven >= 0.9
    assert sonuc.soru == "Masada ne var?"

    kisa = m.cevapla(_MINI_PNG, "Renk nedir?")
    assert "kupa" in kisa.lower() or "renk" in kisa.lower()


def test_kare_ve_str_answerer() -> None:
    def ans(mat: Any, soru: str) -> str:
        _ = mat
        return f"Tek bir lamba yanıyor. ({soru})"

    kare = kare_olustur(
        yol="mem://test-vqa",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    m = gorsel_soru_cevap_olustur(
        dry_run=False,
        answerer=ans,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    sonuc = m.sor(kare, "Işık var mı?")
    assert sonuc.kaynak_yol == "mem://test-vqa"
    assert "lamba" in (sonuc.cevap or "").lower()


def test_dosya_yok_hata() -> None:
    m = GorselSoruCevap(
        dry_run=False,
        zorla_sahte=False,
        answerer=_sahte_answerer,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    try:
        m.sor(str(_KOK / "yok_olmayan_vqa_goruntu_xyz.png"), "Ne var?")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0812"


def test_bos_soru_hata() -> None:
    m = gorsel_soru_cevap_olustur(dry_run=True, olay_yayinla=False)
    try:
        m.sor("image://x", "   ")
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0814"


def test_bilinen_yardimci() -> None:
    bil = gorsel_sor("x://dry", "Test?", dry_run=True)
    assert bil.dry_run is True
    assert bil.cevap == ""
    assert bil.soru == "Test?"

    sahte = gorsel_sor(
        "x://sahte",
        "Var mı?",
        zorla_sahte=True,
        sahne_heuristik=False,
        sahte_cevap="Evet, masa görünüyor.",
    )
    assert sahte.motor == VisionMotoru.SAHTE
    assert sahte.cevap == "Evet, masa görünüyor."


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.ai.vqa.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_VQA_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_VQA_DURDU, lambda ev: alinan.append(ev.ad))

    m = GorselSoruCevap(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await m.baslat()
        assert m.calisiyor is True
        await m.durdur()
        assert m.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_VQA_BASLADI in alinan
    assert OLAY_VQA_DURDU in alinan


def test_serilestirme_wire() -> None:
    m = gorsel_soru_cevap_olustur(
        dry_run=False,
        zorla_sahte=True,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    sonuc = m.sor(
        "wire://test",
        "Masaüstü mü?",
        sahte_cevap="Evet, masaüstü çalışma alanı.",
    )
    d = sonuc.to_dict()
    geri = VisionAiSonucu.from_dict(d)
    assert geri.cevap == sonuc.cevap
    assert geri.soru == "Masaüstü mü?"
    assert d["answer"] == "Evet, masaüstü çalışma alanı."
    assert d["question"] == "Masaüstü mü?"
    assert d["engine"] == "sahte"
    assert d["task"] == "vision_ai"


def test_sahne_heuristik_opsiyonel() -> None:
    """Heuristik kapalı + answerer yok → sahte fallback."""
    m = gorsel_soru_cevap_olustur(
        dry_run=False,
        zorla_sahte=False,
        sahne_heuristik=False,
        olay_yayinla=False,
        varsayilan_sahte="Heuristik kapalı sahte VQA cevabı.",
    )
    assert m.motor == "sahte"
    sonuc = m.sor(_MINI_PNG, "Ne görüyorsun?")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert "sahte" in (sonuc.neden or "") or "fallback" in (sonuc.neden or "")
    assert sonuc.cevap
    assert "VQA" in (sonuc.cevap or "") or "sahte" in (sonuc.cevap or "").lower()

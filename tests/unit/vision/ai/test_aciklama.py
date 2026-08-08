"""vision/ai/aciklama.py birim testleri (dry_run / sahte / mock captioner)."""

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
from vision.ai.aciklama import (
    OLAY_ACIKLAMA,
    OLAY_ACIKLAMA_BASLADI,
    OLAY_ACIKLAMA_DURDU,
    GorselAciklama,
    gorsel_acikla,
    gorsel_aciklama_olustur,
    numpy_var_mi,
    opencv_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_captioner(mat: Any) -> dict[str, Any]:
    _ = mat
    return {
        "description": "Bir ofis masasında dizüstü bilgisayar ve kupa.",
        "confidence": 0.91,
        "engine": "llm",
    }


def test_fabrika_ve_ozet() -> None:
    m = gorsel_aciklama_olustur(dry_run=True)
    assert isinstance(m, GorselAciklama)
    assert isinstance(m, ModulTabani)
    assert m.ad == "vision.ai.aciklama"
    assert m.motor == "dry_run"
    assert m.backend == "dry_run"
    ozet = m.ozet()
    assert ozet["dry_run"] is True
    assert ozet["scene_heuristic"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.ai.aciklama")
    alinan: list[str] = []
    bus.subscribe(OLAY_ACIKLAMA, lambda ev: alinan.append(ev.ad))

    m = GorselAciklama(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = m.acikla("image://dry_run")
    assert isinstance(sonuc, VisionAiSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.aciklama == ""
    assert sonuc.neden == "dry_run"
    assert sonuc.gorev is VisionGorevTuru.AI
    assert m.son_sonuc is sonuc
    assert OLAY_ACIKLAMA in alinan

    d = sonuc.to_dict()
    assert d["description"] == ""
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"
    assert d["task"] == "vision_ai"


def test_zorla_sahte() -> None:
    m = gorsel_aciklama_olustur(
        dry_run=False,
        zorla_sahte=True,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    assert m.motor == "sahte"
    sonuc = m.acikla("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.aciklama
    assert sonuc.guven > 0.0

    s2 = m.acikla(
        b"x",
        sahte_aciklama="Parkta ağaçlar ve bir bank.",
        etiketler=["agac", "bank"],
    )
    assert "park" in s2.aciklama.lower()
    assert "agac" in s2.aciklama.lower()
    assert "bank" in s2.aciklama.lower()


def test_mock_captioner_ve_caption() -> None:
    m = GorselAciklama(
        dry_run=False,
        zorla_sahte=False,
        captioner=_sahte_captioner,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    assert m.motor == "llm"
    assert m.backend == "injected"

    sonuc = m.acikla(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.LLM
    assert sonuc.neden == "injected"
    assert "dizüstü" in sonuc.aciklama.lower() or "kupa" in sonuc.aciklama.lower()
    assert sonuc.guven >= 0.9

    kisa = m.caption(_MINI_PNG, etiketler=["masa"])
    assert "masa" in kisa.lower()


def test_kare_ve_str_captioner() -> None:
    def cap(mat: Any) -> str:
        _ = mat
        return "Karanlık bir oda; tek bir lamba yanıyor."

    kare = kare_olustur(
        yol="mem://test-caption",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    m = gorsel_aciklama_olustur(
        dry_run=False,
        captioner=cap,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    sonuc = m.acikla(kare)
    assert sonuc.kaynak_yol == "mem://test-caption"
    assert "karanlık" in sonuc.aciklama.lower() or "lamba" in sonuc.aciklama.lower()


def test_dosya_yok_hata() -> None:
    m = GorselAciklama(
        dry_run=False,
        zorla_sahte=False,
        captioner=_sahte_captioner,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    try:
        m.acikla(str(_KOK / "yok_olmayan_caption_goruntu_xyz.png"))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0802"


def test_bilinen_yardimci() -> None:
    bil = gorsel_acikla("x://dry", dry_run=True)
    assert bil.dry_run is True
    assert bil.aciklama == ""

    sahte = gorsel_acikla(
        "x://sahte",
        zorla_sahte=True,
        sahne_heuristik=False,
        sahte_aciklama="Test caption metni.",
    )
    assert sahte.motor == VisionMotoru.SAHTE
    assert sahte.aciklama == "Test caption metni."


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.ai.aciklama.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_ACIKLAMA_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_ACIKLAMA_DURDU, lambda ev: alinan.append(ev.ad))

    m = GorselAciklama(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await m.baslat()
        assert m.calisiyor is True
        await m.durdur()
        assert m.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_ACIKLAMA_BASLADI in alinan
    assert OLAY_ACIKLAMA_DURDU in alinan


def test_serilestirme_wire() -> None:
    m = gorsel_aciklama_olustur(
        dry_run=False,
        zorla_sahte=True,
        sahne_heuristik=False,
        olay_yayinla=False,
    )
    sonuc = m.acikla("wire://test", sahte_aciklama="Masaüstü çalışma alanı.")
    d = sonuc.to_dict()
    geri = VisionAiSonucu.from_dict(d)
    assert geri.aciklama == sonuc.aciklama
    assert d["description"] == "Masaüstü çalışma alanı."
    assert d["engine"] == "sahte"
    assert d["task"] == "vision_ai"


def test_sahne_heuristik_opsiyonel() -> None:
    """Heuristik kapalı + captioner yok → sahte fallback."""
    m = gorsel_aciklama_olustur(
        dry_run=False,
        zorla_sahte=False,
        sahne_heuristik=False,
        olay_yayinla=False,
        varsayilan_sahte="Heuristik kapalı sahte caption.",
    )
    assert m.motor == "sahte"
    sonuc = m.acikla(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.SAHTE
    assert "sahte" in (sonuc.neden or "") or "fallback" in (sonuc.neden or "")
    assert "caption" in sonuc.aciklama.lower() or "sahte" in sonuc.aciklama.lower()

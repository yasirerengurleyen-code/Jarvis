"""vision/ai/sayma.py birim testleri (dry_run / sahte / mock counter)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import VisionAiSonucu, VisionGorevTuru, VisionMotoru, kare_olustur
from vision.ai.sayma import (
    OLAY_SAYMA,
    OLAY_SAYMA_BASLADI,
    OLAY_SAYMA_DURDU,
    NesneSayici,
    nesne_say,
    nesne_sayici_olustur,
    numpy_var_mi,
    opencv_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_counter(mat: Any, etiket: Optional[str]) -> dict[str, Any]:
    _ = mat
    if etiket and etiket.lower() == "kupa":
        return {"count": 3, "count_label": "kupa", "confidence": 0.93, "engine": "llm"}
    return {"count": 5, "confidence": 0.91, "engine": "llm"}


def test_fabrika_ve_ozet() -> None:
    m = nesne_sayici_olustur(dry_run=True)
    assert isinstance(m, NesneSayici)
    assert isinstance(m, ModulTabani)
    assert m.ad == "vision.ai.sayma"
    assert m.motor == "dry_run"
    assert m.backend == "dry_run"
    ozet = m.ozet()
    assert ozet["dry_run"] is True
    assert ozet["object_heuristic"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.ai.sayma")
    alinan: list[str] = []
    bus.subscribe(OLAY_SAYMA, lambda ev: alinan.append(ev.ad))

    m = NesneSayici(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = m.say("image://dry_run")
    assert isinstance(sonuc, VisionAiSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.sayim == 0
    assert sonuc.neden == "dry_run"
    assert sonuc.gorev is VisionGorevTuru.AI
    assert m.son_sonuc is sonuc
    assert OLAY_SAYMA in alinan

    d = sonuc.to_dict()
    assert d["count"] == 0
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"
    assert d["task"] == "vision_ai"


def test_zorla_sahte() -> None:
    m = nesne_sayici_olustur(
        dry_run=False,
        zorla_sahte=True,
        nesne_heuristik=False,
        olay_yayinla=False,
    )
    assert m.motor == "sahte"
    sonuc = m.say("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.sayim == 2
    assert sonuc.guven > 0.0
    assert sonuc.aciklama

    s2 = m.say(b"x", sahte_sayim=7, etiket="sandalye")
    assert s2.sayim == 7
    assert s2.sayim_etiket == "sandalye"
    assert "7" in (s2.aciklama or "")
    assert "sandalye" in (s2.aciklama or "").lower()


def test_mock_counter_ve_adet() -> None:
    m = NesneSayici(
        dry_run=False,
        zorla_sahte=False,
        counter=_sahte_counter,
        nesne_heuristik=False,
        olay_yayinla=False,
    )
    assert m.motor == "llm"
    assert m.backend == "injected"

    sonuc = m.say(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.LLM
    assert sonuc.neden == "injected"
    assert sonuc.sayim == 5
    assert sonuc.guven >= 0.9

    kupa = m.say(_MINI_PNG, etiket="kupa")
    assert kupa.sayim == 3
    assert kupa.sayim_etiket == "kupa"

    assert m.adet(_MINI_PNG) == 5


def test_kare_ve_int_counter() -> None:
    def cnt(mat: Any, etiket: Optional[str]) -> int:
        _ = mat
        _ = etiket
        return 4

    kare = kare_olustur(
        yol="mem://test-sayma",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    m = nesne_sayici_olustur(
        dry_run=False,
        counter=cnt,
        nesne_heuristik=False,
        olay_yayinla=False,
    )
    sonuc = m.say(kare)
    assert sonuc.kaynak_yol == "mem://test-sayma"
    assert sonuc.sayim == 4


def test_dosya_yok_hata() -> None:
    m = NesneSayici(
        dry_run=False,
        zorla_sahte=False,
        counter=_sahte_counter,
        nesne_heuristik=False,
        olay_yayinla=False,
    )
    try:
        m.say(str(_KOK / "yok_olmayan_sayma_goruntu_xyz.png"))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0822"


def test_bilinen_yardimci() -> None:
    bil = nesne_say("x://dry", dry_run=True)
    assert bil.dry_run is True
    assert bil.sayim == 0

    sahte = nesne_say(
        "x://sahte",
        zorla_sahte=True,
        nesne_heuristik=False,
        sahte_sayim=9,
        etiket="kisi",
    )
    assert sahte.motor == VisionMotoru.SAHTE
    assert sahte.sayim == 9
    assert sahte.sayim_etiket == "kisi"


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.ai.sayma.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_SAYMA_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_SAYMA_DURDU, lambda ev: alinan.append(ev.ad))

    m = NesneSayici(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await m.baslat()
        assert m.calisiyor is True
        await m.durdur()
        assert m.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_SAYMA_BASLADI in alinan
    assert OLAY_SAYMA_DURDU in alinan


def test_serilestirme_wire() -> None:
    m = nesne_sayici_olustur(
        dry_run=False,
        zorla_sahte=True,
        nesne_heuristik=False,
        olay_yayinla=False,
    )
    sonuc = m.say("wire://test", sahte_sayim=3, etiket="kupa")
    d = sonuc.to_dict()
    geri = VisionAiSonucu.from_dict(d)
    assert geri.sayim == 3
    assert geri.sayim_etiket == "kupa"
    assert d["count"] == 3
    assert d["count_label"] == "kupa"
    assert d["engine"] == "sahte"
    assert d["task"] == "vision_ai"


def test_nesne_heuristik_opsiyonel() -> None:
    """Heuristik kapalı + counter yok → sahte fallback."""
    m = nesne_sayici_olustur(
        dry_run=False,
        zorla_sahte=False,
        nesne_heuristik=False,
        olay_yayinla=False,
        varsayilan_sahte=6,
    )
    assert m.motor == "sahte"
    sonuc = m.say(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.SAHTE
    assert "sahte" in (sonuc.neden or "") or "fallback" in (sonuc.neden or "")
    assert sonuc.sayim == 6


def test_nesne_heuristik_uri() -> None:
    """URI + nesne heuristik → URI yolu (dosya yok)."""
    m = nesne_sayici_olustur(
        dry_run=False,
        zorla_sahte=False,
        nesne_heuristik=True,
        olay_yayinla=False,
        varsayilan_sahte=2,
    )
    # counter yok → nesne_heuristic (modül mevcut)
    assert m.backend in ("nesne_heuristic", "sahte")
    sonuc = m.say("image://sayma-uri")
    assert sonuc.sayim is not None
    assert sonuc.sayim >= 0
    assert sonuc.dry_run is False
    # etiket filtresi
    kisi = m.say("image://sayma-uri", etiket="kisi")
    assert kisi.sayim_etiket == "kisi"
    assert kisi.sayim in (0, 1)

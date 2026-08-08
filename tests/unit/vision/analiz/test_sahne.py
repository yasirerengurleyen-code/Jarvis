"""vision/analiz/sahne.py birim testleri (dry_run / sahte / mock analyzer)."""

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
from vision.modeller import AnalizSonucu, VisionMotoru, kare_olustur
from vision.analiz.sahne import (
    OLAY_SAHNE_ANALIZ,
    OLAY_SAHNE_BASLADI,
    OLAY_SAHNE_DURDU,
    SahneAnalizci,
    numpy_var_mi,
    opencv_var_mi,
    sahne_analiz,
    sahne_analizci_olustur,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_analyzer(mat: Any) -> dict[str, Any]:
    _ = mat
    return {"scene": "Aydınlık bir iç mekan; ofis ortamı."}


def test_fabrika_ve_ozet() -> None:
    s = sahne_analizci_olustur(dry_run=True)
    assert isinstance(s, SahneAnalizci)
    assert isinstance(s, ModulTabani)
    assert s.ad == "vision.analiz.sahne"
    assert s.motor == "dry_run"
    assert s.backend == "dry_run"
    ozet = s.ozet()
    assert ozet["dry_run"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.analiz.sahne")
    alinan: list[str] = []
    bus.subscribe(OLAY_SAHNE_ANALIZ, lambda ev: alinan.append(ev.ad))

    s = SahneAnalizci(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = s.analiz("image://dry_run")
    assert isinstance(sonuc, AnalizSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.sahne == ""
    assert sonuc.neden == "dry_run"
    assert s.son_sonuc is sonuc
    assert OLAY_SAHNE_ANALIZ in alinan

    d = sonuc.to_dict()
    assert d["scene"] == ""
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"


def test_zorla_sahte() -> None:
    s = sahne_analizci_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert s.motor == "sahte"
    sonuc = s.analiz("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.sahne
    assert "mekan" in sonuc.sahne.lower() or "alan" in sonuc.sahne.lower()

    # Özel sahte metin + etiket zenginleştirme
    s2 = s.analiz(
        b"x",
        sahte_sahne="Dış mekan park alanı.",
        etiketler=["agac", "bank"],
    )
    assert "park" in s2.sahne.lower()
    assert "agac" in s2.sahne.lower()
    assert "bank" in s2.sahne.lower()


def test_mock_analyzer_ve_acikla() -> None:
    s = SahneAnalizci(
        dry_run=False,
        zorla_sahte=False,
        analyzer=_sahte_analyzer,
        olay_yayinla=False,
    )
    assert s.motor == "opencv"
    assert s.backend == "injected"

    sonuc = s.analiz(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.OPENCV
    assert sonuc.neden == "injected"
    assert "iç mekan" in sonuc.sahne.lower() or "ofis" in sonuc.sahne.lower()

    kisa = s.acikla(_MINI_PNG, etiketler=["masa"])
    assert "masa" in kisa.lower()


def test_kare_ve_str_analyzer() -> None:
    def det(mat: Any) -> str:
        _ = mat
        return "Karanlık bir iç mekan; kapalı alan."

    kare = kare_olustur(
        yol="mem://test-sahne",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    s = sahne_analizci_olustur(
        dry_run=False,
        analyzer=det,
        olay_yayinla=False,
    )
    sonuc = s.analiz(kare)
    assert sonuc.kaynak_yol == "mem://test-sahne"
    assert "karanlık" in sonuc.sahne.lower()


def test_dosya_yok_hata() -> None:
    s = SahneAnalizci(
        dry_run=False,
        zorla_sahte=False,
        analyzer=_sahte_analyzer,
        olay_yayinla=False,
    )
    try:
        s.analiz(str(_KOK / "yok_olmayan_sahne_goruntu_xyz.png"))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0612"


def test_bilinen_yardimci() -> None:
    bil = sahne_analiz("x://dry", dry_run=True)
    assert bil.dry_run is True
    assert bil.sahne == ""

    sahte = sahne_analiz("x://sahte", zorla_sahte=True, sahte_sahne="Test sahnesi.")
    assert sahte.motor == VisionMotoru.SAHTE
    assert sahte.sahne == "Test sahnesi."


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.analiz.sahne.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_SAHNE_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_SAHNE_DURDU, lambda ev: alinan.append(ev.ad))

    s = SahneAnalizci(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await s.baslat()
        assert s.calisiyor is True
        await s.durdur()
        assert s.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_SAHNE_BASLADI in alinan
    assert OLAY_SAHNE_DURDU in alinan


def test_serilestirme_wire() -> None:
    s = sahne_analizci_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    sonuc = s.analiz("wire://test", sahte_sahne="Masaüstü çalışma alanı.")
    d = sonuc.to_dict()
    geri = AnalizSonucu.from_dict(d)
    assert geri.sahne == sonuc.sahne
    assert d["scene"] == "Masaüstü çalışma alanı."
    assert d["engine"] == "sahte"

"""vision/analiz/renk.py birim testleri (dry_run / sahte / mock analyzer)."""

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
from vision.modeller import AnalizSonucu, RenkOzeti, VisionMotoru, kare_olustur
from vision.analiz.renk import (
    OLAY_RENK_ANALIZ,
    OLAY_RENK_BASLADI,
    OLAY_RENK_DURDU,
    VARSAYILAN_PALET_BOYUTU,
    RenkAnalizci,
    numpy_var_mi,
    opencv_var_mi,
    renk_analiz,
    renk_analizci_olustur,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_analyzer(mat: Any) -> dict[str, Any]:
    _ = mat
    return {
        "dominant_hex": "#FF5500",
        "palette": ["#FF5500", "#112233", "#AABBCC"],
        "mean_rgb": {"r": 255, "g": 85, "b": 0},
    }


def test_fabrika_ve_ozet() -> None:
    r = renk_analizci_olustur(dry_run=True)
    assert isinstance(r, RenkAnalizci)
    assert isinstance(r, ModulTabani)
    assert r.ad == "vision.analiz.renk"
    assert r.motor == "dry_run"
    assert r.backend == "dry_run"
    ozet = r.ozet()
    assert ozet["dry_run"] is True
    assert ozet["palette_size"] == VARSAYILAN_PALET_BOYUTU
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.analiz.renk")
    alinan: list[str] = []
    bus.subscribe(OLAY_RENK_ANALIZ, lambda ev: alinan.append(ev.ad))

    r = RenkAnalizci(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = r.analiz("image://dry_run")
    assert isinstance(sonuc, AnalizSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.renk is None
    assert sonuc.neden == "dry_run"
    assert r.son_sonuc is sonuc
    assert OLAY_RENK_ANALIZ in alinan

    d = sonuc.to_dict()
    assert d["color"] is None
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"


def test_zorla_sahte() -> None:
    r = renk_analizci_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert r.motor == "sahte"
    sonuc = r.analiz("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.renk is not None
    assert sonuc.renk.baskin_hex.startswith("#")
    assert len(sonuc.renk.palette) >= 1
    assert len(sonuc.renk.ortalama_rgb) == 3

    ozel = RenkOzeti(
        baskin_hex="#00FFAA",
        palette=["#00FFAA", "#001122"],
        ortalama_rgb=(0, 255, 170),
    )
    s2 = r.analiz(b"x", sahte_renk=ozel, palet_boyutu=1)
    assert s2.renk is not None
    assert s2.renk.baskin_hex == "#00FFAA"
    assert len(s2.renk.palette) == 1


def test_mock_analyzer_ve_kisayollar() -> None:
    r = RenkAnalizci(
        dry_run=False,
        zorla_sahte=False,
        analyzer=_sahte_analyzer,
        olay_yayinla=False,
    )
    assert r.motor == "opencv"
    assert r.backend == "injected"

    sonuc = r.analiz(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.OPENCV
    assert sonuc.neden == "injected"
    assert sonuc.renk is not None
    assert sonuc.renk.baskin_hex == "#FF5500"
    assert "#112233" in sonuc.renk.palette

    ozet = r.ozet_renk(_MINI_PNG)
    assert ozet is not None
    assert ozet.baskin_hex == "#FF5500"
    assert r.baskin_hex(_MINI_PNG) == "#FF5500"


def test_kare_ve_str_analyzer() -> None:
    def det(mat: Any) -> str:
        _ = mat
        return "#ABCDEF"

    kare = kare_olustur(
        yol="mem://test-renk",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    r = renk_analizci_olustur(
        dry_run=False,
        analyzer=det,
        olay_yayinla=False,
    )
    sonuc = r.analiz(kare)
    assert sonuc.kaynak_yol == "mem://test-renk"
    assert sonuc.renk is not None
    assert sonuc.renk.baskin_hex == "#ABCDEF"


def test_dosya_yok_hata() -> None:
    r = RenkAnalizci(
        dry_run=False,
        zorla_sahte=False,
        analyzer=_sahte_analyzer,
        olay_yayinla=False,
    )
    try:
        r.analiz(str(_KOK / "yok_olmayan_renk_goruntu_xyz.png"))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0622"


def test_bilinen_yardimci() -> None:
    bil = renk_analiz("x://dry", dry_run=True)
    assert bil.dry_run is True
    assert bil.renk is None

    sahte = renk_analiz(
        "x://sahte",
        zorla_sahte=True,
        sahte_renk=RenkOzeti(
            baskin_hex="#112233",
            palette=["#112233"],
            ortalama_rgb=(17, 34, 51),
        ),
    )
    assert sahte.motor == VisionMotoru.SAHTE
    assert sahte.renk is not None
    assert sahte.renk.baskin_hex == "#112233"


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.analiz.renk.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_RENK_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_RENK_DURDU, lambda ev: alinan.append(ev.ad))

    r = RenkAnalizci(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await r.baslat()
        assert r.calisiyor is True
        await r.durdur()
        assert r.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_RENK_BASLADI in alinan
    assert OLAY_RENK_DURDU in alinan


def test_serilestirme_wire() -> None:
    r = renk_analizci_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    sonuc = r.analiz(
        "wire://test",
        sahte_renk=RenkOzeti(
            baskin_hex="#AABBCC",
            palette=["#AABBCC", "#000011"],
            ortalama_rgb=(170, 187, 204),
        ),
    )
    d = sonuc.to_dict()
    geri = AnalizSonucu.from_dict(d)
    assert geri.renk is not None
    assert geri.renk.baskin_hex == "#AABBCC"
    assert d["color"]["dominant_hex"] == "#AABBCC"
    assert d["color"]["mean_rgb"]["r"] == 170
    assert d["engine"] == "sahte"

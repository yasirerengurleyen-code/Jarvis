"""vision/analiz/nesne.py birim testleri (dry_run / sahte / mock detector)."""

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
from vision.modeller import AlgilananNesne, AnalizSonucu, VisionMotoru, kare_olustur
from vision.analiz.nesne import (
    OLAY_NESNE_ALGILANDI,
    OLAY_NESNE_BASLADI,
    OLAY_NESNE_DURDU,
    VARSAYILAN_MIN_GUVEN,
    NesneAlgilayici,
    nesne_algila,
    nesne_algilayici_olustur,
    numpy_var_mi,
    opencv_var_mi,
    yolo_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_detector(mat: Any) -> list[dict[str, Any]]:
    _ = mat
    return [
        {"label": "kupa", "confidence": 0.91, "box": {"x": 1, "y": 2, "w": 30, "h": 40}},
        {"label": "kitap", "confidence": 0.55, "box": {"x": 50, "y": 10, "w": 20, "h": 25}},
        {"label": "dusuk", "confidence": 0.05, "box": {"x": 0, "y": 0, "w": 5, "h": 5}},
    ]


def test_fabrika_ve_ozet() -> None:
    n = nesne_algilayici_olustur(dry_run=True)
    assert isinstance(n, NesneAlgilayici)
    assert isinstance(n, ModulTabani)
    assert n.ad == "vision.analiz.nesne"
    assert n.motor == "dry_run"
    assert n.backend == "dry_run"
    ozet = n.ozet()
    assert ozet["dry_run"] is True
    assert ozet["min_confidence"] == VARSAYILAN_MIN_GUVEN
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)
    assert isinstance(yolo_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.analiz.nesne")
    alinan: list[str] = []
    bus.subscribe(OLAY_NESNE_ALGILANDI, lambda ev: alinan.append(ev.ad))

    n = NesneAlgilayici(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = n.algila("image://dry_run")
    assert isinstance(sonuc, AnalizSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.nesneler == []
    assert sonuc.neden == "dry_run"
    assert n.son_sonuc is sonuc
    assert OLAY_NESNE_ALGILANDI in alinan

    d = sonuc.to_dict()
    assert d["objects"] == []
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"


def test_zorla_sahte() -> None:
    n = nesne_algilayici_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert n.motor == "sahte"
    sonuc = n.algila("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert len(sonuc.nesneler) >= 1
    assert all(isinstance(x, AlgilananNesne) for x in sonuc.nesneler)
    assert sonuc.nesneler[0].etiket
    assert 0.0 <= sonuc.nesneler[0].guven <= 1.0

    # Özel sahte liste
    ozel = [AlgilananNesne(etiket="masa", guven=0.9, kutu=(0, 0, 10, 10))]
    s2 = n.algila(b"x", sahte_nesneler=ozel)
    assert len(s2.nesneler) == 1
    assert s2.nesneler[0].etiket == "masa"


def test_mock_detector_ve_filtre() -> None:
    n = NesneAlgilayici(
        dry_run=False,
        zorla_sahte=False,
        detector=_sahte_detector,
        min_guven=0.5,
        olay_yayinla=False,
    )
    assert n.motor == "opencv"
    assert n.backend == "injected"

    # Ham bayt — cv2 yoksa bile enjekte detector çalışır
    sonuc = n.algila(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.OPENCV
    assert sonuc.neden == "injected"
    etiketler = {x.etiket for x in sonuc.nesneler}
    assert "kupa" in etiketler
    assert "kitap" in etiketler
    assert "dusuk" not in etiketler  # min_guven=0.5

    # Etiket filtresi
    sadece = n.listele(_MINI_PNG, etiket_filtre=["kupa"])
    assert len(sadece) == 1
    assert sadece[0].etiket == "kupa"
    assert n.say(_MINI_PNG, etiket="kupa") == 1
    assert n.say(_MINI_PNG, etiket="yok") == 0


def test_kare_ve_tuple_detector() -> None:
    def det(mat: Any) -> list[Any]:
        _ = mat
        return [
            ("lamba", 0.8, (5, 5, 15, 20)),
            AlgilananNesne(etiket="pencere", guven=0.7),
        ]

    kare = kare_olustur(
        yol="mem://test",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    n = nesne_algilayici_olustur(
        dry_run=False,
        detector=det,
        min_guven=0.1,
        olay_yayinla=False,
    )
    sonuc = n.algila(kare)
    assert sonuc.kaynak_yol == "mem://test"
    assert len(sonuc.nesneler) == 2
    assert sonuc.nesneler[0].kutu == (5, 5, 15, 20)


def test_dosya_yok_hata() -> None:
    n = NesneAlgilayici(
        dry_run=False,
        zorla_sahte=False,
        detector=_sahte_detector,
        olay_yayinla=False,
    )
    try:
        n.algila(str(_KOK / "yok_olmayan_nesne_goruntu_xyz.png"))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0602"


def test_bilinen_yardimci() -> None:
    bil = nesne_algila("x://dry", dry_run=True)
    assert bil.dry_run is True
    assert bil.nesneler == []

    sahte = nesne_algila("x://sahte", zorla_sahte=True, min_guven=0.0)
    assert sahte.motor == VisionMotoru.SAHTE
    assert len(sahte.nesneler) >= 1


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.analiz.nesne.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_NESNE_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_NESNE_DURDU, lambda ev: alinan.append(ev.ad))

    n = NesneAlgilayici(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await n.baslat()
        assert n.calisiyor is True
        await n.durdur()
        assert n.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_NESNE_BASLADI in alinan
    assert OLAY_NESNE_DURDU in alinan


def test_serilestirme_wire() -> None:
    n = nesne_algilayici_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    sonuc = n.algila("wire://test")
    d = sonuc.to_dict()
    geri = AnalizSonucu.from_dict(d)
    assert len(geri.nesneler) == len(sonuc.nesneler)
    assert geri.nesneler[0].etiket == sonuc.nesneler[0].etiket
    assert "box" in d["objects"][0] or sonuc.nesneler[0].kutu is None

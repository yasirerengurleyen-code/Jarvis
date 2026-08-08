"""vision/yuz/algilama.py birim testleri (gizlilik / dry_run / sahte / akış)."""

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
from vision.modeller import VisionMotoru, YuzKutusu, kare_olustur
from vision.yuz.algilama import (
    OLAY_YUZ_AKIS_BASLADI,
    OLAY_YUZ_AKIS_DURDU,
    OLAY_YUZ_ALGILAMA_BASLADI,
    OLAY_YUZ_ALGILAMA_DURDU,
    OLAY_YUZ_ALGILANDI,
    VARSAYILAN_ALGILAMA_ESIK,
    YuzAlgilamaSonucu,
    YuzAlgilayici,
    numpy_var_mi,
    opencv_var_mi,
    yuz_algila,
    yuz_algilayici_olustur,
)
from vision.yuz.gizlilik import yuz_gizlilik_olustur

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_detector(mat: Any) -> list[dict[str, Any]]:
    _ = mat
    return [
        {"x": 10, "y": 20, "w": 80, "h": 90, "confidence": 0.95},
        {"x": 200, "y": 40, "w": 70, "h": 80, "confidence": 0.55},
        {"x": 0, "y": 0, "w": 5, "h": 5, "confidence": 0.05},
    ]


def test_fabrika_ve_ozet() -> None:
    a = yuz_algilayici_olustur(dry_run=True)
    assert isinstance(a, YuzAlgilayici)
    assert isinstance(a, ModulTabani)
    assert a.ad == "vision.yuz.algilama"
    assert a.motor == "dry_run"
    assert a.backend == "dry_run"
    ozet = a.ozet()
    assert ozet["dry_run"] is True
    assert ozet["local_only"] is True
    assert ozet["privacy"] == "local_only"
    assert ozet["min_confidence"] == VARSAYILAN_ALGILAMA_ESIK
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.yuz.algilama")
    alinan: list[str] = []
    bus.subscribe(OLAY_YUZ_ALGILANDI, lambda ev: alinan.append(ev.ad))

    a = yuz_algilayici_olustur(dry_run=True, bus=bus, olay_yayinla=True, kamera_izin=True)
    sonuc = a.algila("image://dry_run")
    assert isinstance(sonuc, YuzAlgilamaSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.kutular == []
    assert sonuc.neden == "dry_run"
    assert a.son_sonuc is sonuc
    assert OLAY_YUZ_ALGILANDI in alinan

    d = sonuc.to_dict()
    assert d["faces"] == []
    assert d["count"] == 0
    assert d["dry_run"] is True
    assert d["local_only"] is True
    assert "embedding" not in d


def test_zorla_sahte() -> None:
    a = yuz_algilayici_olustur(
        dry_run=False, zorla_sahte=True, olay_yayinla=False, kamera_izin=True
    )
    assert a.motor == "sahte"
    sonuc = a.algila("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert len(sonuc.kutular) >= 1
    assert all(isinstance(x, YuzKutusu) for x in sonuc.kutular)
    assert 0.0 <= sonuc.kutular[0].guven <= 1.0

    ozel = [YuzKutusu(x=1, y=2, w=30, h=40, guven=0.9)]
    s2 = a.algila(b"x", sahte_yuzler=ozel)
    assert len(s2.kutular) == 1
    assert s2.kutular[0].w == 30


def test_mock_detector_ve_filtre() -> None:
    a = YuzAlgilayici(
        dry_run=False,
        zorla_sahte=False,
        detector=_sahte_detector,
        min_guven=0.5,
        olay_yayinla=False,
        gizlilik=yuz_gizlilik_olustur(
            kamera_izin=True, dry_run=False, olay_yayinla=False
        ),
    )
    assert a.motor == "opencv"
    assert a.backend == "injected"

    sonuc = a.algila(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.OPENCV
    assert sonuc.neden == "injected"
    assert sonuc.adet == 2  # 0.05 filtrelendi
    assert all(k.guven >= 0.5 for k in sonuc.kutular)


def test_kamera_izni_yok_algilama_yok() -> None:
    """Gizlilik kapalı (kamera izni yok) → net hata, algılama yok."""
    g = yuz_gizlilik_olustur(
        kamera_izin=False,
        yuz_aktif=False,
        dry_run=False,
        olay_yayinla=False,
    )
    a = yuz_algilayici_olustur(
        dry_run=False,
        zorla_sahte=True,
        gizlilik=g,
        olay_yayinla=False,
    )
    assert a.izinli_mi() is False
    try:
        a.algila(b"x")
        raise AssertionError("VIS_0702 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0702"


def test_tanima_toggle_kapali_ham_algilama_ok() -> None:
    """Tanıma toggle kapalı olsa bile ham algılama (kamera izni varsa) çalışır."""
    g = yuz_gizlilik_olustur(
        kamera_izin=True,
        yuz_aktif=False,
        dry_run=False,
        olay_yayinla=False,
    )
    a = yuz_algilayici_olustur(
        dry_run=False,
        zorla_sahte=True,
        gizlilik=g,
        olay_yayinla=False,
    )
    sonuc = a.algila(b"x")
    assert sonuc.adet >= 1
    assert sonuc.yerel_only is True


def test_wire_embedding_yok() -> None:
    a = yuz_algilayici_olustur(
        dry_run=False, zorla_sahte=True, olay_yayinla=False, kamera_izin=True
    )
    d = a.algila(b"x").to_dict()
    for yasak in ("embedding", "template", "sablon", "descriptor", "encoding"):
        assert yasak not in d
        assert all(yasak not in f for f in d["faces"])


def test_kare_girdi_ve_yardimci() -> None:
    kare = kare_olustur(yol="image://test", ham=_MINI_PNG, dry_run=False)
    sonuc = yuz_algila(
        kare,
        zorla_sahte=True,
        kamera_izin=True,
        sahte_yuzler=[YuzKutusu(x=0, y=0, w=10, h=10, guven=0.8)],
    )
    assert sonuc.adet == 1
    assert sonuc.kare_id == kare.id


def test_senkron_akis() -> None:
    bus = EventBus(ad="test.vision.yuz.akis")
    alinan: list[str] = []
    bus.subscribe(OLAY_YUZ_AKIS_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_YUZ_AKIS_DURDU, lambda ev: alinan.append(ev.ad))

    a = yuz_algilayici_olustur(
        dry_run=False,
        zorla_sahte=True,
        fps=60,
        bus=bus,
        olay_yayinla=True,
        kamera_izin=True,
    )
    kareler = [b"a", b"b", b"c"]
    sonuclar = list(a.kareleri_algila(kareler, maks=2))
    assert len(sonuclar) == 2
    assert all(isinstance(s, YuzAlgilamaSonucu) for s in sonuclar)
    assert a.akiyor is False
    assert OLAY_YUZ_AKIS_BASLADI in alinan
    assert OLAY_YUZ_AKIS_DURDU in alinan


def test_async_akis_ve_yasam() -> None:
    async def _calistir() -> None:
        bus = EventBus(ad="test.vision.yuz.async")
        alinan: list[str] = []
        bus.subscribe(OLAY_YUZ_ALGILAMA_BASLADI, lambda ev: alinan.append(ev.ad))
        bus.subscribe(OLAY_YUZ_ALGILAMA_DURDU, lambda ev: alinan.append(ev.ad))

        a = yuz_algilayici_olustur(
            dry_run=True,
            fps=100,
            bus=bus,
            olay_yayinla=True,
            kamera_izin=True,
        )
        await a.baslat()
        assert a.calisiyor is True
        assert OLAY_YUZ_ALGILAMA_BASLADI in alinan

        async def _kaynak():
            for i in range(3):
                yield f"image://f{i}"

        sonuclar = []
        async for s in a.akis_algila(_kaynak(), maks=3):
            sonuclar.append(s)
        assert len(sonuclar) == 3
        assert all(s.dry_run for s in sonuclar)

        await a.durdur()
        assert a.calisiyor is False
        assert OLAY_YUZ_ALGILAMA_DURDU in alinan

    asyncio.run(_calistir())


def test_akis_izin_red() -> None:
    g = yuz_gizlilik_olustur(kamera_izin=False, dry_run=False, olay_yayinla=False)
    a = yuz_algilayici_olustur(
        dry_run=False, zorla_sahte=True, gizlilik=g, olay_yayinla=False
    )
    try:
        list(a.kareleri_algila([b"x"]))
        raise AssertionError("VIS_0702 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0702"


def test_sonuc_from_dict() -> None:
    ham = {
        "faces": [{"x": 1, "y": 2, "w": 3, "h": 4, "confidence": 0.7}],
        "engine": "sahte",
        "dry_run": False,
        "local_only": True,
        "reason": "test",
    }
    s = YuzAlgilamaSonucu.from_dict(ham)
    assert s.adet == 1
    assert s.kutular[0].x == 1
    assert s.motor == VisionMotoru.SAHTE
    assert s.to_dict()["count"] == 1

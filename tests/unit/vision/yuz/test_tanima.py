"""vision/yuz/tanima.py birim testleri (güven / bilinmeyen / karşılama / gizlilik)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import (
    BILINMEYEN_KULLANICI_MESAJI,
    VARSAYILAN_YUZ_ESIK,
    VisionMotoru,
    YuzTanimaSonucu,
)
from vision.yuz.gizlilik import yuz_gizlilik_olustur
from vision.yuz.kayit import yuz_kayit_olustur
from vision.yuz.tanima import (
    OLAY_YUZ_BILINMEYEN,
    OLAY_YUZ_TANIMA_BASLADI,
    OLAY_YUZ_TANIMA_DURDU,
    OLAY_YUZ_TANINDI,
    YuzTaniyici,
    karsilama_metni,
    kosinus_benzerlik,
    yuz_taniyici_olustur,
    yuz_tanima,
)


def test_fabrika_ve_ozet() -> None:
    t = yuz_taniyici_olustur(dry_run=True)
    assert isinstance(t, YuzTaniyici)
    assert isinstance(t, ModulTabani)
    assert t.ad == "vision.yuz.tanima"
    ozet = t.ozet()
    assert ozet["local_only"] is True
    assert ozet["privacy"] == "local_only"
    assert ozet["cloud_allowed"] is False
    assert ozet["dry_run"] is True
    assert ozet["min_confidence"] == VARSAYILAN_YUZ_ESIK


def test_kosinus_ve_karsilama_yardimcilari() -> None:
    assert kosinus_benzerlik([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert kosinus_benzerlik([1.0, 0.0], [-1.0, 0.0]) == 0.0
    assert 0.4 < kosinus_benzerlik([1.0, 0.0], [0.0, 1.0]) < 0.6
    assert karsilama_metni(eslesti=True, gorunen_ad="Yasir") == "Hoş geldin, Yasir."
    assert karsilama_metni(eslesti=False) == BILINMEYEN_KULLANICI_MESAJI


def test_bilinen_karsilama_embedding() -> None:
    """Kayıtlı Yasir → 'Hoş geldin, Yasir.' + güven skoru."""
    bus = EventBus(ad="test.vision.yuz.tanima.known")
    alinan: list[str] = []
    bus.subscribe(OLAY_YUZ_TANINDI, lambda ev: alinan.append(ev.ad))

    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Yasir", embedding=[1.0, 0.0, 0.0])
    kayit.kaydet("Ayse", embedding=[0.0, 1.0, 0.0])

    t = yuz_taniyici_olustur(
        dry_run=False,
        kayit=kayit,
        bus=bus,
        olay_yayinla=True,
        min_guven=0.8,
    )
    sonuc = t.eslestir_embedding([1.0, 0.0, 0.0])
    assert isinstance(sonuc, YuzTanimaSonucu)
    assert sonuc.eslesti is True
    assert sonuc.gorunen_ad == "Yasir"
    assert sonuc.guven >= 0.8
    assert sonuc.karsilama == "Hoş geldin, Yasir."
    assert sonuc.yerel_only is True
    assert sonuc.motor == VisionMotoru.YEREL
    d = sonuc.to_dict()
    assert d["greeting"] == "Hoş geldin, Yasir."
    assert d["matched"] is True
    assert "embedding" not in d
    assert OLAY_YUZ_TANINDI in alinan


def test_bilinmeyen_karsilama() -> None:
    """Eşik altı / yabancı embedding → bilinmeyen mesajı."""
    bus = EventBus(ad="test.vision.yuz.tanima.unknown")
    alinan: list[str] = []
    bus.subscribe(OLAY_YUZ_BILINMEYEN, lambda ev: alinan.append(ev.ad))

    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Yasir", embedding=[1.0, 0.0, 0.0])

    t = yuz_taniyici_olustur(
        dry_run=False,
        kayit=kayit,
        bus=bus,
        olay_yayinla=True,
        min_guven=0.9,
    )
    # Ortogonal vektör → benzerlik ~0.5 < 0.9
    sonuc = t.eslestir_embedding([0.0, 1.0, 0.0])
    assert sonuc.eslesti is False
    assert sonuc.gorunen_ad is None
    assert sonuc.karsilama == "Kayıtlı olmayan bir kullanıcı algılandı."
    assert sonuc.karsilama == BILINMEYEN_KULLANICI_MESAJI
    assert sonuc.neden == "unknown"
    assert 0.0 <= sonuc.guven < 0.9
    assert OLAY_YUZ_BILINMEYEN in alinan


def test_dry_run_eslesme_yok() -> None:
    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Yasir", embedding=[1.0, 0.0])
    t = yuz_taniyici_olustur(dry_run=True, kayit=kayit, olay_yayinla=False)
    sonuc = t.tanima(embedding=[1.0, 0.0])
    assert sonuc.dry_run is True
    assert sonuc.eslesti is False
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.neden == "dry_run"
    assert sonuc.karsilama == BILINMEYEN_KULLANICI_MESAJI


def test_zorla_sahte_bilinen_ve_bilinmeyen() -> None:
    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Yasir", embedding=[0.1, 0.2])

    t = yuz_taniyici_olustur(
        dry_run=False, zorla_sahte=True, kayit=kayit, olay_yayinla=False
    )
    bilinen = t.tanima(sahte_ad="Yasir", algila=False)
    assert bilinen.eslesti is True
    assert bilinen.karsilama == "Hoş geldin, Yasir."
    assert bilinen.motor == VisionMotoru.SAHTE
    assert bilinen.guven >= 0.9

    bilinmeyen = t.tanima(sahte_ad="Yabanci", algila=False)
    assert bilinmeyen.eslesti is False
    assert bilinmeyen.karsilama == BILINMEYEN_KULLANICI_MESAJI


def test_toggle_kapali_tanima_yok() -> None:
    g = yuz_gizlilik_olustur(
        yuz_aktif=False,
        kamera_izin=True,
        dry_run=False,
        olay_yayinla=False,
    )
    t = yuz_taniyici_olustur(dry_run=False, gizlilik=g, olay_yayinla=False)
    assert t.izinli_mi() is False
    try:
        t.tanima(embedding=[1.0])
        raise AssertionError("VIS_0701 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0701"


def test_kamera_izni_yok() -> None:
    g = yuz_gizlilik_olustur(
        yuz_aktif=True,
        kamera_izin=False,
        dry_run=False,
        olay_yayinla=False,
    )
    t = yuz_taniyici_olustur(dry_run=False, gizlilik=g, olay_yayinla=False)
    try:
        t.eslestir_embedding([1.0, 0.0])
        raise AssertionError("VIS_0702 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0702"


def test_wire_embedding_yok() -> None:
    bus = EventBus(ad="test.vision.yuz.tanima.wire")
    yukler: list[dict] = []

    def _al(ev) -> None:
        yukler.append(dict(ev.veri or {}))

    bus.subscribe(OLAY_YUZ_TANINDI, _al)
    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Zeynep", embedding=[1.0, 0.0, 0.0])
    t = yuz_taniyici_olustur(
        dry_run=False, kayit=kayit, bus=bus, olay_yayinla=True, min_guven=0.7
    )
    t.eslestir_embedding([1.0, 0.0, 0.0])
    assert len(yukler) == 1
    assert "embedding" not in yukler[0]
    assert "template_path" not in yukler[0]
    assert yukler[0]["display_name"] == "Zeynep"
    assert yukler[0]["greeting"] == "Hoş geldin, Zeynep."
    assert yukler[0]["local_only"] is True


def test_bulut_engeli_ve_yardimci() -> None:
    t = yuz_taniyici_olustur(dry_run=True, olay_yayinla=False)
    try:
        t.buluta_gonder({"embedding": [1.0]})
        raise AssertionError("VIS_0704 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0704"

    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Yasir", embedding=[1.0, 0.0])
    sonuc = yuz_tanima(
        embedding=[1.0, 0.0],
        dry_run=False,
        kayit=kayit,
        min_guven=0.8,
    )
    assert sonuc.eslesti is True
    assert sonuc.karsilama == "Hoş geldin, Yasir."


def test_embedding_uretici_ve_yasam() -> None:
    kayit = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    kayit.kaydet("Yasir", embedding=[0.0, 1.0, 0.0])

    def _uretici(_girdi):
        return [0.0, 1.0, 0.0]

    t = yuz_taniyici_olustur(
        dry_run=False,
        kayit=kayit,
        embedding_uretici=_uretici,
        olay_yayinla=False,
        min_guven=0.8,
    )
    assert t.karsilama("image://x") == "Hoş geldin, Yasir."

    async def _yasam() -> None:
        bus = EventBus(ad="test.vision.yuz.tanima.life")
        alinan: list[str] = []
        bus.subscribe(OLAY_YUZ_TANIMA_BASLADI, lambda ev: alinan.append(ev.ad))
        bus.subscribe(OLAY_YUZ_TANIMA_DURDU, lambda ev: alinan.append(ev.ad))
        y = yuz_taniyici_olustur(dry_run=True, bus=bus, olay_yayinla=True)
        await y.baslat()
        assert y.calisiyor is True
        assert OLAY_YUZ_TANIMA_BASLADI in alinan
        await y.durdur()
        assert y.calisiyor is False
        assert OLAY_YUZ_TANIMA_DURDU in alinan

    asyncio.run(_yasam())

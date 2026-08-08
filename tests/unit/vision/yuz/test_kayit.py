"""vision/yuz/kayit.py birim testleri (çoklu kullanıcı / local-only / gizlilik)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import KayitliKullanici
from vision.yuz.gizlilik import yuz_gizlilik_olustur
from vision.yuz.kayit import (
    OLAY_YUZ_KAYDEDILDI,
    OLAY_YUZ_KAYIT_BASLADI,
    OLAY_YUZ_KAYIT_DURDU,
    OLAY_YUZ_SILINDI,
    YuzKayitYoneticisi,
    yuz_kayit_olustur,
    yuz_kullanici_kaydet,
)


def test_fabrika_ve_ozet() -> None:
    y = yuz_kayit_olustur(dry_run=True)
    assert isinstance(y, YuzKayitYoneticisi)
    assert isinstance(y, ModulTabani)
    assert y.ad == "vision.yuz.kayit"
    ozet = y.ozet()
    assert ozet["local_only"] is True
    assert ozet["privacy"] == "local_only"
    assert ozet["cloud_allowed"] is False
    assert ozet["dry_run"] is True
    assert ozet["user_count"] == 0


def test_coklu_kayit_liste_sil_dry_run() -> None:
    bus = EventBus(ad="test.vision.yuz.kayit")
    alinan: list[str] = []
    bus.subscribe(OLAY_YUZ_KAYDEDILDI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_YUZ_SILINDI, lambda ev: alinan.append(ev.ad))

    y = yuz_kayit_olustur(dry_run=True, bus=bus, olay_yayinla=True)
    a = y.kaydet("Yasir", embedding=[0.1, 0.2, 0.3])
    b = y.kaydet("Ayse", embedding=[0.4, 0.5])
    assert isinstance(a, KayitliKullanici)
    assert a.gorunen_ad == "Yasir"
    assert a.embedding == [0.1, 0.2, 0.3]
    assert y.say() == 2

    liste = y.listele()
    assert len(liste) == 2
    assert {k.gorunen_ad for k in liste} == {"Yasir", "Ayse"}

    wire = y.wire_liste()
    assert len(wire) == 2
    for w in wire:
        assert "embedding" not in w
        assert "template_path" not in w
        assert w["privacy"] == "local_only"
        assert w["local_only"] is True

    assert y.getir(a.id) is not None
    assert y.getir_ad("yasir") is not None  # casefold
    assert y.sil(a.id) is True
    assert y.say() == 1
    assert y.getir(a.id) is None
    assert OLAY_YUZ_KAYDEDILDI in alinan
    assert OLAY_YUZ_SILINDI in alinan
    assert b.gorunen_ad == "Ayse"


def test_yerel_disk_kalicilik() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp) / "vision" / "faces"
        y1 = yuz_kayit_olustur(
            dry_run=False,
            yerel_kok=kok,
            olay_yayinla=False,
            yuz_aktif=True,
            kamera_izin=True,
        )
        k = y1.kaydet(
            "Mehmet",
            embedding=[1.0, 2.0, 3.0],
            sablon=b"FACE_TEMPLATE_BYTES",
        )
        assert kok.exists()
        assert y1.indeks_yolu.is_file()
        sablon = kok / "templates" / f"{k.id}.bin"
        assert sablon.is_file()
        assert sablon.read_bytes() == b"FACE_TEMPLATE_BYTES"

        ham = json.loads(y1.indeks_yolu.read_text(encoding="utf-8"))
        assert ham["local_only"] is True
        assert ham["privacy"] == "local_only"
        assert len(ham["users"]) == 1
        assert ham["users"][0]["embedding"] == [1.0, 2.0, 3.0]
        assert ham["users"][0]["display_name"] == "Mehmet"

        # Yeni örnek aynı kökten yükler
        y2 = yuz_kayit_olustur(
            dry_run=False,
            yerel_kok=kok,
            olay_yayinla=False,
            yuz_aktif=True,
            kamera_izin=True,
        )
        assert y2.say() == 1
        tekrar = y2.getir(k.id)
        assert tekrar is not None
        assert tekrar.embedding == [1.0, 2.0, 3.0]
        assert tekrar.sablon_yolu is not None

        assert y2.sil(k.id) is True
        assert y2.say() == 0
        assert not sablon.is_file()
        ham2 = json.loads(y2.indeks_yolu.read_text(encoding="utf-8"))
        assert ham2["users"] == []


def test_izin_red_toggle_ve_kamera() -> None:
    g = yuz_gizlilik_olustur(
        yuz_aktif=False,
        kamera_izin=True,
        dry_run=False,
        olay_yayinla=False,
    )
    y = yuz_kayit_olustur(dry_run=True, gizlilik=g, olay_yayinla=False)
    assert y.izinli_mi() is False
    try:
        y.kaydet("X")
        raise AssertionError("VIS_0701 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0701"

    g2 = yuz_gizlilik_olustur(
        yuz_aktif=True,
        kamera_izin=False,
        dry_run=False,
        olay_yayinla=False,
    )
    y2 = yuz_kayit_olustur(dry_run=True, gizlilik=g2, olay_yayinla=False)
    try:
        y2.listele()
        raise AssertionError("VIS_0702 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0702"


def test_wire_olayinda_embedding_yok() -> None:
    bus = EventBus(ad="test.vision.yuz.kayit.wire")
    yukler: list[dict] = []

    def _al(ev) -> None:
        yukler.append(dict(ev.veri or {}))

    bus.subscribe(OLAY_YUZ_KAYDEDILDI, _al)
    y = yuz_kayit_olustur(dry_run=True, bus=bus, olay_yayinla=True)
    y.kaydet("Zeynep", embedding=[9.0, 8.0], sablon=b"secret")
    assert len(yukler) == 1
    assert "embedding" not in yukler[0]
    assert "template_path" not in yukler[0]
    assert yukler[0]["display_name"] == "Zeynep"
    assert yukler[0]["local_only"] is True


def test_tekrar_ad_ve_bos_ad() -> None:
    y = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    y.kaydet("Ali")
    try:
        y.kaydet("ali")
        raise AssertionError("VIS_0724 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0724"
    try:
        y.kaydet("   ")
        raise AssertionError("VIS_0721 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0721"


def test_bulut_engeli() -> None:
    y = yuz_kayit_olustur(dry_run=True, olay_yayinla=False)
    try:
        y.buluta_gonder({"embedding": [1.0]})
        raise AssertionError("VIS_0704 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0704"


def test_yardimci_ve_yasam() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp) / "faces"
        k = yuz_kullanici_kaydet(
            "Deniz",
            embedding=[0.5],
            yerel_kok=kok,
            dry_run=False,
        )
        assert k.gorunen_ad == "Deniz"
        assert (kok / "users.json").is_file()

    async def _yasam() -> None:
        bus = EventBus(ad="test.vision.yuz.kayit.life")
        alinan: list[str] = []
        bus.subscribe(OLAY_YUZ_KAYIT_BASLADI, lambda ev: alinan.append(ev.ad))
        bus.subscribe(OLAY_YUZ_KAYIT_DURDU, lambda ev: alinan.append(ev.ad))
        y = yuz_kayit_olustur(dry_run=True, bus=bus, olay_yayinla=True)
        await y.baslat()
        assert y.calisiyor is True
        assert OLAY_YUZ_KAYIT_BASLADI in alinan
        await y.durdur()
        assert y.calisiyor is False
        assert OLAY_YUZ_KAYIT_DURDU in alinan

    asyncio.run(_yasam())

"""vision/yuz/gizlilik.py birim testleri (toggle / izin / local-only / wire)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from config.ayarlar import Ayarlar
from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import (
    VARSAYILAN_YUZ_KOK,
    YuzGizlilikPolitikasi,
    YuzTanimaSonucu,
    kayitli_kullanici_olustur,
)
from vision.yuz.gizlilik import (
    CFG_KAMERA_IZIN,
    CFG_YUZ_AKTIF,
    CFG_YUZ_KOK,
    OLAY_GIZLILIK_BASLADI,
    OLAY_GIZLILIK_DURDU,
    OLAY_IZIN_RED,
    OLAY_KAMERA_IZIN,
    OLAY_YUZ_TOGGLE,
    YuzGizlilikYoneticisi,
    buluta_gonderilebilir_mi,
    hassas_anahtar_mi,
    wire_temizle,
    yerel_kok_coz,
    yuz_gizlilik_olustur,
    yuz_islemi_izinli_mi,
)


def _tmp_ayarlar(veri: dict[str, Any]) -> Ayarlar:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    json.dump(veri, tmp, ensure_ascii=False)
    tmp.flush()
    tmp.close()
    return Ayarlar(Path(tmp.name))


def test_fabrika_ve_ozet() -> None:
    g = yuz_gizlilik_olustur(dry_run=True)
    assert isinstance(g, YuzGizlilikYoneticisi)
    assert isinstance(g, ModulTabani)
    assert g.ad == "vision.yuz.gizlilik"
    assert g.politika is YuzGizlilikPolitikasi.YEREL_ONLY
    assert g.yerel_only is True
    ozet = g.ozet()
    assert ozet["privacy"] == "local_only"
    assert ozet["local_only"] is True
    assert ozet["cloud_allowed"] is False
    assert ozet["face_enabled"] is False  # varsayılan kapalı
    # dry_run → kamera izni varsayılan True (kanca/config yok)
    assert ozet["camera_permission"] is True
    assert VARSAYILAN_YUZ_KOK in ozet["storage_root"].replace("\\", "/")


def test_toggle_ve_izin_zorla() -> None:
    bus = EventBus(ad="test.vision.yuz.gizlilik")
    olaylar: list[str] = []
    bus.subscribe(OLAY_YUZ_TOGGLE, lambda ev: olaylar.append(ev.ad))
    bus.subscribe(OLAY_IZIN_RED, lambda ev: olaylar.append(ev.ad))

    g = YuzGizlilikYoneticisi(
        dry_run=False,
        bus=bus,
        olay_yayinla=True,
        yuz_aktif=False,
        kamera_izin=True,
    )
    assert g.yuz_tanima_aktif_mi() is False
    assert g.islem_izinli_mi() is False

    try:
        g.izin_zorla()
        raise AssertionError("VIS_0701 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0701"
    assert OLAY_IZIN_RED in olaylar

    g.yuz_tanima_ayarla(True)
    assert g.yuz_tanima_aktif_mi() is True
    assert g.islem_izinli_mi() is True
    g.izin_zorla()  # exception yok
    assert OLAY_YUZ_TOGGLE in olaylar


def test_kamera_izin_kancasi() -> None:
    durum = {"ok": False}

    def kanca() -> bool:
        return bool(durum["ok"])

    g = yuz_gizlilik_olustur(
        dry_run=False,
        yuz_aktif=True,
        kamera_izin_kontrol=kanca,
        olay_yayinla=False,
    )
    assert g.kamera_izni_var_mi() is False
    assert g.islem_izinli_mi() is False
    try:
        g.izin_zorla()
        raise AssertionError("VIS_0702 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0702"

    durum["ok"] = True
    assert g.kamera_izni_var_mi() is True
    g.izin_zorla()

    g.kamera_izni_ayarla(False)
    assert g.kamera_izni_var_mi() is False  # override kancayı ezer


def test_config_toggle() -> None:
    ayar = _tmp_ayarlar(
        {
            "vision": {
                "face": {
                    "enabled": True,
                    "camera_permission": True,
                    "storage_root": "database/faces_test",
                    "min_confidence": 0.8,
                }
            }
        }
    )
    g = YuzGizlilikYoneticisi(ayarlar=ayar, dry_run=False, olay_yayinla=False)
    assert g.yuz_tanima_aktif_mi() is True
    assert g.kamera_izni_var_mi() is True
    assert "faces_test" in str(g.yerel_kok())
    assert abs(g.min_guven - 0.8) < 1e-9
    cfg = g.config_ozeti()
    assert cfg[CFG_YUZ_AKTIF] is True
    assert cfg[CFG_KAMERA_IZIN] is True
    assert cfg[CFG_YUZ_KOK].endswith("faces_test") or "faces_test" in cfg[CFG_YUZ_KOK]


def test_wire_embedding_sizdirmaz() -> None:
    kullanici = kayitli_kullanici_olustur(
        "Yasir",
        embedding=[0.11, 0.22, 0.33],
        sablon_yolu="database/faces/yasir.bin",
    )
    g = yuz_gizlilik_olustur(yuz_aktif=True, kamera_izin=True, olay_yayinla=False)
    wire = g.kullanici_wire(kullanici)
    assert "embedding" not in wire
    assert "template_path" not in wire
    assert wire["display_name"] == "Yasir"
    assert wire["privacy"] == "local_only"
    assert wire["local_only"] is True

    ham = {
        "display_name": "Yasir",
        "embedding": [1.0, 2.0],
        "template_path": "x.bin",
        "nested": {"descriptor": [9.0], "ok": True},
        "faces": [{"confidence": 0.9, "encoding": [0.1]}],
    }
    temiz = wire_temizle(ham)
    assert "embedding" not in temiz
    assert "template_path" not in temiz
    assert "descriptor" not in temiz["nested"]
    assert temiz["nested"]["ok"] is True
    assert "encoding" not in temiz["faces"][0]
    assert temiz["faces"][0]["confidence"] == 0.9

    assert hassas_anahtar_mi("embedding") is True
    assert hassas_anahtar_mi("display_name") is False

    sonuc = YuzTanimaSonucu(
        eslesti=True,
        kullanici_id=kullanici.id,
        gorunen_ad="Yasir",
        guven=0.91,
        yerel_only=True,
    )
    tw = g.tanima_wire(sonuc)
    assert "embedding" not in tw
    assert tw["greeting"] == "Hoş geldin, Yasir."
    assert tw["privacy"] == "local_only"


def test_bulut_engeli_ve_yerel_kok() -> None:
    assert buluta_gonderilebilir_mi() is False
    assert buluta_gonderilebilir_mi({"embedding": [1.0]}) is False

    g = yuz_gizlilik_olustur(olay_yayinla=False)
    try:
        g.bulut_gonderimini_engelle({"embedding": [0.1]})
        raise AssertionError("VIS_0704 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0704"

    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp) / "faces_local"
        g2 = yuz_gizlilik_olustur(yerel_kok=kok, olay_yayinla=False)
        assert g2.yerel_kok() == kok
        hazir = g2.yerel_kok_hazirla()
        assert hazir.exists()
        assert hazir.is_dir()

    assert str(yerel_kok_coz()).replace("\\", "/").endswith(VARSAYILAN_YUZ_KOK)


def test_audit_icin_hassas_temizler() -> None:
    g = yuz_gizlilik_olustur(yuz_aktif=True, kamera_izin=True, olay_yayinla=False)
    audit = g.audit_icin(
        {
            "user": "Yasir",
            "embedding": [0.5, 0.6],
            "template_path": "secret.bin",
        }
    )
    assert "embedding" not in audit
    assert "template_path" not in audit
    assert audit["user"] == "Yasir"
    assert audit["privacy"] == "local_only"
    assert audit["face_enabled"] is True


def test_yasam_dongusu_ve_yardimci() -> None:
    bus = EventBus(ad="test.vision.yuz.gizlilik.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_GIZLILIK_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_GIZLILIK_DURDU, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_KAMERA_IZIN, lambda ev: alinan.append(ev.ad))

    g = YuzGizlilikYoneticisi(
        dry_run=True,
        bus=bus,
        olay_yayinla=True,
        yuz_aktif=False,
    )
    asyncio.run(g.baslat())
    assert g.calisiyor is True
    assert OLAY_GIZLILIK_BASLADI in alinan
    g.kamera_izni_ayarla(True)
    assert OLAY_KAMERA_IZIN in alinan
    # Algılama (tanıma değil) — toggle kapalı olsa da kamera izni yeter
    assert g.islem_izinli_mi(tanima_gerekli=False) is True
    assert g.islem_izinli_mi(tanima_gerekli=True) is False
    asyncio.run(g.durdur())
    assert g.calisiyor is False
    assert OLAY_GIZLILIK_DURDU in alinan

    assert yuz_islemi_izinli_mi(
        yuz_gizlilik_olustur(yuz_aktif=True, kamera_izin=True, olay_yayinla=False)
    )
    assert not yuz_islemi_izinli_mi(
        yuz_gizlilik_olustur(yuz_aktif=False, kamera_izin=True, olay_yayinla=False)
    )


def test_algilama_icin_toggle_zorunlu_degil() -> None:
    g = yuz_gizlilik_olustur(
        yuz_aktif=False,
        kamera_izin=True,
        dry_run=False,
        olay_yayinla=False,
    )
    g.izin_zorla(tanima_gerekli=False)
    try:
        g.izin_zorla(tanima_gerekli=True)
        raise AssertionError("VIS_0701 beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0701"

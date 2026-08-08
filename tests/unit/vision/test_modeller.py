"""vision/modeller.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import VisionError
from vision.modeller import (
    BILINMEYEN_KULLANICI_MESAJI,
    VISION_MODEL_SURUM,
    VARSAYILAN_FPS,
    VARSAYILAN_YUZ_ESIK,
    AlgilananNesne,
    AnalizSonucu,
    KameraAyarlari,
    KameraCihazi,
    KayitliKullanici,
    Kare,
    OcrSonucu,
    RenkOzeti,
    VisionAiSonucu,
    VisionGorevTuru,
    VisionMotoru,
    YuzGizlilikPolitikasi,
    YuzTanimaSonucu,
    gorev_turu_coz,
    guven_sinirla,
    kare_olustur,
    kayitli_kullanici_olustur,
    motor_coz,
)


def test_motor_ve_gorev_coz() -> None:
    assert motor_coz("opencv") is VisionMotoru.OPENCV
    assert motor_coz("sahte") is VisionMotoru.SAHTE
    assert motor_coz("dry_run") is VisionMotoru.DRY_RUN
    assert gorev_turu_coz("kamera") is VisionGorevTuru.KAMERA
    assert gorev_turu_coz("face") is VisionGorevTuru.YUZ
    assert gorev_turu_coz("ocr") is VisionGorevTuru.OCR
    try:
        motor_coz("bilinmeyen_motor")
        raise AssertionError("VisionError beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0020"


def test_guven_sinirla() -> None:
    assert guven_sinirla(None) == 0.0
    assert guven_sinirla(1.5) == 1.0
    assert guven_sinirla(-0.2) == 0.0
    assert guven_sinirla(0.85) == 0.85


def test_kare_ve_kamera_roundtrip() -> None:
    kare = kare_olustur(
        yol="database/captures/test.png",
        genislik=640,
        yukseklik=480,
        cihaz=0,
        motor="dry_run",
        dry_run=True,
    )
    d = kare.to_dict()
    assert d["path"] == "database/captures/test.png"
    assert d["engine"] == "dry_run"
    assert "ham" not in d
    geri = Kare.from_dict(d)
    assert geri.genislik == 640
    assert geri.motor is VisionMotoru.DRY_RUN

    cihaz = KameraCihazi(indeks=0, ad="Webcam", erisilebilir=True)
    assert cihaz.to_dict()["name"] == "Webcam"
    assert KameraCihazi.from_dict(cihaz.to_dict()).indeks == 0

    ayar = KameraAyarlari(cihaz=1, fps=VARSAYILAN_FPS)
    assert ayar.to_dict()["fps"] == 15
    assert KameraAyarlari.from_dict({"device": 2, "fps": 0}).fps == 1


def test_ocr_ve_analiz_roundtrip() -> None:
    ocr = OcrSonucu(
        metin="Merhaba",
        dil="tur",
        motor=VisionMotoru.SAHTE,
        guven=0.9,
    )
    assert OcrSonucu.from_dict(ocr.to_dict()).metin == "Merhaba"

    analiz = AnalizSonucu(
        nesneler=[AlgilananNesne(etiket="kupa", guven=0.8, kutu=(1, 2, 3, 4))],
        sahne="masaüstü",
        renk=RenkOzeti(baskin_hex="#112233", palette=["#112233"], ortalama_rgb=(17, 34, 51)),
        qr_verileri=["https://whitecore.local"],
        motor=VisionMotoru.DRY_RUN,
        dry_run=True,
    )
    d = analiz.to_dict()
    assert d["objects"][0]["label"] == "kupa"
    assert d["color"]["dominant_hex"] == "#112233"
    geri = AnalizSonucu.from_dict(d)
    assert geri.nesneler[0].kutu == (1, 2, 3, 4)
    assert geri.qr_verileri == ["https://whitecore.local"]


def test_yuz_yerel_only_ve_karsilama() -> None:
    kullanici = kayitli_kullanici_olustur(
        "Yasir",
        embedding=[0.1, 0.2, 0.3],
        sablon_yolu="database/faces/yasir.bin",
    )
    assert kullanici.karsilama_mesaji() == "Hoş geldin, Yasir."

    wire = kullanici.to_dict(wire=True)
    assert "embedding" not in wire
    assert "template_path" not in wire
    assert wire["privacy"] == YuzGizlilikPolitikasi.YEREL_ONLY.value
    assert wire["display_name"] == "Yasir"

    yerel = kullanici.to_dict(wire=False)
    assert yerel["embedding"] == [0.1, 0.2, 0.3]
    assert yerel["template_path"] == "database/faces/yasir.bin"
    assert yerel["storage"] == "local"

    sonuc = YuzTanimaSonucu(
        eslesti=True,
        kullanici_id=kullanici.id,
        gorunen_ad="Yasir",
        guven=0.91,
        esik=VARSAYILAN_YUZ_ESIK,
        yerel_only=True,
    )
    d = sonuc.to_dict()
    assert d["greeting"] == "Hoş geldin, Yasir."
    assert d["local_only"] is True
    assert d["privacy"] == "local_only"
    assert YuzTanimaSonucu.from_dict(d).eslesti is True

    bilinmeyen = YuzTanimaSonucu(eslesti=False, guven=0.1)
    assert bilinmeyen.karsilama == BILINMEYEN_KULLANICI_MESAJI
    assert bilinmeyen.to_dict()["greeting"] == (
        "Kayıtlı olmayan bir kullanıcı algılandı."
    )

    try:
        kayitli_kullanici_olustur("  ")
        raise AssertionError("VisionError beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0023"


def test_vision_ai_roundtrip() -> None:
    ai = VisionAiSonucu(
        aciklama="Bir masa ve kupa",
        soru="Kaç kupa var?",
        cevap="1",
        sayim=1,
        sayim_etiket="kupa",
        motor=VisionMotoru.SAHTE,
        dry_run=True,
        ek_metin="odaya bak",
    )
    d = ai.to_dict()
    assert d["v"] == VISION_MODEL_SURUM
    assert d["count"] == 1
    geri = VisionAiSonucu.from_dict(d)
    assert geri.cevap == "1"
    assert geri.gorev is VisionGorevTuru.AI


def test_kayitli_kullanici_from_dict_yerel() -> None:
    ham = {
        "id": "usr_abc",
        "display_name": "Yasir",
        "embedding": [1.0, 2.0],
        "template_path": "database/faces/a.bin",
        "active": True,
    }
    k = KayitliKullanici.from_dict(ham)
    assert k.id == "usr_abc"
    assert k.embedding == [1.0, 2.0]
    # wire dışarı sızdırmaz
    assert "embedding" not in k.to_dict(wire=True)

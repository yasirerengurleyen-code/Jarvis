"""vision/yoneticisi.py birim testleri (offline / dry_run)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.camera.kamera import KameraYoneticisi
from vision.modeller import (
    AnalizSonucu,
    OcrSonucu,
    VisionAiSonucu,
    YakalamaSonucu,
    YuzTanimaSonucu,
)
from vision.ocr.motor import OcrYoneticisi
from vision.yoneticisi import (
    OLAY_VISION_BASLADI,
    OLAY_VISION_DURDU,
    VisionYoneticisi,
    vision_yoneticisi_olustur,
)
from vision.yuz.gizlilik import YuzGizlilikYoneticisi
from vision.yuz.algilama import YuzAlgilamaSonucu


def _yonetici(**kwargs) -> VisionYoneticisi:
    bus = EventBus(ad="test.vision")
    return VisionYoneticisi(
        bus=bus,
        dry_run=True,
        olustur=True,
        olay_yayinla=False,
        **kwargs,
    )


def test_modul_tabani_ve_fabrika() -> None:
    m = vision_yoneticisi_olustur(dry_run=True, olay_yayinla=False)
    assert isinstance(m, VisionYoneticisi)
    assert isinstance(m, ModulTabani)
    assert m.ad == "vision"
    assert m.motor == "dry_run"
    assert isinstance(m.kamera, KameraYoneticisi)
    assert isinstance(m.ocr, OcrYoneticisi)
    assert isinstance(m.gizlilik, YuzGizlilikYoneticisi)
    assert m.calisiyor is False
    # Varsayılan: yüz tanıma kapalı (gizlilik)
    assert m.yuz_tanima_aktif_mi() is False
    # dry_run: kamera izni açık (offline test)
    assert m.gizlilik.kamera_izni_var_mi() is True
    # Paylaşımlı gizlilik
    assert m.tanima.gizlilik is m.gizlilik
    assert m.kayit.gizlilik is m.gizlilik
    assert m.algilama.gizlilik is m.gizlilik
    # Paylaşımlı OCR
    assert m.ekran.ocr is m.ocr
    assert m.pdf.ocr is m.ocr
    # Paylaşımlı kamera
    assert m.akis.kamera is m.kamera


def test_dry_run_baslat_durdur_ozet() -> None:
    async def _run() -> None:
        m = _yonetici()
        assert m.motor == "dry_run"

        await m.baslat()
        assert m.calisiyor
        assert m.kamera.calisiyor
        assert m.ocr.calisiyor
        assert m.gizlilik.calisiyor

        ozet = m.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["enabled"] is True
        assert ozet["dry_run"] is True
        assert ozet["face_enabled"] is False
        assert ozet["local_only"] is True
        assert ozet["cloud_allowed"] is False
        assert ozet["camera"]["bound"] is True
        assert ozet["ocr"]["bound"] is True
        assert ozet["privacy"]["bound"] is True
        assert ozet["caption"]["bound"] is True
        assert ozet["multimodal"]["bound"] is True

        await m.durdur()
        assert not m.calisiyor
        assert not m.kamera.calisiyor

    asyncio.run(_run())


def test_baslamadan_api_hata() -> None:
    m = _yonetici()
    try:
        m.fotograf_cek()
        raise AssertionError("VisionError beklenirdi")
    except VisionError as exc:
        assert exc.kod == "VIS_0051"


def test_kamera_ocr_analiz_ai_facade() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            cihazlar = m.kamera_listele()
            assert isinstance(cihazlar, list)

            foto = m.fotograf_cek()
            assert isinstance(foto, YakalamaSonucu)
            assert foto.kare.dry_run is True

            kare = await m.kare_al()
            assert kare.dry_run is True

            ocr = m.ocr_oku("dummy.png")
            assert isinstance(ocr, OcrSonucu)
            assert ocr.dry_run is True
            assert ocr.metin == ""

            ekran = m.ekran_ocr_oku()
            assert isinstance(ekran, OcrSonucu)
            assert ekran.dry_run is True

            nesne = m.nesne_algila("dummy.png")
            assert isinstance(nesne, AnalizSonucu)
            assert nesne.dry_run is True

            sahne = m.sahne_analiz("dummy.png")
            assert isinstance(sahne, AnalizSonucu)
            assert sahne.dry_run is True

            renk = m.renk_analiz("dummy.png")
            assert isinstance(renk, AnalizSonucu)
            assert renk.dry_run is True

            qr = m.qr_analiz("dummy.png")
            assert isinstance(qr, AnalizSonucu)
            assert qr.dry_run is True
            assert qr.qr_verileri == []

            cap = m.gorsel_acikla("dummy.png")
            assert isinstance(cap, VisionAiSonucu)
            assert cap.dry_run is True

            vqa = m.gorsel_sor("dummy.png", "Ne var?")
            assert isinstance(vqa, VisionAiSonucu)
            assert vqa.dry_run is True
            assert vqa.soru == "Ne var?"

            say = m.nesne_say("dummy.png")
            assert isinstance(say, VisionAiSonucu)
            assert say.dry_run is True
            assert say.sayim == 0

            mm = m.multimodal_analiz("dummy.png", "Bu görüntüyü özetle")
            assert isinstance(mm, VisionAiSonucu)
            assert mm.dry_run is True
            assert mm.ek_metin == "Bu görüntüyü özetle"
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_yuz_toggle_ve_gizlilik() -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            assert m.yuz_tanima_aktif_mi() is False

            # Toggle kapalı → tanıma engellenir
            try:
                m.yuz_tanima("dummy.png")
                raise AssertionError("VisionError beklenirdi (toggle kapalı)")
            except VisionError as exc:
                assert exc.kod == "VIS_0701"

            # Aç → dry_run bilinmeyen yolu
            m.yuz_tanima_ayarla(True)
            assert m.yuz_tanima_aktif_mi() is True

            alg = m.yuz_algila("dummy.png")
            assert isinstance(alg, YuzAlgilamaSonucu)
            assert alg.dry_run is True
            assert alg.kutular == []

            # Kayıt (yerel / dry_run bellek)
            kullanici = m.yuz_kaydet(
                "Test Kullanici",
                embedding=[0.1, 0.2, 0.3, 0.4],
            )
            assert kullanici.gorunen_ad == "Test Kullanici"
            wire_k = kullanici.to_dict(wire=True)
            assert "embedding" not in wire_k
            assert "template" not in wire_k

            sonuc = m.yuz_tanima("dummy.png")
            assert isinstance(sonuc, YuzTanimaSonucu)
            assert sonuc.dry_run is True
            # dry_run → bilinmeyen / eşleşme yok
            assert sonuc.eslesti is False
            assert "Kayıtlı olmayan" in (sonuc.karsilama or "")

            wire = m.yuz_wire(sonuc)
            assert "embedding" not in wire
            assert "template" not in str(wire).lower()
            assert wire.get("matched") is False
            assert "greeting" in wire

            # Kapat
            m.yuz_tanima_ayarla(False)
            assert m.yuz_tanima_aktif_mi() is False
        finally:
            await m.durdur()

    asyncio.run(_run())


def test_olay_yayini() -> None:
    async def _run() -> None:
        bus = EventBus(ad="test.vision.events")
        olaylar: list[str] = []

        def _dinle(event) -> None:
            olaylar.append(event.ad)

        bus.subscribe(OLAY_VISION_BASLADI, _dinle)
        bus.subscribe(OLAY_VISION_DURDU, _dinle)

        m = VisionYoneticisi(
            bus=bus,
            dry_run=True,
            olustur=True,
            olay_yayinla=True,
        )
        await m.baslat()
        await m.durdur()

        assert OLAY_VISION_BASLADI in olaylar
        assert OLAY_VISION_DURDU in olaylar

    asyncio.run(_run())


def test_pdf_ocr_dry_run(tmp_path: Path) -> None:
    async def _run() -> None:
        m = _yonetici()
        await m.baslat()
        try:
            yol = tmp_path / "ornek.pdf"
            yol.write_bytes(b"%PDF-1.4 dry_run")
            sonuc = m.pdf_ocr_oku(yol)
            assert isinstance(sonuc, OcrSonucu)
            assert sonuc.dry_run is True
        finally:
            await m.durdur()

    asyncio.run(_run())

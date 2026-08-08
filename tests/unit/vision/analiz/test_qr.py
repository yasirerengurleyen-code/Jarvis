"""vision/analiz/qr.py birim testleri (dry_run / sahte / mock decoder / skill)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import ModulTabani
from core.events import EventBus
from core.exceptions import VisionError
from vision.modeller import AnalizSonucu, VisionMotoru, kare_olustur
from vision.analiz.qr import (
    OLAY_QR_BASLADI,
    OLAY_QR_DURDU,
    OLAY_QR_OKUNDU,
    QrAnalizci,
    numpy_var_mi,
    opencv_var_mi,
    pyzbar_var_mi,
    qr_analiz,
    qr_analizci_olustur,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sahte_decoder(mat: Any) -> dict[str, Any]:
    _ = mat
    return {
        "qr": ["https://whitecore.test/qr-a", "https://whitecore.test/qr-b"],
        "barcodes": ["8691111111111"],
    }


class _SahteDetector:
    def __init__(self, *, veri: str = "https://whitecore.test/qr") -> None:
        self.veri = veri
        self.cagrilar = 0

    def detectAndDecodeMulti(self, img):  # noqa: ANN001, ARG002
        self.cagrilar += 1
        return False, [], None, None

    def detectAndDecode(self, img):  # noqa: ANN001, ARG002
        self.cagrilar += 1
        return self.veri, None, None


class _SahteCv2:
    IMREAD_COLOR = 1

    def __init__(self, *, veri: str = "https://whitecore.test/qr") -> None:
        self._detector = _SahteDetector(veri=veri)
        self.QRCodeDetector = lambda: self._detector

    def imdecode(self, buf, flags):  # noqa: ANN001, ARG002
        return {"fake": True, "buf_len": len(buf) if buf is not None else 0}

    def imread(self, yol: str, flags=None):  # noqa: ANN001, ARG002
        return {"fake": True, "path": yol}


def test_fabrika_ve_ozet() -> None:
    r = qr_analizci_olustur(dry_run=True)
    assert isinstance(r, QrAnalizci)
    assert isinstance(r, ModulTabani)
    assert r.ad == "vision.analiz.qr"
    assert r.motor == "dry_run"
    assert r.backend == "dry_run"
    ozet = r.ozet()
    assert ozet["dry_run"] is True
    assert ozet["skill_bridge"] is True
    assert ozet["barcode"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)
    assert isinstance(pyzbar_var_mi(), bool)


def test_dry_run_ve_olay() -> None:
    bus = EventBus(ad="test.vision.analiz.qr")
    alinan: list[str] = []
    bus.subscribe(OLAY_QR_OKUNDU, lambda ev: alinan.append(ev.ad))

    r = QrAnalizci(dry_run=True, bus=bus, olay_yayinla=True)
    sonuc = r.analiz("image://dry_run")
    assert isinstance(sonuc, AnalizSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.qr_verileri == []
    assert sonuc.barkodlar == []
    assert sonuc.neden == "dry_run"
    assert r.son_sonuc is sonuc
    assert OLAY_QR_OKUNDU in alinan

    d = sonuc.to_dict()
    assert d["qr"] == []
    assert d["barcodes"] == []
    assert d["dry_run"] is True
    assert d["engine"] == "dry_run"


def test_zorla_sahte() -> None:
    r = qr_analizci_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    assert r.motor == "sahte"
    sonuc = r.analiz("image://sahte")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert len(sonuc.qr_verileri) >= 1
    assert "whitecore" in sonuc.qr_verileri[0].lower()
    assert len(sonuc.barkodlar) >= 1

    s2 = r.analiz(
        b"x",
        sahte_qr=["Jarvis-QR-99"],
        sahte_barkod=["1234567890123"],
    )
    assert s2.qr_verileri == ["Jarvis-QR-99"]
    assert s2.barkodlar == ["1234567890123"]

    s3 = r.analiz("image://no-bc", barkod_oku=False, sahte_qr=["only-qr"])
    assert s3.qr_verileri == ["only-qr"]
    assert s3.barkodlar == []


def test_mock_decoder_ve_kisayollar() -> None:
    r = QrAnalizci(
        dry_run=False,
        zorla_sahte=False,
        decoder=_sahte_decoder,
        olay_yayinla=False,
    )
    assert r.motor == "opencv"
    assert r.backend == "injected"

    sonuc = r.analiz(_MINI_PNG)
    assert sonuc.motor == VisionMotoru.OPENCV
    assert sonuc.neden == "injected"
    assert sonuc.qr_verileri == [
        "https://whitecore.test/qr-a",
        "https://whitecore.test/qr-b",
    ]
    assert sonuc.barkodlar == ["8691111111111"]

    assert r.qr_listesi(_MINI_PNG) == [
        "https://whitecore.test/qr-a",
        "https://whitecore.test/qr-b",
    ]
    assert r.ilk_qr(_MINI_PNG) == "https://whitecore.test/qr-a"
    assert r.barkod_listesi(_MINI_PNG) == ["8691111111111"]
    assert r.oku(_MINI_PNG).neden == "injected"


def test_kare_ve_tuple_decoder() -> None:
    def det(mat: Any) -> tuple[list[str], list[str]]:
        _ = mat
        return ["tek-qr"], ["tek-barkod"]

    kare = kare_olustur(
        yol="mem://test-qr",
        motor=VisionMotoru.SAHTE,
        dry_run=False,
        bayt_sayisi=len(_MINI_PNG),
        ham=_MINI_PNG,
    )
    r = qr_analizci_olustur(dry_run=False, decoder=det, olay_yayinla=False)
    sonuc = r.analiz(kare)
    assert sonuc.kaynak_yol == "mem://test-qr"
    assert sonuc.qr_verileri == ["tek-qr"]
    assert sonuc.barkodlar == ["tek-barkod"]


def test_dosya_yok_hata() -> None:
    r = QrAnalizci(
        dry_run=False,
        zorla_sahte=False,
        decoder=_sahte_decoder,
        olay_yayinla=False,
    )
    try:
        r.analiz(str(_KOK / "yok_olmayan_qr_goruntu_xyz.png"))
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as exc:
        assert exc.kod == "VIS_0632"


def test_skill_kopru_dosya() -> None:
    """Var olan dosya + stub cv2 → skill köprüsü yolu."""
    tmp = Path(tempfile.mkdtemp()) / "mock_qr.png"
    tmp.write_bytes(_MINI_PNG)
    stub = _SahteCv2(veri="https://whitecore.ai/skill-ok")

    r = QrAnalizci(
        dry_run=False,
        zorla_sahte=False,
        cv2_modul=stub,
        numpy_modul=__import__("numpy") if numpy_var_mi() else _FakeNp(),
        olay_yayinla=False,
        barkod_oku=False,
    )
    # OpenCV motor seçilsin
    assert r.motor == "opencv"

    # numpy yoksa FakeNp ile skill imdecode yolu çalışır
    if not numpy_var_mi():
        # skill kendi numpy'sini dener; yoksa imread
        pass

    sonuc = r.analiz(tmp)
    assert sonuc.motor == VisionMotoru.OPENCV
    assert "skill-ok" in (sonuc.qr_verileri[0] if sonuc.qr_verileri else "")
    assert sonuc.barkodlar == []


class _FakeNp:
    """numpy olmadan imdecode stub için minimal yardımcı."""

    uint8 = "uint8"

    @staticmethod
    def frombuffer(ham, dtype=None):  # noqa: ANN001, ARG004
        return ham


def test_bilinen_yardimci() -> None:
    bil = qr_analiz("x://dry", dry_run=True)
    assert bil.dry_run is True
    assert bil.qr_verileri == []

    sahte = qr_analiz(
        "x://sahte",
        zorla_sahte=True,
        sahte_qr=["A"],
        sahte_barkod=["B"],
    )
    assert sahte.motor == VisionMotoru.SAHTE
    assert sahte.qr_verileri == ["A"]
    assert sahte.barkodlar == ["B"]


def test_baslat_durdur() -> None:
    bus = EventBus(ad="test.vision.analiz.qr.life")
    alinan: list[str] = []
    bus.subscribe(OLAY_QR_BASLADI, lambda ev: alinan.append(ev.ad))
    bus.subscribe(OLAY_QR_DURDU, lambda ev: alinan.append(ev.ad))

    r = QrAnalizci(dry_run=True, bus=bus, olay_yayinla=True)

    async def _kos() -> None:
        await r.baslat()
        assert r.calisiyor is True
        await r.durdur()
        assert r.calisiyor is False

    asyncio.run(_kos())
    assert OLAY_QR_BASLADI in alinan
    assert OLAY_QR_DURDU in alinan


def test_serilestirme_wire() -> None:
    r = qr_analizci_olustur(dry_run=False, zorla_sahte=True, olay_yayinla=False)
    sonuc = r.analiz(
        "wire://test",
        sahte_qr=["https://wire.local/qr"],
        sahte_barkod=["999"],
    )
    d = sonuc.to_dict()
    geri = AnalizSonucu.from_dict(d)
    assert geri.qr_verileri == ["https://wire.local/qr"]
    assert geri.barkodlar == ["999"]
    assert d["qr"] == ["https://wire.local/qr"]
    assert d["barcodes"] == ["999"]
    assert d["engine"] == "sahte"


def test_decoder_str_ve_list() -> None:
    r = QrAnalizci(
        dry_run=False,
        decoder=lambda _m: "tek-metin",
        olay_yayinla=False,
    )
    assert r.analiz(_MINI_PNG).qr_verileri == ["tek-metin"]

    r2 = QrAnalizci(
        dry_run=False,
        decoder=lambda _m: ["a", "b", "a"],
        olay_yayinla=False,
    )
    assert r2.analiz(_MINI_PNG).qr_verileri == ["a", "b"]

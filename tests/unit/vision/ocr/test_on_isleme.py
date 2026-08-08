"""vision/ocr/on_isleme.py birim testleri (dry_run / sahte / mock opencv)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import VisionError
from vision.modeller import Kare, VisionMotoru, kare_olustur
from vision.ocr.on_isleme import (
    OnIslemeAyarlari,
    OnIslemeSonucu,
    OcrOnIsleme,
    numpy_var_mi,
    on_isle,
    on_isleme_olustur,
    opencv_var_mi,
)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeArr:
    """Basit numpy benzeri dizi stub'u."""

    def __init__(self, shape: tuple[int, ...], data: Any = None) -> None:
        self.shape = shape
        self.dtype = "uint8"
        self._data = data

    def astype(self, _dtype: Any) -> "_FakeArr":
        return self

    def __len__(self) -> int:
        if len(self.shape) == 1:
            return int(self.shape[0])
        return int(self.shape[0])

    def __gt__(self, _other: Any) -> "_FakeArr":
        # Canny sonrası np.where(kenar > 0) için
        return self

    def __bool__(self) -> bool:
        return True


class _FakeBuf:
    def tobytes(self) -> bytes:
        return _MINI_PNG


class _SahteNp:
    uint8 = "uint8"
    float32 = "float32"

    def frombuffer(self, ham: bytes, dtype: Any = None) -> _FakeArr:  # noqa: ARG002
        return _FakeArr((len(ham),), data=ham)

    def column_stack(self, args: Any) -> _FakeArr:
        # Canny sonucu gibi birkaç nokta
        return _FakeArr((30, 2), data=args)

    def where(self, cond: Any) -> tuple[_FakeArr, ...]:  # noqa: ARG002
        return (_FakeArr((30,)), _FakeArr((30,)))


class _SahteCv2:
    IMREAD_COLOR = 1
    COLOR_BGR2GRAY = 6
    THRESH_BINARY = 0
    THRESH_OTSU = 8
    ADAPTIVE_THRESH_GAUSSIAN_C = 1
    INTER_AREA = 3
    INTER_CUBIC = 2
    BORDER_REPLICATE = 1

    def __init__(self) -> None:
        self.imread_calls = 0
        self.imdecode_calls = 0
        self.cvt_calls = 0
        self.threshold_calls = 0
        self.blur_calls = 0
        self.resize_calls = 0
        self.canny_calls = 0

    def imread(self, path: str, flags: int = 1) -> _FakeArr:  # noqa: ARG002
        self.imread_calls += 1
        return _FakeArr((48, 64, 3))

    def imdecode(self, buf: Any, flags: int = 1) -> _FakeArr:  # noqa: ARG002
        self.imdecode_calls += 1
        return _FakeArr((48, 64, 3))

    def imencode(self, ext: str, mat: Any):  # noqa: ARG002
        return True, _FakeBuf()

    def cvtColor(self, mat: Any, code: int) -> _FakeArr:  # noqa: ARG002
        self.cvt_calls += 1
        h, w = mat.shape[0], mat.shape[1]
        return _FakeArr((h, w))

    def medianBlur(self, mat: Any, k: int) -> Any:  # noqa: ARG002
        self.blur_calls += 1
        return mat

    def threshold(self, mat: Any, *_a: Any, **_k: Any) -> tuple[float, Any]:
        self.threshold_calls += 1
        return 127.0, mat

    def adaptiveThreshold(self, mat: Any, *_a: Any, **_k: Any) -> Any:
        self.threshold_calls += 1
        return mat

    def resize(self, mat: Any, dsize: tuple[int, int], **_k: Any) -> _FakeArr:
        self.resize_calls += 1
        w, h = dsize
        return _FakeArr((h, w) if len(mat.shape) == 2 else (h, w, 3))

    def Canny(self, mat: Any, *_a: Any, **_k: Any) -> _FakeArr:  # noqa: ARG002
        self.canny_calls += 1
        h, w = mat.shape[0], mat.shape[1]
        return _FakeArr((h, w))

    def minAreaRect(self, pts: Any) -> tuple:  # noqa: ARG002
        # (center, size, angle)
        return ((32.0, 24.0), (40.0, 20.0), -2.0)

    def getRotationMatrix2D(self, center: Any, angle: float, scale: float) -> list:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    def warpAffine(self, mat: Any, *_a: Any, **_k: Any) -> Any:
        return mat


def test_fabrika_ve_ozellikler() -> None:
    m = on_isleme_olustur(dry_run=True)
    assert isinstance(m, OcrOnIsleme)
    assert m.ad == "vision.ocr.preprocess"
    assert m.motor == "dry_run"
    ozet = m.ozet()
    assert ozet["dry_run"] is True
    assert ozet["settings"]["grayscale"] is True
    assert isinstance(opencv_var_mi(), bool)
    assert isinstance(numpy_var_mi(), bool)


def test_dry_run_kare_ve_adimlar() -> None:
    kare = kare_olustur(
        yol="ornek.png",
        genislik=100,
        yukseklik=50,
        motor=VisionMotoru.DRY_RUN,
        dry_run=True,
        bayt_sayisi=12,
    )
    sonuc = on_isle(kare, dry_run=True)
    assert isinstance(sonuc, OnIslemeSonucu)
    assert sonuc.dry_run is True
    assert sonuc.motor == VisionMotoru.DRY_RUN
    assert sonuc.kare.dry_run is True
    assert "grayscale" in sonuc.adimlar
    assert any(a.startswith("threshold:") for a in sonuc.adimlar)
    assert "denoise" in sonuc.adimlar
    assert "deskew" in sonuc.adimlar
    assert "resize" in sonuc.adimlar
    assert sonuc.kaynak_yol == "ornek.png"
    d = sonuc.to_dict()
    assert d["engine"] == "dry_run"
    assert d["frame"]["path"] == "ornek.png"
    geri = OnIslemeSonucu.from_dict(d)
    assert geri.motor == VisionMotoru.DRY_RUN
    assert geri.adimlar == sonuc.adimlar


def test_sahte_passthrough_opencv_yok() -> None:
    # Ortamda cv2 yok → sahte passthrough
    sonuc = on_isle(_MINI_PNG, dry_run=False, zorla_sahte=False)
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.dry_run is False
    assert sonuc.adimlar == []
    assert sonuc.neden in ("opencv_yok", "numpy_yok")
    assert sonuc.kare.ham == _MINI_PNG


def test_zorla_sahte_ve_ayarlar_dict() -> None:
    ayar = OnIslemeAyarlari.from_dict(
        {
            "grayscale": True,
            "threshold": False,
            "denoise": False,
            "deskew": False,
            "resize": False,
        }
    )
    assert ayar.esik is False
    m = on_isleme_olustur(dry_run=False, zorla_sahte=True, ayarlar=ayar)
    assert m.motor == "sahte"
    sonuc = m.isle(b"abc")
    assert sonuc.motor == VisionMotoru.SAHTE
    assert sonuc.neden == "zorla_sahte"
    assert sonuc.kare.ham == b"abc"


def test_mock_opencv_tam_pipeline() -> None:
    cv2 = _SahteCv2()
    np = _SahteNp()
    m = on_isleme_olustur(
        dry_run=False,
        zorla_sahte=False,
        cv2_modul=cv2,
        numpy_modul=np,
    )
    assert m.motor == "opencv"

    with tempfile.TemporaryDirectory() as tmp:
        yol = Path(tmp) / "in.png"
        yol.write_bytes(_MINI_PNG)
        cikis = Path(tmp) / "out.png"
        sonuc = m.isle(str(yol), cikis_yolu=cikis)

        assert sonuc.motor == VisionMotoru.OPENCV
        assert sonuc.dry_run is False
        assert "grayscale" in sonuc.adimlar
        assert "denoise" in sonuc.adimlar
        assert any(a.startswith("threshold:") for a in sonuc.adimlar)
        assert cv2.imread_calls == 1
        assert cv2.cvt_calls >= 1
        assert cv2.blur_calls >= 1
        assert cv2.threshold_calls >= 1
        assert sonuc.kare.ham == _MINI_PNG
        assert cikis.is_file()
        assert m.son_sonuc is sonuc


def test_mock_opencv_kare_ham_ve_tek_adimlar() -> None:
    cv2 = _SahteCv2()
    np = _SahteNp()
    m = OcrOnIsleme(dry_run=False, cv2_modul=cv2, numpy_modul=np)
    kare = kare_olustur(
        genislik=64,
        yukseklik=48,
        motor=VisionMotoru.OPENCV,
        dry_run=False,
        ham=_MINI_PNG,
        bayt_sayisi=len(_MINI_PNG),
    )
    s1 = m.gri_yap(kare)
    assert "grayscale" in s1.adimlar
    assert not any(a.startswith("threshold:") for a in s1.adimlar)

    s2 = m.esikle(_MINI_PNG, metod="adaptive")
    assert any("adaptive" in a for a in s2.adimlar)

    s3 = m.gurultu_azalt(_MINI_PNG)
    assert "denoise" in s3.adimlar

    s4 = m.yeniden_boyutlandir(_MINI_PNG, max_genislik=32, max_yukseklik=24)
    # 64x48 → resize uygulanır
    assert "resize" in s4.adimlar
    assert cv2.resize_calls >= 1


def test_mock_deskew_ve_bos_kare_hata() -> None:
    cv2 = _SahteCv2()
    np = _SahteNp()
    m = on_isleme_olustur(dry_run=False, cv2_modul=cv2, numpy_modul=np)
    s = m.egim_duzelt(_MINI_PNG)
    assert s.motor == VisionMotoru.OPENCV
    # açı -2.0 → deskew uygulanır
    assert "deskew" in s.adimlar
    assert cv2.canny_calls >= 1

    bos = Kare(yol=None, ham=None)
    try:
        m.isle(bos)
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0202"


def test_desteklenmeyen_girdi() -> None:
    cv2 = _SahteCv2()
    np = _SahteNp()
    m = on_isleme_olustur(dry_run=False, cv2_modul=cv2, numpy_modul=np)
    try:
        m.isle(object())  # type: ignore[arg-type]
        raise AssertionError("VisionError bekleniyordu")
    except VisionError as hata:
        assert hata.kod == "VIS_0203"

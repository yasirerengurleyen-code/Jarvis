"""skills/media/kamera.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.media.kamera import (
    KameraSkill,
    cihaz_indeksi_ayikla,
    cihazlari_listele,
    fotograf_cek,
    islem_ayikla,
    kayit_yolu_ayikla,
    kamera_ac,
)
from skills.yoneticisi import SkillYoneticisi


class _SahteCap:
    def __init__(self, acik: bool = True, kare=None) -> None:
        self._acik = acik
        self._kare = kare if kare is not None else [[0, 0], [0, 0]]

    def isOpened(self) -> bool:
        return self._acik

    def read(self):
        return True, self._kare

    def release(self) -> None:
        return None


class _SahteCv2:
    """OpenCV olmadan / donanım olmadan test için enjekte edilen stub."""

    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4

    def __init__(self, *, acik: bool = True) -> None:
        self.acik = acik
        self.VideoCapture = lambda idx: _SahteCap(acik=self.acik)  # noqa: ARG005

    def imencode(self, ext, kare):  # noqa: ANN001
        class _Buf:
            def tobytes(self) -> bytes:
                return b"\x89PNG\r\n\x1a\nfake"

        return True, _Buf()


def test_islem_ve_ayiklama() -> None:
    assert islem_ayikla("kamera listele") == "listele"
    assert islem_ayikla("camera list devices") == "listele"
    assert islem_ayikla("kamera aç") == "ac"
    assert islem_ayikla("fotoğraf çek") == "cek"
    assert islem_ayikla("snapshot al") == "cek"
    assert cihaz_indeksi_ayikla("kamera 2 ile çek") == 2
    assert kayit_yolu_ayikla('çek "C:/tmp/a.png"') == "C:/tmp/a.png"
    assert kayit_yolu_ayikla("foto snap.JPG").lower().endswith("snap.jpg")


def test_dry_run_ve_sahte() -> None:
    bil = cihazlari_listele(dry_run=True)
    assert bil["dry_run"] is True
    assert bil["count"] >= 1

    bil2 = cihazlari_listele(zorla_sahte=True)
    assert bil2["engine"] == "sahte"

    ac = kamera_ac(0, dry_run=True)
    assert ac["dry_run"] is True
    assert ac["opened"] is True

    tmp = Path(tempfile.mkdtemp()) / "snap.png"
    cek = fotograf_cek(0, yol=tmp, dry_run=True)
    assert cek["dry_run"] is True
    assert not tmp.exists()

    cek2 = fotograf_cek(0, yol=tmp, zorla_sahte=True)
    assert cek2["engine"] == "sahte"
    assert tmp.is_file()
    assert tmp.stat().st_size > 0


def test_mock_opencv_ve_skill() -> None:
    async def _run() -> None:
        stub = _SahteCv2(acik=True)
        tmp = Path(tempfile.mkdtemp()) / "mock.png"

        # Stub VideoCapture ok; imencode sahte bayt yazar
        # Kare shape için basit liste yerine gerçek ndarray benzeri
        class _Kare:
            shape = (10, 20, 3)

        stub.VideoCapture = lambda idx: _SahteCap(acik=True, kare=_Kare())  # noqa: ARG005
        bil = fotograf_cek(0, yol=tmp, cv2_modul=stub)
        assert bil["engine"] == "opencv"
        assert bil["width"] == 20
        assert bil["height"] == 10
        assert tmp.is_file()

        liste = cihazlari_listele(cv2_modul=stub, max_indeks=2)
        assert liste["engine"] == "opencv"
        assert liste["count"] >= 1

        s = KameraSkill()
        assert s.eslesir_mi("fotoğraf çek")
        assert s.eslesir_mi("kamera listele")

        r = await s.calistir("kamera listele", dry_run=True)
        assert r.basarili
        assert r.veri["dry_run"] is True

        r2 = await s.calistir("fotoğraf çek", zorla_sahte=True, yol=str(tmp.with_name("s2.png")))
        assert r2.basarili
        assert r2.veri["engine"] == "sahte"

        r3 = await s.calistir("kamera aç", dry_run=True)
        assert r3.basarili

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r4 = await y.calistir("snapshot", dry_run=True)
        assert r4.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_islem_ve_ayiklama()
    test_dry_run_ve_sahte()
    test_mock_opencv_ve_skill()
    print("OK test_kamera")

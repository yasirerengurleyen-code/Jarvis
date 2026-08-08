"""skills/media/qr_okuyucu.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.media.qr_okuyucu import (
    QrOkuyucuSkill,
    gorsel_yolu_ayikla,
    opencv_var_mi,
    qr_oku,
)
from skills.yoneticisi import SkillYoneticisi

# 1x1 PNG — gerçek görüntü dosyası (QR motor stub ile okunur)
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _SahteDetector:
    """cv2.QRCodeDetector stub'u."""

    def __init__(
        self,
        *,
        veri: str = "https://whitecore.test/qr",
        coklu: list[str] | None = None,
        hata: bool = False,
    ) -> None:
        self.veri = veri
        self.coklu = coklu
        self.hata = hata
        self.cagrilar = 0

    def detectAndDecodeMulti(self, img):  # noqa: ANN001, ARG002
        self.cagrilar += 1
        if self.hata:
            raise RuntimeError("detector hata")
        if self.coklu is not None:
            return True, list(self.coklu), None, None
        return False, [], None, None

    def detectAndDecode(self, img):  # noqa: ANN001, ARG002
        self.cagrilar += 1
        if self.hata:
            raise RuntimeError("detector hata")
        return self.veri, None, None


class _SahteCv2:
    """OpenCV olmadan test için enjekte edilen stub."""

    IMREAD_COLOR = 1

    def __init__(
        self,
        *,
        veri: str = "https://whitecore.test/qr",
        coklu: list[str] | None = None,
        imread_none: bool = False,
        detector_hata: bool = False,
    ) -> None:
        self._detector = _SahteDetector(
            veri=veri, coklu=coklu, hata=detector_hata
        )
        self.imread_none = imread_none
        self.QRCodeDetector = lambda: self._detector

    def imdecode(self, buf, flags):  # noqa: ANN001, ARG002
        if self.imread_none:
            return None
        return {"fake": True, "buf_len": len(buf) if buf is not None else 0}

    def imread(self, yol: str):  # noqa: ARG002
        if self.imread_none:
            return None
        return {"fake": True, "path": yol}


def test_gorsel_yolu_ayikla() -> None:
    assert gorsel_yolu_ayikla('qr oku "C:/tmp/a.png"') == "C:/tmp/a.png"
    assert gorsel_yolu_ayikla("karekod oku foto.JPG").lower().endswith("foto.jpg")
    assert gorsel_yolu_ayikla("qr yok") is None


def test_dry_run_ve_sahte() -> None:
    tmp = Path(tempfile.mkdtemp()) / "snap.png"
    tmp.write_bytes(_MINI_PNG)

    bil = qr_oku(tmp, dry_run=True)
    assert bil["dry_run"] is True
    assert bil["engine"] == "dry_run"
    assert bil["data"] == ""
    assert bil["count"] == 0

    bil2 = qr_oku(tmp, zorla_sahte=True)
    assert bil2["engine"] == "sahte"
    assert bil2["count"] == 1
    assert "whitecore" in bil2["data"].lower()

    bil3 = qr_oku(tmp, sahte_veri="Jarvis-QR-123")
    assert bil3["engine"] == "sahte"
    assert bil3["data"] == "Jarvis-QR-123"


def test_mock_opencv_ve_skill() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "mock_qr.png"
        tmp.write_bytes(_MINI_PNG)

        stub = _SahteCv2(veri="https://whitecore.ai/ok")
        bil = qr_oku(tmp, cv2_modul=stub)
        assert bil["engine"] == "opencv"
        assert bil["data"] == "https://whitecore.ai/ok"
        assert bil["count"] == 1
        assert stub._detector.cagrilar >= 1

        # çoklu QR
        stub_m = _SahteCv2(coklu=["bir", "iki"])
        bil_m = qr_oku(tmp, cv2_modul=stub_m)
        assert bil_m["count"] == 2
        assert bil_m["codes"] == ["bir", "iki"]
        assert bil_m["data"] == "bir"

        # QR yok
        stub_b = _SahteCv2(veri="")
        bil_b = qr_oku(tmp, cv2_modul=stub_b)
        assert bil_b["engine"] == "opencv"
        assert bil_b["count"] == 0
        assert bil_b.get("reason") == "qr_bulunamadi"

        s = QrOkuyucuSkill()
        assert s.eslesir_mi("qr oku test.png")
        assert s.eslesir_mi("karekod tara")
        assert s.eslesir_mi("read qr")

        r = await s.calistir(f'qr oku "{tmp}"', dry_run=True)
        assert r.basarili
        assert r.veri["dry_run"] is True

        r2 = await s.calistir(f'qr oku "{tmp}"', zorla_sahte=True)
        assert r2.basarili
        assert r2.veri["engine"] == "sahte"

        r3 = await s.calistir(f'qr "{tmp}"', cv2_modul=stub)
        assert r3.basarili
        assert r3.veri["engine"] == "opencv"

        r4 = await s.calistir("qr oku")
        assert not r4.basarili

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r5 = await y.calistir(f'qr oku "{tmp}"', dry_run=True)
        assert r5.basarili
        await y.durdur()

        assert isinstance(opencv_var_mi(), bool)

    asyncio.run(_run())


def test_dosya_yok_gercek_motor() -> None:
    """Stub motor ile olmayan dosya FileNotFoundError → skill hata."""

    async def _run() -> None:
        s = QrOkuyucuSkill()
        stub = _SahteCv2()
        r = await s.calistir(
            'qr oku "C:/olmayan_whitecore_qr_xyz.png"',
            cv2_modul=stub,
        )
        assert not r.basarili

    asyncio.run(_run())


if __name__ == "__main__":
    test_gorsel_yolu_ayikla()
    test_dry_run_ve_sahte()
    test_mock_opencv_ve_skill()
    test_dosya_yok_gercek_motor()
    print("OK test_qr_okuyucu")

"""
skills/media/qr_okuyucu.py
--------------------------
QR kod okuma skill'i.

Görev:
- Görüntü dosyasından QR kod çözmek (OpenCV QRCodeDetector)
- OpenCV / paket yoksa dry_run veya sahte fallback
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from skills.taban import SkillTabani

try:
    import cv2 as _cv2

    _OPENCV_VAR = True
except ImportError:  # pragma: no cover
    _cv2 = None  # type: ignore[assignment]
    _OPENCV_VAR = False

_GORSEL_UZANTILAR = ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "gif")
_SAHTE_VERI = "https://whitecore.local/sahte-qr"


def opencv_var_mi() -> bool:
    return bool(_OPENCV_VAR)


def gorsel_yolu_ayikla(komut: str) -> Optional[str]:
    """Komuttan görüntü yolunu (tırnaklı veya uzantılı) alır."""
    uz = "|".join(_GORSEL_UZANTILAR)
    yollar = re.findall(
        rf'"([^"]+\.(?:{uz}))"|'
        rf"'([^']+\.(?:{uz}))'",
        komut or "",
        flags=re.I,
    )
    duz = [a or b for a, b in yollar]
    if duz:
        return duz[0]
    m = re.search(rf"(\S+\.(?:{uz}))\b", komut or "", flags=re.I)
    return m.group(1) if m else None


def _gorsel_yukle(cv: Any, yol: Path) -> Any:
    """
    Görüntüyü yükler.

    Windows Unicode yolları için önce bytes + imdecode dener.
    """
    ham = yol.read_bytes()
    try:
        import numpy as np

        buf = np.frombuffer(ham, dtype=np.uint8)
        img = cv.imdecode(buf, cv.IMREAD_COLOR)
        if img is not None:
            return img
    except Exception:
        pass

    img = cv.imread(str(yol))
    if img is None:
        raise ValueError(f"Görüntü okunamadı: {yol}")
    return img


def _qr_coz_opencv(cv: Any, img: Any) -> list[str]:
    """OpenCV QRCodeDetector ile bir veya daha fazla QR içeriği döner."""
    detector = cv.QRCodeDetector()
    sonuclar: list[str] = []

    # Çoklu QR (varsa)
    if hasattr(detector, "detectAndDecodeMulti"):
        try:
            ok, veriler, _pts, _ = detector.detectAndDecodeMulti(img)
            if ok and veriler:
                for v in veriler:
                    metin = (v or "").strip() if isinstance(v, str) else str(v or "").strip()
                    if metin:
                        sonuclar.append(metin)
                if sonuclar:
                    return sonuclar
        except Exception:
            pass

    data, _pts, _ = detector.detectAndDecode(img)
    metin = (data or "").strip() if isinstance(data, str) else str(data or "").strip()
    if metin:
        sonuclar.append(metin)
    return sonuclar


def qr_oku(
    yol: str | Path,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_veri: Optional[str] = None,
    cv2_modul: Any = None,
) -> dict[str, Any]:
    """
    Görüntüdeki QR kod(lar)ı çözer.

    dry_run / zorla_sahte / sahte_veri / OpenCV yok → sahte/dry sonuç.
    """
    p = Path(yol).expanduser()

    if dry_run:
        return {
            "path": str(p),
            "data": "",
            "codes": [],
            "count": 0,
            "engine": "dry_run",
            "dry_run": True,
        }

    if sahte_veri is not None:
        metin = str(sahte_veri)
        return {
            "path": str(p.resolve()) if p.exists() else str(p),
            "data": metin,
            "codes": [metin] if metin else [],
            "count": 1 if metin else 0,
            "engine": "sahte",
            "dry_run": False,
            "reason": "sahte_veri",
        }

    if zorla_sahte or (cv2_modul is None and not _OPENCV_VAR):
        metin = _SAHTE_VERI
        return {
            "path": str(p.resolve()) if p.exists() else str(p),
            "data": metin,
            "codes": [metin],
            "count": 1,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte" if zorla_sahte else "opencv_yok",
        }

    if not p.is_file():
        raise FileNotFoundError(f"Görüntü yok: {p}")

    cv = cv2_modul if cv2_modul is not None else _cv2

    try:
        img = _gorsel_yukle(cv, p)
        kodlar = _qr_coz_opencv(cv, img)
        if not kodlar:
            return {
                "path": str(p.resolve()),
                "data": "",
                "codes": [],
                "count": 0,
                "engine": "opencv",
                "dry_run": False,
                "reason": "qr_bulunamadi",
            }
        return {
            "path": str(p.resolve()),
            "data": kodlar[0],
            "codes": kodlar,
            "count": len(kodlar),
            "engine": "opencv",
            "dry_run": False,
        }
    except FileNotFoundError:
        raise
    except Exception as exc:
        metin = _SAHTE_VERI
        return {
            "path": str(p.resolve()) if p.exists() else str(p),
            "data": metin,
            "codes": [metin],
            "count": 1,
            "engine": "sahte",
            "dry_run": False,
            "reason": f"hata:{exc}",
            "error": str(exc),
        }


class QrOkuyucuSkill(SkillTabani):
    """Görüntü dosyasından QR kod okur."""

    ad = "qr_okuyucu"
    aciklama = "Görüntülerdeki QR kodları okur (OpenCV QRCodeDetector)"
    kategori = "media"
    tehlikeli = False
    anahtarlar = (
        "qr",
        "qr oku",
        "qr okuyucu",
        "qr kod",
        "qrcode",
        "barkod",
        "karekod",
        "read qr",
        "scan qr",
    )
    ornekler = (
        'qr oku "kod.png"',
        'karekod oku "foto.jpg"',
        "qr dry_run test.png",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        yol = kwargs.get("yol") or gorsel_yolu_ayikla(komut)
        dry_run = bool(kwargs.get("dry_run", False))
        zorla_sahte = bool(kwargs.get("zorla_sahte", False))
        sahte = kwargs.get("sahte_veri")
        if sahte is None:
            sahte = kwargs.get("sahte_metin")

        if not yol:
            if dry_run or zorla_sahte or sahte is not None:
                yol = "sahte_qr.png"
            else:
                return self.hata(
                    'Görüntü yolu gerekli. Örnek: qr oku "kod.png"',
                    veri={"komut": komut},
                )

        try:
            bil = qr_oku(
                str(yol),
                dry_run=dry_run,
                zorla_sahte=zorla_sahte,
                sahte_veri=sahte,
                cv2_modul=kwargs.get("cv2_modul"),
            )
        except Exception as exc:
            return self.hata(str(exc), veri={"path": str(yol)})

        if bil.get("dry_run"):
            mesaj = f"QR okuma planlandı (dry_run): {bil.get('path')}"
        elif bil.get("engine") == "sahte":
            mesaj = f"Sahte QR okundu ({bil.get('count', 0)} kod)"
        elif bil.get("count", 0) == 0:
            mesaj = "QR kod bulunamadı"
        elif bil.get("count", 0) == 1:
            mesaj = f"QR okundu: {(bil.get('data') or '')[:120]}"
        else:
            mesaj = f"{bil.get('count')} QR kod okundu"

        ozet = (bil.get("data") or "")[:500]
        return self.ok(mesaj, veri={**bil, "preview": ozet})


qr_okuyucu_skill = QrOkuyucuSkill()

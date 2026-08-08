"""
skills/media/kamera.py
----------------------
Kamera skill'i.

Görev:
- Kamera cihazlarını listelemek
- Kamerayı açıp doğrulamak
- Fotoğraf çekmek (OpenCV)
- OpenCV / kamera yoksa dry_run veya sahte fallback
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from skills.taban import SkillTabani

# 1x1 PNG (RGBA) — Pillow/OpenCV gerekmez
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

try:
    import cv2 as _cv2

    _OPENCV_VAR = True
except ImportError:  # pragma: no cover
    _cv2 = None  # type: ignore[assignment]
    _OPENCV_VAR = False


def opencv_var_mi() -> bool:
    return bool(_OPENCV_VAR)


def islem_ayikla(komut: str) -> str:
    """Komuttan kamera işlemini çıkarır: listele | ac | cek."""
    n = (komut or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    if not n:
        return "cek"

    if re.search(r"\b(listele|list|cihazlar|devices)\b", n):
        return "listele"
    if re.search(r"\b(aç|ac|open|test|doğrula|dogrula)\b", n) and not re.search(
        r"\b(çek|cek|foto|fotoğraf|fotograf|snapshot|capture)\b", n
    ):
        return "ac"
    if re.search(r"\b(çek|cek|foto|fotoğraf|fotograf|snapshot|capture|kaydet)\b", n):
        return "cek"
    # varsayılan: fotoğraf
    return "cek"


def cihaz_indeksi_ayikla(komut: str) -> Optional[int]:
    """'kamera 1', 'cihaz 0' vb."""
    m = re.search(r"(?i)(?:kamera|cihaz|camera|device)\s*[:=]?\s*(\d+)", komut or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)\b(?:index|indeks)\s*[:=]?\s*(\d+)", komut or "")
    if m:
        return int(m.group(1))
    return None


def kayit_yolu_ayikla(komut: str) -> Optional[str]:
    """Komuttan kayıt yolu (tırnaklı veya uzantılı)."""
    yollar = re.findall(
        r'"([^"]+\.(?:png|jpg|jpeg|bmp|webp))"|'
        r"'([^']+\.(?:png|jpg|jpeg|bmp|webp))'",
        komut or "",
        flags=re.I,
    )
    duz = [a or b for a, b in yollar]
    if duz:
        return duz[0]
    m = re.search(r"(\S+\.(?:png|jpg|jpeg|bmp|webp))\b", komut or "", flags=re.I)
    return m.group(1) if m else None


def _varsayilan_yol() -> Path:
    damga = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    klasor = Path.cwd() / "database" / "captures"
    return klasor / f"kamera_{damga}.png"


def _sahte_kaydet(
    yol: Path,
    *,
    neden: str,
    cihaz: Optional[int] = None,
) -> dict[str, Any]:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_bytes(_MINI_PNG)
    return {
        "path": str(yol.resolve()),
        "device": cihaz,
        "width": 1,
        "height": 1,
        "engine": "sahte",
        "reason": neden,
        "bytes": yol.stat().st_size,
        "opened": False,
        "dry_run": False,
    }


def cihazlari_listele(
    *,
    max_indeks: int = 5,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    cv2_modul: Any = None,
) -> dict[str, Any]:
    """
    0..max_indeks-1 aralığında açılabilen kameraları dener.

    dry_run / OpenCV yok / zorla_sahte → sahte cihaz listesi.
    """
    if dry_run:
        return {
            "devices": [{"index": 0, "available": True, "note": "dry_run"}],
            "count": 1,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte or (cv2_modul is None and not _OPENCV_VAR):
        return {
            "devices": [
                {"index": 0, "available": True, "note": "sahte varsayılan kamera"}
            ],
            "count": 1,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte" if zorla_sahte else "opencv_yok",
        }

    cv = cv2_modul if cv2_modul is not None else _cv2
    bulunan: list[dict[str, Any]] = []
    for i in range(max(0, int(max_indeks))):
        cap = None
        try:
            cap = cv.VideoCapture(i)
            if cap is not None and cap.isOpened():
                bulunan.append({"index": i, "available": True})
        except Exception:
            continue
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    return {
        "devices": bulunan,
        "count": len(bulunan),
        "engine": "opencv",
        "dry_run": False,
    }


def kamera_ac(
    cihaz: int = 0,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    cv2_modul: Any = None,
) -> dict[str, Any]:
    """Kamerayı kısa süre açıp kapatır (erişilebilirlik testi)."""
    if dry_run:
        return {
            "device": int(cihaz),
            "opened": True,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte or (cv2_modul is None and not _OPENCV_VAR):
        return {
            "device": int(cihaz),
            "opened": True,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte" if zorla_sahte else "opencv_yok",
        }

    cv = cv2_modul if cv2_modul is not None else _cv2
    cap = None
    try:
        cap = cv.VideoCapture(int(cihaz))
        acik = bool(cap is not None and cap.isOpened())
        if not acik:
            return {
                "device": int(cihaz),
                "opened": False,
                "engine": "sahte",
                "dry_run": False,
                "reason": "kamera_yok",
            }
        return {
            "device": int(cihaz),
            "opened": True,
            "engine": "opencv",
            "dry_run": False,
        }
    except Exception as exc:
        return {
            "device": int(cihaz),
            "opened": False,
            "engine": "sahte",
            "dry_run": False,
            "reason": f"hata:{exc}",
            "error": str(exc),
        }
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def fotograf_cek(
    cihaz: int = 0,
    *,
    yol: Optional[str | Path] = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    cv2_modul: Any = None,
) -> dict[str, Any]:
    """
    Kameradan kare yakalar ve dosyaya yazar.

    OpenCV yoksa / zorla_sahte: mini PNG yazar.
    dry_run: dosya yazmaz, planlanan yolu döner.
    """
    hedef = Path(yol).expanduser() if yol else _varsayilan_yol()

    if dry_run:
        return {
            "path": str(hedef),
            "device": int(cihaz),
            "opened": False,
            "engine": "dry_run",
            "dry_run": True,
            "bytes": 0,
        }

    if zorla_sahte or (cv2_modul is None and not _OPENCV_VAR):
        return _sahte_kaydet(
            hedef,
            neden="zorla_sahte" if zorla_sahte else "opencv_yok",
            cihaz=int(cihaz),
        )

    cv = cv2_modul if cv2_modul is not None else _cv2
    cap = None
    try:
        cap = cv.VideoCapture(int(cihaz))
        if cap is None or not cap.isOpened():
            # donanım yok → sahte fallback
            return _sahte_kaydet(hedef, neden="kamera_yok", cihaz=int(cihaz))

        ok, kare = cap.read()
        if not ok or kare is None:
            return _sahte_kaydet(hedef, neden="kare_okunamadi", cihaz=int(cihaz))

        hedef.parent.mkdir(parents=True, exist_ok=True)
        # cv2.imwrite Türkçe yol sorunlarına karşı bytes üzerinden
        uzanti = hedef.suffix.lower() or ".png"
        if uzanti in {".jpg", ".jpeg"}:
            basarili, buf = cv.imencode(".jpg", kare)
        else:
            basarili, buf = cv.imencode(".png", kare)
            if hedef.suffix.lower() not in {".png"}:
                hedef = hedef.with_suffix(".png")

        if not basarili:
            return _sahte_kaydet(hedef, neden="encode_hatasi", cihaz=int(cihaz))

        hedef.write_bytes(buf.tobytes())
        h, w = kare.shape[:2]
        return {
            "path": str(hedef.resolve()),
            "device": int(cihaz),
            "width": int(w),
            "height": int(h),
            "engine": "opencv",
            "dry_run": False,
            "bytes": hedef.stat().st_size,
            "opened": True,
        }
    except Exception as exc:
        # beklenmeyen hata → sahte + hata notu
        bil = _sahte_kaydet(hedef, neden=f"hata:{exc}", cihaz=int(cihaz))
        bil["error"] = str(exc)
        return bil
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


class KameraSkill(SkillTabani):
    """Kamera listeleme / açma / fotoğraf çekme."""

    ad = "kamera"
    aciklama = "Kamera cihazlarını listeler, açar ve fotoğraf çeker (OpenCV)"
    kategori = "media"
    tehlikeli = False
    anahtarlar = (
        "kamera",
        "fotoğraf",
        "fotograf",
        "foto çek",
        "foto cek",
        "snapshot",
        "camera",
        "webcam",
        "görüntü al",
        "goruntu al",
    )
    ornekler = (
        "fotoğraf çek",
        "kamera listele",
        'kamera çek "C:/tmp/snap.png"',
        "kamera aç",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        islem = str(kwargs.get("islem") or islem_ayikla(komut))
        dry_run = bool(kwargs.get("dry_run", False))
        zorla_sahte = bool(kwargs.get("zorla_sahte", False))
        cv2_modul = kwargs.get("cv2_modul")
        cihaz = kwargs.get("cihaz")
        if cihaz is None:
            cihaz = cihaz_indeksi_ayikla(komut)
        if cihaz is None:
            cihaz = 0
        cihaz = int(cihaz)

        try:
            if islem == "listele":
                bil = cihazlari_listele(
                    max_indeks=int(kwargs.get("max_indeks", 5)),
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                    cv2_modul=cv2_modul,
                )
                return self.ok(
                    f"{bil.get('count', 0)} kamera bulundu",
                    veri=bil,
                )

            if islem == "ac":
                bil = kamera_ac(
                    cihaz,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                    cv2_modul=cv2_modul,
                )
                if bil.get("opened"):
                    mesaj = f"Kamera {cihaz} erişilebilir"
                else:
                    mesaj = f"Kamera {cihaz} açılamadı (sahte/fallback)"
                return self.ok(mesaj, veri=bil)

            if islem == "cek":
                yol = kwargs.get("yol") or kayit_yolu_ayikla(komut)
                bil = fotograf_cek(
                    cihaz,
                    yol=yol,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                    cv2_modul=cv2_modul,
                )
                if bil.get("dry_run"):
                    mesaj = f"Fotoğraf planlandı (dry_run): {bil.get('path')}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte fotoğraf kaydedildi: {bil.get('path')}"
                else:
                    mesaj = f"Fotoğraf kaydedildi: {bil.get('path')}"
                return self.ok(mesaj, veri=bil)

            return self.desteklenmiyor(f"Bilinmeyen kamera işlemi: {islem}")
        except Exception as exc:
            return self.hata(
                str(exc),
                veri={"islem": islem, "device": cihaz},
            )


kamera_skill = KameraSkill()

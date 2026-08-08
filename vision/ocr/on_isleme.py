"""
vision/ocr/on_isleme.py
-----------------------
OCR görüntü ön işleme — gri, eşik, gürültü azaltma, eğim düzeltme, yeniden boyutlandırma.

Görev:
- OCR öncesi görüntü iyileştirme (gri ton, eşikleme, denoise, deskew, resize)
- OpenCV / numpy yoksa dry_run veya sahte/passthrough
- Girdi: yol, bayt, Kare veya (varsa) numpy dizisi
- Çıktı: OnIslemeSonucu + vision.modeller.Kare

Not: Tesseract OCR motoru `vision/ocr/motor.py` dosyasına aittir;
bu modül yalnızca ön işlemedir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from core.exceptions import VisionError
from core.logger import logger_al
from vision.modeller import Kare, VisionMotoru, kare_olustur, motor_coz

log = logger_al("vision.ocr.on_isleme")

# Sahte / dry_run için 1x1 PNG (OpenCV/Pillow gerekmez)
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]

try:
    import cv2 as _cv2  # type: ignore

    _CV2_VAR = True
except ImportError:  # pragma: no cover
    _cv2 = None  # type: ignore[assignment]
    _CV2_VAR = False

try:
    import numpy as _np  # type: ignore

    _NUMPY_VAR = True
except ImportError:  # pragma: no cover
    _np = None  # type: ignore[assignment]
    _NUMPY_VAR = False


def opencv_var_mi() -> bool:
    return bool(_CV2_VAR)


def numpy_var_mi() -> bool:
    return bool(_NUMPY_VAR)


@dataclass
class OnIslemeAyarlari:
    """Hangi ön işleme adımlarının uygulanacağı."""

    gri: bool = True
    esik: bool = True
    gurultu_azalt: bool = True
    egim_duzelt: bool = True
    yeniden_boyutlandir: bool = True
    max_genislik: int = 2000
    max_yukseklik: int = 2000
    # otsu | adaptive | binary
    esik_metodu: str = "otsu"
    binary_esik: int = 127
    # Eğim düzeltme için minimum açı (derece); daha küçükleri yok say
    min_egim_derece: float = 0.3
    max_egim_derece: float = 15.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "grayscale": bool(self.gri),
            "threshold": bool(self.esik),
            "denoise": bool(self.gurultu_azalt),
            "deskew": bool(self.egim_duzelt),
            "resize": bool(self.yeniden_boyutlandir),
            "max_width": int(self.max_genislik),
            "max_height": int(self.max_yukseklik),
            "threshold_method": str(self.esik_metodu),
            "binary_threshold": int(self.binary_esik),
            "min_skew_deg": float(self.min_egim_derece),
            "max_skew_deg": float(self.max_egim_derece),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "OnIslemeAyarlari":
        return cls(
            gri=bool(veri.get("grayscale", True)),
            esik=bool(veri.get("threshold", True)),
            gurultu_azalt=bool(veri.get("denoise", True)),
            egim_duzelt=bool(veri.get("deskew", True)),
            yeniden_boyutlandir=bool(veri.get("resize", True)),
            max_genislik=int(veri.get("max_width") or 2000),
            max_yukseklik=int(veri.get("max_height") or 2000),
            esik_metodu=str(veri.get("threshold_method") or "otsu"),
            binary_esik=int(veri.get("binary_threshold") or 127),
            min_egim_derece=float(veri.get("min_skew_deg") or 0.3),
            max_egim_derece=float(veri.get("max_skew_deg") or 15.0),
        )


@dataclass
class OnIslemeSonucu:
    """Ön işleme çıktısı (wire anahtarları İngilizce)."""

    kare: Kare
    adimlar: list[str] = field(default_factory=list)
    motor: VisionMotoru = VisionMotoru.DRY_RUN
    dry_run: bool = False
    kaynak_yol: Optional[str] = None
    neden: Optional[str] = None
    # Bellek içi matris — wire'a yazılmaz
    matris: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.kare.to_dict(),
            "steps": list(self.adimlar),
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "source_path": self.kaynak_yol,
            "reason": self.neden,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "OnIslemeSonucu":
        kare_ham = veri.get("frame") or {}
        return cls(
            kare=Kare.from_dict(kare_ham) if isinstance(kare_ham, dict) else kare_olustur(),
            adimlar=[str(x) for x in (veri.get("steps") or [])],
            motor=motor_coz(veri.get("engine") or VisionMotoru.DRY_RUN),
            dry_run=bool(veri.get("dry_run", False)),
            kaynak_yol=veri.get("source_path"),
            neden=veri.get("reason"),
            matris=None,
        )


class OcrOnIsleme:
    """
    OCR ön işleyici.

    OpenCV varsa gerçek işlem; yoksa / dry_run / zorla_sahte ile passthrough.
    """

    ad = "vision.ocr.preprocess"
    surum = "0.1.0"

    def __init__(
        self,
        *,
        ayarlar: Optional[OnIslemeAyarlari] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
    ) -> None:
        self.ayarlar = ayarlar or OnIslemeAyarlari()
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np
        self._sonuc: Optional[OnIslemeSonucu] = None
        self._log = logger_al(f"modul.{self.ad}")
        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def son_sonuc(self) -> Optional[OnIslemeSonucu]:
        return self._sonuc

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self.motor,
            "dry_run": bool(self.dry_run) or self.motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self.motor == VisionMotoru.SAHTE.value,
            "opencv": self._cv2 is not None,
            "numpy": self._np is not None,
            "settings": self.ayarlar.to_dict(),
            "last": self._sonuc.to_dict() if self._sonuc else None,
        }

    # ------------------------------------------------------------------ API

    def isle(
        self,
        girdi: GirdiTuru,
        *,
        ayarlar: Optional[OnIslemeAyarlari] = None,
        cikis_yolu: Optional[Union[str, Path]] = None,
    ) -> OnIslemeSonucu:
        """
        Görüntüyü OCR için ön işler.

        dry_run → işlem yapmaz, meta döner.
        OpenCV yok / zorla_sahte → passthrough (sahte motor).
        """
        cfg = ayarlar or self.ayarlar
        kaynak_yol = self._kaynak_yol(girdi)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = self._dry_run_sonuc(girdi, kaynak_yol=kaynak_yol, cfg=cfg)
            self._sonuc = sonuc
            return sonuc

        if (
            self.zorla_sahte
            or self._motor == VisionMotoru.SAHTE.value
            or self._cv2 is None
            or self._np is None
        ):
            neden = (
                "zorla_sahte"
                if self.zorla_sahte
                else ("opencv_yok" if self._cv2 is None else "numpy_yok")
            )
            sonuc = self._passthrough_sonuc(
                girdi,
                kaynak_yol=kaynak_yol,
                cfg=cfg,
                neden=neden,
            )
            self._sonuc = sonuc
            return sonuc

        try:
            mat = self._yukle(girdi)
            adimlar: list[str] = []

            if cfg.yeniden_boyutlandir:
                mat, uygulandi = self._yeniden_boyutlandir(mat, cfg)
                if uygulandi:
                    adimlar.append("resize")

            if cfg.gri:
                mat = self._gri(mat)
                adimlar.append("grayscale")

            if cfg.gurultu_azalt:
                mat = self._gurultu_azalt(mat)
                adimlar.append("denoise")

            if cfg.esik:
                mat = self._esikle(mat, cfg)
                adimlar.append(f"threshold:{cfg.esik_metodu}")

            if cfg.egim_duzelt:
                mat, duzeltildi = self._egim_duzelt(mat, cfg)
                if duzeltildi:
                    adimlar.append("deskew")

            ham = self._encode_png(mat)
            h, w = self._boyut(mat)
            kare = kare_olustur(
                yol=str(cikis_yolu) if cikis_yolu else kaynak_yol,
                genislik=w,
                yukseklik=h,
                motor=VisionMotoru.OPENCV,
                dry_run=False,
                bayt_sayisi=len(ham) if ham else 0,
                ham=ham,
            )

            if cikis_yolu is not None and ham:
                self._diske_yaz(cikis_yolu, ham)

            sonuc = OnIslemeSonucu(
                kare=kare,
                adimlar=adimlar,
                motor=VisionMotoru.OPENCV,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                matris=mat,
            )
            self._sonuc = sonuc
            self._log.debug(
                "OCR on isleme tamam adimlar=%s boyut=%sx%s",
                adimlar,
                w,
                h,
            )
            return sonuc
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.debug("OpenCV on isleme hatasi, passthrough: %s", exc)
            sonuc = self._passthrough_sonuc(
                girdi,
                kaynak_yol=kaynak_yol,
                cfg=cfg,
                neden=f"hata:{exc}",
            )
            self._sonuc = sonuc
            return sonuc

    # Tek adımlık yardımcılar (test / motor.py için)

    def gri_yap(self, girdi: GirdiTuru) -> OnIslemeSonucu:
        return self.isle(girdi, ayarlar=OnIslemeAyarlari(
            gri=True,
            esik=False,
            gurultu_azalt=False,
            egim_duzelt=False,
            yeniden_boyutlandir=False,
        ))

    def esikle(self, girdi: GirdiTuru, *, metod: str = "otsu") -> OnIslemeSonucu:
        return self.isle(girdi, ayarlar=OnIslemeAyarlari(
            gri=True,
            esik=True,
            gurultu_azalt=False,
            egim_duzelt=False,
            yeniden_boyutlandir=False,
            esik_metodu=metod,
        ))

    def gurultu_azalt(self, girdi: GirdiTuru) -> OnIslemeSonucu:
        return self.isle(girdi, ayarlar=OnIslemeAyarlari(
            gri=True,
            esik=False,
            gurultu_azalt=True,
            egim_duzelt=False,
            yeniden_boyutlandir=False,
        ))

    def egim_duzelt(self, girdi: GirdiTuru) -> OnIslemeSonucu:
        return self.isle(girdi, ayarlar=OnIslemeAyarlari(
            gri=True,
            esik=False,
            gurultu_azalt=False,
            egim_duzelt=True,
            yeniden_boyutlandir=False,
        ))

    def yeniden_boyutlandir(
        self,
        girdi: GirdiTuru,
        *,
        max_genislik: int = 2000,
        max_yukseklik: int = 2000,
    ) -> OnIslemeSonucu:
        return self.isle(
            girdi,
            ayarlar=OnIslemeAyarlari(
                gri=False,
                esik=False,
                gurultu_azalt=False,
                egim_duzelt=False,
                yeniden_boyutlandir=True,
                max_genislik=max_genislik,
                max_yukseklik=max_yukseklik,
            ),
        )

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._cv2 is not None and self._np is not None:
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    # ------------------------------------------------------------------ iç — yükle / yaz

    def _kaynak_yol(self, girdi: GirdiTuru) -> Optional[str]:
        if isinstance(girdi, Kare):
            return girdi.yol
        if isinstance(girdi, Path):
            return str(girdi)
        if isinstance(girdi, str):
            return girdi
        return None

    def _yukle(self, girdi: GirdiTuru) -> Any:
        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yuklu degil",
                kod="VIS_0201",
                modul=self.ad,
            )

        if isinstance(girdi, Kare):
            if girdi.ham:
                return self._bayttan_matris(bytes(girdi.ham))
            if girdi.yol:
                return self._yoldan_matris(girdi.yol)
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0202",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            return self._bayttan_matris(bytes(girdi))

        if isinstance(girdi, (str, Path)):
            return self._yoldan_matris(str(girdi))

        # numpy dizisi varsay
        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen on isleme girdisi: {type(girdi)!r}",
            kod="VIS_0203",
            modul=self.ad,
        )

    def _yoldan_matris(self, yol: str) -> Any:
        p = Path(yol).expanduser()
        if not p.is_file():
            raise VisionError(
                f"Goruntu yok: {p}",
                kod="VIS_0204",
                modul=self.ad,
            )
        mat = self._cv2.imread(str(p), self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                f"Goruntu okunamadi: {p}",
                kod="VIS_0204",
                modul=self.ad,
            )
        return mat

    def _bayttan_matris(self, ham: bytes) -> Any:
        np = self._np
        buf = np.frombuffer(ham, dtype=np.uint8)
        mat = self._cv2.imdecode(buf, self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                "Bayt goruntu cozulemedi",
                kod="VIS_0205",
                modul=self.ad,
            )
        return mat

    def _encode_png(self, mat: Any) -> Optional[bytes]:
        try:
            ok, buf = self._cv2.imencode(".png", mat)
            if not ok or buf is None:
                return None
            return bytes(buf.tobytes())
        except Exception:  # noqa: BLE001
            return None

    def _diske_yaz(self, yol: Union[str, Path], ham: bytes) -> None:
        p = Path(yol).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(ham)

    def _boyut(self, mat: Any) -> tuple[int, int]:
        shape = getattr(mat, "shape", None)
        if shape is None or len(shape) < 2:
            return 0, 0
        return int(shape[0]), int(shape[1])

    # ------------------------------------------------------------------ iç — adımlar

    def _gri(self, mat: Any) -> Any:
        if len(getattr(mat, "shape", ())) == 2:
            return mat
        return self._cv2.cvtColor(mat, self._cv2.COLOR_BGR2GRAY)

    def _gurultu_azalt(self, mat: Any) -> Any:
        # medianBlur tek kanallı / çok kanallı çalışır
        k = 3
        return self._cv2.medianBlur(mat, k)

    def _esikle(self, mat: Any, cfg: OnIslemeAyarlari) -> Any:
        gri = self._gri(mat)
        metod = (cfg.esik_metodu or "otsu").strip().lower()
        cv2 = self._cv2

        if metod == "adaptive":
            return cv2.adaptiveThreshold(
                gri,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                15,
                11,
            )
        if metod == "binary":
            _, out = cv2.threshold(gri, int(cfg.binary_esik), 255, cv2.THRESH_BINARY)
            return out
        # varsayılan: otsu
        _, out = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return out

    def _yeniden_boyutlandir(
        self, mat: Any, cfg: OnIslemeAyarlari
    ) -> tuple[Any, bool]:
        h, w = self._boyut(mat)
        max_w = max(1, int(cfg.max_genislik))
        max_h = max(1, int(cfg.max_yukseklik))
        if w <= max_w and h <= max_h:
            return mat, False
        oran = min(max_w / float(w), max_h / float(h))
        yeni_w = max(1, int(w * oran))
        yeni_h = max(1, int(h * oran))
        out = self._cv2.resize(
            mat,
            (yeni_w, yeni_h),
            interpolation=self._cv2.INTER_AREA,
        )
        return out, True

    def _egim_duzelt(
        self, mat: Any, cfg: OnIslemeAyarlari
    ) -> tuple[Any, bool]:
        """
        Basit deskew: kenar + minAreaRect açısı.
        Küçük açılar veya hata → orijinal matris.
        """
        cv2 = self._cv2
        np = self._np
        try:
            gri = self._gri(mat)
            kenar = cv2.Canny(gri, 50, 150)
            coords = np.column_stack(np.where(kenar > 0))
            if coords is None or len(coords) < 20:
                return mat, False
            rect = cv2.minAreaRect(coords.astype(np.float32))
            aci = float(rect[-1])
            # OpenCV minAreaRect açısı -90..0 aralığında olabilir
            if aci < -45:
                aci = -(90.0 + aci)
            else:
                aci = -aci
            if abs(aci) < float(cfg.min_egim_derece):
                return mat, False
            if abs(aci) > float(cfg.max_egim_derece):
                return mat, False
            h, w = self._boyut(mat)
            merkez = (w / 2.0, h / 2.0)
            M = cv2.getRotationMatrix2D(merkez, aci, 1.0)
            flags = cv2.INTER_CUBIC
            border = cv2.BORDER_REPLICATE
            out = cv2.warpAffine(mat, M, (w, h), flags=flags, borderMode=border)
            return out, True
        except Exception as exc:  # noqa: BLE001
            self._log.debug("Deskew atlandi: %s", exc)
            return mat, False

    # ------------------------------------------------------------------ iç — fallback

    def _planlanan_adimlar(self, cfg: OnIslemeAyarlari) -> list[str]:
        adimlar: list[str] = []
        if cfg.yeniden_boyutlandir:
            adimlar.append("resize")
        if cfg.gri:
            adimlar.append("grayscale")
        if cfg.gurultu_azalt:
            adimlar.append("denoise")
        if cfg.esik:
            adimlar.append(f"threshold:{cfg.esik_metodu}")
        if cfg.egim_duzelt:
            adimlar.append("deskew")
        return adimlar

    def _dry_run_sonuc(
        self,
        girdi: GirdiTuru,
        *,
        kaynak_yol: Optional[str],
        cfg: OnIslemeAyarlari,
    ) -> OnIslemeSonucu:
        w, h, bayt = self._girdi_meta(girdi)
        kare = kare_olustur(
            yol=kaynak_yol,
            genislik=w,
            yukseklik=h,
            motor=VisionMotoru.DRY_RUN,
            dry_run=True,
            bayt_sayisi=bayt,
            ham=None,
        )
        return OnIslemeSonucu(
            kare=kare,
            adimlar=self._planlanan_adimlar(cfg),
            motor=VisionMotoru.DRY_RUN,
            dry_run=True,
            kaynak_yol=kaynak_yol,
            neden="dry_run",
        )

    def _passthrough_sonuc(
        self,
        girdi: GirdiTuru,
        *,
        kaynak_yol: Optional[str],
        cfg: OnIslemeAyarlari,
        neden: str,
    ) -> OnIslemeSonucu:
        w, h, bayt = self._girdi_meta(girdi)
        ham = self._girdi_ham(girdi)
        kare = kare_olustur(
            yol=kaynak_yol,
            genislik=w or (1 if ham else 0),
            yukseklik=h or (1 if ham else 0),
            motor=VisionMotoru.SAHTE,
            dry_run=False,
            bayt_sayisi=len(ham) if ham else bayt,
            ham=ham,
        )
        return OnIslemeSonucu(
            kare=kare,
            adimlar=[],  # gerçek işlem yok — passthrough
            motor=VisionMotoru.SAHTE,
            dry_run=False,
            kaynak_yol=kaynak_yol,
            neden=neden,
        )

    def _girdi_meta(self, girdi: GirdiTuru) -> tuple[int, int, int]:
        if isinstance(girdi, Kare):
            return (
                int(girdi.genislik),
                int(girdi.yukseklik),
                int(girdi.bayt_sayisi or (len(girdi.ham) if girdi.ham else 0)),
            )
        if isinstance(girdi, (bytes, bytearray)):
            return 0, 0, len(girdi)
        if isinstance(girdi, (str, Path)):
            p = Path(girdi).expanduser()
            if p.is_file():
                return 0, 0, int(p.stat().st_size)
            return 0, 0, 0
        shape = getattr(girdi, "shape", None)
        if shape is not None and len(shape) >= 2:
            return int(shape[1]), int(shape[0]), 0
        return 0, 0, 0

    def _girdi_ham(self, girdi: GirdiTuru) -> Optional[bytes]:
        if isinstance(girdi, Kare):
            return bytes(girdi.ham) if girdi.ham else None
        if isinstance(girdi, (bytes, bytearray)):
            return bytes(girdi)
        if isinstance(girdi, (str, Path)):
            p = Path(girdi).expanduser()
            if p.is_file():
                try:
                    return p.read_bytes()
                except OSError:
                    return None
            return None
        return None


def on_isleme_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[OnIslemeAyarlari] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
) -> OcrOnIsleme:
    """Test / demo için güvenli varsayılanlarla OcrOnIsleme üretir."""
    return OcrOnIsleme(
        ayarlar=ayarlar,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
    )


def on_isle(
    girdi: GirdiTuru,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    ayarlar: Optional[OnIslemeAyarlari] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    cikis_yolu: Optional[Union[str, Path]] = None,
) -> OnIslemeSonucu:
    """Tek çağrılık ön işleme yardımcısı."""
    motor = on_isleme_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        ayarlar=ayarlar,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
    )
    return motor.isle(girdi, cikis_yolu=cikis_yolu)


__all__ = [
    "OnIslemeAyarlari",
    "OnIslemeSonucu",
    "OcrOnIsleme",
    "opencv_var_mi",
    "numpy_var_mi",
    "on_isleme_olustur",
    "on_isle",
]

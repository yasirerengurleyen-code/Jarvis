"""
vision/analiz/nesne.py
----------------------
Nesne algılama — OpenCV / isteğe bağlı YOLO, dry_run / sahte fallback.

Görev:
- Görüntüden nesne algılama (`AlgilananNesne` → `AnalizSonucu`)
- OpenCV HOG kişi algılama (yerel hafif yol)
- Ultralytics YOLO varsa kullan (isteğe bağlı)
- Enjekte edilebilir detector (birim test / özel motor)
- OpenCV / YOLO yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Sahne / renk / QR → sonraki dosyalar; bu modül yalnızca nesne.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    AlgilananNesne,
    AnalizSonucu,
    Kare,
    VisionMotoru,
    guven_sinirla,
)

log = logger_al("vision.analiz.nesne")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_NESNE_ALGILANDI = "vision.analysis.objects.detected"
OLAY_NESNE_BASLADI = "vision.analysis.objects.started"
OLAY_NESNE_DURDU = "vision.analysis.objects.stopped"

VARSAYILAN_MIN_GUVEN = 0.25

# Sahte / dry_run için örnek nesneler (CI / offline)
_SAHTE_NESNELER: tuple[AlgilananNesne, ...] = (
    AlgilananNesne(etiket="kisi", guven=0.88, kutu=(40, 30, 120, 220)),
    AlgilananNesne(etiket="sandalye", guven=0.72, kutu=(200, 140, 90, 110)),
)

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# detector(mat) → list[AlgilananNesne | dict]
DetectorTuru = Callable[[Any], Sequence[Any]]

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
    """OpenCV kullanılabilir mi?"""
    return bool(_CV2_VAR)


def numpy_var_mi() -> bool:
    """numpy kullanılabilir mi?"""
    return bool(_NUMPY_VAR)


def yolo_var_mi() -> bool:
    """Ultralytics YOLO paketi yüklü mü?"""
    try:
        import ultralytics  # noqa: F401

        return True
    except ImportError:
        return False


def _sahte_nesne_kopyala(
    kaynak: Optional[Sequence[AlgilananNesne]] = None,
) -> list[AlgilananNesne]:
    """Sahte nesne listesi (kopya)."""
    liste = list(kaynak) if kaynak is not None else list(_SAHTE_NESNELER)
    return [
        AlgilananNesne(
            etiket=n.etiket,
            guven=guven_sinirla(n.guven),
            kutu=tuple(n.kutu) if n.kutu is not None else None,  # type: ignore[arg-type]
        )
        for n in liste
    ]


def _nesne_normalize(ham: Any) -> Optional[AlgilananNesne]:
    """dict / AlgilananNesne / tuple → AlgilananNesne."""
    if isinstance(ham, AlgilananNesne):
        return AlgilananNesne(
            etiket=str(ham.etiket or ""),
            guven=guven_sinirla(ham.guven),
            kutu=ham.kutu,
        )
    if isinstance(ham, dict):
        n = AlgilananNesne.from_dict(ham)
        if not n.etiket:
            return None
        return n
    if isinstance(ham, (list, tuple)) and len(ham) >= 2:
        # (etiket, guven) veya (etiket, guven, x, y, w, h)
        etiket = str(ham[0] or "")
        if not etiket:
            return None
        guven = guven_sinirla(ham[1] if len(ham) > 1 else 0.0)
        kutu = None
        if len(ham) >= 6:
            kutu = (int(ham[2]), int(ham[3]), int(ham[4]), int(ham[5]))
        elif len(ham) == 3 and isinstance(ham[2], (list, tuple)) and len(ham[2]) == 4:
            b = ham[2]
            kutu = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        return AlgilananNesne(etiket=etiket, guven=guven, kutu=kutu)
    return None


class NesneAlgilayici(ModulTabani):
    """
    Vision nesne algılama.

    1) dry_run → boş nesne listesi + plan meta
    2) zorla_sahte / motor yok → sahte nesneler
    3) Enjekte detector → OpenCV motoru ile çağrı
    4) YOLO (ultralytics) veya OpenCV HOG kişi algılama
    """

    ad = "vision.analiz.nesne"
    surum = "0.1.0"
    aciklama = "Nesne algılama — OpenCV / YOLO, dry_run / sahte fallback"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        min_guven: Optional[float] = None,
        detector: Optional[DetectorTuru] = None,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
        yolo_modul: Any = None,
        olay_yayinla: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self._detector = detector
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np
        self._yolo = yolo_modul
        self._hog: Any = None

        cfg_guven = self.ayarlar.al("vision.analiz.min_confidence", VARSAYILAN_MIN_GUVEN)
        try:
            varsayilan = float(cfg_guven if cfg_guven is not None else VARSAYILAN_MIN_GUVEN)
        except (TypeError, ValueError):
            varsayilan = VARSAYILAN_MIN_GUVEN
        self.min_guven = guven_sinirla(
            min_guven if min_guven is not None else varsayilan,
            varsayilan=VARSAYILAN_MIN_GUVEN,
        )

        self._son_sonuc: Optional[AnalizSonucu] = None
        self._log = logger_al(f"modul.{self.ad}")
        self._motor = self._motor_sec()
        self._backend = self._backend_sec()

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def backend(self) -> str:
        """opencv_hog | yolo | injected | sahte | dry_run."""
        return self._backend

    @property
    def son_sonuc(self) -> Optional[AnalizSonucu]:
        return self._son_sonuc

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self._motor,
            "backend": self._backend,
            "dry_run": bool(self.dry_run) or self._motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "min_confidence": float(self.min_guven),
            "opencv": self._cv2 is not None or opencv_var_mi(),
            "numpy": self._np is not None or numpy_var_mi(),
            "yolo": self._yolo is not None or yolo_var_mi(),
            "injected": self._detector is not None,
            "last": self._son_sonuc.to_dict() if self._son_sonuc else None,
        }

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001
                pass
        self._motor = self._motor_sec()
        self._backend = self._backend_sec()
        self._isaret_basladi()
        self._audit(
            "vision.analysis.objects.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_NESNE_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "Nesne algilayici basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._hog = None
        self._isaret_durdu()
        self._audit("vision.analysis.objects.stopped", {"engine": self._motor})
        self._yayin(OLAY_NESNE_DURDU, {"engine": self._motor})
        self._log.info("Nesne algilayici durdu")

    # ------------------------------------------------------------------ API

    def algila(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        etiket_filtre: Optional[Sequence[str]] = None,
        sahte_nesneler: Optional[Sequence[AlgilananNesne]] = None,
    ) -> AnalizSonucu:
        """
        Görüntüde nesne algılar → AnalizSonucu.

        dry_run → boş nesne listesi.
        zorla_sahte / motor yok → sahte nesneler.
        """
        kaynak_yol = self._kaynak_yol(girdi)
        esik = guven_sinirla(
            min_guven if min_guven is not None else self.min_guven,
            varsayilan=self.min_guven,
        )
        filtre = (
            {str(x).strip().lower() for x in etiket_filtre if str(x).strip()}
            if etiket_filtre
            else None
        )

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = AnalizSonucu(
                nesneler=[],
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                kaynak_yol=kaynak_yol,
                neden="dry_run",
            )
            return self._sonucla(sonuc)

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            nesneler = self._filtrele(
                _sahte_nesne_kopyala(sahte_nesneler),
                esik=esik,
                filtre=filtre,
            )
            sonuc = AnalizSonucu(
                nesneler=nesneler,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            return self._sonucla(sonuc)

        # Gerçek / enjekte yol — dosya varsa doğrula
        try:
            mat = self._yukle(girdi)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Goruntu yuklenemedi: {exc}",
                kod="VIS_0602",
                modul=self.ad,
            ) from exc

        try:
            ham_liste, neden = self._algila_matris(mat)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.warning("Nesne algilama basarisiz → sahte: %s", exc)
            nesneler = self._filtrele(
                _sahte_nesne_kopyala(sahte_nesneler),
                esik=esik,
                filtre=filtre,
            )
            sonuc = AnalizSonucu(
                nesneler=nesneler,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden=f"algilama_hata:{exc}",
            )
            return self._sonucla(sonuc)

        nesneler = self._filtrele(ham_liste, esik=esik, filtre=filtre)
        sonuc = AnalizSonucu(
            nesneler=nesneler,
            motor=VisionMotoru.OPENCV,
            dry_run=False,
            kaynak_yol=kaynak_yol,
            neden=neden,
        )
        return self._sonucla(sonuc)

    def listele(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        etiket_filtre: Optional[Sequence[str]] = None,
        sahte_nesneler: Optional[Sequence[AlgilananNesne]] = None,
    ) -> list[AlgilananNesne]:
        """Yalnızca nesne listesi döndüren kısayol."""
        return self.algila(
            girdi,
            min_guven=min_guven,
            etiket_filtre=etiket_filtre,
            sahte_nesneler=sahte_nesneler,
        ).nesneler

    def say(
        self,
        girdi: GirdiTuru,
        *,
        etiket: Optional[str] = None,
        min_guven: Optional[float] = None,
    ) -> int:
        """Algılanan nesne sayısı (isteğe bağlı etiket filtresi)."""
        filtre = [etiket] if etiket else None
        return len(
            self.listele(girdi, min_guven=min_guven, etiket_filtre=filtre)
        )

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._detector is not None:
            return VisionMotoru.OPENCV.value
        if self._yolo is not None or yolo_var_mi():
            return VisionMotoru.OPENCV.value
        if self._cv2 is not None or opencv_var_mi():
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _backend_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._detector is not None:
            return "injected"
        if self._yolo is not None or yolo_var_mi():
            return "yolo"
        if self._cv2 is not None or opencv_var_mi():
            return "opencv_hog"
        return "sahte"

    # ------------------------------------------------------------------ iç — girdi

    def _kaynak_yol(self, girdi: GirdiTuru) -> Optional[str]:
        if isinstance(girdi, Kare):
            return girdi.yol
        if isinstance(girdi, Path):
            return str(girdi)
        if isinstance(girdi, str):
            return girdi
        return None

    def _yukle(self, girdi: GirdiTuru) -> Any:
        """Görüntüyü OpenCV matrisine (veya ham bayta) yükler."""
        # Enjekte detector numpy olmadan da çalışabilir — ham bayt ver
        if self._detector is not None and (self._cv2 is None or self._np is None):
            if isinstance(girdi, Kare):
                if girdi.ham:
                    return bytes(girdi.ham)
                if girdi.yol and Path(girdi.yol).expanduser().is_file():
                    return Path(girdi.yol).expanduser().read_bytes()
                raise VisionError(
                    "Kare'de yol veya ham veri yok",
                    kod="VIS_0601",
                    modul=self.ad,
                )
            if isinstance(girdi, (bytes, bytearray)):
                return bytes(girdi)
            if isinstance(girdi, (str, Path)):
                p = Path(girdi).expanduser()
                if not p.is_file():
                    raise VisionError(
                        f"Goruntu yok: {p}",
                        kod="VIS_0602",
                        modul=self.ad,
                    )
                return p.read_bytes()
            return girdi

        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yuklu degil",
                kod="VIS_0601",
                modul=self.ad,
            )

        if isinstance(girdi, Kare):
            if girdi.ham:
                return self._bayttan_matris(bytes(girdi.ham))
            if girdi.yol:
                return self._yoldan_matris(girdi.yol)
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0601",
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
            f"Desteklenmeyen nesne algilama girdisi: {type(girdi)!r}",
            kod="VIS_0601",
            modul=self.ad,
        )

    def _yoldan_matris(self, yol: str) -> Any:
        p = Path(yol).expanduser()
        if not p.is_file():
            raise VisionError(
                f"Goruntu yok: {p}",
                kod="VIS_0602",
                modul=self.ad,
            )
        mat = self._cv2.imread(str(p), self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                f"Goruntu okunamadi: {p}",
                kod="VIS_0602",
                modul=self.ad,
            )
        return mat

    def _bayttan_matris(self, ham: bytes) -> Any:
        if not ham:
            raise VisionError(
                "Bos goruntu baytlari",
                kod="VIS_0601",
                modul=self.ad,
            )
        buf = self._np.frombuffer(ham, dtype=self._np.uint8)
        mat = self._cv2.imdecode(buf, self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                "Bayt goruntu cozulemedi",
                kod="VIS_0602",
                modul=self.ad,
            )
        return mat

    # ------------------------------------------------------------------ iç — algılama

    def _algila_matris(self, mat: Any) -> tuple[list[AlgilananNesne], str]:
        """Matris üzerinde algılama; (liste, neden/backend)."""
        if self._detector is not None:
            ham = self._detector(mat)
            return self._ham_liste_coz(ham), "injected"

        if self._yolo is not None or yolo_var_mi():
            return self._yolo_algila(mat), "yolo"

        if self._cv2 is not None or opencv_var_mi():
            return self._hog_algila(mat), "opencv_hog"

        raise VisionError(
            "Nesne algilama motoru yok (OpenCV/YOLO)",
            kod="VIS_0603",
            modul=self.ad,
        )

    def _ham_liste_coz(self, ham: Any) -> list[AlgilananNesne]:
        if ham is None:
            return []
        if isinstance(ham, AnalizSonucu):
            return list(ham.nesneler)
        if isinstance(ham, AlgilananNesne):
            n = _nesne_normalize(ham)
            return [n] if n else []
        if not isinstance(ham, (list, tuple)):
            raise VisionError(
                f"Detector gecersiz sonuc tipi: {type(ham)!r}",
                kod="VIS_0603",
                modul=self.ad,
            )
        out: list[AlgilananNesne] = []
        for item in ham:
            n = _nesne_normalize(item)
            if n is not None:
                out.append(n)
        return out

    def _yolo_algila(self, mat: Any) -> list[AlgilananNesne]:
        """Ultralytics YOLO ile algılama."""
        model = self._yolo_coz()
        try:
            # YOLO: numpy BGR kabul eder; yol da olabilir
            sonuclar = model.predict(source=mat, verbose=False)
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"YOLO algilama basarisiz: {exc}",
                kod="VIS_0603",
                modul=self.ad,
            ) from exc

        out: list[AlgilananNesne] = []
        if not sonuclar:
            return out
        for res in sonuclar:
            boxes = getattr(res, "boxes", None)
            names = getattr(res, "names", None) or {}
            if boxes is None:
                continue
            try:
                xyxy = boxes.xyxy
                confs = boxes.conf
                clss = boxes.cls
                # torch tensor → liste
                if hasattr(xyxy, "cpu"):
                    xyxy = xyxy.cpu().numpy()
                    confs = confs.cpu().numpy()
                    clss = clss.cpu().numpy()
            except Exception:  # noqa: BLE001
                continue
            for i in range(len(xyxy)):
                x1, y1, x2, y2 = [int(v) for v in xyxy[i][:4]]
                guven = float(confs[i]) if confs is not None else 0.0
                cls_id = int(clss[i]) if clss is not None else -1
                etiket = str(names.get(cls_id, names.get(str(cls_id), f"sinif_{cls_id}")))
                out.append(
                    AlgilananNesne(
                        etiket=etiket,
                        guven=guven_sinirla(guven),
                        kutu=(x1, y1, max(0, x2 - x1), max(0, y2 - y1)),
                    )
                )
        return out

    def _yolo_coz(self) -> Any:
        if self._yolo is not None:
            # Sınıf verilmişse örnekle; örnek verilmişse kullan
            if callable(self._yolo) and not hasattr(self._yolo, "predict"):
                try:
                    return self._yolo()
                except TypeError:
                    return self._yolo
            return self._yolo
        try:
            from ultralytics import YOLO

            return YOLO("yolov8n.pt")
        except Exception as exc:  # pragma: no cover
            raise VisionError(
                f"YOLO yuklenemedi: {exc}",
                kod="VIS_0603",
                modul=self.ad,
            ) from exc

    def _hog_algila(self, mat: Any) -> list[AlgilananNesne]:
        """OpenCV HOGDescriptor ile kişi algılama."""
        cv2 = self._cv2
        if cv2 is None:
            raise VisionError(
                "OpenCV yok",
                kod="VIS_0601",
                modul=self.ad,
            )
        if self._hog is None:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self._hog = hog

        # Gri / renk — HOG renkli bekler; tek kanalsa BGR'ye çevir
        girdi = mat
        shape = getattr(mat, "shape", None)
        if shape is not None and len(shape) == 2:
            girdi = cv2.cvtColor(mat, cv2.COLOR_GRAY2BGR)

        try:
            kutular, agirliklar = self._hog.detectMultiScale(
                girdi,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.05,
            )
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"HOG algilama basarisiz: {exc}",
                kod="VIS_0603",
                modul=self.ad,
            ) from exc

        out: list[AlgilananNesne] = []
        if kutular is None or len(kutular) == 0:
            return out
        for i, (x, y, w, h) in enumerate(kutular):
            guven = 0.6
            if agirliklar is not None and len(agirliklar) > i:
                # HOG ağırlığı genelde >0; 0..1'e yumuşak sıkıştır
                try:
                    raw = float(
                        agirliklar[i][0]
                        if hasattr(agirliklar[i], "__len__")
                        else agirliklar[i]
                    )
                    # Ağırlık büyüdükçe güven artsın (0..1)
                    guven = guven_sinirla(min(0.99, 0.5 + raw * 0.1))
                except (TypeError, ValueError, IndexError):
                    guven = 0.6
            out.append(
                AlgilananNesne(
                    etiket="kisi",
                    guven=guven,
                    kutu=(int(x), int(y), int(w), int(h)),
                )
            )
        return out

    def _filtrele(
        self,
        nesneler: Sequence[AlgilananNesne],
        *,
        esik: float,
        filtre: Optional[set[str]],
    ) -> list[AlgilananNesne]:
        out: list[AlgilananNesne] = []
        for n in nesneler:
            if guven_sinirla(n.guven) < esik:
                continue
            if filtre is not None and str(n.etiket or "").strip().lower() not in filtre:
                continue
            out.append(n)
        return out

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(self, sonuc: AnalizSonucu) -> AnalizSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        if sonuc.neden in ("injected", "yolo", "opencv_hog"):
            self._backend = str(sonuc.neden)
        elif sonuc.dry_run:
            self._backend = "dry_run"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"
        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "count": len(sonuc.nesneler),
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.analysis.objects.detected", detay)
        self._yayin(OLAY_NESNE_ALGILANDI, sonuc.to_dict())
        self._log.debug(
            "Nesne algilama tamam motor=%s adet=%s",
            sonuc.motor.value,
            len(sonuc.nesneler),
        )
        return sonuc

    def _yayin(self, olay: str, veri: dict[str, Any]) -> None:
        if not self.olay_yayinla or self.bus is None:
            return
        try:
            self.bus.publish_sync(olay, dict(veri), kaynak=self.ad)
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Olay yayinlanamadi %s: %s", olay, hata)

    def _audit(self, olay: str, detay: dict[str, Any]) -> None:
        try:
            audit_yaz(olay, modul=self.ad, detay=detay)
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Audit yazilamadi %s: %s", olay, hata)


def nesne_algilayici_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    min_guven: float = VARSAYILAN_MIN_GUVEN,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    detector: Optional[DetectorTuru] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    yolo_modul: Any = None,
    olay_yayinla: bool = False,
) -> NesneAlgilayici:
    """Test / demo için güvenli varsayılanlarla NesneAlgilayici üretir."""
    return NesneAlgilayici(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        min_guven=min_guven,
        detector=detector,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        yolo_modul=yolo_modul,
        olay_yayinla=olay_yayinla,
    )


def nesne_algila(
    girdi: GirdiTuru,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    min_guven: float = VARSAYILAN_MIN_GUVEN,
    etiket_filtre: Optional[Sequence[str]] = None,
    sahte_nesneler: Optional[Sequence[AlgilananNesne]] = None,
    detector: Optional[DetectorTuru] = None,
) -> AnalizSonucu:
    """Tek çağrılık nesne algılama yardımcısı."""
    n = nesne_algilayici_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        min_guven=min_guven,
        detector=detector,
        olay_yayinla=False,
    )
    return n.algila(
        girdi,
        min_guven=min_guven,
        etiket_filtre=etiket_filtre,
        sahte_nesneler=sahte_nesneler,
    )


__all__ = [
    "OLAY_NESNE_ALGILANDI",
    "OLAY_NESNE_BASLADI",
    "OLAY_NESNE_DURDU",
    "VARSAYILAN_MIN_GUVEN",
    "NesneAlgilayici",
    "opencv_var_mi",
    "numpy_var_mi",
    "yolo_var_mi",
    "nesne_algilayici_olustur",
    "nesne_algila",
]

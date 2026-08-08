"""
vision/yuz/algilama.py
----------------------
Gerçek zamanlı yüz algılama (LOCAL ONLY).

Görev:
- Görüntü / kareden yüz kutusu algılama (`YuzKutusu`)
- OpenCV Haar cascade (yerel hafif yol)
- Enjekte edilebilir detector (birim test / özel motor)
- OpenCV yoksa dry_run veya sahte
- Gerçek zamanlı akış API'si (kare dizisi / async iterator)
- YuzGizlilikYoneticisi zorunlu: izin yoksa algılama yok / net hata

Gizlilik:
- Ham algılama için kamera izni gerekir (`tanima_gerekli=False`)
- Yüz tanıma toggle kapalı olsa bile ham kutu algılanabilir
- Embedding / şablon üretilmez; wire'da yalnızca kutular + güven
- Bulut / sync / harici API yok
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Union,
)

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    VARSAYILAN_FPS,
    Kare,
    VisionMotoru,
    YuzGizlilikPolitikasi,
    YuzKutusu,
    guven_sinirla,
    motor_coz,
)
from vision.yuz.gizlilik import (
    YuzGizlilikYoneticisi,
    wire_temizle,
    yuz_gizlilik_olustur,
)

log = logger_al("vision.yuz.algilama")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_YUZ_ALGILANDI = "vision.face.detection.detected"
OLAY_YUZ_ALGILAMA_BASLADI = "vision.face.detection.started"
OLAY_YUZ_ALGILAMA_DURDU = "vision.face.detection.stopped"
OLAY_YUZ_AKIS_BASLADI = "vision.face.detection.stream.started"
OLAY_YUZ_AKIS_DURDU = "vision.face.detection.stream.stopped"

# Algılama için sahte / dry_run güven eşiği (tanıma eşiğinden düşük)
VARSAYILAN_ALGILAMA_ESIK = 0.35

# Sahte / dry_run örnek yüzler (CI / offline)
_SAHTE_YUZLER: tuple[YuzKutusu, ...] = (
    YuzKutusu(x=80, y=60, w=120, h=140, guven=0.92),
    YuzKutusu(x=260, y=90, w=100, h=120, guven=0.78),
)

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# detector(mat) → Sequence[YuzKutusu | dict | tuple]
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


@dataclass
class YuzAlgilamaSonucu:
    """Tek kare yüz algılama sonucu (tanıma değil — yalnızca kutular)."""

    kutular: list[YuzKutusu] = field(default_factory=list)
    motor: VisionMotoru = VisionMotoru.DRY_RUN
    dry_run: bool = False
    yerel_only: bool = True
    kaynak_yol: Optional[str] = None
    kare_id: Optional[str] = None
    neden: Optional[str] = None
    zaman_ms: float = 0.0

    @property
    def adet(self) -> int:
        return len(self.kutular)

    def to_dict(self) -> dict[str, Any]:
        return {
            "faces": [k.to_dict() for k in self.kutular],
            "count": self.adet,
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "local_only": bool(self.yerel_only),
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "source_path": self.kaynak_yol,
            "frame_id": self.kare_id,
            "reason": self.neden,
            "elapsed_ms": float(self.zaman_ms),
        }

    @classmethod
    def from_dict(cls, veri: Mapping[str, Any]) -> "YuzAlgilamaSonucu":
        return cls(
            kutular=[
                YuzKutusu.from_dict(x)
                for x in (veri.get("faces") or [])
                if isinstance(x, dict)
            ],
            motor=motor_coz(veri.get("engine") or VisionMotoru.DRY_RUN),
            dry_run=bool(veri.get("dry_run", False)),
            yerel_only=bool(veri.get("local_only", True)),
            kaynak_yol=veri.get("source_path"),
            kare_id=veri.get("frame_id"),
            neden=veri.get("reason"),
            zaman_ms=float(veri.get("elapsed_ms") or 0.0),
        )


def _sahte_yuz_kopyala(
    kaynak: Optional[Sequence[YuzKutusu]] = None,
) -> list[YuzKutusu]:
    """Sahte yüz listesi (kopya)."""
    liste = list(kaynak) if kaynak is not None else list(_SAHTE_YUZLER)
    return [
        YuzKutusu(
            x=int(k.x),
            y=int(k.y),
            w=int(k.w),
            h=int(k.h),
            guven=guven_sinirla(k.guven),
        )
        for k in liste
    ]


def _kutu_normalize(ham: Any) -> Optional[YuzKutusu]:
    """dict / YuzKutusu / tuple → YuzKutusu."""
    if isinstance(ham, YuzKutusu):
        if ham.w <= 0 or ham.h <= 0:
            return None
        return YuzKutusu(
            x=int(ham.x),
            y=int(ham.y),
            w=int(ham.w),
            h=int(ham.h),
            guven=guven_sinirla(ham.guven),
        )
    if isinstance(ham, Mapping):
        # OpenCV / wire: x,y,w,h + confidence | box
        if "box" in ham and isinstance(ham["box"], (list, tuple)) and len(ham["box"]) >= 4:
            b = ham["box"]
            return YuzKutusu(
                x=int(b[0]),
                y=int(b[1]),
                w=int(b[2]),
                h=int(b[3]),
                guven=guven_sinirla(ham.get("confidence", ham.get("guven", 0.0))),
            )
        k = YuzKutusu.from_dict(dict(ham))
        if k.w <= 0 or k.h <= 0:
            return None
        return k
    if isinstance(ham, (list, tuple)):
        # (x, y, w, h) veya (x, y, w, h, guven)
        if len(ham) >= 4:
            return YuzKutusu(
                x=int(ham[0]),
                y=int(ham[1]),
                w=int(ham[2]),
                h=int(ham[3]),
                guven=guven_sinirla(ham[4] if len(ham) > 4 else 0.85),
            )
    return None


class YuzAlgilayici(ModulTabani):
    """
    Vision yüz algılama (gerçek zamanlı uyumlu).

    1) Gizlilik izni yoksa → VisionError (algılama yok)
    2) dry_run → boş kutu listesi
    3) zorla_sahte / motor yok → sahte yüzler
    4) Enjekte detector → OpenCV motoru ile çağrı
    5) OpenCV Haar cascade frontal face
    """

    ad = "vision.yuz.algilama"
    surum = "0.1.0"
    aciklama = "Yüz algılama — OpenCV Haar, dry_run / sahte, gizlilik kapılı"

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
        cascade_yolu: Optional[Union[str, Path]] = None,
        gizlilik: Optional[YuzGizlilikYoneticisi] = None,
        olay_yayinla: bool = True,
        fps: Optional[int] = None,
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
        self._cascade_yolu = Path(cascade_yolu) if cascade_yolu else None
        self._cascade: Any = None
        self._fps = max(1, int(fps if fps is not None else VARSAYILAN_FPS))

        # Gizlilik — yoksa güvenli varsayılan (dry_run ile uyumlu)
        if gizlilik is not None:
            self.gizlilik = gizlilik
        else:
            self.gizlilik = yuz_gizlilik_olustur(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                olay_yayinla=False,
                kamera_izin=True if self.dry_run else None,
            )

        cfg_guven = self._cfg_al("vision.face.detection_min_confidence", VARSAYILAN_ALGILAMA_ESIK)
        try:
            varsayilan = float(
                cfg_guven if cfg_guven is not None else VARSAYILAN_ALGILAMA_ESIK
            )
        except (TypeError, ValueError):
            varsayilan = VARSAYILAN_ALGILAMA_ESIK
        self.min_guven = guven_sinirla(
            min_guven if min_guven is not None else varsayilan,
            varsayilan=VARSAYILAN_ALGILAMA_ESIK,
        )

        self._son_sonuc: Optional[YuzAlgilamaSonucu] = None
        self._akiyor = False
        self._akis_kare = 0
        self._log = logger_al(f"modul.{self.ad}")
        self._motor = self._motor_sec()
        self._backend = self._backend_sec()

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def backend(self) -> str:
        """opencv_haar | injected | sahte | dry_run."""
        return self._backend

    @property
    def son_sonuc(self) -> Optional[YuzAlgilamaSonucu]:
        return self._son_sonuc

    @property
    def akiyor(self) -> bool:
        """Gerçek zamanlı akış döngüsü aktif mi?"""
        return bool(self._akiyor)

    @property
    def fps(self) -> int:
        return int(self._fps)

    def fps_ayarla(self, fps: int) -> int:
        """Akış throttle FPS'i."""
        self._fps = max(1, int(fps))
        return self._fps

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self._motor,
            "backend": self._backend,
            "dry_run": bool(self.dry_run) or self._motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "min_confidence": float(self.min_guven),
            "fps": self.fps,
            "opencv": self._cv2 is not None or opencv_var_mi(),
            "numpy": self._np is not None or numpy_var_mi(),
            "injected": self._detector is not None,
            "local_only": True,
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "camera_permission": self.gizlilik.kamera_izni_var_mi(),
            "face_enabled": self.gizlilik.yuz_tanima_aktif_mi(),
            "streaming": bool(self._akiyor),
            "stream_frames": int(self._akis_kare),
            "running": bool(self._calisiyor),
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
        # Gizlilik modülü de ayaktaysa senkron tut
        if not self.gizlilik.calisiyor:
            try:
                await self.gizlilik.baslat()
            except Exception as hata:  # noqa: BLE001
                self._log.debug("Gizlilik baslat atlandi: %s", hata)
        self._motor = self._motor_sec()
        self._backend = self._backend_sec()
        self._isaret_basladi()
        detay = self._audit_detay(
            {"engine": self._motor, "backend": self._backend}
        )
        self._audit("vision.face.detection.started", detay)
        self._yayin(OLAY_YUZ_ALGILAMA_BASLADI, detay)
        self._log.info(
            "Yuz algilayici basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if self._akiyor:
            self._akiyor = False
        if not self._calisiyor:
            return
        self._cascade = None
        self._isaret_durdu()
        detay = self._audit_detay({"engine": self._motor})
        self._audit("vision.face.detection.stopped", detay)
        self._yayin(OLAY_YUZ_ALGILAMA_DURDU, detay)
        self._log.info("Yuz algilayici durdu")

    # ------------------------------------------------------------------ izin

    def izin_kontrol(self) -> None:
        """
        Algılama öncesi gizlilik kapısı.

        Ham algılama: kamera izni zorunlu; tanıma toggle zorunlu değil.
        İzin yoksa net VisionError (VIS_0702); algılama yapılmaz.
        """
        self.gizlilik.izin_zorla(tanima_gerekli=False)

    def izinli_mi(self) -> bool:
        """Kamera izni var mı? (ham algılama)."""
        return self.gizlilik.islem_izinli_mi(tanima_gerekli=False)

    # ------------------------------------------------------------------ API

    def algila(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        sahte_yuzler: Optional[Sequence[YuzKutusu]] = None,
        izin_zorla: bool = True,
    ) -> YuzAlgilamaSonucu:
        """
        Tek karede yüz algılar → YuzAlgilamaSonucu.

        izin_zorla=True (varsayılan): gizlilik kapalıysa hata, algılama yok.
        dry_run → boş kutu listesi.
        zorla_sahte / motor yok → sahte yüzler.
        """
        t0 = time.perf_counter()
        if izin_zorla:
            self.izin_kontrol()

        kaynak_yol = self._kaynak_yol(girdi)
        kare_id = girdi.id if isinstance(girdi, Kare) else None
        esik = guven_sinirla(
            min_guven if min_guven is not None else self.min_guven,
            varsayilan=self.min_guven,
        )

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = YuzAlgilamaSonucu(
                kutular=[],
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                kaynak_yol=kaynak_yol,
                kare_id=kare_id,
                neden="dry_run",
                zaman_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return self._sonucla(sonuc)

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            kutular = self._filtrele(_sahte_yuz_kopyala(sahte_yuzler), esik=esik)
            sonuc = YuzAlgilamaSonucu(
                kutular=kutular,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                kare_id=kare_id,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
                zaman_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return self._sonucla(sonuc)

        try:
            mat = self._yukle(girdi)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Goruntu yuklenemedi: {exc}",
                kod="VIS_0712",
                modul=self.ad,
            ) from exc

        try:
            ham_liste, neden = self._algila_matris(mat)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.warning("Yuz algilama basarisiz → sahte: %s", exc)
            kutular = self._filtrele(_sahte_yuz_kopyala(sahte_yuzler), esik=esik)
            sonuc = YuzAlgilamaSonucu(
                kutular=kutular,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                kare_id=kare_id,
                neden=f"algilama_hata:{exc}",
                zaman_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return self._sonucla(sonuc)

        kutular = self._filtrele(ham_liste, esik=esik)
        sonuc = YuzAlgilamaSonucu(
            kutular=kutular,
            motor=VisionMotoru.OPENCV,
            dry_run=False,
            kaynak_yol=kaynak_yol,
            kare_id=kare_id,
            neden=neden,
            zaman_ms=(time.perf_counter() - t0) * 1000.0,
        )
        return self._sonucla(sonuc)

    def listele(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        sahte_yuzler: Optional[Sequence[YuzKutusu]] = None,
        izin_zorla: bool = True,
    ) -> list[YuzKutusu]:
        """Yalnızca yüz kutusu listesi."""
        return self.algila(
            girdi,
            min_guven=min_guven,
            sahte_yuzler=sahte_yuzler,
            izin_zorla=izin_zorla,
        ).kutular

    def say(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        izin_zorla: bool = True,
    ) -> int:
        """Algılanan yüz sayısı."""
        return len(self.listele(girdi, min_guven=min_guven, izin_zorla=izin_zorla))

    def kareleri_algila(
        self,
        kareler: Iterable[GirdiTuru],
        *,
        min_guven: Optional[float] = None,
        sahte_yuzler: Optional[Sequence[YuzKutusu]] = None,
        izin_zorla: bool = True,
        maks: Optional[int] = None,
    ) -> Iterator[YuzAlgilamaSonucu]:
        """
        Senkron kare dizisi üzerinde algılama (gerçek zamanlı uyumlu).

        FPS throttle uygulanır; maks verilirse o kadar kareden sonra durur.
        """
        if izin_zorla:
            self.izin_kontrol()

        self._akiyor = True
        self._akis_kare = 0
        aralik = 1.0 / float(self.fps)
        detay = self._audit_detay({"engine": self._motor, "fps": self.fps, "mode": "sync"})
        self._audit("vision.face.detection.stream.started", detay)
        self._yayin(OLAY_YUZ_AKIS_BASLADI, detay)
        try:
            for girdi in kareler:
                if not self._akiyor:
                    break
                if maks is not None and self._akis_kare >= int(maks):
                    break
                t_bas = time.perf_counter()
                # Akış içinde tekrar izin_zorla=False — kapı akış başında açıldı
                sonuc = self.algila(
                    girdi,
                    min_guven=min_guven,
                    sahte_yuzler=sahte_yuzler,
                    izin_zorla=False,
                )
                self._akis_kare += 1
                yield sonuc
                gecen = time.perf_counter() - t_bas
                bekle = aralik - gecen
                if bekle > 0:
                    time.sleep(bekle)
        finally:
            self._akiyor = False
            bitis = self._audit_detay(
                {"engine": self._motor, "frames": self._akis_kare, "mode": "sync"}
            )
            self._audit("vision.face.detection.stream.stopped", bitis)
            self._yayin(OLAY_YUZ_AKIS_DURDU, bitis)

    async def akis_algila(
        self,
        kareler: Union[AsyncIterator[GirdiTuru], Iterable[GirdiTuru]],
        *,
        min_guven: Optional[float] = None,
        sahte_yuzler: Optional[Sequence[YuzKutusu]] = None,
        izin_zorla: bool = True,
        maks: Optional[int] = None,
    ) -> AsyncIterator[YuzAlgilamaSonucu]:
        """
        Async kare akışında yüz algılama (gerçek zamanlı).

        AsyncIterator veya Iterable kabul eder; FPS throttle uygular.
        """
        if izin_zorla:
            self.izin_kontrol()

        self._akiyor = True
        self._akis_kare = 0
        aralik = 1.0 / float(self.fps)
        detay = self._audit_detay({"engine": self._motor, "fps": self.fps, "mode": "async"})
        self._audit("vision.face.detection.stream.started", detay)
        self._yayin(OLAY_YUZ_AKIS_BASLADI, detay)

        async def _uretec() -> AsyncIterator[GirdiTuru]:
            if hasattr(kareler, "__aiter__"):
                async for k in kareler:  # type: ignore[union-attr]
                    yield k
            else:
                for k in kareler:  # type: ignore[union-attr]
                    yield k
                    await asyncio.sleep(0)

        try:
            async for girdi in _uretec():
                if not self._akiyor:
                    break
                if maks is not None and self._akis_kare >= int(maks):
                    break
                t_bas = time.perf_counter()
                sonuc = self.algila(
                    girdi,
                    min_guven=min_guven,
                    sahte_yuzler=sahte_yuzler,
                    izin_zorla=False,
                )
                self._akis_kare += 1
                yield sonuc
                gecen = time.perf_counter() - t_bas
                bekle = aralik - gecen
                if bekle > 0:
                    await asyncio.sleep(bekle)
        finally:
            self._akiyor = False
            bitis = self._audit_detay(
                {"engine": self._motor, "frames": self._akis_kare, "mode": "async"}
            )
            self._audit("vision.face.detection.stream.stopped", bitis)
            self._yayin(OLAY_YUZ_AKIS_DURDU, bitis)

    def akis_durdur(self) -> None:
        """Aktif gerçek zamanlı akışı güvenli şekilde durdurur."""
        self._akiyor = False

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._detector is not None:
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
        if self._cv2 is not None or opencv_var_mi():
            return "opencv_haar"
        return "sahte"

    def _cfg_al(self, anahtar: str, varsayilan: Any = None) -> Any:
        try:
            return self.ayarlar.al(anahtar, varsayilan)
        except Exception:  # noqa: BLE001
            return varsayilan

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
        if self._detector is not None and (self._cv2 is None or self._np is None):
            if isinstance(girdi, Kare):
                if girdi.ham:
                    return bytes(girdi.ham)
                if girdi.yol and Path(girdi.yol).expanduser().is_file():
                    return Path(girdi.yol).expanduser().read_bytes()
                raise VisionError(
                    "Kare'de yol veya ham veri yok",
                    kod="VIS_0711",
                    modul=self.ad,
                )
            if isinstance(girdi, (bytes, bytearray)):
                return bytes(girdi)
            if isinstance(girdi, (str, Path)):
                p = Path(girdi).expanduser()
                if not p.is_file():
                    raise VisionError(
                        f"Goruntu yok: {p}",
                        kod="VIS_0712",
                        modul=self.ad,
                    )
                return p.read_bytes()
            return girdi

        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yok; yuz algilama yapilamaz",
                kod="VIS_0711",
                modul=self.ad,
            )

        if isinstance(girdi, Kare):
            if girdi.ham:
                buf = np.frombuffer(bytes(girdi.ham), dtype=np.uint8)
                mat = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if mat is None:
                    raise VisionError(
                        "Kare ham verisi cozulemedi",
                        kod="VIS_0712",
                        modul=self.ad,
                    )
                return mat
            if girdi.yol and Path(girdi.yol).expanduser().is_file():
                mat = cv2.imread(str(Path(girdi.yol).expanduser()))
                if mat is None:
                    raise VisionError(
                        f"Goruntu okunamadi: {girdi.yol}",
                        kod="VIS_0712",
                        modul=self.ad,
                    )
                return mat
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0711",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            buf = np.frombuffer(bytes(girdi), dtype=np.uint8)
            mat = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if mat is None:
                raise VisionError(
                    "Bayt goruntu cozulemedi",
                    kod="VIS_0712",
                    modul=self.ad,
                )
            return mat

        if isinstance(girdi, (str, Path)):
            p = Path(girdi).expanduser()
            if not p.is_file():
                raise VisionError(
                    f"Goruntu yok: {p}",
                    kod="VIS_0712",
                    modul=self.ad,
                )
            mat = cv2.imread(str(p))
            if mat is None:
                raise VisionError(
                    f"Goruntu okunamadi: {p}",
                    kod="VIS_0712",
                    modul=self.ad,
                )
            return mat

        # Zaten matris olabilir (numpy ndarray)
        if np is not None and isinstance(girdi, np.ndarray):
            return girdi

        raise VisionError(
            f"Desteklenmeyen yuz algilama girdisi: {type(girdi)!r}",
            kod="VIS_0711",
            modul=self.ad,
        )

    # ------------------------------------------------------------------ iç — algıla

    def _algila_matris(self, mat: Any) -> tuple[list[YuzKutusu], str]:
        if self._detector is not None:
            ham = self._detector(mat)
            kutular = []
            for x in ham or []:
                k = _kutu_normalize(x)
                if k is not None:
                    kutular.append(k)
            return kutular, "injected"

        return self._haar_algila(mat), "opencv_haar"

    def _haar_algila(self, mat: Any) -> list[YuzKutusu]:
        cv2 = self._cv2
        if cv2 is None:
            raise VisionError(
                "OpenCV yok; Haar yuz algilama yapilamaz",
                kod="VIS_0713",
                modul=self.ad,
            )
        cascade = self._cascade_al()
        try:
            gri = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
        except Exception:
            # Zaten gri olabilir
            gri = mat
        try:
            faces = cascade.detectMultiScale(
                gri,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30),
            )
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Haar yuz algilama basarisiz: {exc}",
                kod="VIS_0713",
                modul=self.ad,
                detay={"error": str(exc)},
            ) from exc

        kutular: list[YuzKutusu] = []
        for (x, y, w, h) in faces:
            kutular.append(
                YuzKutusu(
                    x=int(x),
                    y=int(y),
                    w=int(w),
                    h=int(h),
                    guven=0.85,  # Haar skor vermez — sabit orta-yüksek
                )
            )
        return kutular

    def _cascade_al(self) -> Any:
        if self._cascade is not None:
            return self._cascade
        cv2 = self._cv2
        if cv2 is None:
            raise VisionError(
                "OpenCV yok",
                kod="VIS_0713",
                modul=self.ad,
            )
        yol: Optional[str] = None
        if self._cascade_yolu is not None:
            yol = str(self._cascade_yolu)
        else:
            try:
                yol = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            except Exception:  # noqa: BLE001
                yol = None
        if not yol or not Path(yol).is_file():
            raise VisionError(
                "Haar cascade dosyasi bulunamadi",
                kod="VIS_0713",
                modul=self.ad,
                detay={"path": yol},
            )
        cascade = cv2.CascadeClassifier(yol)
        if cascade.empty():
            raise VisionError(
                f"Haar cascade yuklenemedi: {yol}",
                kod="VIS_0713",
                modul=self.ad,
            )
        self._cascade = cascade
        return cascade

    def _filtrele(
        self,
        kutular: Sequence[YuzKutusu],
        *,
        esik: float,
    ) -> list[YuzKutusu]:
        return [k for k in kutular if guven_sinirla(k.guven) >= float(esik)]

    # ------------------------------------------------------------------ iç — sonuç / olay

    def _sonucla(self, sonuc: YuzAlgilamaSonucu) -> YuzAlgilamaSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        if sonuc.neden in ("injected", "opencv_haar"):
            self._backend = str(sonuc.neden)
        elif sonuc.dry_run:
            self._backend = "dry_run"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"
        detay = self._audit_detay(
            {
                "engine": sonuc.motor.value,
                "backend": self._backend,
                "count": sonuc.adet,
                "dry_run": bool(sonuc.dry_run),
                "source_path": sonuc.kaynak_yol,
                "frame_id": sonuc.kare_id,
                "reason": sonuc.neden,
                "elapsed_ms": sonuc.zaman_ms,
            }
        )
        self._audit("vision.face.detection.detected", detay)
        # Wire: yalnızca kutular + meta (embedding yok)
        self._yayin(OLAY_YUZ_ALGILANDI, wire_temizle(sonuc.to_dict()))
        self._log.debug(
            "Yuz algilama tamam motor=%s adet=%s",
            sonuc.motor.value,
            sonuc.adet,
        )
        return sonuc

    def _audit_detay(self, ekstra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        temel = {
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "local_only": True,
            "camera_permission": self.gizlilik.kamera_izni_var_mi(),
            "face_enabled": self.gizlilik.yuz_tanima_aktif_mi(),
        }
        if ekstra:
            temel.update(dict(ekstra))
        return wire_temizle(temel)

    def _yayin(self, olay: str, veri: Mapping[str, Any]) -> None:
        if not self.olay_yayinla or self.bus is None:
            return
        try:
            self.bus.publish_sync(olay, wire_temizle(dict(veri)), kaynak=self.ad)
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Olay yayinlanamadi %s: %s", olay, hata)

    def _audit(self, olay: str, detay: Mapping[str, Any]) -> None:
        try:
            audit_yaz(olay, modul=self.ad, detay=wire_temizle(dict(detay)))
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Audit yazilamadi %s: %s", olay, hata)


def yuz_algilayici_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    min_guven: float = VARSAYILAN_ALGILAMA_ESIK,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    detector: Optional[DetectorTuru] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    cascade_yolu: Optional[Union[str, Path]] = None,
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    olay_yayinla: bool = False,
    fps: int = VARSAYILAN_FPS,
    kamera_izin: Optional[bool] = True,
    yuz_aktif: Optional[bool] = None,
) -> YuzAlgilayici:
    """Test / demo için güvenli varsayılanlarla YuzAlgilayici üretir."""
    g = gizlilik
    if g is None:
        g = yuz_gizlilik_olustur(
            ayarlar=ayarlar,
            bus=bus,
            dry_run=dry_run,
            olay_yayinla=False,
            kamera_izin=kamera_izin,
            yuz_aktif=yuz_aktif,
        )
    return YuzAlgilayici(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        min_guven=min_guven,
        detector=detector,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        cascade_yolu=cascade_yolu,
        gizlilik=g,
        olay_yayinla=olay_yayinla,
        fps=fps,
    )


def yuz_algila(
    girdi: GirdiTuru,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    min_guven: float = VARSAYILAN_ALGILAMA_ESIK,
    sahte_yuzler: Optional[Sequence[YuzKutusu]] = None,
    detector: Optional[DetectorTuru] = None,
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    kamera_izin: bool = True,
) -> YuzAlgilamaSonucu:
    """Tek çağrılık yüz algılama yardımcısı."""
    a = yuz_algilayici_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        min_guven=min_guven,
        detector=detector,
        gizlilik=gizlilik,
        kamera_izin=kamera_izin,
        olay_yayinla=False,
    )
    return a.algila(girdi, min_guven=min_guven, sahte_yuzler=sahte_yuzler)


__all__ = [
    "OLAY_YUZ_ALGILANDI",
    "OLAY_YUZ_ALGILAMA_BASLADI",
    "OLAY_YUZ_ALGILAMA_DURDU",
    "OLAY_YUZ_AKIS_BASLADI",
    "OLAY_YUZ_AKIS_DURDU",
    "VARSAYILAN_ALGILAMA_ESIK",
    "YuzAlgilamaSonucu",
    "YuzAlgilayici",
    "opencv_var_mi",
    "numpy_var_mi",
    "yuz_algilayici_olustur",
    "yuz_algila",
]

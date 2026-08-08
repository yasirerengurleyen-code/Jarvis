"""
vision/camera/kamera.py
-----------------------
Kamera Manager — start/stop, cihaz seçimi, fotoğraf, FPS.

Görev:
- Kamerayı başlat / durdur (oturum yaşam döngüsü)
- Cihaz seçimi ve FPS ayarı (KameraAyarlari)
- Fotoğraf çekme (skills/media/kamera köprüsü)
- OpenCV / donanım yoksa dry_run veya sahte fallback
- Logger + audit + isteğe bağlı EventBus kancaları

Not: Sürekli video kare üretimi `vision/camera/akis.py` dosyasına aittir;
bu modül oturum, seçim, FPS ve tek kare fotoğraf sağlar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from skills.media import kamera as skill_kamera
from vision.modeller import (
    VARSAYILAN_FPS,
    KameraAyarlari,
    KameraCihazi,
    Kare,
    VisionMotoru,
    YakalamaSonucu,
    kare_olustur,
    motor_coz,
)

log = logger_al("vision.camera.kamera")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_KAMERA_BASLADI = "vision.camera.started"
OLAY_KAMERA_DURDU = "vision.camera.stopped"
OLAY_KAMERA_FOTO = "vision.camera.photo"
OLAY_KAMERA_CIHAZ = "vision.camera.device"
OLAY_KAMERA_FPS = "vision.camera.fps"

# OpenCV CAP_PROP sabitleri (cv2 yokken de kullanılabilir)
_CAP_PROP_FRAME_WIDTH = 3
_CAP_PROP_FRAME_HEIGHT = 4
_CAP_PROP_FPS = 5


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _varsayilan_foto_yolu() -> Path:
    damga = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / "database" / "captures" / f"vision_{damga}.png"


class KameraYoneticisi(ModulTabani):
    """
    Vision Kamera Manager.

    skills/media/kamera sarmalayıcısını yeniden yazmaz; listeler / açar / çeker.
    Oturum açıkken gerçek OpenCV yakalayıcıyı tutabilir (akis.py için hazırlık).
    """

    ad = "vision.camera"
    surum = "0.1.0"
    aciklama = "Kamera Manager — start/stop, seçim, fotoğraf, FPS"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        cihaz: Optional[int] = None,
        fps: Optional[int] = None,
        cv2_modul: Any = None,
        olay_yayinla: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self._cv2 = cv2_modul

        # Config (config.vision Engine köprüsünde genişler; şimdilik opsiyonel)
        cfg_cihaz = self.ayarlar.al("vision.camera.device", 0)
        cfg_fps = self.ayarlar.al("vision.camera.fps", VARSAYILAN_FPS)
        cfg_w = int(self.ayarlar.al("vision.camera.width", 0) or 0)
        cfg_h = int(self.ayarlar.al("vision.camera.height", 0) or 0)

        self.kamera_ayarlari = KameraAyarlari(
            cihaz=int(cihaz if cihaz is not None else cfg_cihaz or 0),
            fps=max(1, int(fps if fps is not None else cfg_fps or VARSAYILAN_FPS)),
            genislik=cfg_w,
            yukseklik=cfg_h,
        )

        self._cap: Any = None  # OpenCV VideoCapture veya None
        self._son_yakalama: Optional[YakalamaSonucu] = None
        self._son_cihazlar: list[KameraCihazi] = []
        self._motor = self._motor_sec()
        self._log = logger_al(f"modul.{self.ad}")

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def cihaz(self) -> int:
        return int(self.kamera_ayarlari.cihaz)

    @property
    def fps(self) -> int:
        return max(1, int(self.kamera_ayarlari.fps))

    @property
    def cap(self) -> Any:
        """Açık OpenCV VideoCapture (yoksa None). akis.py kullanabilir."""
        return self._cap

    @property
    def son_yakalama(self) -> Optional[YakalamaSonucu]:
        return self._son_yakalama

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        """Kamerayı / oturumu başlatır."""
        if self._calisiyor:
            return

        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — test / bellek ayarları
                pass

        self._motor = self._motor_sec()
        self._cap_serbest()

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            self._motor = VisionMotoru.DRY_RUN.value
            self._isaret_basladi()
            self._audit("vision.camera.started", {"engine": self._motor, "device": self.cihaz})
            self._yayin(OLAY_KAMERA_BASLADI, {"engine": self._motor, "device": self.cihaz, "fps": self.fps})
            self._log.info("Kamera oturumu basladi (dry_run) cihaz=%s", self.cihaz)
            return

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            self._motor = VisionMotoru.SAHTE.value
            self._isaret_basladi()
            self._audit(
                "vision.camera.started",
                {"engine": self._motor, "device": self.cihaz, "reason": "sahte"},
            )
            self._yayin(
                OLAY_KAMERA_BASLADI,
                {"engine": self._motor, "device": self.cihaz, "fps": self.fps, "reason": "sahte"},
            )
            self._log.info("Kamera oturumu basladi (sahte) cihaz=%s", self.cihaz)
            return

        cv = self._cv2_coz()
        if cv is None:
            # OpenCV yok → sahte oturum
            self._motor = VisionMotoru.SAHTE.value
            self._isaret_basladi()
            self._audit(
                "vision.camera.started",
                {"engine": self._motor, "device": self.cihaz, "reason": "opencv_yok"},
            )
            self._yayin(
                OLAY_KAMERA_BASLADI,
                {
                    "engine": self._motor,
                    "device": self.cihaz,
                    "fps": self.fps,
                    "reason": "opencv_yok",
                },
            )
            self._log.warning("OpenCV yok; sahte kamera oturumu")
            return

        # Gerçek yakalayıcıyı açmayı dene
        try:
            cap = cv.VideoCapture(int(self.cihaz))
            if cap is None or not cap.isOpened():
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:  # noqa: BLE001
                        pass
                # Donanım yok → sahte oturum (CI / laptop kamerasız)
                self._motor = VisionMotoru.SAHTE.value
                self._isaret_basladi()
                self._audit(
                    "vision.camera.started",
                    {
                        "engine": self._motor,
                        "device": self.cihaz,
                        "reason": "kamera_yok",
                    },
                )
                self._yayin(
                    OLAY_KAMERA_BASLADI,
                    {
                        "engine": self._motor,
                        "device": self.cihaz,
                        "fps": self.fps,
                        "reason": "kamera_yok",
                    },
                )
                self._log.warning("Kamera %s acilamadi; sahte oturum", self.cihaz)
                return

            self._cap = cap
            self._cap_fps_uygula(cv)
            self._motor = VisionMotoru.OPENCV.value
            self._isaret_basladi()
            self._audit(
                "vision.camera.started",
                {"engine": self._motor, "device": self.cihaz, "fps": self.fps},
            )
            self._yayin(
                OLAY_KAMERA_BASLADI,
                {"engine": self._motor, "device": self.cihaz, "fps": self.fps},
            )
            self._log.info("Kamera oturumu basladi (opencv) cihaz=%s fps=%s", self.cihaz, self.fps)
        except Exception as exc:  # noqa: BLE001
            self._cap_serbest()
            self._motor = VisionMotoru.SAHTE.value
            self._isaret_basladi()
            self._audit(
                "vision.camera.started",
                {
                    "engine": self._motor,
                    "device": self.cihaz,
                    "reason": f"hata:{exc}",
                },
            )
            self._yayin(
                OLAY_KAMERA_BASLADI,
                {
                    "engine": self._motor,
                    "device": self.cihaz,
                    "fps": self.fps,
                    "reason": f"hata:{exc}",
                },
            )
            self._log.warning("Kamera baslatma hatasi → sahte: %s", exc)

    async def durdur(self) -> None:
        """Kamerayı / oturumu güvenli kapatır."""
        if not self._calisiyor and self._cap is None:
            return

        cihaz = self.cihaz
        motor = self._motor
        self._cap_serbest()
        self._isaret_durdu()
        self._audit("vision.camera.stopped", {"engine": motor, "device": cihaz})
        self._yayin(OLAY_KAMERA_DURDU, {"engine": motor, "device": cihaz})
        self._log.info("Kamera oturumu durdu cihaz=%s", cihaz)

    # ------------------------------------------------------------------ API

    def cihazlari_listele(self, *, max_indeks: int = 5) -> list[KameraCihazi]:
        """Erişilebilir kameraları listeler (skill köprüsü)."""
        bil = skill_kamera.cihazlari_listele(
            max_indeks=max(0, int(max_indeks)),
            dry_run=self.dry_run,
            zorla_sahte=self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value,
            cv2_modul=self._cv2,
        )
        cihazlar: list[KameraCihazi] = []
        for d in bil.get("devices") or []:
            if not isinstance(d, dict):
                continue
            cihazlar.append(
                KameraCihazi(
                    indeks=int(d.get("index", 0)),
                    ad=str(d.get("name") or f"camera_{d.get('index', 0)}"),
                    erisilebilir=bool(d.get("available", True)),
                    not_=str(d.get("note") or ""),
                )
            )
        self._son_cihazlar = cihazlar
        return list(cihazlar)

    def cihaz_sec(self, indeks: int) -> KameraAyarlari:
        """Aktif kamera cihazını seçer; oturum açıksa yeniden bağlanır (best-effort)."""
        try:
            idx = int(indeks)
        except (TypeError, ValueError) as hata:
            raise VisionError(
                f"Gecersiz kamera cihaz indeksi: {indeks!r}",
                kod="VIS_0101",
                modul=self.ad,
            ) from hata
        if idx < 0:
            raise VisionError(
                f"Kamera cihaz indeksi negatif olamaz: {idx}",
                kod="VIS_0101",
                modul=self.ad,
            )

        onceki = self.kamera_ayarlari.cihaz
        self.kamera_ayarlari.cihaz = idx
        self._audit(
            "vision.camera.device",
            {"device": idx, "previous": onceki, "running": self._calisiyor},
        )
        self._yayin(
            OLAY_KAMERA_CIHAZ,
            {"device": idx, "previous": onceki, "running": self._calisiyor},
        )
        self._log.info("Kamera cihaz secildi: %s → %s", onceki, idx)

        if self._calisiyor and self._motor == VisionMotoru.OPENCV.value:
            # Yeniden aç (senkron; async baslat döngüsüne girmeden)
            self._cap_serbest()
            cv = self._cv2_coz()
            if cv is not None:
                try:
                    cap = cv.VideoCapture(idx)
                    if cap is not None and cap.isOpened():
                        self._cap = cap
                        self._cap_fps_uygula(cv)
                    else:
                        if cap is not None:
                            try:
                                cap.release()
                            except Exception:  # noqa: BLE001
                                pass
                        self._motor = VisionMotoru.SAHTE.value
                except Exception as exc:  # noqa: BLE001
                    self._log.warning("Cihaz degistirilemedi: %s", exc)
                    self._motor = VisionMotoru.SAHTE.value

        return KameraAyarlari(
            cihaz=self.kamera_ayarlari.cihaz,
            fps=self.kamera_ayarlari.fps,
            genislik=self.kamera_ayarlari.genislik,
            yukseklik=self.kamera_ayarlari.yukseklik,
        )

    def fps_ayarla(self, fps: int) -> KameraAyarlari:
        """FPS ayarlar (akis.py ve açık cap için)."""
        try:
            deger = int(fps)
        except (TypeError, ValueError) as hata:
            raise VisionError(
                f"Gecersiz FPS: {fps!r}",
                kod="VIS_0102",
                modul=self.ad,
            ) from hata
        if deger < 1:
            raise VisionError(
                f"FPS en az 1 olmali: {deger}",
                kod="VIS_0102",
                modul=self.ad,
            )

        onceki = self.kamera_ayarlari.fps
        self.kamera_ayarlari.fps = deger
        if self._cap is not None:
            cv = self._cv2_coz()
            if cv is not None:
                self._cap_fps_uygula(cv)

        self._audit(
            "vision.camera.fps",
            {"fps": deger, "previous": onceki, "device": self.cihaz},
        )
        self._yayin(
            OLAY_KAMERA_FPS,
            {"fps": deger, "previous": onceki, "device": self.cihaz},
        )
        self._log.info("Kamera FPS: %s → %s", onceki, deger)
        return KameraAyarlari(
            cihaz=self.kamera_ayarlari.cihaz,
            fps=self.kamera_ayarlari.fps,
            genislik=self.kamera_ayarlari.genislik,
            yukseklik=self.kamera_ayarlari.yukseklik,
        )

    def fotograf_cek(self, *, yol: Optional[str | Path] = None) -> YakalamaSonucu:
        """
        Fotoğraf çeker.

        Oturum opencv + açık cap ise doğrudan kare alır;
        aksi halde skills/media/kamera.fotograf_cek köprüsüne düşer.
        """
        hedef = Path(yol).expanduser() if yol else _varsayilan_foto_yolu()

        # Açık opencv oturumu → doğrudan oku
        if (
            self._calisiyor
            and self._cap is not None
            and self._motor == VisionMotoru.OPENCV.value
            and not self.dry_run
            and not self.zorla_sahte
        ):
            sonuc = self._cap_tan_cek(hedef)
            self._son_yakalama = sonuc
            self._audit(
                "vision.camera.photo",
                {
                    "engine": sonuc.kare.motor.value,
                    "device": self.cihaz,
                    "path": sonuc.kare.yol,
                    "dry_run": sonuc.kare.dry_run,
                },
            )
            self._yayin(OLAY_KAMERA_FOTO, sonuc.to_dict())
            return sonuc

        # Skill köprüsü (dry_run / sahte / kapalı oturum / opencv yok)
        bil = skill_kamera.fotograf_cek(
            self.cihaz,
            yol=hedef,
            dry_run=self.dry_run,
            zorla_sahte=self.zorla_sahte
            or (self._motor == VisionMotoru.SAHTE.value and not self.dry_run),
            cv2_modul=self._cv2,
        )
        sonuc = self._skill_sonucundan(bil)
        self._son_yakalama = sonuc
        self._audit(
            "vision.camera.photo",
            {
                "engine": sonuc.kare.motor.value,
                "device": self.cihaz,
                "path": sonuc.kare.yol,
                "dry_run": sonuc.kare.dry_run,
                "reason": sonuc.neden,
            },
        )
        self._yayin(OLAY_KAMERA_FOTO, sonuc.to_dict())
        return sonuc

    def ozet(self) -> dict[str, Any]:
        """Durum özeti (wire İngilizce anahtarlar)."""
        return {
            "name": self.ad,
            "version": self.surum,
            "running": bool(self._calisiyor),
            "engine": self._motor,
            "dry_run": bool(self.dry_run),
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "device": self.cihaz,
            "fps": self.fps,
            "settings": self.kamera_ayarlari.to_dict(),
            "capture_open": self._cap is not None,
            "devices_cached": len(self._son_cihazlar),
            "last_photo": self._son_yakalama.to_dict() if self._son_yakalama else None,
            "opencv": skill_kamera.opencv_var_mi() or self._cv2 is not None,
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._cv2 is not None or skill_kamera.opencv_var_mi():
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _cv2_coz(self) -> Any:
        if self._cv2 is not None:
            return self._cv2
        if skill_kamera.opencv_var_mi():
            return skill_kamera._cv2  # noqa: SLF001 — bilinçli köprü
        return None

    def _cap_serbest(self) -> None:
        if self._cap is None:
            return
        try:
            self._cap.release()
        except Exception:  # noqa: BLE001
            pass
        self._cap = None

    def _cap_fps_uygula(self, cv: Any) -> None:
        if self._cap is None:
            return
        prop = getattr(cv, "CAP_PROP_FPS", _CAP_PROP_FPS)
        try:
            self._cap.set(prop, float(self.fps))
        except Exception:  # noqa: BLE001
            pass
        # İsteğe bağlı çözünürlük
        if self.kamera_ayarlari.genislik > 0:
            try:
                self._cap.set(
                    getattr(cv, "CAP_PROP_FRAME_WIDTH", _CAP_PROP_FRAME_WIDTH),
                    float(self.kamera_ayarlari.genislik),
                )
            except Exception:  # noqa: BLE001
                pass
        if self.kamera_ayarlari.yukseklik > 0:
            try:
                self._cap.set(
                    getattr(cv, "CAP_PROP_FRAME_HEIGHT", _CAP_PROP_FRAME_HEIGHT),
                    float(self.kamera_ayarlari.yukseklik),
                )
            except Exception:  # noqa: BLE001
                pass

    def _cap_tan_cek(self, hedef: Path) -> YakalamaSonucu:
        cv = self._cv2_coz()
        if cv is None or self._cap is None:
            bil = skill_kamera.fotograf_cek(
                self.cihaz,
                yol=hedef,
                dry_run=False,
                zorla_sahte=True,
                cv2_modul=None,
            )
            return self._skill_sonucundan(bil)

        try:
            ok, kare = self._cap.read()
            if not ok or kare is None:
                bil = skill_kamera.fotograf_cek(
                    self.cihaz,
                    yol=hedef,
                    zorla_sahte=True,
                    cv2_modul=None,
                )
                sonuc = self._skill_sonucundan(bil)
                sonuc.neden = sonuc.neden or "kare_okunamadi"
                return sonuc

            hedef.parent.mkdir(parents=True, exist_ok=True)
            uzanti = hedef.suffix.lower() or ".png"
            if uzanti in {".jpg", ".jpeg"}:
                basarili, buf = cv.imencode(".jpg", kare)
            else:
                basarili, buf = cv.imencode(".png", kare)
                if hedef.suffix.lower() not in {".png"}:
                    hedef = hedef.with_suffix(".png")

            if not basarili:
                bil = skill_kamera.fotograf_cek(
                    self.cihaz,
                    yol=hedef,
                    zorla_sahte=True,
                )
                return self._skill_sonucundan(bil)

            hedef.write_bytes(buf.tobytes())
            h, w = kare.shape[:2]
            self.kamera_ayarlari.genislik = int(w)
            self.kamera_ayarlari.yukseklik = int(h)
            k = kare_olustur(
                yol=str(hedef.resolve()),
                genislik=int(w),
                yukseklik=int(h),
                cihaz=self.cihaz,
                motor=VisionMotoru.OPENCV,
                dry_run=False,
                bayt_sayisi=hedef.stat().st_size,
            )
            return YakalamaSonucu(kare=k, acik=True, neden=None, hata=None)
        except Exception as exc:  # noqa: BLE001
            bil = skill_kamera.fotograf_cek(
                self.cihaz,
                yol=hedef,
                zorla_sahte=True,
            )
            sonuc = self._skill_sonucundan(bil)
            sonuc.hata = str(exc)
            sonuc.neden = f"hata:{exc}"
            return sonuc

    def _skill_sonucundan(self, bil: dict[str, Any]) -> YakalamaSonucu:
        motor = motor_coz(bil.get("engine") or VisionMotoru.SAHTE)
        k = Kare(
            yol=str(bil["path"]) if bil.get("path") else None,
            genislik=int(bil.get("width") or 0),
            yukseklik=int(bil.get("height") or 0),
            cihaz=int(bil["device"]) if bil.get("device") is not None else self.cihaz,
            motor=motor,
            dry_run=bool(bil.get("dry_run", False)),
            bayt_sayisi=int(bil.get("bytes") or 0),
            zaman=_utc_iso(),
        )
        return YakalamaSonucu(
            kare=k,
            acik=bool(bil.get("opened", False)),
            neden=bil.get("reason"),
            hata=bil.get("error"),
        )

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

    def _isaret_basladi(self) -> None:
        self._calisiyor = True

    def _isaret_durdu(self) -> None:
        self._calisiyor = False


def kamera_yoneticisi_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    cihaz: int = 0,
    fps: int = VARSAYILAN_FPS,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    cv2_modul: Any = None,
    olay_yayinla: bool = False,
) -> KameraYoneticisi:
    """Test / demo için güvenli varsayılanlarla KameraYoneticisi üretir."""
    return KameraYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        cihaz=cihaz,
        fps=fps,
        cv2_modul=cv2_modul,
        olay_yayinla=olay_yayinla,
    )


__all__ = [
    "OLAY_KAMERA_BASLADI",
    "OLAY_KAMERA_DURDU",
    "OLAY_KAMERA_FOTO",
    "OLAY_KAMERA_CIHAZ",
    "OLAY_KAMERA_FPS",
    "KameraYoneticisi",
    "kamera_yoneticisi_olustur",
]

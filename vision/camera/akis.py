"""
vision/camera/akis.py
---------------------
Video akışı — kare üretimi, FPS, dry_run.

Görev:
- KameraYoneticisi oturumu üzerinde sürekli kare üretimi
- FPS'e göre akış hızı (throttle)
- OpenCV / donanım yoksa dry_run veya sahte kare
- EventBus + audit (akış başla/dur/kare)
- Temiz durdurma (döngü güvenli çıkar)

Not: Oturum yaşam döngüsü, cihaz seçimi ve tek fotoğraf
`vision/camera/kamera.py` sorumluluğundadır; bu modül yalnızca akış.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional

from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.camera.kamera import KameraYoneticisi, kamera_yoneticisi_olustur
from vision.modeller import (
    VARSAYILAN_FPS,
    Kare,
    VisionMotoru,
    kare_olustur,
)

log = logger_al("vision.camera.akis")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_AKIS_BASLADI = "vision.camera.stream.started"
OLAY_AKIS_DURDU = "vision.camera.stream.stopped"
OLAY_AKIS_KARE = "vision.camera.stream.frame"

# Sahte / dry_run için 1x1 PNG (OpenCV/Pillow gerekmez)
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Sahte kare varsayılan boyut (wire / özet için)
_SAHTE_GENISLIK = 64
_SAHTE_YUKSEKLIK = 48


class VideoAkis:
    """
    FPS'li video kare akışı.

    KameraYoneticisi'ni sarar; oturum yoksa isteğe bağlı olarak başlatır/durdurur.
    """

    ad = "vision.camera.stream"
    surum = "0.1.0"

    def __init__(
        self,
        kamera: Optional[KameraYoneticisi] = None,
        *,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        fps: Optional[int] = None,
        olay_yayinla: bool = True,
        kamera_yonet: bool = True,
        cihaz: Optional[int] = None,
        cv2_modul: Any = None,
    ) -> None:
        self.olay_yayinla = bool(olay_yayinla)
        self.kamera_yonet = bool(kamera_yonet)
        self._sahip_kamera = kamera is None

        if kamera is not None:
            self.kamera = kamera
            # Dışarıdan verilen yöneticiye dry_run/sahte zorlanmaz; mevcut motor kullanılır
            if fps is not None:
                self.kamera.fps_ayarla(int(fps))
            self.bus = bus if bus is not None else getattr(kamera, "bus", None) or olay_yolu
        else:
            self.kamera = kamera_yoneticisi_olustur(
                dry_run=dry_run,
                zorla_sahte=zorla_sahte,
                cihaz=int(cihaz if cihaz is not None else 0),
                fps=int(fps if fps is not None else VARSAYILAN_FPS),
                bus=bus,
                cv2_modul=cv2_modul,
                olay_yayinla=False,  # akış kendi olaylarını yayınlar
            )
            self.bus = bus if bus is not None else self.kamera.bus

        self._akiyor = False
        self._son_kare: Optional[Kare] = None
        self._uretilen = 0
        self._log = logger_al(f"modul.{self.ad}")

    # ------------------------------------------------------------------ özellik

    @property
    def akiyor(self) -> bool:
        """Akış döngüsü aktif mi?"""
        return bool(self._akiyor)

    @property
    def fps(self) -> int:
        return max(1, int(self.kamera.fps))

    @property
    def motor(self) -> str:
        return str(self.kamera.motor)

    @property
    def son_kare(self) -> Optional[Kare]:
        return self._son_kare

    @property
    def uretilen(self) -> int:
        """Bu oturumda üretilen kare sayısı."""
        return int(self._uretilen)

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        """Akışı (ve gerekirse kamera oturumunu) başlatır."""
        if self._akiyor:
            return

        if self.kamera_yonet and not self.kamera.calisiyor:
            await self.kamera.baslat()

        self._akiyor = True
        self._uretilen = 0
        self._audit(
            "vision.camera.stream.started",
            {
                "engine": self.motor,
                "device": self.kamera.cihaz,
                "fps": self.fps,
            },
        )
        self._yayin(
            OLAY_AKIS_BASLADI,
            {
                "engine": self.motor,
                "device": self.kamera.cihaz,
                "fps": self.fps,
            },
        )
        self._log.info(
            "Video akisi basladi motor=%s cihaz=%s fps=%s",
            self.motor,
            self.kamera.cihaz,
            self.fps,
        )

    async def durdur(self) -> None:
        """Akışı temiz durdurur; kamera_yonet ise oturumu da kapatır."""
        if not self._akiyor and not (
            self.kamera_yonet and self._sahip_kamera and self.kamera.calisiyor
        ):
            # Zaten kapalı — yine de bayrağı temizle
            self._akiyor = False
            return

        motor = self.motor
        cihaz = self.kamera.cihaz
        uretilen = self._uretilen
        self._akiyor = False

        if self.kamera_yonet and self._sahip_kamera and self.kamera.calisiyor:
            await self.kamera.durdur()
        elif self.kamera_yonet and not self._sahip_kamera:
            # Dışarıdan verilen kamerayı kapatma — yalnızca akış bayrağı
            pass

        self._audit(
            "vision.camera.stream.stopped",
            {
                "engine": motor,
                "device": cihaz,
                "frames": uretilen,
            },
        )
        self._yayin(
            OLAY_AKIS_DURDU,
            {
                "engine": motor,
                "device": cihaz,
                "frames": uretilen,
            },
        )
        self._log.info(
            "Video akisi durdu cihaz=%s kare=%s",
            cihaz,
            uretilen,
        )

    # ------------------------------------------------------------------ API

    def fps_ayarla(self, fps: int) -> int:
        """Akış FPS'ini ayarlar (KameraYoneticisi üzerinden)."""
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
        self.kamera.fps_ayarla(deger)
        return self.fps

    async def kare_al(self) -> Kare:
        """Tek bir kare üretir (akış bayrağını değiştirmez)."""
        if not self.kamera.calisiyor and self.kamera_yonet:
            await self.kamera.baslat()
        kare = await asyncio.to_thread(self._kare_uret)
        self._son_kare = kare
        self._uretilen += 1
        self._yayin(OLAY_AKIS_KARE, kare.to_dict())
        return kare

    async def akis(
        self,
        *,
        max_kare: Optional[int] = None,
        olay_kare: bool = True,
    ) -> AsyncIterator[Kare]:
        """
        FPS'li async kare üreteci.

        max_kare verilirse o kadar kare sonra döngü biter (test / kısa çekim).
        durdur() çağrılırsa döngü temiz çıkar.
        """
        if max_kare is not None and int(max_kare) < 0:
            raise VisionError(
                f"max_kare negatif olamaz: {max_kare}",
                kod="VIS_0103",
                modul=self.ad,
            )

        if not self._akiyor:
            await self.baslat()

        sayac = 0
        hedef = int(max_kare) if max_kare is not None else None
        aralik = 1.0 / float(self.fps)

        try:
            while self._akiyor:
                if hedef is not None and sayac >= hedef:
                    break

                t0 = time.perf_counter()
                kare = await asyncio.to_thread(self._kare_uret)
                self._son_kare = kare
                self._uretilen += 1
                sayac += 1

                if olay_kare:
                    self._yayin(OLAY_AKIS_KARE, kare.to_dict())

                yield kare

                # FPS throttle — fps_ayarla anında yansısın
                aralik = 1.0 / float(self.fps)
                gecen = time.perf_counter() - t0
                bekle = aralik - gecen
                if bekle > 0 and self._akiyor:
                    await asyncio.sleep(bekle)
        finally:
            # max_kare ile doğal bittiğinde veya iptalde akış bayrağını kapat
            if self._akiyor and hedef is not None and sayac >= hedef:
                # Kısa çekim: akış bayrağını bırak; kullanıcı durdur() çağırabilir
                pass

    def ozet(self) -> dict[str, Any]:
        """Durum özeti (wire İngilizce anahtarlar)."""
        return {
            "name": self.ad,
            "version": self.surum,
            "streaming": bool(self._akiyor),
            "engine": self.motor,
            "device": self.kamera.cihaz,
            "fps": self.fps,
            "frames": self._uretilen,
            "camera_running": bool(self.kamera.calisiyor),
            "owns_camera": bool(self._sahip_kamera),
            "manage_camera": bool(self.kamera_yonet),
            "last_frame": self._son_kare.to_dict() if self._son_kare else None,
            "dry_run": bool(getattr(self.kamera, "dry_run", False))
            or self.motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(getattr(self.kamera, "zorla_sahte", False))
            or self.motor == VisionMotoru.SAHTE.value,
        }

    # ------------------------------------------------------------------ iç

    def _kare_uret(self) -> Kare:
        """Senkron tek kare üretimi (thread'den çağrılır)."""
        motor = self.motor

        if getattr(self.kamera, "dry_run", False) or motor == VisionMotoru.DRY_RUN.value:
            return self._sentetik_kare(VisionMotoru.DRY_RUN, dry_run=True)

        if (
            getattr(self.kamera, "zorla_sahte", False)
            or motor == VisionMotoru.SAHTE.value
        ):
            return self._sentetik_kare(VisionMotoru.SAHTE, dry_run=False)

        # OpenCV — açık cap üzerinden oku
        if motor == VisionMotoru.OPENCV.value and self.kamera.cap is not None:
            return self._opencv_kare()

        # Fallback
        return self._sentetik_kare(VisionMotoru.SAHTE, dry_run=False, neden="fallback")

    def _opencv_kare(self) -> Kare:
        cap = self.kamera.cap
        if cap is None:
            return self._sentetik_kare(
                VisionMotoru.SAHTE, dry_run=False, neden="cap_yok"
            )
        try:
            ok, kare = cap.read()
            if not ok or kare is None:
                return self._sentetik_kare(
                    VisionMotoru.SAHTE, dry_run=False, neden="kare_okunamadi"
                )
            h, w = kare.shape[:2]
            # Disk yazmadan bellek içi meta; ham numpy wire'a gitmez
            return kare_olustur(
                yol=None,
                genislik=int(w),
                yukseklik=int(h),
                cihaz=self.kamera.cihaz,
                motor=VisionMotoru.OPENCV,
                dry_run=False,
                bayt_sayisi=0,
                ham=None,
            )
        except Exception as exc:  # noqa: BLE001
            self._log.debug("OpenCV kare okunamadi: %s", exc)
            return self._sentetik_kare(
                VisionMotoru.SAHTE, dry_run=False, neden=f"hata:{exc}"
            )

    def _sentetik_kare(
        self,
        motor: VisionMotoru,
        *,
        dry_run: bool,
        neden: Optional[str] = None,  # noqa: ARG002 — ileride meta için
    ) -> Kare:
        # neden şimdilik Kare modelinde yok; dry_run/sahte yolu yeterli
        ham = None if dry_run else _MINI_PNG
        return kare_olustur(
            yol=None,
            genislik=_SAHTE_GENISLIK if not dry_run else 0,
            yukseklik=_SAHTE_YUKSEKLIK if not dry_run else 0,
            cihaz=self.kamera.cihaz,
            motor=motor,
            dry_run=dry_run,
            bayt_sayisi=len(ham) if ham else 0,
            ham=ham,
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


def video_akis_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    cihaz: int = 0,
    fps: int = VARSAYILAN_FPS,
    bus: Optional[EventBus] = None,
    cv2_modul: Any = None,
    olay_yayinla: bool = False,
    kamera: Optional[KameraYoneticisi] = None,
    kamera_yonet: bool = True,
) -> VideoAkis:
    """Test / demo için güvenli varsayılanlarla VideoAkis üretir."""
    return VideoAkis(
        kamera,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        fps=fps,
        olay_yayinla=olay_yayinla,
        kamera_yonet=kamera_yonet,
        cihaz=cihaz,
        cv2_modul=cv2_modul,
    )


__all__ = [
    "OLAY_AKIS_BASLADI",
    "OLAY_AKIS_DURDU",
    "OLAY_AKIS_KARE",
    "VideoAkis",
    "video_akis_olustur",
]

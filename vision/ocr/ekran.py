"""
vision/ocr/ekran.py
-------------------
Ekran görüntüsünden OCR — tam ekran / bölge yakalama + OcrYoneticisi.

Görev:
- Ekran yakalama (Pillow ImageGrab; yoksa dry_run / sahte)
- Tam ekran veya bölge (x, y, genislik, yukseklik)
- OCR için `vision.ocr.motor.OcrYoneticisi` kullanır (yeniden yazılmaz)
- EventBus + Logger/audit + VisionError

Not: Belge/görüntü OCR → `motor.py`; PDF OCR → `pdf.py`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import Kare, OcrSonucu, VisionMotoru, kare_olustur
from vision.ocr.motor import (
    VARSAYILAN_OCR_DIL,
    OcrYoneticisi,
    ocr_yoneticisi_olustur,
)

log = logger_al("vision.ocr.ekran")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_EKRAN_YAKALANDI = "vision.ocr.screen.captured"
OLAY_EKRAN_OKUNDU = "vision.ocr.screen.read"
OLAY_EKRAN_BASLADI = "vision.ocr.screen.started"
OLAY_EKRAN_DURDU = "vision.ocr.screen.stopped"

# Sahte / dry_run için 1x1 PNG
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

_SAHTE_GENISLIK = 64
_SAHTE_YUKSEKLIK = 48

BolgeTuru = Union["EkranBolgesi", Sequence[int], None]


@dataclass
class EkranBolgesi:
    """Ekran yakalama bölgesi (sol-üst + boyut). w/h <= 0 → tam ekran."""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def tam_ekran_mi(self) -> bool:
        """w ve h sıfır (veya ikisi de sıfır) → tam ekran. Negatif boyut geçersizdir."""
        return int(self.w) == 0 and int(self.h) == 0

    def bbox(self) -> Optional[tuple[int, int, int, int]]:
        """Pillow ImageGrab bbox: (left, top, right, bottom)."""
        if self.tam_ekran_mi():
            return None
        sol = int(self.x)
        ust = int(self.y)
        return (sol, ust, sol + int(self.w), ust + int(self.h))

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": int(self.x),
            "y": int(self.y),
            "w": int(self.w),
            "h": int(self.h),
            "full": self.tam_ekran_mi(),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "EkranBolgesi":
        return cls(
            x=int(veri.get("x", 0) or 0),
            y=int(veri.get("y", 0) or 0),
            w=int(veri.get("w", 0) or 0),
            h=int(veri.get("h", 0) or 0),
        )


def bolge_coz(bolge: BolgeTuru) -> EkranBolgesi:
    """tuple/list/dict/EkranBolgesi/None → EkranBolgesi."""
    if bolge is None:
        return EkranBolgesi()
    if isinstance(bolge, EkranBolgesi):
        return bolge
    if isinstance(bolge, dict):
        return EkranBolgesi.from_dict(bolge)
    if isinstance(bolge, Sequence) and not isinstance(bolge, (str, bytes, bytearray)):
        if len(bolge) != 4:
            raise VisionError(
                f"Bolge 4 eleman bekler (x,y,w,h); alinan={len(bolge)}",
                kod="VIS_0401",
                modul="vision.ocr.screen",
            )
        return EkranBolgesi(
            x=int(bolge[0]),
            y=int(bolge[1]),
            w=int(bolge[2]),
            h=int(bolge[3]),
        )
    raise VisionError(
        f"Desteklenmeyen bolge tipi: {type(bolge)!r}",
        kod="VIS_0401",
        modul="vision.ocr.screen",
    )


def imagegrab_var_mi() -> bool:
    """Pillow ImageGrab kullanılabilir mi?"""
    try:
        from PIL import ImageGrab  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


def pillow_var_mi() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


class EkranOcr(ModulTabani):
    """
    Ekran görüntüsü OCR.

    Yakalar → Kare üretir → OcrYoneticisi ile metin okur.
    ImageGrab yoksa dry_run / sahte fallback.
    """

    ad = "vision.ocr.screen"
    surum = "0.1.0"
    aciklama = "Ekran OCR — tam ekran / bölge yakalama + OcrYoneticisi"

    def __init__(
        self,
        *,
        ocr: Optional[OcrYoneticisi] = None,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        dil: Optional[str] = None,
        on_isleme_aktif: bool = True,
        imagegrab_modul: Any = None,
        olay_yayinla: bool = True,
        ocr_yonet: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self.ocr_yonet = bool(ocr_yonet)
        self._imagegrab = imagegrab_modul
        self._sahip_ocr = ocr is None

        if ocr is not None:
            self.ocr = ocr
            # Dış OCR'ın bus'ı yoksa bizimkini kullan
            if bus is not None:
                self.bus = bus
            elif getattr(ocr, "bus", None) is not None:
                self.bus = ocr.bus
        else:
            self.ocr = ocr_yoneticisi_olustur(
                dry_run=self.dry_run,
                zorla_sahte=self.zorla_sahte,
                dil=dil or VARSAYILAN_OCR_DIL,
                on_isleme_aktif=on_isleme_aktif,
                ayarlar=self.ayarlar,
                bus=self.bus,
                olay_yayinla=False,  # ekran kendi olaylarını yayınlar
            )

        self._son_kare: Optional[Kare] = None
        self._son_sonuc: Optional[OcrSonucu] = None
        self._motor = self._motor_sec()
        self._log = logger_al(f"modul.{self.ad}")

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def son_kare(self) -> Optional[Kare]:
        return self._son_kare

    @property
    def son_sonuc(self) -> Optional[OcrSonucu]:
        return self._son_sonuc

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self._motor,
            "dry_run": bool(self.dry_run) or self._motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "imagegrab": self._imagegrab is not None or imagegrab_var_mi(),
            "ocr": self.ocr.ozet() if hasattr(self.ocr, "ozet") else None,
            "last_frame": self._son_kare.to_dict() if self._son_kare else None,
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
        if self.ocr_yonet and self._sahip_ocr and hasattr(self.ocr, "baslat"):
            try:
                await self.ocr.baslat()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("OCR baslat atlandi: %s", exc)
        self._isaret_basladi()
        self._audit(
            "vision.ocr.screen.started",
            {"engine": self._motor},
        )
        self._yayin(OLAY_EKRAN_BASLADI, {"engine": self._motor})
        self._log.info("Ekran OCR basladi motor=%s", self._motor)

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        if self.ocr_yonet and self._sahip_ocr and hasattr(self.ocr, "durdur"):
            try:
                await self.ocr.durdur()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("OCR durdur atlandi: %s", exc)
        self._isaret_durdu()
        self._audit("vision.ocr.screen.stopped", {"engine": self._motor})
        self._yayin(OLAY_EKRAN_DURDU, {"engine": self._motor})
        self._log.info("Ekran OCR durdu")

    # ------------------------------------------------------------------ API

    def yakala(self, bolge: BolgeTuru = None) -> Kare:
        """
        Ekran (veya bölge) görüntüsü yakalar → Kare.

        dry_run → boş/plan kare.
        zorla_sahte / ImageGrab yok → sahte mini PNG.
        """
        bol = bolge_coz(bolge)
        self._bolge_dogrula(bol)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            kare = kare_olustur(
                yol="screen://dry_run",
                genislik=int(bol.w) if not bol.tam_ekran_mi() else _SAHTE_GENISLIK,
                yukseklik=int(bol.h) if not bol.tam_ekran_mi() else _SAHTE_YUKSEKLIK,
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                bayt_sayisi=0,
                ham=None,
            )
            return self._kare_sonucla(kare, bol, neden="dry_run")

        if self.zorla_sahte or not self._grab_var_mi():
            neden = (
                "zorla_sahte"
                if self.zorla_sahte
                else "imagegrab_yok"
            )
            kare = kare_olustur(
                yol="screen://sahte",
                genislik=int(bol.w) if not bol.tam_ekran_mi() else _SAHTE_GENISLIK,
                yukseklik=int(bol.h) if not bol.tam_ekran_mi() else _SAHTE_YUKSEKLIK,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                bayt_sayisi=len(_MINI_PNG),
                ham=_MINI_PNG,
            )
            return self._kare_sonucla(kare, bol, neden=neden)

        try:
            ham, gw, gh = self._ekran_yakala(bol)
        except Exception as exc:  # noqa: BLE001
            # Yakalama başarısız → sahte fallback (CI / headless)
            # VIS_0401 (geçersiz bölge) yukarıda doğrulanır; burada yalnızca yakalama
            self._log.warning("Ekran yakalama basarisiz → sahte: %s", exc)
            kare = kare_olustur(
                yol="screen://sahte",
                genislik=int(bol.w) if not bol.tam_ekran_mi() else _SAHTE_GENISLIK,
                yukseklik=int(bol.h) if not bol.tam_ekran_mi() else _SAHTE_YUKSEKLIK,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                bayt_sayisi=len(_MINI_PNG),
                ham=_MINI_PNG,
            )
            return self._kare_sonucla(kare, bol, neden=f"yakalama_hata:{exc}")

        kare = kare_olustur(
            yol="screen://capture",
            genislik=gw,
            yukseklik=gh,
            motor=VisionMotoru.PILLOW,
            dry_run=False,
            bayt_sayisi=len(ham),
            ham=ham,
        )
        return self._kare_sonucla(kare, bol, neden=None)

    def oku(
        self,
        bolge: BolgeTuru = None,
        *,
        dil: Optional[str] = None,
        on_isle: Optional[bool] = None,
        sahte_metin: Optional[str] = None,
    ) -> OcrSonucu:
        """
        Ekranı yakalar ve OCR uygular.

        dry_run → OCR dry_run (yakalama atlanır / plan).
        """
        bol = bolge_coz(bolge)
        self._bolge_dogrula(bol)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            # Plan kare + dry_run OCR (dosya yolu doğrulanmaz)
            self.yakala(bol)
            ocr_dry = bool(getattr(self.ocr, "dry_run", False)) or (
                str(getattr(self.ocr, "motor", "")) == VisionMotoru.DRY_RUN.value
            )
            if ocr_dry:
                sonuc = self.ocr.oku("screen://dry_run", dil=dil, on_isle=False)
                if not sonuc.kaynak_yol:
                    sonuc.kaynak_yol = "screen://dry_run"
                if not sonuc.neden:
                    sonuc.neden = "dry_run"
            else:
                sonuc = OcrSonucu(
                    metin="",
                    dil=dil or getattr(self.ocr, "dil", VARSAYILAN_OCR_DIL),
                    kaynak_yol="screen://dry_run",
                    motor=VisionMotoru.DRY_RUN,
                    dry_run=True,
                    guven=0.0,
                    neden="dry_run",
                )
            return self._ocr_sonucla(sonuc, bol)

        kare = self.yakala(bol)

        # Sahte kare → OCR'a sahte_metin veya zorla_sahte ile git
        if kare.motor == VisionMotoru.SAHTE or kare.dry_run:
            sonuc = self.ocr.oku(
                kare if kare.ham else _MINI_PNG,
                dil=dil,
                on_isle=False,
                sahte_metin=sahte_metin
                if sahte_metin is not None
                else ("[Sahte Ekran OCR] WhiteCore test metni" if kare.motor == VisionMotoru.SAHTE else None),
            )
            if kare.motor == VisionMotoru.SAHTE and sonuc.neden in (None, "sahte_metin", "zorla_sahte"):
                # Ekran katmanı nedenini koru
                if kare.yol == "screen://sahte" and not sonuc.neden:
                    sonuc.neden = "ekran_sahte"
            if not sonuc.kaynak_yol:
                sonuc.kaynak_yol = kare.yol
            return self._ocr_sonucla(sonuc, bol)

        try:
            sonuc = self.ocr.oku(
                kare,
                dil=dil,
                on_isle=on_isle,
                sahte_metin=sahte_metin,
            )
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Ekran OCR basarisiz: {exc}",
                kod="VIS_0403",
                modul=self.ad,
            ) from exc

        if not sonuc.kaynak_yol:
            sonuc.kaynak_yol = kare.yol or "screen://capture"
        return self._ocr_sonucla(sonuc, bol)

    def metin_oku(
        self,
        bolge: BolgeTuru = None,
        *,
        dil: Optional[str] = None,
        on_isle: Optional[bool] = None,
    ) -> str:
        """Yalnızca metin döndüren kısayol."""
        return self.oku(bolge, dil=dil, on_isle=on_isle).metin

    # ------------------------------------------------------------------ iç — motor / grab

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._grab_var_mi():
            return VisionMotoru.PILLOW.value
        return VisionMotoru.SAHTE.value

    def _grab_var_mi(self) -> bool:
        if self._imagegrab is not None:
            return True
        return imagegrab_var_mi()

    def _imagegrab_coz(self) -> Any:
        if self._imagegrab is not None:
            return self._imagegrab
        try:
            from PIL import ImageGrab

            return ImageGrab
        except ImportError as exc:  # pragma: no cover
            raise VisionError(
                "Pillow ImageGrab yok; ekran yakalama yapilamaz",
                kod="VIS_0402",
                modul=self.ad,
            ) from exc

    def _bolge_dogrula(self, bol: EkranBolgesi) -> None:
        w, h = int(bol.w), int(bol.h)
        if w < 0 or h < 0:
            raise VisionError(
                f"Bolge boyutlari negatif olamaz: w={bol.w} h={bol.h}",
                kod="VIS_0401",
                modul=self.ad,
            )
        # Biri sıfır diğeri pozitif → belirsiz; ikisi sıfır = tam ekran
        if (w == 0) ^ (h == 0):
            raise VisionError(
                f"Bolge w/h birlikte sifir (tam ekran) veya ikisi de pozitif olmali: w={w} h={h}",
                kod="VIS_0401",
                modul=self.ad,
            )
        if bol.tam_ekran_mi():
            return
        bb = bol.bbox()
        if bb is not None:
            sol, ust, sag, alt = bb
            if sag <= sol or alt <= ust:
                raise VisionError(
                    f"Gecersiz bolge bbox: {bb}",
                    kod="VIS_0401",
                    modul=self.ad,
                )

    def _ekran_yakala(self, bol: EkranBolgesi) -> tuple[bytes, int, int]:
        """ImageGrab ile PNG baytları + boyut döner."""
        ig = self._imagegrab_coz()
        bbox = bol.bbox()
        try:
            if bbox is None:
                img = ig.grab()
            else:
                img = ig.grab(bbox=bbox)
        except TypeError:
            # Bazı stub'lar bbox anahtarsız bekler
            img = ig.grab(bbox) if bbox is not None else ig.grab()
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Ekran yakalanamadi: {exc}",
                kod="VIS_0402",
                modul=self.ad,
            ) from exc

        if img is None:
            raise VisionError(
                "Ekran yakalama bos sonuc dondu",
                kod="VIS_0402",
                modul=self.ad,
            )

        # Zaten bayt ise
        if isinstance(img, (bytes, bytearray)):
            ham = bytes(img)
            gw = int(bol.w) if not bol.tam_ekran_mi() else _SAHTE_GENISLIK
            gh = int(bol.h) if not bol.tam_ekran_mi() else _SAHTE_YUKSEKLIK
            return ham, gw, gh

        # PIL Image benzeri
        size = getattr(img, "size", None)
        if size and len(size) >= 2:
            gw, gh = int(size[0]), int(size[1])
        else:
            gw = int(bol.w) if not bol.tam_ekran_mi() else 0
            gh = int(bol.h) if not bol.tam_ekran_mi() else 0

        buf = io.BytesIO()
        try:
            if hasattr(img, "save"):
                img.save(buf, format="PNG")
            else:
                raise TypeError(f"Kaydedilemeyen goruntu tipi: {type(img)!r}")
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Ekran PNG yazilamadi: {exc}",
                kod="VIS_0402",
                modul=self.ad,
            ) from exc
        ham = buf.getvalue()
        if not ham:
            raise VisionError(
                "Ekran PNG bos",
                kod="VIS_0402",
                modul=self.ad,
            )
        return ham, gw, gh

    # ------------------------------------------------------------------ iç — olay

    def _kare_sonucla(
        self,
        kare: Kare,
        bol: EkranBolgesi,
        *,
        neden: Optional[str],
    ) -> Kare:
        self._son_kare = kare
        self._motor = kare.motor.value
        detay = {
            "engine": kare.motor.value,
            "dry_run": bool(kare.dry_run),
            "width": kare.genislik,
            "height": kare.yukseklik,
            "bytes": kare.bayt_sayisi,
            "region": bol.to_dict(),
            "reason": neden,
        }
        self._audit("vision.ocr.screen.captured", detay)
        veri = kare.to_dict()
        veri["region"] = bol.to_dict()
        veri["reason"] = neden
        self._yayin(OLAY_EKRAN_YAKALANDI, veri)
        self._log.debug(
            "Ekran yakalandi motor=%s %sx%s bolge=%s",
            kare.motor.value,
            kare.genislik,
            kare.yukseklik,
            bol.to_dict(),
        )
        return kare

    def _ocr_sonucla(self, sonuc: OcrSonucu, bol: EkranBolgesi) -> OcrSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        detay = {
            "engine": sonuc.motor.value,
            "lang": sonuc.dil,
            "chars": len(sonuc.metin or ""),
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "region": bol.to_dict(),
            "reason": sonuc.neden,
        }
        self._audit("vision.ocr.screen.read", detay)
        veri = sonuc.to_dict()
        veri["region"] = bol.to_dict()
        self._yayin(OLAY_EKRAN_OKUNDU, veri)
        self._log.debug(
            "Ekran OCR tamam motor=%s karakter=%s",
            sonuc.motor.value,
            len(sonuc.metin or ""),
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


def ekran_ocr_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    dil: str = VARSAYILAN_OCR_DIL,
    on_isleme_aktif: bool = True,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    imagegrab_modul: Any = None,
    ocr: Optional[OcrYoneticisi] = None,
    olay_yayinla: bool = False,
) -> EkranOcr:
    """Test / demo için güvenli varsayılanlarla EkranOcr üretir."""
    return EkranOcr(
        ocr=ocr,
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        dil=dil,
        on_isleme_aktif=on_isleme_aktif,
        imagegrab_modul=imagegrab_modul,
        olay_yayinla=olay_yayinla,
    )


def ekran_ocr_oku(
    bolge: BolgeTuru = None,
    *,
    dil: str = VARSAYILAN_OCR_DIL,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    on_isle: bool = False,
    sahte_metin: Optional[str] = None,
    imagegrab_modul: Any = None,
) -> OcrSonucu:
    """Tek çağrılık ekran OCR yardımcısı."""
    e = ekran_ocr_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        dil=dil,
        on_isleme_aktif=on_isle,
        imagegrab_modul=imagegrab_modul,
        olay_yayinla=False,
    )
    return e.oku(bolge, dil=dil, on_isle=on_isle, sahte_metin=sahte_metin)


__all__ = [
    "OLAY_EKRAN_YAKALANDI",
    "OLAY_EKRAN_OKUNDU",
    "OLAY_EKRAN_BASLADI",
    "OLAY_EKRAN_DURDU",
    "EkranBolgesi",
    "EkranOcr",
    "bolge_coz",
    "imagegrab_var_mi",
    "pillow_var_mi",
    "ekran_ocr_olustur",
    "ekran_ocr_oku",
]

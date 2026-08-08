"""
vision/ocr/motor.py
-------------------
OCR Manager — Tesseract tur+eng, belge/görüntü, skill köprüsü.

Görev:
- Görüntü/belgeden metin çıkarma (pytesseract + Tesseract)
- Türkçe + İngilizce (varsayılan `tur+eng`)
- İsteğe bağlı ön işleme (`vision.ocr.on_isleme`)
- `skills/media/ocr` köprüsü (yeniden yazılmaz; sarmalanır)
- pytesseract / Tesseract yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Ekran OCR → `ekran.py`; PDF OCR → `pdf.py`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from skills.media import ocr as skill_ocr
from vision.modeller import Kare, OcrSonucu, VisionMotoru, motor_coz
from vision.ocr.on_isleme import OnIslemeAyarlari, OcrOnIsleme, on_isleme_olustur

log = logger_al("vision.ocr.motor")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_OCR_OKUNDU = "vision.ocr.read"
OLAY_OCR_BASLADI = "vision.ocr.started"
OLAY_OCR_DURDU = "vision.ocr.stopped"

VARSAYILAN_OCR_DIL = "tur+eng"
_SAHTE_METIN = "[Sahte OCR] WhiteCore test metni"

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]


def pytesseract_var_mi() -> bool:
    return skill_ocr.pytesseract_var_mi()


def pillow_var_mi() -> bool:
    return skill_ocr.pillow_var_mi()


def _skill_motordan(engine: Optional[str]) -> VisionMotoru:
    """skills/media/ocr motor adını VisionMotoru'ya çevirir."""
    metin = str(engine or "").strip().lower()
    if metin in ("pytesseract", "tesseract"):
        return VisionMotoru.TESSERACT
    if not metin:
        return VisionMotoru.SAHTE
    return motor_coz(metin)


class OcrYoneticisi(ModulTabani):
    """
    Vision OCR Manager.

    skills/media/ocr sarmalayıcısını yeniden yazmaz; belge/görüntü okur,
    isteğe bağlı ön işleme uygular, dry_run/sahte fallback sağlar.
    """

    ad = "vision.ocr"
    surum = "0.1.0"
    aciklama = "OCR Manager — Tesseract tur+eng, ön işleme, skill köprüsü"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        dil: Optional[str] = None,
        on_isleme_aktif: bool = True,
        on_isleme: Optional[OcrOnIsleme] = None,
        on_isleme_ayarlari: Optional[OnIslemeAyarlari] = None,
        pytesseract_modul: Any = None,
        pillow_modul: Any = None,
        olay_yayinla: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self._pytesseract = pytesseract_modul
        self._pillow = pillow_modul

        cfg_dil = self.ayarlar.al("vision.ocr.lang", VARSAYILAN_OCR_DIL)
        self.dil = (dil or str(cfg_dil or VARSAYILAN_OCR_DIL)).strip() or VARSAYILAN_OCR_DIL

        # Açıkça verilen ön işleyici → kullan; aksi halde bayrak + config
        if on_isleme is not None:
            self._on_isleme = on_isleme
            self.on_isleme_aktif = True
        else:
            cfg_on = self.ayarlar.al("vision.ocr.preprocess", True)
            config_kapali = cfg_on is False or str(cfg_on).lower() in (
                "0",
                "false",
                "hayir",
                "no",
            )
            self.on_isleme_aktif = bool(on_isleme_aktif) and not config_kapali
            self._on_isleme = on_isleme_olustur(
                dry_run=self.dry_run,
                zorla_sahte=False,  # OCR sahte'si motor katmanında
                ayarlar=on_isleme_ayarlari,
            )
        self._son_sonuc: Optional[OcrSonucu] = None
        self._log = logger_al(f"modul.{self.ad}")
        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

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
            "lang": self.dil,
            "preprocess": bool(self.on_isleme_aktif),
            "pytesseract": self._pt_var_mi(),
            "pillow": self._pillow is not None or pillow_var_mi(),
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
        self._isaret_basladi()
        self._audit(
            "vision.ocr.started",
            {"engine": self._motor, "lang": self.dil},
        )
        self._yayin(
            OLAY_OCR_BASLADI,
            {"engine": self._motor, "lang": self.dil, "preprocess": self.on_isleme_aktif},
        )
        self._log.info("OCR yoneticisi basladi motor=%s dil=%s", self._motor, self.dil)

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.ocr.stopped", {"engine": self._motor})
        self._yayin(OLAY_OCR_DURDU, {"engine": self._motor})
        self._log.info("OCR yoneticisi durdu")

    # ------------------------------------------------------------------ API

    def oku(
        self,
        girdi: GirdiTuru,
        *,
        dil: Optional[str] = None,
        on_isle: Optional[bool] = None,
        on_isleme_ayarlari: Optional[OnIslemeAyarlari] = None,
        sahte_metin: Optional[str] = None,
        sayfa: Optional[int] = None,
    ) -> OcrSonucu:
        """
        Görüntü/belgeden metin okur.

        dry_run → boş metin + plan meta.
        zorla_sahte / motor yok → sahte metin.
        on_isle=True → önce `OcrOnIsleme` (OpenCV yoksa passthrough).
        """
        dil_kod = (dil or self.dil or VARSAYILAN_OCR_DIL).strip() or VARSAYILAN_OCR_DIL
        kaynak_yol = self._kaynak_yol(girdi)
        on_isle_mi = self.on_isleme_aktif if on_isle is None else bool(on_isle)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = OcrSonucu(
                metin="",
                dil=dil_kod,
                kaynak_yol=kaynak_yol,
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                guven=0.0,
                sayfa=sayfa,
                neden="dry_run",
            )
            return self._sonucla(sonuc)

        if sahte_metin is not None:
            metin = str(sahte_metin)
            sonuc = OcrSonucu(
                metin=metin,
                dil=dil_kod,
                kaynak_yol=kaynak_yol,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=0.0,
                sayfa=sayfa,
                neden="sahte_metin",
            )
            return self._sonucla(sonuc)

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value or not self._pt_var_mi():
            neden = (
                "zorla_sahte"
                if self.zorla_sahte
                else ("motor_sahte" if self._motor == VisionMotoru.SAHTE.value else "pytesseract_yok")
            )
            sonuc = OcrSonucu(
                metin=_SAHTE_METIN,
                dil=dil_kod,
                kaynak_yol=kaynak_yol,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=0.0,
                sayfa=sayfa,
                neden=neden,
            )
            return self._sonucla(sonuc)

        # İsteğe bağlı ön işleme
        ocr_girdi: GirdiTuru = girdi
        if on_isle_mi:
            try:
                on_sonuc = self._on_isleme.isle(girdi, ayarlar=on_isleme_ayarlari)
                if on_sonuc.kare is not None:
                    ocr_girdi = on_sonuc.kare
                    if on_sonuc.kaynak_yol and not kaynak_yol:
                        kaynak_yol = on_sonuc.kaynak_yol
            except VisionError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.debug("On isleme atlandi: %s", exc)

        tmp_yol: Optional[Path] = None
        try:
            yol, tmp_yol = self._yol_hazirla(ocr_girdi)
            bil = skill_ocr.ocr_oku(
                yol,
                dil=dil_kod,
                dry_run=False,
                zorla_sahte=False,
                sahte_metin=None,
                pytesseract_modul=self._pytesseract,
                pillow_modul=self._pillow,
            )
        except FileNotFoundError as exc:
            raise VisionError(
                str(exc),
                kod="VIS_0302",
                modul=self.ad,
            ) from exc
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"OCR basarisiz: {exc}",
                kod="VIS_0303",
                modul=self.ad,
            ) from exc
        finally:
            if tmp_yol is not None:
                try:
                    tmp_yol.unlink(missing_ok=True)  # type: ignore[arg-type]
                except TypeError:
                    # Python <3.8 uyumu gerekmez; yine de güvenli sil
                    try:
                        if tmp_yol.exists():
                            tmp_yol.unlink()
                    except OSError:
                        pass
                except OSError:
                    pass

        motor = _skill_motordan(bil.get("engine"))
        sonuc = OcrSonucu(
            metin=str(bil.get("text") or ""),
            dil=str(bil.get("lang") or dil_kod),
            kaynak_yol=str(bil.get("path") or kaynak_yol or ""),
            motor=motor,
            dry_run=bool(bil.get("dry_run", False)),
            guven=0.85 if motor == VisionMotoru.TESSERACT else 0.0,
            sayfa=sayfa,
            neden=bil.get("reason"),
        )
        if not sonuc.kaynak_yol:
            sonuc.kaynak_yol = kaynak_yol
        return self._sonucla(sonuc)

    def metin_oku(
        self,
        girdi: GirdiTuru,
        *,
        dil: Optional[str] = None,
        on_isle: Optional[bool] = None,
    ) -> str:
        """Yalnızca metin döndüren kısayol."""
        return self.oku(girdi, dil=dil, on_isle=on_isle).metin

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._pt_var_mi():
            return VisionMotoru.TESSERACT.value
        return VisionMotoru.SAHTE.value

    def _pt_var_mi(self) -> bool:
        if self._pytesseract is not None:
            return True
        return pytesseract_var_mi()

    # ------------------------------------------------------------------ iç — girdi

    def _kaynak_yol(self, girdi: GirdiTuru) -> Optional[str]:
        if isinstance(girdi, Kare):
            return girdi.yol
        if isinstance(girdi, Path):
            return str(girdi)
        if isinstance(girdi, str):
            return girdi
        return None

    def _yol_hazirla(self, girdi: GirdiTuru) -> tuple[str, Optional[Path]]:
        """
        skill_ocr.ocr_oku için dosya yolu üretir.
        Bayt / Kare.ham → geçici PNG; yol yoksa VisionError.
        """
        if isinstance(girdi, Kare):
            if girdi.yol and Path(girdi.yol).expanduser().is_file():
                return str(Path(girdi.yol).expanduser()), None
            if girdi.ham:
                return self._gecici_yaz(bytes(girdi.ham))
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0301",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            return self._gecici_yaz(bytes(girdi))

        if isinstance(girdi, (str, Path)):
            p = Path(girdi).expanduser()
            if not p.is_file():
                raise VisionError(
                    f"Goruntu yok: {p}",
                    kod="VIS_0302",
                    modul=self.ad,
                )
            return str(p), None

        # numpy / matris — ön işlemeden ham PNG beklenir; aksi halde desteklenmez
        raise VisionError(
            f"Desteklenmeyen OCR girdisi: {type(girdi)!r}",
            kod="VIS_0301",
            modul=self.ad,
        )

    def _gecici_yaz(self, ham: bytes) -> tuple[str, Path]:
        if not ham:
            raise VisionError(
                "Bos goruntu baytlari",
                kod="VIS_0301",
                modul=self.ad,
            )
        fd, ad = tempfile.mkstemp(prefix="whitecore_ocr_", suffix=".png")
        p = Path(ad)
        try:
            import os

            os.close(fd)
            p.write_bytes(ham)
        except Exception as exc:  # noqa: BLE001
            try:
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                pass
            raise VisionError(
                f"Gecici OCR dosyasi yazilamadi: {exc}",
                kod="VIS_0303",
                modul=self.ad,
            ) from exc
        return str(p), p

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(self, sonuc: OcrSonucu) -> OcrSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        detay = {
            "engine": sonuc.motor.value,
            "lang": sonuc.dil,
            "chars": len(sonuc.metin or ""),
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.ocr.read", detay)
        self._yayin(OLAY_OCR_OKUNDU, sonuc.to_dict())
        self._log.debug(
            "OCR tamam motor=%s dil=%s karakter=%s",
            sonuc.motor.value,
            sonuc.dil,
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


def ocr_yoneticisi_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    dil: str = VARSAYILAN_OCR_DIL,
    on_isleme_aktif: bool = True,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    pytesseract_modul: Any = None,
    pillow_modul: Any = None,
    olay_yayinla: bool = False,
) -> OcrYoneticisi:
    """Test / demo için güvenli varsayılanlarla OcrYoneticisi üretir."""
    return OcrYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        dil=dil,
        on_isleme_aktif=on_isleme_aktif,
        pytesseract_modul=pytesseract_modul,
        pillow_modul=pillow_modul,
        olay_yayinla=olay_yayinla,
    )


def ocr_oku(
    girdi: GirdiTuru,
    *,
    dil: str = VARSAYILAN_OCR_DIL,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    on_isle: bool = False,
    sahte_metin: Optional[str] = None,
    pytesseract_modul: Any = None,
    pillow_modul: Any = None,
) -> OcrSonucu:
    """Tek çağrılık OCR yardımcısı."""
    y = ocr_yoneticisi_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        dil=dil,
        on_isleme_aktif=on_isle,
        pytesseract_modul=pytesseract_modul,
        pillow_modul=pillow_modul,
        olay_yayinla=False,
    )
    return y.oku(girdi, dil=dil, on_isle=on_isle, sahte_metin=sahte_metin)


__all__ = [
    "OLAY_OCR_OKUNDU",
    "OLAY_OCR_BASLADI",
    "OLAY_OCR_DURDU",
    "VARSAYILAN_OCR_DIL",
    "OcrYoneticisi",
    "pytesseract_var_mi",
    "pillow_var_mi",
    "ocr_yoneticisi_olustur",
    "ocr_oku",
]

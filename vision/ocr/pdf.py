"""
vision/ocr/pdf.py
-----------------
PDF OCR — metin PDF + taranmış sayfa OCR.

Görev:
- Metin PDF: PyPDF2 ile sayfa metni (skills/files/pdf_okuyucu kalıbı)
- Taranmış / boş metin: pdf2image → görüntü → OcrYoneticisi (Tesseract)
- PyPDF2 / pdf2image / OCR yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Belge/görüntü OCR → `motor.py`; ekran OCR → `ekran.py`.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import OcrSonucu, VisionMotoru
from vision.ocr.motor import (
    VARSAYILAN_OCR_DIL,
    OcrYoneticisi,
    ocr_yoneticisi_olustur,
)

log = logger_al("vision.ocr.pdf")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_PDF_OKUNDU = "vision.ocr.pdf.read"
OLAY_PDF_BASLADI = "vision.ocr.pdf.started"
OLAY_PDF_DURDU = "vision.ocr.pdf.stopped"

_SAHTE_METIN = "[Sahte PDF OCR] WhiteCore test metni"
# Sayfa metni bu eşiğin altında → OCR dene (auto mod)
_METIN_ESIK = 20

PdfGirdi = Union[str, Path]


def pypdf_var_mi() -> bool:
    """PyPDF2 kullanılabilir mi?"""
    try:
        from PyPDF2 import PdfReader  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


def pdf2image_var_mi() -> bool:
    """pdf2image kullanılabilir mi?"""
    try:
        import pdf2image  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


def pillow_var_mi() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


class PdfOcr(ModulTabani):
    """
    PDF OCR Manager.

    1) Metin katmanı varsa PyPDF2 ile çıkarır.
    2) Boş / yetersiz metin → pdf2image + OcrYoneticisi.
    3) Bağımlılık yoksa dry_run / sahte.
    """

    ad = "vision.ocr.pdf"
    surum = "0.1.0"
    aciklama = "PDF OCR — metin PDF + taranmış sayfa (PyPDF2 / pdf2image / OcrYoneticisi)"

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
        pypdf_modul: Any = None,
        pdf2image_modul: Any = None,
        olay_yayinla: bool = True,
        ocr_yonet: bool = True,
        metin_esik: int = _METIN_ESIK,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self.ocr_yonet = bool(ocr_yonet)
        self.metin_esik = max(0, int(metin_esik))
        self._pypdf = pypdf_modul
        self._pdf2image = pdf2image_modul
        self._sahip_ocr = ocr is None

        cfg_dil = self.ayarlar.al("vision.ocr.lang", VARSAYILAN_OCR_DIL)
        self.dil = (dil or str(cfg_dil or VARSAYILAN_OCR_DIL)).strip() or VARSAYILAN_OCR_DIL

        if ocr is not None:
            self.ocr = ocr
            if bus is not None:
                self.bus = bus
            elif getattr(ocr, "bus", None) is not None:
                self.bus = ocr.bus
        else:
            self.ocr = ocr_yoneticisi_olustur(
                dry_run=self.dry_run,
                zorla_sahte=self.zorla_sahte,
                dil=self.dil,
                on_isleme_aktif=on_isleme_aktif,
                ayarlar=self.ayarlar,
                bus=self.bus,
                olay_yayinla=False,  # PDF kendi olaylarını yayınlar
            )

        self._son_sonuc: Optional[OcrSonucu] = None
        self._son_sayfa_sayisi: int = 0
        self._motor = self._motor_sec()
        self._log = logger_al(f"modul.{self.ad}")

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def son_sonuc(self) -> Optional[OcrSonucu]:
        return self._son_sonuc

    @property
    def son_sayfa_sayisi(self) -> int:
        return self._son_sayfa_sayisi

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self._motor,
            "dry_run": bool(self.dry_run) or self._motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "lang": self.dil,
            "pypdf": self._pypdf is not None or pypdf_var_mi(),
            "pdf2image": self._pdf2image is not None or pdf2image_var_mi(),
            "pillow": pillow_var_mi(),
            "ocr": self.ocr.ozet() if hasattr(self.ocr, "ozet") else None,
            "pages_last": self._son_sayfa_sayisi,
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
            "vision.ocr.pdf.started",
            {"engine": self._motor, "lang": self.dil},
        )
        self._yayin(
            OLAY_PDF_BASLADI,
            {"engine": self._motor, "lang": self.dil},
        )
        self._log.info("PDF OCR basladi motor=%s dil=%s", self._motor, self.dil)

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        if self.ocr_yonet and self._sahip_ocr and hasattr(self.ocr, "durdur"):
            try:
                await self.ocr.durdur()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("OCR durdur atlandi: %s", exc)
        self._isaret_durdu()
        self._audit("vision.ocr.pdf.stopped", {"engine": self._motor})
        self._yayin(OLAY_PDF_DURDU, {"engine": self._motor})
        self._log.info("PDF OCR durdu")

    # ------------------------------------------------------------------ API

    def oku(
        self,
        yol: PdfGirdi,
        *,
        dil: Optional[str] = None,
        sayfa: Optional[int] = None,
        max_sayfa: Optional[int] = None,
        mod: str = "auto",
        on_isle: Optional[bool] = None,
        sahte_metin: Optional[str] = None,
        dpi: int = 200,
    ) -> OcrSonucu:
        """
        PDF'den metin okur.

        mod:
          - ``auto``  → önce metin katmanı; yetersizse OCR
          - ``metin`` → yalnızca PyPDF2
          - ``ocr``   → yalnızca pdf2image + OcrYoneticisi

        sayfa: 1 tabanlı sayfa numarası (yalnızca o sayfa).
        max_sayfa: okunacak üst sınır (1. sayfadan itibaren).
        """
        dil_kod = (dil or self.dil or VARSAYILAN_OCR_DIL).strip() or VARSAYILAN_OCR_DIL
        mod_kod = (mod or "auto").strip().lower()
        if mod_kod not in ("auto", "metin", "ocr", "text"):
            raise VisionError(
                f"Gecersiz PDF OCR modu: {mod!r} (auto|metin|ocr)",
                kod="VIS_0501",
                modul=self.ad,
            )
        if mod_kod == "text":
            mod_kod = "metin"

        p = self._yol_coz(yol)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = OcrSonucu(
                metin="",
                dil=dil_kod,
                kaynak_yol=str(p),
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                guven=0.0,
                sayfa=sayfa,
                neden="dry_run",
            )
            self._son_sayfa_sayisi = 0
            return self._sonucla(sonuc, sayfa_sayisi=0, mod=mod_kod)

        if sahte_metin is not None:
            sonuc = OcrSonucu(
                metin=str(sahte_metin),
                dil=dil_kod,
                kaynak_yol=str(p),
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=0.0,
                sayfa=sayfa,
                neden="sahte_metin",
            )
            self._son_sayfa_sayisi = 1
            return self._sonucla(sonuc, sayfa_sayisi=1, mod=mod_kod)

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            # Dosya yoksa yine de doğrula (zorla_sahte hariç dry_run'da yol opsiyonel)
            if not self.zorla_sahte:
                self._yol_dogrula(p)
            sonuc = OcrSonucu(
                metin=_SAHTE_METIN,
                dil=dil_kod,
                kaynak_yol=str(p),
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=0.0,
                sayfa=sayfa,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            self._son_sayfa_sayisi = 1
            return self._sonucla(sonuc, sayfa_sayisi=1, mod=mod_kod)

        self._yol_dogrula(p)

        try:
            if mod_kod == "metin":
                sonuc = self._metin_oku(
                    p, dil=dil_kod, sayfa=sayfa, max_sayfa=max_sayfa
                )
            elif mod_kod == "ocr":
                sonuc = self._ocr_oku(
                    p,
                    dil=dil_kod,
                    sayfa=sayfa,
                    max_sayfa=max_sayfa,
                    on_isle=on_isle,
                    dpi=dpi,
                )
            else:
                # auto: metin dene → yetersizse OCR
                sonuc = self._auto_oku(
                    p,
                    dil=dil_kod,
                    sayfa=sayfa,
                    max_sayfa=max_sayfa,
                    on_isle=on_isle,
                    dpi=dpi,
                )
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"PDF OCR basarisiz: {exc}",
                kod="VIS_0503",
                modul=self.ad,
            ) from exc

        return self._sonucla(
            sonuc,
            sayfa_sayisi=self._son_sayfa_sayisi,
            mod=mod_kod,
        )

    def metin_oku(
        self,
        yol: PdfGirdi,
        *,
        dil: Optional[str] = None,
        sayfa: Optional[int] = None,
        max_sayfa: Optional[int] = None,
        mod: str = "auto",
    ) -> str:
        """Yalnızca metin döndüren kısayol."""
        return self.oku(
            yol, dil=dil, sayfa=sayfa, max_sayfa=max_sayfa, mod=mod
        ).metin

    # ------------------------------------------------------------------ iç — okuma

    def _auto_oku(
        self,
        p: Path,
        *,
        dil: str,
        sayfa: Optional[int],
        max_sayfa: Optional[int],
        on_isle: Optional[bool],
        dpi: int,
    ) -> OcrSonucu:
        """Önce metin; yetersiz / PyPDF yok → OCR; o da yok → sahte."""
        metin_sonuc: Optional[OcrSonucu] = None
        if self._pypdf_var_mi():
            try:
                metin_sonuc = self._metin_oku(
                    p, dil=dil, sayfa=sayfa, max_sayfa=max_sayfa
                )
            except VisionError as exc:
                # PyPDF bozuk / desteklenmiyor → OCR'a düş
                if exc.kod == "VIS_0502":
                    raise
                self._log.debug("Metin PDF atlandi: %s", exc)
                metin_sonuc = None

        if metin_sonuc is not None:
            temiz = (metin_sonuc.metin or "").strip()
            if len(temiz) >= self.metin_esik:
                return metin_sonuc
            self._log.debug(
                "Metin yetersiz (%s < %s) → OCR denenecek",
                len(temiz),
                self.metin_esik,
            )

        if self._pdf2image_var_mi():
            return self._ocr_oku(
                p,
                dil=dil,
                sayfa=sayfa,
                max_sayfa=max_sayfa,
                on_isle=on_isle,
                dpi=dpi,
            )

        # Ne metin ne OCR — sahte veya zayıf metin sonucu
        if metin_sonuc is not None and (metin_sonuc.metin or "").strip():
            metin_sonuc.neden = metin_sonuc.neden or "metin_zayif_pdf2image_yok"
            return metin_sonuc

        sonuc = OcrSonucu(
            metin=_SAHTE_METIN,
            dil=dil,
            kaynak_yol=str(p),
            motor=VisionMotoru.SAHTE,
            dry_run=False,
            guven=0.0,
            sayfa=sayfa,
            neden="pdf2image_yok" if not self._pypdf_var_mi() else "metin_yok_pdf2image_yok",
        )
        self._son_sayfa_sayisi = max(self._son_sayfa_sayisi, 1)
        return sonuc

    def _metin_oku(
        self,
        p: Path,
        *,
        dil: str,
        sayfa: Optional[int],
        max_sayfa: Optional[int],
    ) -> OcrSonucu:
        """PyPDF2 ile metin katmanı çıkarır."""
        if not self._pypdf_var_mi():
            raise VisionError(
                "PyPDF2 yok; metin PDF okunamaz",
                kod="VIS_0502",
                modul=self.ad,
            )

        PdfReader = self._pypdf_coz()
        try:
            okuyucu = PdfReader(str(p))
            toplam = len(okuyucu.pages)
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"PDF acilamadi: {exc}",
                kod="VIS_0503",
                modul=self.ad,
            ) from exc

        if toplam <= 0:
            raise VisionError(
                "PDF sayfa icermiyor",
                kod="VIS_0501",
                modul=self.ad,
            )

        indeksler = self._sayfa_indeksleri(toplam, sayfa=sayfa, max_sayfa=max_sayfa)
        sayfalar: list[str] = []
        for i in indeksler:
            try:
                sayfalar.append(okuyucu.pages[i].extract_text() or "")
            except Exception:  # noqa: BLE001
                sayfalar.append("")

        metin = "\n\n".join(sayfalar).strip()
        self._son_sayfa_sayisi = toplam
        tek_sayfa = sayfa if sayfa is not None else (indeksler[0] + 1 if len(indeksler) == 1 else None)

        return OcrSonucu(
            metin=metin,
            dil=dil,
            kaynak_yol=str(p),
            motor=VisionMotoru.YEREL,  # PyPDF2 yerel metin
            dry_run=False,
            guven=0.9 if metin else 0.0,
            sayfa=tek_sayfa,
            neden="pypdf",
        )

    def _ocr_oku(
        self,
        p: Path,
        *,
        dil: str,
        sayfa: Optional[int],
        max_sayfa: Optional[int],
        on_isle: Optional[bool],
        dpi: int,
    ) -> OcrSonucu:
        """pdf2image ile sayfa görüntüsü → OcrYoneticisi."""
        if not self._pdf2image_var_mi():
            # OCR zorunlu ama pdf2image yok → sahte
            self._son_sayfa_sayisi = 1
            return OcrSonucu(
                metin=_SAHTE_METIN,
                dil=dil,
                kaynak_yol=str(p),
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=0.0,
                sayfa=sayfa,
                neden="pdf2image_yok",
            )

        convert = self._pdf2image_coz()
        # Önce toplam sayfa (PyPDF varsa); yoksa convert tümünü alıp kırp
        toplam: Optional[int] = None
        if self._pypdf_var_mi():
            try:
                PdfReader = self._pypdf_coz()
                toplam = len(PdfReader(str(p)).pages)
            except Exception:  # noqa: BLE001
                toplam = None

        first, last = self._convert_aralik(toplam, sayfa=sayfa, max_sayfa=max_sayfa)

        tmp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
        try:
            tmp_dir = tempfile.TemporaryDirectory(prefix="whitecore_pdf_ocr_")
            kwargs: dict[str, Any] = {
                "dpi": int(dpi) if dpi else 200,
                "fmt": "png",
                "output_folder": tmp_dir.name,
            }
            if first is not None:
                kwargs["first_page"] = first
            if last is not None:
                kwargs["last_page"] = last

            try:
                imgeler = convert(str(p), **kwargs)
            except TypeError:
                # Stub / sade imza
                imgeler = convert(str(p))
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"PDF sayfa goruntusu uretilemedi: {exc}",
                kod="VIS_0503",
                modul=self.ad,
            ) from exc

        if not imgeler:
            if tmp_dir is not None:
                try:
                    tmp_dir.cleanup()
                except Exception:  # noqa: BLE001
                    pass
            raise VisionError(
                "PDF'den goruntu uretilemedi (bos)",
                kod="VIS_0503",
                modul=self.ad,
            )

        if toplam is None:
            toplam = len(imgeler)
            if first is not None and last is not None:
                # Kısmi convert — toplam bilinmiyor
                self._son_sayfa_sayisi = last
            else:
                self._son_sayfa_sayisi = len(imgeler)
        else:
            self._son_sayfa_sayisi = toplam

        metinler: list[str] = []
        son_ocr: Optional[OcrSonucu] = None
        baslangic_sayfa = first or 1

        try:
            for idx, img in enumerate(imgeler):
                sayfa_no = baslangic_sayfa + idx
                ham = self._img_png_bayt(img)
                try:
                    son_ocr = self.ocr.oku(
                        ham,
                        dil=dil,
                        on_isle=on_isle,
                        sayfa=sayfa_no,
                    )
                except VisionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise VisionError(
                        f"PDF sayfa OCR basarisiz (sayfa={sayfa_no}): {exc}",
                        kod="VIS_0503",
                        modul=self.ad,
                    ) from exc
                metinler.append((son_ocr.metin or "").strip())
        finally:
            if tmp_dir is not None:
                try:
                    tmp_dir.cleanup()
                except Exception:  # noqa: BLE001
                    pass

        birlesik = "\n\n".join(m for m in metinler if m).strip()
        motor = (
            son_ocr.motor
            if son_ocr is not None
            else VisionMotoru.TESSERACT
        )
        # OCR dry_run/sahte motorunu koru
        if son_ocr is not None and son_ocr.dry_run:
            motor = VisionMotoru.DRY_RUN
        elif son_ocr is not None and son_ocr.motor == VisionMotoru.SAHTE:
            motor = VisionMotoru.SAHTE

        tek_sayfa = sayfa if sayfa is not None else (
            baslangic_sayfa if len(imgeler) == 1 else None
        )
        return OcrSonucu(
            metin=birlesik,
            dil=dil,
            kaynak_yol=str(p),
            motor=motor,
            dry_run=bool(son_ocr.dry_run) if son_ocr else False,
            guven=float(son_ocr.guven) if son_ocr else 0.0,
            sayfa=tek_sayfa,
            neden="pdf2image+ocr",
        )

    # ------------------------------------------------------------------ iç — yardımcılar

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._pypdf_var_mi() or self._pdf2image_var_mi():
            # Yerel PDF yolu mevcut
            return VisionMotoru.YEREL.value
        return VisionMotoru.SAHTE.value

    def _pypdf_var_mi(self) -> bool:
        if self._pypdf is not None:
            return True
        return pypdf_var_mi()

    def _pdf2image_var_mi(self) -> bool:
        if self._pdf2image is not None:
            return True
        return pdf2image_var_mi()

    def _pypdf_coz(self) -> Any:
        if self._pypdf is not None:
            # Doğrudan PdfReader sınıfı veya modül
            if hasattr(self._pypdf, "PdfReader"):
                return self._pypdf.PdfReader
            return self._pypdf
        try:
            from PyPDF2 import PdfReader

            return PdfReader
        except ImportError as exc:  # pragma: no cover
            raise VisionError(
                "PyPDF2 yok; PDF metin okunamaz",
                kod="VIS_0502",
                modul=self.ad,
            ) from exc

    def _pdf2image_coz(self) -> Any:
        if self._pdf2image is not None:
            if callable(self._pdf2image):
                return self._pdf2image
            if hasattr(self._pdf2image, "convert_from_path"):
                return self._pdf2image.convert_from_path
            raise VisionError(
                "pdf2image_modul convert_from_path veya callable olmali",
                kod="VIS_0502",
                modul=self.ad,
            )
        try:
            from pdf2image import convert_from_path

            return convert_from_path
        except ImportError as exc:  # pragma: no cover
            raise VisionError(
                "pdf2image yok; taranmis PDF OCR yapilamaz",
                kod="VIS_0502",
                modul=self.ad,
            ) from exc

    def _yol_coz(self, yol: PdfGirdi) -> Path:
        if isinstance(yol, Path):
            return yol.expanduser()
        if isinstance(yol, str):
            return Path(yol).expanduser()
        raise VisionError(
            f"Desteklenmeyen PDF yolu tipi: {type(yol)!r}",
            kod="VIS_0501",
            modul=self.ad,
        )

    def _yol_dogrula(self, p: Path) -> None:
        if not p.is_file():
            raise VisionError(
                f"PDF yok: {p}",
                kod="VIS_0502",
                modul=self.ad,
            )
        if p.suffix.lower() != ".pdf":
            # Uzantı uyarısı — yine de dene; tamamen reddetmek yerine log
            self._log.debug("PDF uzantisi beklenmiyor: %s", p.suffix)

    def _sayfa_indeksleri(
        self,
        toplam: int,
        *,
        sayfa: Optional[int],
        max_sayfa: Optional[int],
    ) -> list[int]:
        """1 tabanlı sayfa → 0 tabanlı indeks listesi."""
        if sayfa is not None:
            no = int(sayfa)
            if no < 1 or no > toplam:
                raise VisionError(
                    f"Sayfa aralik disi: {no} (1..{toplam})",
                    kod="VIS_0501",
                    modul=self.ad,
                )
            return [no - 1]

        limit = toplam if max_sayfa is None else min(toplam, max(1, int(max_sayfa)))
        return list(range(limit))

    def _convert_aralik(
        self,
        toplam: Optional[int],
        *,
        sayfa: Optional[int],
        max_sayfa: Optional[int],
    ) -> tuple[Optional[int], Optional[int]]:
        """pdf2image first_page / last_page (1 tabanlı)."""
        if sayfa is not None:
            no = int(sayfa)
            if no < 1:
                raise VisionError(
                    f"Sayfa numarasi 1+ olmali: {no}",
                    kod="VIS_0501",
                    modul=self.ad,
                )
            if toplam is not None and no > toplam:
                raise VisionError(
                    f"Sayfa aralik disi: {no} (1..{toplam})",
                    kod="VIS_0501",
                    modul=self.ad,
                )
            return no, no

        if max_sayfa is not None:
            last = max(1, int(max_sayfa))
            if toplam is not None:
                last = min(last, toplam)
            return 1, last

        return None, None

    def _img_png_bayt(self, img: Any) -> bytes:
        """PIL Image / bayt → PNG baytları."""
        if isinstance(img, (bytes, bytearray)):
            return bytes(img)
        if isinstance(img, Path):
            return img.read_bytes()
        if isinstance(img, str) and Path(img).is_file():
            return Path(img).read_bytes()

        buf = io.BytesIO()
        try:
            if hasattr(img, "save"):
                img.save(buf, format="PNG")
            else:
                raise TypeError(f"Kaydedilemeyen goruntu tipi: {type(img)!r}")
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"PDF sayfa PNG yazilamadi: {exc}",
                kod="VIS_0503",
                modul=self.ad,
            ) from exc
        ham = buf.getvalue()
        if not ham:
            raise VisionError(
                "PDF sayfa PNG bos",
                kod="VIS_0503",
                modul=self.ad,
            )
        return ham

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(
        self,
        sonuc: OcrSonucu,
        *,
        sayfa_sayisi: int,
        mod: str,
    ) -> OcrSonucu:
        self._son_sonuc = sonuc
        self._son_sayfa_sayisi = int(sayfa_sayisi)
        self._motor = sonuc.motor.value
        detay = {
            "engine": sonuc.motor.value,
            "lang": sonuc.dil,
            "chars": len(sonuc.metin or ""),
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "page": sonuc.sayfa,
            "pages": self._son_sayfa_sayisi,
            "mode": mod,
            "reason": sonuc.neden,
        }
        self._audit("vision.ocr.pdf.read", detay)
        veri = sonuc.to_dict()
        veri["pages"] = self._son_sayfa_sayisi
        veri["mode"] = mod
        self._yayin(OLAY_PDF_OKUNDU, veri)
        self._log.debug(
            "PDF OCR tamam motor=%s karakter=%s sayfa=%s",
            sonuc.motor.value,
            len(sonuc.metin or ""),
            self._son_sayfa_sayisi,
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


def pdf_ocr_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    dil: str = VARSAYILAN_OCR_DIL,
    on_isleme_aktif: bool = True,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    pypdf_modul: Any = None,
    pdf2image_modul: Any = None,
    ocr: Optional[OcrYoneticisi] = None,
    olay_yayinla: bool = False,
) -> PdfOcr:
    """Test / demo için güvenli varsayılanlarla PdfOcr üretir."""
    return PdfOcr(
        ocr=ocr,
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        dil=dil,
        on_isleme_aktif=on_isleme_aktif,
        pypdf_modul=pypdf_modul,
        pdf2image_modul=pdf2image_modul,
        olay_yayinla=olay_yayinla,
    )


def pdf_ocr_oku(
    yol: PdfGirdi,
    *,
    dil: str = VARSAYILAN_OCR_DIL,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sayfa: Optional[int] = None,
    max_sayfa: Optional[int] = None,
    mod: str = "auto",
    on_isle: bool = False,
    sahte_metin: Optional[str] = None,
    pypdf_modul: Any = None,
    pdf2image_modul: Any = None,
) -> OcrSonucu:
    """Tek çağrılık PDF OCR yardımcısı."""
    p = pdf_ocr_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        dil=dil,
        on_isleme_aktif=on_isle,
        pypdf_modul=pypdf_modul,
        pdf2image_modul=pdf2image_modul,
        olay_yayinla=False,
    )
    return p.oku(
        yol,
        dil=dil,
        sayfa=sayfa,
        max_sayfa=max_sayfa,
        mod=mod,
        on_isle=on_isle,
        sahte_metin=sahte_metin,
    )


__all__ = [
    "OLAY_PDF_OKUNDU",
    "OLAY_PDF_BASLADI",
    "OLAY_PDF_DURDU",
    "PdfOcr",
    "pypdf_var_mi",
    "pdf2image_var_mi",
    "pillow_var_mi",
    "pdf_ocr_olustur",
    "pdf_ocr_oku",
]

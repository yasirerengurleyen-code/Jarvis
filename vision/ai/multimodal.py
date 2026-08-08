"""
vision/ai/multimodal.py
-----------------------
Metin + görsel birlikte analiz — Vision AI, dry_run / sahte / bileşim fallback.

Görev:
- Kullanıcı metni + görüntü → birleşik analiz (`VisionAiSonucu.ek_metin` / `.cevap`)
- Enjekte edilebilir analyzer (LLM / özel motor testleri)
- LLM yoksa: aciklama + OCR + sayma sonuçlarını birleştir (compose)
- OpenCV / OCR / bağımlılık yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Caption → `aciklama.py`; VQA → `soru_cevap.py`; sayma → `sayma.py`.
      Orkestrasyon → `vision/yoneticisi.py` (sonraki onaylı dosya).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    Kare,
    VisionAiSonucu,
    VisionGorevTuru,
    VisionMotoru,
    guven_sinirla,
)

log = logger_al("vision.ai.multimodal")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_MULTIMODAL = "vision.ai.multimodal.done"
OLAY_MULTIMODAL_BASLADI = "vision.ai.multimodal.started"
OLAY_MULTIMODAL_DURDU = "vision.ai.multimodal.stopped"

# Sahte / dry_run için örnek birleşik yanıt (CI / offline)
_SAHTE_CEVAP = (
    "Metin ve görüntü birlikte değerlendirildi: masaüstü çalışma alanı; "
    "ekran ve nesneler görünüyor. Kullanıcı metniyle uyumlu özet."
)

VARSAYILAN_GUVEN_SAHTE = 0.55
VARSAYILAN_GUVEN_COMPOSE = 0.62
VARSAYILAN_GUVEN_LLM = 0.80
VARSAYILAN_MIN_GUVEN = 0.25

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# analyzer(mat | bytes | yol, metin) → str | dict | VisionAiSonucu
AnalyzerTuru = Callable[[Any, str], Any]

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


def _metin_temizle(metin: Optional[str]) -> str:
    """Kullanıcı metnini doğrula / temizle; boşsa VisionError."""
    t = str(metin or "").strip()
    if not t:
        raise VisionError(
            "Multimodal metin bos olamaz",
            kod="VIS_0834",
            modul="vision.ai.multimodal",
        )
    return t


def _sonuc_normalize(
    ham: Any,
) -> tuple[str, float, Optional[str], Optional[int], Optional[str]]:
    """
    str / dict / VisionAiSonucu → (cevap, güven, motor, sayim, sayim_etiket).

    dict anahtarları: answer / cevap / analysis / description / text;
    isteğe bağlı confidence / engine / count.
    """
    if ham is None:
        return "", 0.0, None, None, None
    if isinstance(ham, VisionAiSonucu):
        metin = str(ham.cevap or ham.aciklama or "").strip()
        return (
            metin,
            guven_sinirla(ham.guven),
            ham.motor.value if ham.motor else None,
            ham.sayim,
            ham.sayim_etiket,
        )
    if isinstance(ham, str):
        return ham.strip(), 0.0, None, None, None
    if isinstance(ham, dict):
        metin = ""
        for anahtar in (
            "answer",
            "cevap",
            "analysis",
            "analiz",
            "description",
            "aciklama",
            "text",
            "response",
            "yanit",
        ):
            deger = ham.get(anahtar)
            if deger is not None and str(deger).strip():
                metin = str(deger).strip()
                break
        guven = guven_sinirla(ham.get("confidence"))
        motor = ham.get("engine") or ham.get("motor")
        sayim = None
        for anahtar in ("count", "sayim", "n", "adet"):
            if ham.get(anahtar) is not None:
                try:
                    sayim = max(0, int(ham[anahtar]))
                except (TypeError, ValueError):
                    sayim = None
                break
        etiket = None
        for anahtar in ("count_label", "sayim_etiket", "etiket", "label"):
            deger = ham.get(anahtar)
            if deger is not None and str(deger).strip():
                etiket = str(deger).strip()
                break
        return metin, guven, str(motor) if motor else None, sayim, etiket
    return str(ham).strip(), 0.0, None, None, None


def _sahte_yanit(kullanici_metni: str, sahte: str) -> str:
    """Kullanıcı metnini sahte özetle birleştir."""
    baz = (sahte or _SAHTE_CEVAP).strip()
    return f"{baz} Kullanıcı metni: {kullanici_metni}"


class MultimodalAnaliz(ModulTabani):
    """
    Vision AI — metin + görsel birlikte analiz (multimodal).

    1) dry_run → boş cevap + plan meta (ek_metin saklanır)
    2) zorla_sahte / motor yok → sahte birleşik yanıt
    3) Enjekte analyzer → LLM / özel motor
    4) compose=True → aciklama + OCR + sayma bileşim
    5) Aksi halde sahte
    """

    ad = "vision.ai.multimodal"
    surum = "0.1.0"
    aciklama = "Metin + görsel birlikte analiz — dry_run / sahte / compose"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        analyzer: Optional[AnalyzerTuru] = None,
        compose: bool = True,
        caption_kullan: bool = True,
        ocr_kullan: bool = True,
        sayma_kullan: bool = True,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
        olay_yayinla: bool = True,
        varsayilan_sahte: str = _SAHTE_CEVAP,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.compose = bool(compose)
        self.caption_kullan = bool(caption_kullan)
        self.ocr_kullan = bool(ocr_kullan)
        self.sayma_kullan = bool(sayma_kullan)
        self.olay_yayinla = bool(olay_yayinla)
        self._analyzer = analyzer
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np
        self.varsayilan_sahte = str(varsayilan_sahte or _SAHTE_CEVAP)

        cfg = self.ayarlar.al("vision.ai.multimodal_fake", None)
        if cfg and not zorla_sahte:
            self.varsayilan_sahte = str(cfg)

        self._son_sonuc: Optional[VisionAiSonucu] = None
        self._log = logger_al(f"modul.{self.ad}")
        self._motor = self._motor_sec()
        self._backend = self._backend_sec()

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def backend(self) -> str:
        """injected | compose | sahte | dry_run."""
        return self._backend

    @property
    def son_sonuc(self) -> Optional[VisionAiSonucu]:
        return self._son_sonuc

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self._motor,
            "backend": self._backend,
            "dry_run": bool(self.dry_run) or self._motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "opencv": self._cv2 is not None or opencv_var_mi(),
            "numpy": self._np is not None or numpy_var_mi(),
            "injected": self._analyzer is not None,
            "compose": bool(self.compose),
            "use_caption": bool(self.caption_kullan),
            "use_ocr": bool(self.ocr_kullan),
            "use_count": bool(self.sayma_kullan),
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
            "vision.ai.multimodal.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_MULTIMODAL_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "Multimodal analiz basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.ai.multimodal.stopped", {"engine": self._motor})
        self._yayin(OLAY_MULTIMODAL_DURDU, {"engine": self._motor})
        self._log.info("Multimodal analiz durdu")

    # ------------------------------------------------------------------ API

    def analiz(
        self,
        girdi: GirdiTuru,
        metin: str,
        *,
        sahte_cevap: Optional[str] = None,
        dil: str = "tr",
        sayim_etiket: Optional[str] = None,
    ) -> VisionAiSonucu:
        """
        Metin + görüntü → birleşik multimodal sonuç (`VisionAiSonucu`).

        dry_run → boş cevap (ek_metin saklanır).
        zorla_sahte / motor yok → sahte yanıt.
        """
        _ = dil  # gelecek dil seçimi; şimdilik Türkçe
        metin_temiz = _metin_temizle(metin)
        kaynak_yol = self._kaynak_yol(girdi)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = VisionAiSonucu(
                gorev=VisionGorevTuru.AI,
                ek_metin=metin_temiz,
                soru=metin_temiz,
                cevap="",
                aciklama="",
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                guven=0.0,
                kaynak_yol=kaynak_yol,
                neden="dry_run",
            )
            return self._sonucla(sonuc, backend="dry_run")

        if self.zorla_sahte or (
            self._motor == VisionMotoru.SAHTE.value
            and self._analyzer is None
            and not self._compose_kullanilabilir()
        ):
            cevap = _sahte_yanit(
                metin_temiz,
                sahte_cevap if sahte_cevap is not None else self.varsayilan_sahte,
            )
            sonuc = VisionAiSonucu(
                gorev=VisionGorevTuru.AI,
                ek_metin=metin_temiz,
                soru=metin_temiz,
                cevap=cevap,
                aciklama=cevap,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=VARSAYILAN_GUVEN_SAHTE,
                kaynak_yol=kaynak_yol,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            return self._sonucla(sonuc, backend="sahte")

        # Enjekte analyzer (LLM / mock)
        if self._analyzer is not None:
            try:
                yuk = self._yukle_hafif(girdi)
                ham = self._analyzer(yuk, metin_temiz)
                cevap, guven, motor_ipu, sayim, etiket = _sonuc_normalize(ham)
                if not cevap:
                    raise VisionError(
                        "Analyzer bos cevap dondurdu",
                        kod="VIS_0833",
                        modul=self.ad,
                    )
                if guven <= 0.0:
                    guven = VARSAYILAN_GUVEN_LLM
                motor = VisionMotoru.LLM
                if motor_ipu:
                    try:
                        from vision.modeller import motor_coz

                        motor = motor_coz(motor_ipu)
                    except VisionError:
                        motor = VisionMotoru.LLM
                sonuc = VisionAiSonucu(
                    gorev=VisionGorevTuru.AI,
                    ek_metin=metin_temiz,
                    soru=metin_temiz,
                    cevap=cevap,
                    aciklama=cevap,
                    sayim=sayim,
                    sayim_etiket=etiket or sayim_etiket,
                    motor=motor,
                    dry_run=False,
                    guven=guven,
                    kaynak_yol=kaynak_yol,
                    neden="injected",
                )
                return self._sonucla(sonuc, backend="injected")
            except VisionError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Analyzer basarisiz → fallback: %s", exc)
                # aşağıda compose / sahte

        # Bileşim: caption + OCR + sayma
        if self.compose and self._compose_kullanilabilir():
            try:
                cevap, sayim, etiket, neden = self._compose_analiz(
                    girdi,
                    metin_temiz,
                    sayim_etiket=sayim_etiket,
                )
                if cevap:
                    sonuc = VisionAiSonucu(
                        gorev=VisionGorevTuru.AI,
                        ek_metin=metin_temiz,
                        soru=metin_temiz,
                        cevap=cevap,
                        aciklama=cevap,
                        sayim=sayim,
                        sayim_etiket=etiket,
                        motor=VisionMotoru.OPENCV,
                        dry_run=False,
                        guven=VARSAYILAN_GUVEN_COMPOSE,
                        kaynak_yol=kaynak_yol,
                        neden=neden,
                    )
                    return self._sonucla(sonuc, backend="compose")
            except VisionError as exc:
                # Compose alt motor boş → sahte; diğer VisionError yukarı
                if getattr(exc, "kod", None) == "VIS_0833":
                    self._log.warning("Compose multimodal basarisiz → sahte: %s", exc)
                else:
                    raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Compose multimodal basarisiz → sahte: %s", exc)

        # Son çare: sahte
        cevap = _sahte_yanit(
            metin_temiz,
            sahte_cevap if sahte_cevap is not None else self.varsayilan_sahte,
        )
        sonuc = VisionAiSonucu(
            gorev=VisionGorevTuru.AI,
            ek_metin=metin_temiz,
            soru=metin_temiz,
            cevap=cevap,
            aciklama=cevap,
            motor=VisionMotoru.SAHTE,
            dry_run=False,
            guven=VARSAYILAN_GUVEN_SAHTE,
            kaynak_yol=kaynak_yol,
            neden="fallback_sahte",
        )
        return self._sonucla(sonuc, backend="sahte")

    def yanitla(
        self,
        girdi: GirdiTuru,
        metin: str,
        *,
        sahte_cevap: Optional[str] = None,
        dil: str = "tr",
        sayim_etiket: Optional[str] = None,
    ) -> str:
        """Yalnızca cevap metni döndüren kısayol."""
        return (
            self.analiz(
                girdi,
                metin,
                sahte_cevap=sahte_cevap,
                dil=dil,
                sayim_etiket=sayim_etiket,
            ).cevap
            or ""
        )

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._analyzer is not None:
            return VisionMotoru.LLM.value
        if self.compose and self._compose_kullanilabilir():
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _backend_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._analyzer is not None:
            return "injected"
        if self.compose and self._compose_kullanilabilir():
            return "compose"
        return "sahte"

    def _compose_kullanilabilir(self) -> bool:
        """Bileşim için en az bir alt motor kullanılabilir mi?"""
        if not self.compose:
            return False
        if self.caption_kullan:
            try:
                from vision.ai import aciklama as _a  # noqa: F401

                return True
            except ImportError:  # pragma: no cover
                pass
        if self.ocr_kullan:
            try:
                from vision.ocr import motor as _o  # noqa: F401

                return True
            except ImportError:  # pragma: no cover
                pass
        if self.sayma_kullan:
            try:
                from vision.ai import sayma as _s  # noqa: F401

                return True
            except ImportError:  # pragma: no cover
                pass
        return False

    # ------------------------------------------------------------------ iç — girdi

    def _kaynak_yol(self, girdi: GirdiTuru) -> Optional[str]:
        if isinstance(girdi, Kare):
            return girdi.yol
        if isinstance(girdi, Path):
            return str(girdi)
        if isinstance(girdi, str):
            return girdi
        return None

    def _yukle_hafif(self, girdi: GirdiTuru) -> Any:
        """
        Analyzer için girdi hazırla (matris veya bayt).

        Dosya yolu doğrulanır; olmayan dosya → VisionError.
        """
        if isinstance(girdi, Kare):
            if girdi.ham:
                return bytes(girdi.ham)
            if girdi.yol:
                p = Path(girdi.yol).expanduser()
                if "://" in str(girdi.yol):
                    return girdi.yol
                if not p.is_file():
                    raise VisionError(
                        f"Goruntu yok: {p}",
                        kod="VIS_0832",
                        modul=self.ad,
                    )
                return p.read_bytes()
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0831",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            if not girdi:
                raise VisionError(
                    "Bos goruntu baytlari",
                    kod="VIS_0831",
                    modul=self.ad,
                )
            return bytes(girdi)

        if isinstance(girdi, Path):
            p = girdi.expanduser()
            if not p.is_file():
                raise VisionError(
                    f"Goruntu yok: {p}",
                    kod="VIS_0832",
                    modul=self.ad,
                )
            return p.read_bytes()

        if isinstance(girdi, str):
            if "://" in girdi:
                return girdi
            p = Path(girdi).expanduser()
            if not p.is_file():
                raise VisionError(
                    f"Goruntu yok: {p}",
                    kod="VIS_0832",
                    modul=self.ad,
                )
            return p.read_bytes()

        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen multimodal girdisi: {type(girdi)!r}",
            kod="VIS_0831",
            modul=self.ad,
        )

    def _compose_analiz(
        self,
        girdi: GirdiTuru,
        metin: str,
        *,
        sayim_etiket: Optional[str] = None,
    ) -> tuple[str, Optional[int], Optional[str], str]:
        """
        Caption + OCR + sayma sonuçlarını kullanıcı metniyle birleştir.

        Dönüş: (cevap, sayim, sayim_etiket, neden).
        """
        parcalar: list[str] = [f"Kullanıcı metni: {metin}"]
        sayim: Optional[int] = None
        etiket: Optional[str] = sayim_etiket
        kaynaklar: list[str] = []

        # Sanal URI — alt motorlara dosya yok; kontrollü sahte/heuristik
        uri_mi = (
            isinstance(girdi, str)
            and "://" in girdi
            and not Path(girdi).is_file()
        )

        if self.caption_kullan:
            try:
                from vision.ai.aciklama import GorselAciklama

                cap = GorselAciklama(
                    ayarlar=self.ayarlar,
                    bus=None,
                    dry_run=False,
                    zorla_sahte=bool(uri_mi),
                    sahne_heuristik=not uri_mi,
                    cv2_modul=self._cv2,
                    numpy_modul=self._np,
                    olay_yayinla=False,
                )
                cap_son = cap.acikla(girdi)
                if cap_son.aciklama:
                    parcalar.append(f"Görsel açıklama: {cap_son.aciklama}")
                    kaynaklar.append("caption")
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Compose caption atlandi: %s", exc)

        if self.ocr_kullan:
            try:
                from vision.ocr.motor import OcrYoneticisi

                ocr = OcrYoneticisi(
                    ayarlar=self.ayarlar,
                    bus=None,
                    dry_run=False,
                    zorla_sahte=True if uri_mi else False,
                    on_isleme_aktif=not uri_mi,
                    olay_yayinla=False,
                )
                ocr_son = ocr.oku(girdi)
                ocr_metin = (ocr_son.metin or "").strip()
                if ocr_metin:
                    # Uzun OCR kısalt
                    kisa = ocr_metin if len(ocr_metin) <= 240 else ocr_metin[:237] + "..."
                    parcalar.append(f"OCR metni: {kisa}")
                    kaynaklar.append("ocr")
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Compose OCR atlandi: %s", exc)

        if self.sayma_kullan:
            try:
                from vision.ai.sayma import NesneSayici

                say = NesneSayici(
                    ayarlar=self.ayarlar,
                    bus=None,
                    dry_run=False,
                    zorla_sahte=bool(uri_mi),
                    nesne_heuristik=not uri_mi,
                    cv2_modul=self._cv2,
                    numpy_modul=self._np,
                    olay_yayinla=False,
                )
                say_son = say.say(girdi, etiket=sayim_etiket)
                if say_son.sayim is not None:
                    sayim = int(say_son.sayim)
                    etiket = say_son.sayim_etiket or etiket
                    if say_son.aciklama:
                        parcalar.append(f"Nesne sayımı: {say_son.aciklama}")
                    else:
                        e = f" ({etiket})" if etiket else ""
                        parcalar.append(f"Nesne sayımı: {sayim}{e}")
                    kaynaklar.append("count")
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Compose sayma atlandi: %s", exc)

        if len(parcalar) <= 1:
            # Yalnızca kullanıcı metni kaldı — bileşim başarısız
            raise VisionError(
                "Compose alt motorlari sonuc uretemedi",
                kod="VIS_0833",
                modul=self.ad,
            )

        # Kısa sentez cümlesi
        ozet = "Metin ve görüntü birlikte analiz edildi"
        if kaynaklar:
            ozet = f"{ozet} ({', '.join(kaynaklar)})"
        parcalar.insert(0, f"{ozet}.")

        neden = "compose"
        if uri_mi:
            neden = "compose_uri"
        elif kaynaklar:
            neden = f"compose:{'+'.join(kaynaklar)}"
        return " ".join(parcalar), sayim, etiket, neden

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(
        self,
        sonuc: VisionAiSonucu,
        *,
        backend: Optional[str] = None,
    ) -> VisionAiSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        if backend:
            self._backend = backend
        elif sonuc.dry_run:
            self._backend = "dry_run"
        elif sonuc.neden == "injected":
            self._backend = "injected"
        elif sonuc.neden and "compose" in str(sonuc.neden):
            self._backend = "compose"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"

        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "prompt_text": sonuc.ek_metin,
            "answer": sonuc.cevap,
            "count": sonuc.sayim,
            "count_label": sonuc.sayim_etiket,
            "confidence": sonuc.guven,
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.ai.multimodal.done", detay)
        self._yayin(OLAY_MULTIMODAL, sonuc.to_dict())
        self._log.debug(
            "Multimodal tamam motor=%s metin_len=%s cevap_len=%s",
            sonuc.motor.value,
            len(sonuc.ek_metin or ""),
            len(sonuc.cevap or ""),
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


def multimodal_analiz_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    analyzer: Optional[AnalyzerTuru] = None,
    compose: bool = True,
    caption_kullan: bool = True,
    ocr_kullan: bool = True,
    sayma_kullan: bool = True,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    olay_yayinla: bool = False,
    varsayilan_sahte: str = _SAHTE_CEVAP,
) -> MultimodalAnaliz:
    """Test / demo için güvenli varsayılanlarla MultimodalAnaliz üretir."""
    return MultimodalAnaliz(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        analyzer=analyzer,
        compose=compose,
        caption_kullan=caption_kullan,
        ocr_kullan=ocr_kullan,
        sayma_kullan=sayma_kullan,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        olay_yayinla=olay_yayinla,
        varsayilan_sahte=varsayilan_sahte,
    )


def multimodal_analiz(
    girdi: GirdiTuru,
    metin: str,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_cevap: Optional[str] = None,
    analyzer: Optional[AnalyzerTuru] = None,
    compose: bool = True,
    caption_kullan: bool = True,
    ocr_kullan: bool = True,
    sayma_kullan: bool = True,
    sayim_etiket: Optional[str] = None,
) -> VisionAiSonucu:
    """Tek çağrılık multimodal analiz yardımcısı."""
    m = multimodal_analiz_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        analyzer=analyzer,
        compose=compose,
        caption_kullan=caption_kullan,
        ocr_kullan=ocr_kullan,
        sayma_kullan=sayma_kullan,
        olay_yayinla=False,
    )
    return m.analiz(
        girdi,
        metin,
        sahte_cevap=sahte_cevap,
        sayim_etiket=sayim_etiket,
    )


__all__ = [
    "OLAY_MULTIMODAL",
    "OLAY_MULTIMODAL_BASLADI",
    "OLAY_MULTIMODAL_DURDU",
    "MultimodalAnaliz",
    "opencv_var_mi",
    "numpy_var_mi",
    "multimodal_analiz_olustur",
    "multimodal_analiz",
]

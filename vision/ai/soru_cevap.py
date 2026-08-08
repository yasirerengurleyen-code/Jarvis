"""
vision/ai/soru_cevap.py
-----------------------
Görsel soru-cevap (VQA) — Vision AI, dry_run / sahte / heuristik fallback.

Görev:
- Görüntü + soru → Türkçe cevap (`VisionAiSonucu.cevap` / `.soru`)
- Enjekte edilebilir answerer (LLM / özel motor testleri)
- LLM / vision model yoksa: isteğe bağlı sahne heuristiği (`vision.analiz.sahne`)
- OpenCV / bağımlılık yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Caption → `aciklama.py`; sayma → `sayma.py`; multimodal → `multimodal.py`
      (sonraki onaylı dosyalar; bu modül yalnızca VQA).
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

log = logger_al("vision.ai.soru_cevap")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_VQA = "vision.ai.vqa.done"
OLAY_VQA_BASLADI = "vision.ai.vqa.started"
OLAY_VQA_DURDU = "vision.ai.vqa.stopped"

# Sahte / dry_run için örnek cevap (CI / offline)
_SAHTE_CEVAP = (
    "Evet; görüntüde bir masaüstü çalışma alanı, ekran ve "
    "masaüstü nesneleri görünüyor."
)

VARSAYILAN_GUVEN_SAHTE = 0.55
VARSAYILAN_GUVEN_HEURISTIK = 0.60
VARSAYILAN_GUVEN_LLM = 0.80

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# answerer(mat | bytes | yol, soru) → str | dict | VisionAiSonucu
AnswererTuru = Callable[[Any, str], Any]

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


def _cevap_normalize(ham: Any) -> tuple[str, float, Optional[str]]:
    """
    str / dict / VisionAiSonucu → (cevap, güven, motor_ipuucu).

    dict anahtarları: answer / cevap / text / response;
    isteğe bağlı confidence / engine.
    """
    if ham is None:
        return "", 0.0, None
    if isinstance(ham, VisionAiSonucu):
        metin = str(ham.cevap or ham.aciklama or "").strip()
        return (
            metin,
            guven_sinirla(ham.guven),
            ham.motor.value if ham.motor else None,
        )
    if isinstance(ham, str):
        return ham.strip(), 0.0, None
    if isinstance(ham, dict):
        metin = ""
        for anahtar in (
            "answer",
            "cevap",
            "text",
            "response",
            "yanit",
            "description",
            "aciklama",
        ):
            deger = ham.get(anahtar)
            if deger is not None and str(deger).strip():
                metin = str(deger).strip()
                break
        guven = guven_sinirla(ham.get("confidence"))
        motor = ham.get("engine") or ham.get("motor")
        return metin, guven, str(motor) if motor else None
    return str(ham).strip(), 0.0, None


def _soru_temizle(soru: Optional[str]) -> str:
    """Soru metnini doğrula / temizle; boşsa VisionError."""
    metin = str(soru or "").strip()
    if not metin:
        raise VisionError(
            "VQA sorusu bos olamaz",
            kod="VIS_0814",
            modul="vision.ai.soru_cevap",
        )
    return metin


class GorselSoruCevap(ModulTabani):
    """
    Vision AI — görsel soru-cevap (VQA).

    1) dry_run → boş cevap + plan meta
    2) zorla_sahte / motor yok → sahte cevap
    3) Enjekte answerer → LLM / özel motor
    4) sahne_heuristik=True → `vision.analiz.sahne` üzerinden kısa yanıt
    5) Aksi halde sahte
    """

    ad = "vision.ai.soru_cevap"
    surum = "0.1.0"
    aciklama = "Görsel soru-cevap (VQA) — dry_run / sahte / sahne heuristik"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        answerer: Optional[AnswererTuru] = None,
        sahne_heuristik: bool = True,
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
        self.sahne_heuristik = bool(sahne_heuristik)
        self.olay_yayinla = bool(olay_yayinla)
        self._answerer = answerer
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np
        self.varsayilan_sahte = str(varsayilan_sahte or _SAHTE_CEVAP)

        cfg = self.ayarlar.al("vision.ai.vqa_fake", None)
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
        """injected | sahne_heuristic | sahte | dry_run."""
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
            "injected": self._answerer is not None,
            "scene_heuristic": bool(self.sahne_heuristik),
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
            "vision.ai.vqa.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_VQA_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "Gorsel soru-cevap basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.ai.vqa.stopped", {"engine": self._motor})
        self._yayin(OLAY_VQA_DURDU, {"engine": self._motor})
        self._log.info("Gorsel soru-cevap durdu")

    # ------------------------------------------------------------------ API

    def sor(
        self,
        girdi: GirdiTuru,
        soru: str,
        *,
        sahte_cevap: Optional[str] = None,
        dil: str = "tr",
    ) -> VisionAiSonucu:
        """
        Görüntü + soru → VQA sonucu (`VisionAiSonucu`).

        dry_run → boş cevap (soru saklanır).
        zorla_sahte / motor yok → sahte cevap.
        """
        _ = dil  # gelecek dil seçimi; şimdilik Türkçe
        soru_temiz = _soru_temizle(soru)
        kaynak_yol = self._kaynak_yol(girdi)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = VisionAiSonucu(
                gorev=VisionGorevTuru.AI,
                soru=soru_temiz,
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
            and self._answerer is None
            and not self._heuristik_kullanilabilir()
        ):
            cevap = (
                sahte_cevap if sahte_cevap is not None else self.varsayilan_sahte
            )
            sonuc = VisionAiSonucu(
                gorev=VisionGorevTuru.AI,
                soru=soru_temiz,
                cevap=cevap,
                aciklama=cevap,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=VARSAYILAN_GUVEN_SAHTE,
                kaynak_yol=kaynak_yol,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            return self._sonucla(sonuc, backend="sahte")

        # Enjekte answerer (LLM / mock)
        if self._answerer is not None:
            try:
                yuk = self._yukle_hafif(girdi)
                ham = self._answerer(yuk, soru_temiz)
                cevap, guven, motor_ipu = _cevap_normalize(ham)
                if not cevap:
                    raise VisionError(
                        "Answerer bos cevap dondurdu",
                        kod="VIS_0813",
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
                    soru=soru_temiz,
                    cevap=cevap,
                    aciklama=cevap,
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
                self._log.warning("Answerer basarisiz → fallback: %s", exc)
                # aşağıda heuristik / sahte

        # Sahne heuristiği (opsiyonel)
        if self.sahne_heuristik and self._heuristik_kullanilabilir():
            try:
                cevap, neden = self._sahne_cevap(girdi, soru_temiz)
                if cevap:
                    sonuc = VisionAiSonucu(
                        gorev=VisionGorevTuru.AI,
                        soru=soru_temiz,
                        cevap=cevap,
                        aciklama=cevap,
                        motor=VisionMotoru.OPENCV,
                        dry_run=False,
                        guven=VARSAYILAN_GUVEN_HEURISTIK,
                        kaynak_yol=kaynak_yol,
                        neden=neden,
                    )
                    return self._sonucla(sonuc, backend="sahne_heuristic")
            except VisionError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Sahne heuristik VQA basarisiz → sahte: %s", exc)

        # Son çare: sahte
        cevap = sahte_cevap if sahte_cevap is not None else self.varsayilan_sahte
        sonuc = VisionAiSonucu(
            gorev=VisionGorevTuru.AI,
            soru=soru_temiz,
            cevap=cevap,
            aciklama=cevap,
            motor=VisionMotoru.SAHTE,
            dry_run=False,
            guven=VARSAYILAN_GUVEN_SAHTE,
            kaynak_yol=kaynak_yol,
            neden="fallback_sahte",
        )
        return self._sonucla(sonuc, backend="sahte")

    def cevapla(
        self,
        girdi: GirdiTuru,
        soru: str,
        *,
        sahte_cevap: Optional[str] = None,
        dil: str = "tr",
    ) -> str:
        """Yalnızca cevap metni döndüren kısayol."""
        return (
            self.sor(
                girdi,
                soru,
                sahte_cevap=sahte_cevap,
                dil=dil,
            ).cevap
            or ""
        )

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._answerer is not None:
            return VisionMotoru.LLM.value
        if self.sahne_heuristik and self._heuristik_kullanilabilir():
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _backend_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._answerer is not None:
            return "injected"
        if self.sahne_heuristik and self._heuristik_kullanilabilir():
            return "sahne_heuristic"
        return "sahte"

    def _heuristik_kullanilabilir(self) -> bool:
        """Sahne modülü kullanılabilir mi?"""
        if not self.sahne_heuristik:
            return False
        try:
            from vision.analiz import sahne as _sahne_mod  # noqa: F401

            return True
        except ImportError:  # pragma: no cover
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
        Answerer için girdi hazırla (matris veya bayt).

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
                        kod="VIS_0812",
                        modul=self.ad,
                    )
                return p.read_bytes()
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0811",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            if not girdi:
                raise VisionError(
                    "Bos goruntu baytlari",
                    kod="VIS_0811",
                    modul=self.ad,
                )
            return bytes(girdi)

        if isinstance(girdi, Path):
            p = girdi.expanduser()
            if not p.is_file():
                raise VisionError(
                    f"Goruntu yok: {p}",
                    kod="VIS_0812",
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
                    kod="VIS_0812",
                    modul=self.ad,
                )
            return p.read_bytes()

        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen VQA girdisi: {type(girdi)!r}",
            kod="VIS_0811",
            modul=self.ad,
        )

    def _sahne_cevap(self, girdi: GirdiTuru, soru: str) -> tuple[str, str]:
        """Sahne analizinden VQA cevabı üret; (metin, neden)."""
        from vision.analiz.sahne import SahneAnalizci

        s = SahneAnalizci(
            ayarlar=self.ayarlar,
            bus=None,
            dry_run=False,
            zorla_sahte=False,
            cv2_modul=self._cv2,
            numpy_modul=self._np,
            olay_yayinla=False,
        )
        if isinstance(girdi, str) and "://" in girdi and not Path(girdi).is_file():
            # Sanal URI — sahne yüklemesi yok; soruya bağlı sahte-heuristik
            return (
                f"Görüntü özeti: {self.varsayilan_sahte} "
                f"(Soru: {soru})",
                "sahne_heuristic_uri",
            )
        bil = s.analiz(girdi)
        sahne = (bil.sahne or "").strip()
        if not sahne:
            raise VisionError(
                "Sahne heuristik bos cevap dondurdu",
                kod="VIS_0813",
                modul=self.ad,
            )
        soru_k = soru.lower()
        # Basit soru kalıpları: ne görünüyor / neler var
        if any(
            k in soru_k
            for k in (
                "ne gör",
                "neler var",
                "ne var",
                "açıkla",
                "anlat",
                "sahne",
                "what",
                "describe",
            )
        ):
            return f"Görüntüde: {sahne}", "sahne_heuristic"
        # Evet/hayır tipi
        if soru_k.startswith("var mı") or " var mı" in soru_k or soru_k.startswith(
            "is there"
        ):
            return (
                f"Sahne analizi buna işaret ediyor: {sahne}. "
                "Kesin nesne doğrulaması için LLM gerekir.",
                "sahne_heuristic",
            )
        return (
            f"Sahne: {sahne}. Sorunuz ('{soru}') için heuristik yanıt bu "
            "sahne özetine dayanır.",
            "sahne_heuristic",
        )

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
        elif sonuc.neden and "sahne" in str(sonuc.neden):
            self._backend = "sahne_heuristic"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"

        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "question": sonuc.soru,
            "answer": sonuc.cevap,
            "confidence": sonuc.guven,
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.ai.vqa.done", detay)
        self._yayin(OLAY_VQA, sonuc.to_dict())
        self._log.debug(
            "VQA tamam motor=%s soru_len=%s cevap_len=%s",
            sonuc.motor.value,
            len(sonuc.soru or ""),
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


def gorsel_soru_cevap_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    answerer: Optional[AnswererTuru] = None,
    sahne_heuristik: bool = True,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    olay_yayinla: bool = False,
    varsayilan_sahte: str = _SAHTE_CEVAP,
) -> GorselSoruCevap:
    """Test / demo için güvenli varsayılanlarla GorselSoruCevap üretir."""
    return GorselSoruCevap(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        answerer=answerer,
        sahne_heuristik=sahne_heuristik,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        olay_yayinla=olay_yayinla,
        varsayilan_sahte=varsayilan_sahte,
    )


def gorsel_sor(
    girdi: GirdiTuru,
    soru: str,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_cevap: Optional[str] = None,
    answerer: Optional[AnswererTuru] = None,
    sahne_heuristik: bool = True,
) -> VisionAiSonucu:
    """Tek çağrılık görsel soru-cevap yardımcısı."""
    m = gorsel_soru_cevap_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        answerer=answerer,
        sahne_heuristik=sahne_heuristik,
        olay_yayinla=False,
    )
    return m.sor(girdi, soru, sahte_cevap=sahte_cevap)


__all__ = [
    "OLAY_VQA",
    "OLAY_VQA_BASLADI",
    "OLAY_VQA_DURDU",
    "GorselSoruCevap",
    "opencv_var_mi",
    "numpy_var_mi",
    "gorsel_soru_cevap_olustur",
    "gorsel_sor",
]

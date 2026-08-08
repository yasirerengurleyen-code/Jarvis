"""
vision/analiz/sahne.py
----------------------
Sahne analizi + kısa görsel açıklama — OpenCV heuristik, dry_run / sahte fallback.

Görev:
- Görüntüden sahne etiketi / kısa Türkçe açıklama (`AnalizSonucu.sahne`)
- OpenCV ile hafif heuristik (parlaklık, renk, kenar yoğunluğu)
- Enjekte edilebilir analyzer (birim test / özel motor)
- OpenCV yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Tam caption / VQA → `vision/ai/aciklama.py` (sonraki).
      Renk / QR → sonraki dosyalar; bu modül yalnızca sahne.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import AnalizSonucu, Kare, VisionMotoru

log = logger_al("vision.analiz.sahne")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_SAHNE_ANALIZ = "vision.analysis.scene.analyzed"
OLAY_SAHNE_BASLADI = "vision.analysis.scene.started"
OLAY_SAHNE_DURDU = "vision.analysis.scene.stopped"

# Sahte / dry_run için örnek sahne açıklaması (CI / offline)
_SAHTE_SAHNE = "İç mekan; ofis veya çalışma alanı."

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# analyzer(mat) → str | dict | AnalizSonucu
AnalyzerTuru = Callable[[Any], Any]

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


def _sahne_metni_normalize(ham: Any) -> str:
    """str / dict / AnalizSonucu → sahne metni."""
    if ham is None:
        return ""
    if isinstance(ham, AnalizSonucu):
        return str(ham.sahne or "").strip()
    if isinstance(ham, str):
        return ham.strip()
    if isinstance(ham, dict):
        for anahtar in ("scene", "sahne", "description", "aciklama", "label", "etiket"):
            deger = ham.get(anahtar)
            if deger is not None and str(deger).strip():
                return str(deger).strip()
        return ""
    return str(ham).strip()


def _aciklama_zenginlestir(sahne: str, etiketler: Optional[Sequence[str]]) -> str:
    """İsteğe bağlı nesne etiketleriyle kısa açıklamayı zenginleştir."""
    metin = (sahne or "").strip()
    if not etiketler:
        return metin
    temiz = []
    for e in etiketler:
        t = str(e or "").strip()
        if t and t.lower() not in {x.lower() for x in temiz}:
            temiz.append(t)
    if not temiz:
        return metin
    ek = ", ".join(temiz[:8])
    if not metin:
        return f"Görünen: {ek}."
    if metin.endswith("."):
        return f"{metin} Görünen: {ek}."
    return f"{metin}. Görünen: {ek}."


class SahneAnalizci(ModulTabani):
    """
    Vision sahne analizi + kısa açıklama.

    1) dry_run → boş sahne + plan meta
    2) zorla_sahte / motor yok → sahte açıklama
    3) Enjekte analyzer → OpenCV motoru ile çağrı
    4) OpenCV heuristik (parlaklık / renk / kenar)
    """

    ad = "vision.analiz.sahne"
    surum = "0.1.0"
    aciklama = "Sahne analizi + kısa açıklama — OpenCV heuristik, dry_run / sahte"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        analyzer: Optional[AnalyzerTuru] = None,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
        olay_yayinla: bool = True,
        varsayilan_sahte: str = _SAHTE_SAHNE,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self._analyzer = analyzer
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np
        self.varsayilan_sahte = str(varsayilan_sahte or _SAHTE_SAHNE)

        cfg = self.ayarlar.al("vision.analiz.scene_fake", None)
        if cfg and not zorla_sahte:
            # yalnızca varsayılan metin olarak kullan; zorla değil
            self.varsayilan_sahte = str(cfg)

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
        """opencv_heuristic | injected | sahte | dry_run."""
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
            "opencv": self._cv2 is not None or opencv_var_mi(),
            "numpy": self._np is not None or numpy_var_mi(),
            "injected": self._analyzer is not None,
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
            "vision.analysis.scene.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_SAHNE_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "Sahne analizci basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.analysis.scene.stopped", {"engine": self._motor})
        self._yayin(OLAY_SAHNE_DURDU, {"engine": self._motor})
        self._log.info("Sahne analizci durdu")

    # ------------------------------------------------------------------ API

    def analiz(
        self,
        girdi: GirdiTuru,
        *,
        sahte_sahne: Optional[str] = None,
        etiketler: Optional[Sequence[str]] = None,
    ) -> AnalizSonucu:
        """
        Görüntüde sahne analizi → AnalizSonucu (sahne alanı dolu).

        dry_run → boş sahne.
        zorla_sahte / motor yok → sahte kısa açıklama.
        """
        kaynak_yol = self._kaynak_yol(girdi)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = AnalizSonucu(
                sahne="",
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                kaynak_yol=kaynak_yol,
                neden="dry_run",
            )
            return self._sonucla(sonuc)

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            metin = _aciklama_zenginlestir(
                (sahte_sahne if sahte_sahne is not None else self.varsayilan_sahte),
                etiketler,
            )
            sonuc = AnalizSonucu(
                sahne=metin,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            return self._sonucla(sonuc)

        try:
            mat = self._yukle(girdi)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Goruntu yuklenemedi: {exc}",
                kod="VIS_0612",
                modul=self.ad,
            ) from exc

        try:
            ham_metin, neden = self._analiz_matris(mat)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.warning("Sahne analizi basarisiz → sahte: %s", exc)
            metin = _aciklama_zenginlestir(
                sahte_sahne if sahte_sahne is not None else self.varsayilan_sahte,
                etiketler,
            )
            sonuc = AnalizSonucu(
                sahne=metin,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden=f"analiz_hata:{exc}",
            )
            return self._sonucla(sonuc)

        metin = _aciklama_zenginlestir(ham_metin, etiketler)
        sonuc = AnalizSonucu(
            sahne=metin,
            motor=VisionMotoru.OPENCV,
            dry_run=False,
            kaynak_yol=kaynak_yol,
            neden=neden,
        )
        return self._sonucla(sonuc)

    def acikla(
        self,
        girdi: GirdiTuru,
        *,
        sahte_sahne: Optional[str] = None,
        etiketler: Optional[Sequence[str]] = None,
    ) -> str:
        """Yalnızca kısa sahne açıklaması döndüren kısayol."""
        return self.analiz(
            girdi,
            sahte_sahne=sahte_sahne,
            etiketler=etiketler,
        ).sahne

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._analyzer is not None:
            return VisionMotoru.OPENCV.value
        if self._cv2 is not None or opencv_var_mi():
            if self._np is not None or numpy_var_mi():
                return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _backend_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._analyzer is not None:
            return "injected"
        if (self._cv2 is not None or opencv_var_mi()) and (
            self._np is not None or numpy_var_mi()
        ):
            return "opencv_heuristic"
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
        if self._analyzer is not None and (self._cv2 is None or self._np is None):
            if isinstance(girdi, Kare):
                if girdi.ham:
                    return bytes(girdi.ham)
                if girdi.yol and Path(girdi.yol).expanduser().is_file():
                    return Path(girdi.yol).expanduser().read_bytes()
                raise VisionError(
                    "Kare'de yol veya ham veri yok",
                    kod="VIS_0611",
                    modul=self.ad,
                )
            if isinstance(girdi, (bytes, bytearray)):
                return bytes(girdi)
            if isinstance(girdi, (str, Path)):
                p = Path(girdi).expanduser()
                if not p.is_file():
                    raise VisionError(
                        f"Goruntu yok: {p}",
                        kod="VIS_0612",
                        modul=self.ad,
                    )
                return p.read_bytes()
            return girdi

        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yuklu degil",
                kod="VIS_0611",
                modul=self.ad,
            )

        if isinstance(girdi, Kare):
            if girdi.ham:
                return self._bayttan_matris(bytes(girdi.ham))
            if girdi.yol:
                return self._yoldan_matris(girdi.yol)
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0611",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            return self._bayttan_matris(bytes(girdi))

        if isinstance(girdi, (str, Path)):
            return self._yoldan_matris(str(girdi))

        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen sahne analizi girdisi: {type(girdi)!r}",
            kod="VIS_0611",
            modul=self.ad,
        )

    def _yoldan_matris(self, yol: str) -> Any:
        p = Path(yol).expanduser()
        if not p.is_file():
            raise VisionError(
                f"Goruntu yok: {p}",
                kod="VIS_0612",
                modul=self.ad,
            )
        mat = self._cv2.imread(str(p), self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                f"Goruntu okunamadi: {p}",
                kod="VIS_0612",
                modul=self.ad,
            )
        return mat

    def _bayttan_matris(self, ham: bytes) -> Any:
        if not ham:
            raise VisionError(
                "Bos goruntu baytlari",
                kod="VIS_0611",
                modul=self.ad,
            )
        buf = self._np.frombuffer(ham, dtype=self._np.uint8)
        mat = self._cv2.imdecode(buf, self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                "Bayt goruntu cozulemedi",
                kod="VIS_0612",
                modul=self.ad,
            )
        return mat

    # ------------------------------------------------------------------ iç — analiz

    def _analiz_matris(self, mat: Any) -> tuple[str, str]:
        """Matris üzerinde sahne analizi; (açıklama, neden/backend)."""
        if self._analyzer is not None:
            ham = self._analyzer(mat)
            metin = _sahne_metni_normalize(ham)
            if not metin:
                raise VisionError(
                    "Analyzer bos sahne dondurdu",
                    kod="VIS_0613",
                    modul=self.ad,
                )
            return metin, "injected"

        if (self._cv2 is not None or opencv_var_mi()) and (
            self._np is not None or numpy_var_mi()
        ):
            return self._heuristik_analiz(mat), "opencv_heuristic"

        raise VisionError(
            "Sahne analizi motoru yok (OpenCV)",
            kod="VIS_0613",
            modul=self.ad,
        )

    def _heuristik_analiz(self, mat: Any) -> str:
        """
        OpenCV ile hafif sahne heuristiği → kısa Türkçe açıklama.

        Tam caption değildir; parlaklık / renk / kenar yoğunluğuna göre özet.
        """
        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yok",
                kod="VIS_0611",
                modul=self.ad,
            )

        # Tek kanalsa BGR'ye çevir
        girdi = mat
        shape = getattr(mat, "shape", None)
        if shape is None or len(shape) < 2:
            raise VisionError(
                "Gecersiz goruntu matrisi",
                kod="VIS_0612",
                modul=self.ad,
            )
        if len(shape) == 2:
            girdi = cv2.cvtColor(mat, cv2.COLOR_GRAY2BGR)
        elif len(shape) == 3 and shape[2] == 4:
            girdi = cv2.cvtColor(mat, cv2.COLOR_BGRA2BGR)

        try:
            hsv = cv2.cvtColor(girdi, cv2.COLOR_BGR2HSV)
            gri = cv2.cvtColor(girdi, cv2.COLOR_BGR2GRAY)
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Renk donusumu basarisiz: {exc}",
                kod="VIS_0613",
                modul=self.ad,
            ) from exc

        parlaklik = float(np.mean(gri))
        doygunluk = float(np.mean(hsv[:, :, 1]))
        # Üst şerit — gökyüzü tahmini (mavi ton)
        h, w = gri.shape[:2]
        ust = hsv[0 : max(1, h // 3), :, :]
        hue_ust = ust[:, :, 0]
        sat_ust = ust[:, :, 1]
        mavi_mask = (hue_ust >= 90) & (hue_ust <= 130) & (sat_ust > 40)
        mavi_oran = float(np.mean(mavi_mask.astype(np.float32))) if mavi_mask.size else 0.0
        # Yeşil ton (doğa)
        hue = hsv[:, :, 0]
        sat = hsv[:, :, 1]
        yesil_mask = (hue >= 35) & (hue <= 85) & (sat > 40)
        yesil_oran = float(np.mean(yesil_mask.astype(np.float32))) if yesil_mask.size else 0.0

        try:
            kenar = cv2.Canny(gri, 80, 160)
            kenar_oran = float(np.mean(kenar > 0))
        except Exception:  # noqa: BLE001
            kenar_oran = 0.0

        # --- sınıflandırma ---
        if parlaklik < 45:
            mekan = "Karanlık bir ortam"
        elif parlaklik > 170:
            mekan = "Aydınlık bir ortam"
        else:
            mekan = "Orta aydınlatmalı bir ortam"

        dis_mekan = yesil_oran > 0.18 or mavi_oran > 0.22
        if dis_mekan:
            tip = "dış mekan"
            if yesil_oran > 0.25:
                detay = "doğal çevre veya yeşillik ağırlıklı"
            elif mavi_oran > 0.25:
                detay = "açık alan veya gökyüzü belirgin"
            else:
                detay = "açık hava sahnesi"
        else:
            tip = "iç mekan"
            if kenar_oran > 0.12 and doygunluk < 70:
                detay = "ofis veya çalışma alanı izlenimi"
            elif doygunluk < 45:
                detay = "nötr renkli kapalı alan"
            elif kenar_oran > 0.15:
                detay = "nesne açısından zengin kapalı alan"
            else:
                detay = "kapalı alan"

        return f"{mekan}; {tip}, {detay}."

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(self, sonuc: AnalizSonucu) -> AnalizSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        if sonuc.neden in ("injected", "opencv_heuristic"):
            self._backend = str(sonuc.neden)
        elif sonuc.dry_run:
            self._backend = "dry_run"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"
        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "scene": sonuc.sahne,
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.analysis.scene.analyzed", detay)
        self._yayin(OLAY_SAHNE_ANALIZ, sonuc.to_dict())
        self._log.debug(
            "Sahne analizi tamam motor=%s sahne=%s",
            sonuc.motor.value,
            (sonuc.sahne or "")[:80],
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


def sahne_analizci_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    analyzer: Optional[AnalyzerTuru] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    olay_yayinla: bool = False,
    varsayilan_sahte: str = _SAHTE_SAHNE,
) -> SahneAnalizci:
    """Test / demo için güvenli varsayılanlarla SahneAnalizci üretir."""
    return SahneAnalizci(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        analyzer=analyzer,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        olay_yayinla=olay_yayinla,
        varsayilan_sahte=varsayilan_sahte,
    )


def sahne_analiz(
    girdi: GirdiTuru,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_sahne: Optional[str] = None,
    etiketler: Optional[Sequence[str]] = None,
    analyzer: Optional[AnalyzerTuru] = None,
) -> AnalizSonucu:
    """Tek çağrılık sahne analizi yardımcısı."""
    s = sahne_analizci_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        analyzer=analyzer,
        olay_yayinla=False,
    )
    return s.analiz(girdi, sahte_sahne=sahte_sahne, etiketler=etiketler)


__all__ = [
    "OLAY_SAHNE_ANALIZ",
    "OLAY_SAHNE_BASLADI",
    "OLAY_SAHNE_DURDU",
    "SahneAnalizci",
    "opencv_var_mi",
    "numpy_var_mi",
    "sahne_analizci_olustur",
    "sahne_analiz",
]

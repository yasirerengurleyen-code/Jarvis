"""
vision/analiz/renk.py
---------------------
Renk analizi — OpenCV heuristik, dry_run / sahte fallback.

Görev:
- Görüntüden baskın renk + palet + ortalama RGB (`AnalizSonucu.renk` / `RenkOzeti`)
- OpenCV ile hafif heuristik (k-means / örnekleme)
- Enjekte edilebilir analyzer (birim test / özel motor)
- OpenCV yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: QR / barkod → sonraki dosya; bu modül yalnızca renk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import AnalizSonucu, Kare, RenkOzeti, VisionMotoru

log = logger_al("vision.analiz.renk")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_RENK_ANALIZ = "vision.analysis.color.analyzed"
OLAY_RENK_BASLADI = "vision.analysis.color.started"
OLAY_RENK_DURDU = "vision.analysis.color.stopped"

VARSAYILAN_PALET_BOYUTU = 5

# Sahte / dry_run için örnek renk özeti (CI / offline)
_SAHTE_RENK = RenkOzeti(
    baskin_hex="#3A7BD5",
    palette=["#3A7BD5", "#2E4057", "#E8E8E8", "#F4A261", "#1B1B2F"],
    ortalama_rgb=(58, 123, 213),
)

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# analyzer(mat) → RenkOzeti | dict | AnalizSonucu
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


def _kanal_sinirla(deger: Any, varsayilan: int = 0) -> int:
    """0..255 kanal değeri."""
    try:
        v = int(round(float(deger)))
    except (TypeError, ValueError):
        v = varsayilan
    return max(0, min(255, v))


def _rgb_hex(r: Any, g: Any, b: Any) -> str:
    """RGB → #RRGGBB."""
    return (
        f"#{_kanal_sinirla(r):02X}"
        f"{_kanal_sinirla(g):02X}"
        f"{_kanal_sinirla(b):02X}"
    )


def _hex_normalize(ham: Any, varsayilan: str = "#000000") -> str:
    """Hex rengi normalize et (#RRGGBB)."""
    if ham is None:
        return varsayilan
    s = str(ham).strip()
    if not s:
        return varsayilan
    if not s.startswith("#"):
        s = f"#{s}"
    if len(s) == 4:
        # #RGB → #RRGGBB
        s = f"#{s[1]*2}{s[2]*2}{s[3]*2}"
    if len(s) != 7:
        return varsayilan
    try:
        r = int(s[1:3], 16)
        g = int(s[3:5], 16)
        b = int(s[5:7], 16)
    except ValueError:
        return varsayilan
    return _rgb_hex(r, g, b)


def _rgb_tuple(ham: Any) -> tuple[int, int, int]:
    """dict / list / tuple → (r, g, b)."""
    if isinstance(ham, dict):
        return (
            _kanal_sinirla(ham.get("r", ham.get("R", 0))),
            _kanal_sinirla(ham.get("g", ham.get("G", 0))),
            _kanal_sinirla(ham.get("b", ham.get("B", 0))),
        )
    if isinstance(ham, (list, tuple)) and len(ham) >= 3:
        return (
            _kanal_sinirla(ham[0]),
            _kanal_sinirla(ham[1]),
            _kanal_sinirla(ham[2]),
        )
    return (0, 0, 0)


def _sahte_renk_kopyala(kaynak: Optional[RenkOzeti] = None) -> RenkOzeti:
    """Sahte renk özeti (kopya)."""
    k = kaynak if kaynak is not None else _SAHTE_RENK
    return RenkOzeti(
        baskin_hex=_hex_normalize(k.baskin_hex, "#3A7BD5"),
        palette=[_hex_normalize(x) for x in (k.palette or [])],
        ortalama_rgb=_rgb_tuple(k.ortalama_rgb),
    )


def _renk_normalize(ham: Any) -> Optional[RenkOzeti]:
    """str / dict / RenkOzeti / AnalizSonucu → RenkOzeti."""
    if ham is None:
        return None
    if isinstance(ham, AnalizSonucu):
        return _renk_normalize(ham.renk)
    if isinstance(ham, RenkOzeti):
        return RenkOzeti(
            baskin_hex=_hex_normalize(ham.baskin_hex),
            palette=[_hex_normalize(x) for x in (ham.palette or [])],
            ortalama_rgb=_rgb_tuple(ham.ortalama_rgb),
        )
    if isinstance(ham, str):
        hex_r = _hex_normalize(ham)
        return RenkOzeti(
            baskin_hex=hex_r,
            palette=[hex_r],
            ortalama_rgb=(
                int(hex_r[1:3], 16),
                int(hex_r[3:5], 16),
                int(hex_r[5:7], 16),
            ),
        )
    if isinstance(ham, dict):
        # Wire veya Türkçe anahtarlar
        baskin = ham.get("dominant_hex") or ham.get("baskin_hex") or ham.get("hex")
        palette_ham = ham.get("palette") or ham.get("palet") or []
        mean = ham.get("mean_rgb") or ham.get("ortalama_rgb") or ham.get("rgb")
        if baskin is None and mean is None and not palette_ham:
            # belki doğrudan RenkOzeti.from_dict uyumlu
            if any(k in ham for k in ("dominant_hex", "palette", "mean_rgb")):
                return RenkOzeti.from_dict(ham)
            return None
        ozet = RenkOzeti(
            baskin_hex=_hex_normalize(baskin) if baskin is not None else "#000000",
            palette=[_hex_normalize(x) for x in (palette_ham or [])],
            ortalama_rgb=_rgb_tuple(mean) if mean is not None else (0, 0, 0),
        )
        if ozet.baskin_hex == "#000000" and ozet.ortalama_rgb != (0, 0, 0):
            r, g, b = ozet.ortalama_rgb
            ozet.baskin_hex = _rgb_hex(r, g, b)
        if not ozet.palette and ozet.baskin_hex:
            ozet.palette = [ozet.baskin_hex]
        if ozet.ortalama_rgb == (0, 0, 0) and ozet.baskin_hex != "#000000":
            hx = ozet.baskin_hex
            ozet.ortalama_rgb = (
                int(hx[1:3], 16),
                int(hx[3:5], 16),
                int(hx[5:7], 16),
            )
        return ozet
    return None


class RenkAnalizci(ModulTabani):
    """
    Vision renk analizi.

    1) dry_run → renk=None + plan meta
    2) zorla_sahte / motor yok → sahte RenkOzeti
    3) Enjekte analyzer → OpenCV motoru ile çağrı
    4) OpenCV heuristik (ortalama + k-means palet)
    """

    ad = "vision.analiz.renk"
    surum = "0.1.0"
    aciklama = "Renk analizi — OpenCV heuristik, dry_run / sahte fallback"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        palet_boyutu: Optional[int] = None,
        analyzer: Optional[AnalyzerTuru] = None,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
        olay_yayinla: bool = True,
        varsayilan_sahte: Optional[RenkOzeti] = None,
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
        self.varsayilan_sahte = _sahte_renk_kopyala(varsayilan_sahte)

        cfg_palet = self.ayarlar.al("vision.analiz.palette_size", VARSAYILAN_PALET_BOYUTU)
        try:
            varsayilan = int(cfg_palet if cfg_palet is not None else VARSAYILAN_PALET_BOYUTU)
        except (TypeError, ValueError):
            varsayilan = VARSAYILAN_PALET_BOYUTU
        boyut = palet_boyutu if palet_boyutu is not None else varsayilan
        self.palet_boyutu = max(1, min(16, int(boyut)))

        cfg = self.ayarlar.al("vision.analiz.color_fake", None)
        if isinstance(cfg, dict) and not zorla_sahte:
            ozel = _renk_normalize(cfg)
            if ozel is not None:
                self.varsayilan_sahte = ozel

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
        """opencv_kmeans | injected | sahte | dry_run."""
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
            "palette_size": int(self.palet_boyutu),
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
            "vision.analysis.color.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_RENK_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "Renk analizci basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.analysis.color.stopped", {"engine": self._motor})
        self._yayin(OLAY_RENK_DURDU, {"engine": self._motor})
        self._log.info("Renk analizci durdu")

    # ------------------------------------------------------------------ API

    def analiz(
        self,
        girdi: GirdiTuru,
        *,
        palet_boyutu: Optional[int] = None,
        sahte_renk: Optional[RenkOzeti] = None,
    ) -> AnalizSonucu:
        """
        Görüntüde renk analizi → AnalizSonucu (renk alanı dolu).

        dry_run → renk=None.
        zorla_sahte / motor yok → sahte RenkOzeti.
        """
        kaynak_yol = self._kaynak_yol(girdi)
        k = (
            max(1, min(16, int(palet_boyutu)))
            if palet_boyutu is not None
            else self.palet_boyutu
        )

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = AnalizSonucu(
                renk=None,
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                kaynak_yol=kaynak_yol,
                neden="dry_run",
            )
            return self._sonucla(sonuc)

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            renk = _sahte_renk_kopyala(
                sahte_renk if sahte_renk is not None else self.varsayilan_sahte
            )
            # Palet boyutunu kısalt (isteğe bağlı)
            if renk.palette and len(renk.palette) > k:
                renk.palette = list(renk.palette[:k])
            sonuc = AnalizSonucu(
                renk=renk,
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
                kod="VIS_0622",
                modul=self.ad,
            ) from exc

        try:
            renk, neden = self._analiz_matris(mat, palet_boyutu=k)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.warning("Renk analizi basarisiz → sahte: %s", exc)
            renk = _sahte_renk_kopyala(
                sahte_renk if sahte_renk is not None else self.varsayilan_sahte
            )
            sonuc = AnalizSonucu(
                renk=renk,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden=f"analiz_hata:{exc}",
            )
            return self._sonucla(sonuc)

        sonuc = AnalizSonucu(
            renk=renk,
            motor=VisionMotoru.OPENCV,
            dry_run=False,
            kaynak_yol=kaynak_yol,
            neden=neden,
        )
        return self._sonucla(sonuc)

    def ozet_renk(
        self,
        girdi: GirdiTuru,
        *,
        palet_boyutu: Optional[int] = None,
        sahte_renk: Optional[RenkOzeti] = None,
    ) -> Optional[RenkOzeti]:
        """Yalnızca RenkOzeti döndüren kısayol."""
        return self.analiz(
            girdi,
            palet_boyutu=palet_boyutu,
            sahte_renk=sahte_renk,
        ).renk

    def baskin_hex(
        self,
        girdi: GirdiTuru,
        *,
        sahte_renk: Optional[RenkOzeti] = None,
    ) -> str:
        """Yalnızca baskın hex döndüren kısayol."""
        renk = self.ozet_renk(girdi, sahte_renk=sahte_renk)
        if renk is None:
            return ""
        return str(renk.baskin_hex or "")

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
            return "opencv_kmeans"
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
                    kod="VIS_0621",
                    modul=self.ad,
                )
            if isinstance(girdi, (bytes, bytearray)):
                return bytes(girdi)
            if isinstance(girdi, (str, Path)):
                p = Path(girdi).expanduser()
                if not p.is_file():
                    raise VisionError(
                        f"Goruntu yok: {p}",
                        kod="VIS_0622",
                        modul=self.ad,
                    )
                return p.read_bytes()
            return girdi

        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yuklu degil",
                kod="VIS_0621",
                modul=self.ad,
            )

        if isinstance(girdi, Kare):
            if girdi.ham:
                return self._bayttan_matris(bytes(girdi.ham))
            if girdi.yol:
                return self._yoldan_matris(girdi.yol)
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0621",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            return self._bayttan_matris(bytes(girdi))

        if isinstance(girdi, (str, Path)):
            return self._yoldan_matris(str(girdi))

        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen renk analizi girdisi: {type(girdi)!r}",
            kod="VIS_0621",
            modul=self.ad,
        )

    def _yoldan_matris(self, yol: str) -> Any:
        p = Path(yol).expanduser()
        if not p.is_file():
            raise VisionError(
                f"Goruntu yok: {p}",
                kod="VIS_0622",
                modul=self.ad,
            )
        mat = self._cv2.imread(str(p), self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                f"Goruntu okunamadi: {p}",
                kod="VIS_0622",
                modul=self.ad,
            )
        return mat

    def _bayttan_matris(self, ham: bytes) -> Any:
        if not ham:
            raise VisionError(
                "Bos goruntu baytlari",
                kod="VIS_0621",
                modul=self.ad,
            )
        buf = self._np.frombuffer(ham, dtype=self._np.uint8)
        mat = self._cv2.imdecode(buf, self._cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                "Bayt goruntu cozulemedi",
                kod="VIS_0622",
                modul=self.ad,
            )
        return mat

    # ------------------------------------------------------------------ iç — analiz

    def _analiz_matris(
        self, mat: Any, *, palet_boyutu: int
    ) -> tuple[RenkOzeti, str]:
        """Matris üzerinde renk analizi; (RenkOzeti, neden/backend)."""
        if self._analyzer is not None:
            ham = self._analyzer(mat)
            renk = _renk_normalize(ham)
            if renk is None:
                raise VisionError(
                    "Analyzer bos renk dondurdu",
                    kod="VIS_0623",
                    modul=self.ad,
                )
            if renk.palette and len(renk.palette) > palet_boyutu:
                renk.palette = list(renk.palette[:palet_boyutu])
            return renk, "injected"

        if (self._cv2 is not None or opencv_var_mi()) and (
            self._np is not None or numpy_var_mi()
        ):
            return self._heuristik_analiz(mat, palet_boyutu=palet_boyutu), "opencv_kmeans"

        raise VisionError(
            "Renk analizi motoru yok (OpenCV)",
            kod="VIS_0623",
            modul=self.ad,
        )

    def _heuristik_analiz(self, mat: Any, *, palet_boyutu: int) -> RenkOzeti:
        """
        OpenCV ile hafif renk heuristiği → RenkOzeti.

        Küçük yeniden boyut + k-means (veya histogram yedek).
        """
        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yok",
                kod="VIS_0621",
                modul=self.ad,
            )

        girdi = mat
        shape = getattr(mat, "shape", None)
        if shape is None or len(shape) < 2:
            raise VisionError(
                "Gecersiz goruntu matrisi",
                kod="VIS_0622",
                modul=self.ad,
            )
        if len(shape) == 2:
            girdi = cv2.cvtColor(mat, cv2.COLOR_GRAY2BGR)
        elif len(shape) == 3 and shape[2] == 4:
            girdi = cv2.cvtColor(mat, cv2.COLOR_BGRA2BGR)

        # Hız için küçült
        h, w = girdi.shape[:2]
        max_kenar = 160
        if max(h, w) > max_kenar:
            olcek = max_kenar / float(max(h, w))
            girdi = cv2.resize(
                girdi,
                (max(1, int(w * olcek)), max(1, int(h * olcek))),
                interpolation=cv2.INTER_AREA,
            )

        # Ortalama BGR → RGB
        ortalama_bgr = np.mean(girdi.reshape(-1, 3), axis=0)
        ortalama_rgb = (
            _kanal_sinirla(ortalama_bgr[2]),
            _kanal_sinirla(ortalama_bgr[1]),
            _kanal_sinirla(ortalama_bgr[0]),
        )

        k = max(1, min(16, int(palet_boyutu)))
        palette_rgb = self._kmeans_palet(girdi, k=k)
        if not palette_rgb:
            palette_rgb = [ortalama_rgb]

        baskin = palette_rgb[0]
        return RenkOzeti(
            baskin_hex=_rgb_hex(*baskin),
            palette=[_rgb_hex(*c) for c in palette_rgb],
            ortalama_rgb=ortalama_rgb,
        )

    def _kmeans_palet(
        self, bgr: Any, *, k: int
    ) -> list[tuple[int, int, int]]:
        """OpenCV k-means ile baskın renkler (RGB, sıklığa göre)."""
        cv2 = self._cv2
        np = self._np
        assert cv2 is not None and np is not None

        pikseller = bgr.reshape((-1, 3)).astype(np.float32)
        if pikseller.shape[0] == 0:
            return []

        # Çok az piksel → k'yi düşür
        k_eff = max(1, min(k, int(pikseller.shape[0])))
        kriter = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
            20,
            1.0,
        )
        try:
            _compact, etiketler, merkezler = cv2.kmeans(
                pikseller,
                k_eff,
                None,
                kriter,
                3,
                cv2.KMEANS_PP_CENTERS,
            )
        except Exception:  # noqa: BLE001
            # Yedek: basit ortalama + örnek noktalar
            return self._histogram_palet(bgr, k=k_eff)

        etiketler = etiketler.flatten()
        sayilar = [int(np.sum(etiketler == i)) for i in range(k_eff)]
        sirali = sorted(range(k_eff), key=lambda i: sayilar[i], reverse=True)

        out: list[tuple[int, int, int]] = []
        for i in sirali:
            b, g, r = merkezler[i]
            out.append(
                (
                    _kanal_sinirla(r),
                    _kanal_sinirla(g),
                    _kanal_sinirla(b),
                )
            )
        return out

    def _histogram_palet(
        self, bgr: Any, *, k: int
    ) -> list[tuple[int, int, int]]:
        """K-means başarısız olursa kaba 4-bit histogram yedek."""
        np = self._np
        assert np is not None
        # 16 seviye kuantizasyon
        q = (bgr // 16) * 16 + 8
        duz = q.reshape(-1, 3)
        # Benzersiz satırlar + sayım
        try:
            uniq, counts = np.unique(duz, axis=0, return_counts=True)
            idx = np.argsort(-counts)[:k]
            out: list[tuple[int, int, int]] = []
            for i in idx:
                b, g, r = uniq[i]
                out.append(
                    (
                        _kanal_sinirla(r),
                        _kanal_sinirla(g),
                        _kanal_sinirla(b),
                    )
                )
            return out
        except Exception:  # noqa: BLE001
            mean = np.mean(bgr.reshape(-1, 3), axis=0)
            return [
                (
                    _kanal_sinirla(mean[2]),
                    _kanal_sinirla(mean[1]),
                    _kanal_sinirla(mean[0]),
                )
            ]

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(self, sonuc: AnalizSonucu) -> AnalizSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        if sonuc.neden in ("injected", "opencv_kmeans"):
            self._backend = str(sonuc.neden)
        elif sonuc.dry_run:
            self._backend = "dry_run"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"
        renk = sonuc.renk
        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "dominant_hex": renk.baskin_hex if renk else None,
            "palette_count": len(renk.palette) if renk else 0,
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.analysis.color.analyzed", detay)
        self._yayin(OLAY_RENK_ANALIZ, sonuc.to_dict())
        self._log.debug(
            "Renk analizi tamam motor=%s baskin=%s",
            sonuc.motor.value,
            renk.baskin_hex if renk else None,
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


def renk_analizci_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    palet_boyutu: int = VARSAYILAN_PALET_BOYUTU,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    analyzer: Optional[AnalyzerTuru] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    olay_yayinla: bool = False,
    varsayilan_sahte: Optional[RenkOzeti] = None,
) -> RenkAnalizci:
    """Test / demo için güvenli varsayılanlarla RenkAnalizci üretir."""
    return RenkAnalizci(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        palet_boyutu=palet_boyutu,
        analyzer=analyzer,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        olay_yayinla=olay_yayinla,
        varsayilan_sahte=varsayilan_sahte,
    )


def renk_analiz(
    girdi: GirdiTuru,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    palet_boyutu: int = VARSAYILAN_PALET_BOYUTU,
    sahte_renk: Optional[RenkOzeti] = None,
    analyzer: Optional[AnalyzerTuru] = None,
) -> AnalizSonucu:
    """Tek çağrılık renk analizi yardımcısı."""
    r = renk_analizci_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        palet_boyutu=palet_boyutu,
        analyzer=analyzer,
        olay_yayinla=False,
    )
    return r.analiz(girdi, palet_boyutu=palet_boyutu, sahte_renk=sahte_renk)


__all__ = [
    "OLAY_RENK_ANALIZ",
    "OLAY_RENK_BASLADI",
    "OLAY_RENK_DURDU",
    "VARSAYILAN_PALET_BOYUTU",
    "RenkAnalizci",
    "opencv_var_mi",
    "numpy_var_mi",
    "renk_analizci_olustur",
    "renk_analiz",
]

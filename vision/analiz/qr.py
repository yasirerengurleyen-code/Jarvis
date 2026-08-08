"""
vision/analiz/qr.py
-------------------
QR + barkod okuma — skills/media/qr_okuyucu köprüsü, dry_run / sahte fallback.

Görev:
- Görüntüden QR kod(lar) (`AnalizSonucu.qr_verileri`)
- Görüntüden barkod(lar) (`AnalizSonucu.barkodlar`) — isteğe bağlı pyzbar / OpenCV
- `skills/media/qr_okuyucu` sarmalayıcısını yeniden yazmaz; köprüler
- Enjekte edilebilir decoder (birim test / özel motor)
- OpenCV / bağımlılık yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Yüz / Vision AI → sonraki dosyalar; bu modül yalnızca QR + barkod.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from skills.media import qr_okuyucu as skill_qr
from vision.modeller import AnalizSonucu, Kare, VisionMotoru, motor_coz

log = logger_al("vision.analiz.qr")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_QR_OKUNDU = "vision.analysis.qr.read"
OLAY_QR_BASLADI = "vision.analysis.qr.started"
OLAY_QR_DURDU = "vision.analysis.qr.stopped"

# Sahte / dry_run için örnek veriler (CI / offline)
_SAHTE_QR = "https://whitecore.local/sahte-qr"
_SAHTE_BARKOD = "8690000000000"

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# decoder(mat) → AnalizSonucu | dict | list[str] | tuple[list[str], list[str]]
DecoderTuru = Callable[[Any], Any]

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
    """OpenCV kullanılabilir mi? (skill köprüsü öncelikli)."""
    return bool(_CV2_VAR) or bool(skill_qr.opencv_var_mi())


def numpy_var_mi() -> bool:
    """numpy kullanılabilir mi?"""
    return bool(_NUMPY_VAR)


def pyzbar_var_mi() -> bool:
    """pyzbar paketi yüklü mü? (isteğe bağlı barkod)."""
    try:
        import pyzbar  # noqa: F401

        return True
    except ImportError:
        return False


def _metin_listesi(ham: Any) -> list[str]:
    """str / list / tuple → temiz metin listesi (benzersiz sıra korunur)."""
    if ham is None:
        return []
    if isinstance(ham, str):
        t = ham.strip()
        return [t] if t else []
    if isinstance(ham, (list, tuple)):
        out: list[str] = []
        for x in ham:
            t = str(x or "").strip()
            if t and t not in out:
                out.append(t)
        return out
    t = str(ham).strip()
    return [t] if t else []


def _sahte_qr_listesi(kaynak: Optional[Sequence[str]] = None) -> list[str]:
    """Sahte QR listesi (kopya)."""
    if kaynak is not None:
        return _metin_listesi(kaynak) or [_SAHTE_QR]
    return [_SAHTE_QR]


def _sahte_barkod_listesi(kaynak: Optional[Sequence[str]] = None) -> list[str]:
    """Sahte barkod listesi (kopya)."""
    if kaynak is not None:
        return _metin_listesi(kaynak) or [_SAHTE_BARKOD]
    return [_SAHTE_BARKOD]


def _decoder_sonucunu_ayikla(ham: Any) -> tuple[list[str], list[str]]:
    """
    Enjekte decoder çıktısını (qr_listesi, barkod_listesi) yapar.

    Desteklenen biçimler:
    - AnalizSonucu
    - dict: qr / codes / barcodes / barkodlar
    - list[str] → yalnızca QR
    - (qr_list, barcode_list)
    - str → tek QR
    """
    if ham is None:
        return [], []
    if isinstance(ham, AnalizSonucu):
        return list(ham.qr_verileri or []), list(ham.barkodlar or [])
    if isinstance(ham, dict):
        qr = (
            ham.get("qr")
            or ham.get("codes")
            or ham.get("qr_verileri")
            or ham.get("data")
        )
        barkod = ham.get("barcodes") or ham.get("barkodlar") or ham.get("barcode")
        # Tek "data" str ise QR say
        if isinstance(qr, str) or qr is None:
            qr_list = _metin_listesi(qr)
        else:
            qr_list = _metin_listesi(qr)
        return qr_list, _metin_listesi(barkod)
    if isinstance(ham, tuple) and len(ham) == 2:
        return _metin_listesi(ham[0]), _metin_listesi(ham[1])
    if isinstance(ham, (list, tuple)):
        return _metin_listesi(ham), []
    if isinstance(ham, str):
        return _metin_listesi(ham), []
    return [], []


def _skill_motordan(engine: Optional[str]) -> VisionMotoru:
    """skills/media/qr_okuyucu motor adını VisionMotoru'ya çevirir."""
    metin = str(engine or "").strip().lower()
    if not metin:
        return VisionMotoru.SAHTE
    return motor_coz(metin)


class QrAnalizci(ModulTabani):
    """
    Vision QR + barkod okuyucu.

    1) dry_run → boş listeler + plan meta
    2) zorla_sahte / motor yok → sahte QR (+ isteğe bağlı barkod)
    3) Enjekte decoder → OpenCV motoru ile çağrı
    4) Dosya yolu → skills/media/qr_okuyucu köprüsü + barkod denemesi
    5) OpenCV QRCodeDetector / isteğe bağlı pyzbar veya cv2.barcode
    """

    ad = "vision.analiz.qr"
    surum = "0.1.0"
    aciklama = "QR + barkod — skill köprüsü, dry_run / sahte fallback"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        decoder: Optional[DecoderTuru] = None,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
        pyzbar_modul: Any = None,
        olay_yayinla: bool = True,
        varsayilan_sahte_qr: Optional[Sequence[str]] = None,
        varsayilan_sahte_barkod: Optional[Sequence[str]] = None,
        barkod_oku: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self.barkod_oku = bool(barkod_oku)
        self._decoder = decoder
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np
        self._pyzbar = pyzbar_modul
        self.varsayilan_sahte_qr = _sahte_qr_listesi(varsayilan_sahte_qr)
        self.varsayilan_sahte_barkod = _sahte_barkod_listesi(varsayilan_sahte_barkod)

        cfg_qr = self.ayarlar.al("vision.analiz.qr_fake", None)
        if isinstance(cfg_qr, (str, list, tuple)) and not zorla_sahte:
            self.varsayilan_sahte_qr = _sahte_qr_listesi(
                [cfg_qr] if isinstance(cfg_qr, str) else cfg_qr
            )
        cfg_bc = self.ayarlar.al("vision.analiz.barcode_fake", None)
        if isinstance(cfg_bc, (str, list, tuple)) and not zorla_sahte:
            self.varsayilan_sahte_barkod = _sahte_barkod_listesi(
                [cfg_bc] if isinstance(cfg_bc, str) else cfg_bc
            )

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
        """skill | opencv | injected | pyzbar | sahte | dry_run."""
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
            "pyzbar": self._pyzbar is not None or pyzbar_var_mi(),
            "barcode": bool(self.barkod_oku),
            "injected": self._decoder is not None,
            "skill_bridge": True,
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
            "vision.analysis.qr.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_QR_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "QR analizci basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.analysis.qr.stopped", {"engine": self._motor})
        self._yayin(OLAY_QR_DURDU, {"engine": self._motor})
        self._log.info("QR analizci durdu")

    # ------------------------------------------------------------------ API

    def analiz(
        self,
        girdi: GirdiTuru,
        *,
        sahte_qr: Optional[Sequence[str]] = None,
        sahte_barkod: Optional[Sequence[str]] = None,
        barkod_oku: Optional[bool] = None,
    ) -> AnalizSonucu:
        """
        Görüntüde QR (+ isteğe bağlı barkod) okur → AnalizSonucu.

        dry_run → boş listeler.
        zorla_sahte / motor yok → sahte QR / barkod.
        """
        kaynak_yol = self._kaynak_yol(girdi)
        bc_aktif = self.barkod_oku if barkod_oku is None else bool(barkod_oku)

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = AnalizSonucu(
                qr_verileri=[],
                barkodlar=[],
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                kaynak_yol=kaynak_yol,
                neden="dry_run",
            )
            return self._sonucla(sonuc, backend="dry_run")

        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            qr = _sahte_qr_listesi(
                sahte_qr if sahte_qr is not None else self.varsayilan_sahte_qr
            )
            barkod = (
                _sahte_barkod_listesi(
                    sahte_barkod
                    if sahte_barkod is not None
                    else self.varsayilan_sahte_barkod
                )
                if bc_aktif
                else []
            )
            sonuc = AnalizSonucu(
                qr_verileri=qr,
                barkodlar=barkod,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            return self._sonucla(sonuc, backend="sahte")

        # Enjekte decoder — matris veya ham bayt
        if self._decoder is not None:
            try:
                mat = self._yukle(girdi)
                qr, barkod = _decoder_sonucunu_ayikla(self._decoder(mat))
            except VisionError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise VisionError(
                    f"Decoder basarisiz: {exc}",
                    kod="VIS_0633",
                    modul=self.ad,
                ) from exc
            if not bc_aktif:
                barkod = []
            sonuc = AnalizSonucu(
                qr_verileri=qr,
                barkodlar=barkod,
                motor=VisionMotoru.OPENCV,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden="injected",
            )
            return self._sonucla(sonuc, backend="injected")

        # Dosya yolu → skill köprüsü (QR) + yerel barkod
        yol = self._dosya_yolu(girdi)
        if yol is not None:
            return self._skill_ile_oku(
                yol,
                kaynak_yol=kaynak_yol or str(yol),
                barkod_oku=bc_aktif,
                sahte_qr=sahte_qr,
                sahte_barkod=sahte_barkod,
            )

        # Bellek / matris → OpenCV (+ barkod)
        try:
            mat = self._yukle(girdi)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError(
                f"Goruntu yuklenemedi: {exc}",
                kod="VIS_0632",
                modul=self.ad,
            ) from exc

        try:
            qr, barkod, neden = self._opencv_ile_oku(mat, barkod_oku=bc_aktif)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.warning("QR/barkod analizi basarisiz → sahte: %s", exc)
            qr = _sahte_qr_listesi(
                sahte_qr if sahte_qr is not None else self.varsayilan_sahte_qr
            )
            barkod = (
                _sahte_barkod_listesi(
                    sahte_barkod
                    if sahte_barkod is not None
                    else self.varsayilan_sahte_barkod
                )
                if bc_aktif
                else []
            )
            sonuc = AnalizSonucu(
                qr_verileri=qr,
                barkodlar=barkod,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden=f"analiz_hata:{exc}",
            )
            return self._sonucla(sonuc, backend="sahte")

        sonuc = AnalizSonucu(
            qr_verileri=qr,
            barkodlar=barkod,
            motor=VisionMotoru.OPENCV,
            dry_run=False,
            kaynak_yol=kaynak_yol,
            neden=neden,
        )
        return self._sonucla(sonuc, backend=neden)

    def oku(
        self,
        girdi: GirdiTuru,
        *,
        sahte_qr: Optional[Sequence[str]] = None,
        sahte_barkod: Optional[Sequence[str]] = None,
        barkod_oku: Optional[bool] = None,
    ) -> AnalizSonucu:
        """analiz() için eş anlamlı kısayol."""
        return self.analiz(
            girdi,
            sahte_qr=sahte_qr,
            sahte_barkod=sahte_barkod,
            barkod_oku=barkod_oku,
        )

    def qr_listesi(
        self,
        girdi: GirdiTuru,
        *,
        sahte_qr: Optional[Sequence[str]] = None,
    ) -> list[str]:
        """Yalnızca QR metinlerini döndüren kısayol."""
        return list(
            self.analiz(girdi, sahte_qr=sahte_qr, barkod_oku=False).qr_verileri or []
        )

    def barkod_listesi(
        self,
        girdi: GirdiTuru,
        *,
        sahte_barkod: Optional[Sequence[str]] = None,
    ) -> list[str]:
        """Yalnızca barkod metinlerini döndüren kısayol."""
        return list(
            self.analiz(
                girdi,
                sahte_barkod=sahte_barkod,
                barkod_oku=True,
            ).barkodlar
            or []
        )

    def ilk_qr(
        self,
        girdi: GirdiTuru,
        *,
        sahte_qr: Optional[Sequence[str]] = None,
    ) -> str:
        """İlk QR metni (yoksa boş str)."""
        liste = self.qr_listesi(girdi, sahte_qr=sahte_qr)
        return liste[0] if liste else ""

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._decoder is not None:
            return VisionMotoru.OPENCV.value
        if self._cv2 is not None or opencv_var_mi():
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _backend_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._decoder is not None:
            return "injected"
        if self._cv2 is not None or opencv_var_mi():
            return "skill"
        return "sahte"

    def _cv2_coz(self) -> Any:
        if self._cv2 is not None:
            return self._cv2
        if skill_qr.opencv_var_mi():
            return skill_qr._cv2  # noqa: SLF001 — bilinçli köprü
        if _CV2_VAR:
            return _cv2
        return None

    def _np_coz(self) -> Any:
        if self._np is not None:
            return self._np
        if _NUMPY_VAR:
            return _np
        return None

    # ------------------------------------------------------------------ iç — girdi

    def _kaynak_yol(self, girdi: GirdiTuru) -> Optional[str]:
        if isinstance(girdi, Kare):
            return girdi.yol
        if isinstance(girdi, Path):
            return str(girdi)
        if isinstance(girdi, str):
            return girdi
        return None

    def _dosya_yolu(self, girdi: GirdiTuru) -> Optional[Path]:
        """Var olan görüntü dosyası yolu (skill köprüsü için)."""
        if isinstance(girdi, Kare) and girdi.yol:
            p = Path(girdi.yol).expanduser()
            return p if p.is_file() else None
        if isinstance(girdi, Path):
            p = girdi.expanduser()
            return p if p.is_file() else None
        if isinstance(girdi, str):
            # scheme'li sahte yollar (image:// …) dosya değil
            if "://" in girdi and not girdi.lower().startswith("file:"):
                return None
            p = Path(girdi).expanduser()
            return p if p.is_file() else None
        return None

    def _yukle(self, girdi: GirdiTuru) -> Any:
        """Görüntüyü OpenCV matrisine (veya ham bayta) yükler."""
        if self._decoder is not None and self._cv2_coz() is None:
            if isinstance(girdi, Kare):
                if girdi.ham:
                    return bytes(girdi.ham)
                if girdi.yol and Path(girdi.yol).expanduser().is_file():
                    return Path(girdi.yol).expanduser().read_bytes()
                raise VisionError(
                    "Kare'de yol veya ham veri yok",
                    kod="VIS_0631",
                    modul=self.ad,
                )
            if isinstance(girdi, (bytes, bytearray)):
                return bytes(girdi)
            if isinstance(girdi, (str, Path)):
                p = Path(girdi).expanduser()
                if not p.is_file():
                    raise VisionError(
                        f"Goruntu yok: {p}",
                        kod="VIS_0632",
                        modul=self.ad,
                    )
                return p.read_bytes()
            return girdi

        cv2 = self._cv2_coz()
        np = self._np_coz()
        if cv2 is None or np is None:
            raise VisionError(
                "OpenCV/numpy yuklu degil",
                kod="VIS_0631",
                modul=self.ad,
            )

        if isinstance(girdi, Kare):
            if girdi.ham:
                return self._bayttan_matris(bytes(girdi.ham))
            if girdi.yol:
                return self._yoldan_matris(girdi.yol)
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0631",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            return self._bayttan_matris(bytes(girdi))

        if isinstance(girdi, (str, Path)):
            return self._yoldan_matris(str(girdi))

        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen QR/barkod girdisi: {type(girdi)!r}",
            kod="VIS_0631",
            modul=self.ad,
        )

    def _yoldan_matris(self, yol: str) -> Any:
        p = Path(yol).expanduser()
        if not p.is_file():
            raise VisionError(
                f"Goruntu yok: {p}",
                kod="VIS_0632",
                modul=self.ad,
            )
        cv2 = self._cv2_coz()
        np = self._np_coz()
        assert cv2 is not None and np is not None
        # Unicode yol: bytes + imdecode (skill ile aynı)
        try:
            ham = p.read_bytes()
            buf = np.frombuffer(ham, dtype=np.uint8)
            mat = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if mat is not None:
                return mat
        except Exception:  # noqa: BLE001
            pass
        mat = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                f"Goruntu okunamadi: {p}",
                kod="VIS_0632",
                modul=self.ad,
            )
        return mat

    def _bayttan_matris(self, ham: bytes) -> Any:
        if not ham:
            raise VisionError(
                "Bos goruntu baytlari",
                kod="VIS_0631",
                modul=self.ad,
            )
        cv2 = self._cv2_coz()
        np = self._np_coz()
        assert cv2 is not None and np is not None
        buf = np.frombuffer(ham, dtype=np.uint8)
        mat = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if mat is None:
            raise VisionError(
                "Bayt goruntu cozulemedi",
                kod="VIS_0632",
                modul=self.ad,
            )
        return mat

    # ------------------------------------------------------------------ iç — skill / opencv

    def _skill_ile_oku(
        self,
        yol: Path,
        *,
        kaynak_yol: str,
        barkod_oku: bool,
        sahte_qr: Optional[Sequence[str]],
        sahte_barkod: Optional[Sequence[str]],
    ) -> AnalizSonucu:
        """skills/media/qr_okuyucu.qr_oku köprüsü + yerel barkod."""
        try:
            bil = skill_qr.qr_oku(
                yol,
                dry_run=False,
                zorla_sahte=False,
                cv2_modul=self._cv2_coz(),
            )
        except FileNotFoundError as exc:
            raise VisionError(
                f"Goruntu yok: {yol}",
                kod="VIS_0632",
                modul=self.ad,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            self._log.warning("Skill QR basarisiz → sahte: %s", exc)
            qr = _sahte_qr_listesi(
                sahte_qr if sahte_qr is not None else self.varsayilan_sahte_qr
            )
            barkod = (
                _sahte_barkod_listesi(
                    sahte_barkod
                    if sahte_barkod is not None
                    else self.varsayilan_sahte_barkod
                )
                if barkod_oku
                else []
            )
            sonuc = AnalizSonucu(
                qr_verileri=qr,
                barkodlar=barkod,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                kaynak_yol=kaynak_yol,
                neden=f"skill_hata:{exc}",
            )
            return self._sonucla(sonuc, backend="sahte")

        motor = _skill_motordan(bil.get("engine"))
        qr = _metin_listesi(bil.get("codes") or bil.get("data"))
        neden = str(bil.get("reason") or "skill")
        if motor == VisionMotoru.SAHTE and sahte_qr is not None:
            qr = _sahte_qr_listesi(sahte_qr)

        barkod: list[str] = []
        if barkod_oku and motor == VisionMotoru.OPENCV:
            try:
                mat = self._yoldan_matris(str(yol))
                barkod = self._barkod_coz(mat)
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Barkod okunamadi: %s", exc)
        elif barkod_oku and motor == VisionMotoru.SAHTE:
            barkod = _sahte_barkod_listesi(
                sahte_barkod
                if sahte_barkod is not None
                else self.varsayilan_sahte_barkod
            )

        sonuc = AnalizSonucu(
            qr_verileri=qr,
            barkodlar=barkod,
            motor=motor,
            dry_run=bool(bil.get("dry_run", False)),
            kaynak_yol=kaynak_yol,
            neden=neden,
        )
        backend = "skill" if motor == VisionMotoru.OPENCV else motor.value
        return self._sonucla(sonuc, backend=backend)

    def _opencv_ile_oku(
        self, mat: Any, *, barkod_oku: bool
    ) -> tuple[list[str], list[str], str]:
        """Matris üzerinde QR (+ barkod); (qr, barkod, neden)."""
        cv2 = self._cv2_coz()
        if cv2 is None:
            raise VisionError(
                "QR analizi motoru yok (OpenCV)",
                kod="VIS_0633",
                modul=self.ad,
            )

        qr = self._qr_coz_opencv(cv2, mat)
        barkod = self._barkod_coz(mat) if barkod_oku else []
        if not qr and not barkod:
            return [], [], "qr_bulunamadi"
        neden = "opencv"
        if barkod and not qr:
            neden = "barcode"
        elif barkod:
            neden = "opencv+barcode"
        return qr, barkod, neden

    def _qr_coz_opencv(self, cv: Any, img: Any) -> list[str]:
        """OpenCV QRCodeDetector — skill ile aynı mantık."""
        # Skill iç yardımcılarını tercih et (tek kaynak)
        try:
            return list(skill_qr._qr_coz_opencv(cv, img))  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass

        detector = cv.QRCodeDetector()
        sonuclar: list[str] = []

        if hasattr(detector, "detectAndDecodeMulti"):
            try:
                ok, veriler, _pts, _ = detector.detectAndDecodeMulti(img)
                if ok and veriler:
                    for v in veriler:
                        metin = (
                            (v or "").strip()
                            if isinstance(v, str)
                            else str(v or "").strip()
                        )
                        if metin and metin not in sonuclar:
                            sonuclar.append(metin)
                    if sonuclar:
                        return sonuclar
            except Exception:  # noqa: BLE001
                pass

        data, _pts, _ = detector.detectAndDecode(img)
        metin = (data or "").strip() if isinstance(data, str) else str(data or "").strip()
        if metin:
            sonuclar.append(metin)
        return sonuclar

    def _barkod_coz(self, mat: Any) -> list[str]:
        """pyzbar veya OpenCV barcode_BarcodeDetector ile barkod."""
        # 1) Enjekte / mevcut pyzbar
        pz = self._pyzbar
        if pz is None and pyzbar_var_mi():
            try:
                from pyzbar import pyzbar as pz  # type: ignore
            except ImportError:  # pragma: no cover
                pz = None
        if pz is not None:
            try:
                decode = getattr(pz, "decode", None)
                if decode is None and hasattr(pz, "pyzbar"):
                    decode = getattr(pz.pyzbar, "decode", None)
                if decode is not None:
                    out: list[str] = []
                    for nesne in decode(mat) or []:
                        ham = getattr(nesne, "data", b"")
                        if isinstance(ham, (bytes, bytearray)):
                            metin = ham.decode("utf-8", errors="replace").strip()
                        else:
                            metin = str(ham or "").strip()
                        # QR'yi barkod listesine koyma — pyzbar QR de dönebilir
                        tip = str(getattr(nesne, "type", "") or "").upper()
                        if tip == "QRCODE":
                            continue
                        if metin and metin not in out:
                            out.append(metin)
                    if out:
                        return out
            except Exception as exc:  # noqa: BLE001
                self._log.debug("pyzbar barkod hatasi: %s", exc)

        # 2) OpenCV contrib barcode (varsa)
        cv2 = self._cv2_coz()
        if cv2 is not None and hasattr(cv2, "barcode_BarcodeDetector"):
            try:
                det = cv2.barcode_BarcodeDetector()
                ok, decoded, _types, _pts = det.detectAndDecode(mat)
                if ok and decoded:
                    return _metin_listesi(decoded)
            except Exception as exc:  # noqa: BLE001
                self._log.debug("OpenCV barcode hatasi: %s", exc)

        return []

    # ------------------------------------------------------------------ iç — olay

    def _sonucla(self, sonuc: AnalizSonucu, *, backend: str) -> AnalizSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        self._backend = backend
        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "qr_count": len(sonuc.qr_verileri or []),
            "barcode_count": len(sonuc.barkodlar or []),
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.analysis.qr.read", detay)
        self._yayin(OLAY_QR_OKUNDU, sonuc.to_dict())
        self._log.debug(
            "QR analizi tamam motor=%s qr=%d barkod=%d",
            sonuc.motor.value,
            len(sonuc.qr_verileri or []),
            len(sonuc.barkodlar or []),
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


def qr_analizci_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    decoder: Optional[DecoderTuru] = None,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    pyzbar_modul: Any = None,
    olay_yayinla: bool = False,
    varsayilan_sahte_qr: Optional[Sequence[str]] = None,
    varsayilan_sahte_barkod: Optional[Sequence[str]] = None,
    barkod_oku: bool = True,
) -> QrAnalizci:
    """Test / demo için güvenli varsayılanlarla QrAnalizci üretir."""
    return QrAnalizci(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        decoder=decoder,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        pyzbar_modul=pyzbar_modul,
        olay_yayinla=olay_yayinla,
        varsayilan_sahte_qr=varsayilan_sahte_qr,
        varsayilan_sahte_barkod=varsayilan_sahte_barkod,
        barkod_oku=barkod_oku,
    )


def qr_analiz(
    girdi: GirdiTuru,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_qr: Optional[Sequence[str]] = None,
    sahte_barkod: Optional[Sequence[str]] = None,
    decoder: Optional[DecoderTuru] = None,
    barkod_oku: bool = True,
) -> AnalizSonucu:
    """Tek çağrılık QR + barkod analizi yardımcısı."""
    r = qr_analizci_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        decoder=decoder,
        olay_yayinla=False,
        barkod_oku=barkod_oku,
    )
    return r.analiz(
        girdi,
        sahte_qr=sahte_qr,
        sahte_barkod=sahte_barkod,
        barkod_oku=barkod_oku,
    )


def qr_oku_gecici(
    ham: bytes,
    *,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    suffix: str = ".png",
) -> AnalizSonucu:
    """Bayt görüntüyü geçici dosyaya yazıp skill köprüsü ile okur (test yardımcısı)."""
    if dry_run or zorla_sahte:
        return qr_analiz(ham, dry_run=dry_run, zorla_sahte=zorla_sahte)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(ham)
        yol = Path(tmp.name)
    try:
        return qr_analiz(yol, dry_run=False, zorla_sahte=False)
    finally:
        try:
            yol.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "OLAY_QR_OKUNDU",
    "OLAY_QR_BASLADI",
    "OLAY_QR_DURDU",
    "QrAnalizci",
    "opencv_var_mi",
    "numpy_var_mi",
    "pyzbar_var_mi",
    "qr_analizci_olustur",
    "qr_analiz",
    "qr_oku_gecici",
]

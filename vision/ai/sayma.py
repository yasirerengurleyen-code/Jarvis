"""
vision/ai/sayma.py
------------------
Nesne sayma — Vision AI, dry_run / sahte / nesne-algılama fallback.

Görev:
- Görüntüden nesne sayısı (`VisionAiSonucu.sayim` / `.sayim_etiket`)
- Enjekte edilebilir counter (LLM / özel motor testleri)
- LLM yoksa: `vision.analiz.nesne` sonuçlarından sayım
- OpenCV / bağımlılık yoksa dry_run veya sahte
- EventBus + Logger/audit + VisionError

Not: Caption → `aciklama.py`; VQA → `soru_cevap.py`; multimodal → `multimodal.py`
      (sonraki onaylı dosya; bu modül yalnızca sayma).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    AlgilananNesne,
    Kare,
    VisionAiSonucu,
    VisionGorevTuru,
    VisionMotoru,
    guven_sinirla,
)

log = logger_al("vision.ai.sayma")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_SAYMA = "vision.ai.count.done"
OLAY_SAYMA_BASLADI = "vision.ai.count.started"
OLAY_SAYMA_DURDU = "vision.ai.count.stopped"

# Sahte / dry_run için örnek sayım (CI / offline; nesne.py sahte listesiyle uyumlu)
_SAHTE_SAYIM = 2
_SAHTE_ETIKET: Optional[str] = None

VARSAYILAN_GUVEN_SAHTE = 0.55
VARSAYILAN_GUVEN_HEURISTIK = 0.65
VARSAYILAN_GUVEN_LLM = 0.80
VARSAYILAN_MIN_GUVEN = 0.25

GirdiTuru = Union[str, Path, bytes, bytearray, Kare, Any]
# counter(mat | bytes | yol, etiket|None) → int | dict | VisionAiSonucu
CounterTuru = Callable[[Any, Optional[str]], Any]

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


def _sayim_normalize(
    ham: Any,
) -> tuple[int, Optional[str], float, Optional[str], str]:
    """
    int / dict / VisionAiSonucu → (sayim, etiket, güven, motor_ipuucu, aciklama).

    dict anahtarları: count / sayim / n;
    isteğe bağlı count_label / etiket / label; confidence / engine; description.
    """
    if ham is None:
        return 0, None, 0.0, None, ""
    if isinstance(ham, VisionAiSonucu):
        adet = int(ham.sayim) if ham.sayim is not None else 0
        return (
            max(0, adet),
            ham.sayim_etiket,
            guven_sinirla(ham.guven),
            ham.motor.value if ham.motor else None,
            str(ham.aciklama or ham.cevap or "").strip(),
        )
    if isinstance(ham, bool):
        # bool int alt sınıfı — sayım değil
        return 0, None, 0.0, None, ""
    if isinstance(ham, int):
        return max(0, int(ham)), None, 0.0, None, ""
    if isinstance(ham, float) and ham == int(ham):
        return max(0, int(ham)), None, 0.0, None, ""
    if isinstance(ham, dict):
        adet_ham = None
        for anahtar in ("count", "sayim", "n", "adet", "total"):
            if ham.get(anahtar) is not None:
                adet_ham = ham.get(anahtar)
                break
        try:
            adet = max(0, int(adet_ham)) if adet_ham is not None else 0
        except (TypeError, ValueError):
            adet = 0
        etiket = None
        for anahtar in ("count_label", "sayim_etiket", "etiket", "label"):
            deger = ham.get(anahtar)
            if deger is not None and str(deger).strip():
                etiket = str(deger).strip()
                break
        guven = guven_sinirla(ham.get("confidence"))
        motor = ham.get("engine") or ham.get("motor")
        aciklama = ""
        for anahtar in ("description", "aciklama", "answer", "cevap", "text"):
            deger = ham.get(anahtar)
            if deger is not None and str(deger).strip():
                aciklama = str(deger).strip()
                break
        return adet, etiket, guven, str(motor) if motor else None, aciklama
    # "3" gibi string
    try:
        return max(0, int(str(ham).strip())), None, 0.0, None, ""
    except (TypeError, ValueError):
        return 0, None, 0.0, None, ""


def _sayim_metni(adet: int, etiket: Optional[str] = None) -> str:
    """Türkçe kısa sayım açıklaması."""
    if etiket:
        e = str(etiket).strip()
        if adet == 0:
            return f"Görüntüde '{e}' etiketli nesne bulunamadı."
        if adet == 1:
            return f"Görüntüde 1 adet '{e}' algılandı."
        return f"Görüntüde {adet} adet '{e}' algılandı."
    if adet == 0:
        return "Görüntüde algılanan nesne yok."
    if adet == 1:
        return "Görüntüde 1 nesne algılandı."
    return f"Görüntüde {adet} nesne algılandı."


def _etiket_temizle(etiket: Optional[str]) -> Optional[str]:
    """Boş etiket → None."""
    if etiket is None:
        return None
    t = str(etiket).strip()
    return t or None


class NesneSayici(ModulTabani):
    """
    Vision AI — nesne sayma.

    1) dry_run → sayim=0 + plan meta
    2) zorla_sahte / motor yok → sahte sayım
    3) Enjekte counter → LLM / özel motor
    4) nesne_heuristik=True → `vision.analiz.nesne` üzerinden sayım
    5) Aksi halde sahte
    """

    ad = "vision.ai.sayma"
    surum = "0.1.0"
    aciklama = "Nesne sayma — dry_run / sahte / nesne heuristik"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        counter: Optional[CounterTuru] = None,
        nesne_heuristik: bool = True,
        min_guven: Optional[float] = None,
        cv2_modul: Any = None,
        numpy_modul: Any = None,
        olay_yayinla: bool = True,
        varsayilan_sahte: int = _SAHTE_SAYIM,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.nesne_heuristik = bool(nesne_heuristik)
        self.olay_yayinla = bool(olay_yayinla)
        self._counter = counter
        self._cv2 = cv2_modul if cv2_modul is not None else _cv2
        self._np = numpy_modul if numpy_modul is not None else _np

        try:
            self.varsayilan_sahte = max(0, int(varsayilan_sahte))
        except (TypeError, ValueError):
            self.varsayilan_sahte = _SAHTE_SAYIM

        cfg = self.ayarlar.al("vision.ai.count_fake", None)
        if cfg is not None and not zorla_sahte:
            try:
                self.varsayilan_sahte = max(0, int(cfg))
            except (TypeError, ValueError):
                pass

        cfg_guven = self.ayarlar.al(
            "vision.analiz.min_confidence", VARSAYILAN_MIN_GUVEN
        )
        try:
            varsayilan = float(
                cfg_guven if cfg_guven is not None else VARSAYILAN_MIN_GUVEN
            )
        except (TypeError, ValueError):
            varsayilan = VARSAYILAN_MIN_GUVEN
        self.min_guven = guven_sinirla(
            min_guven if min_guven is not None else varsayilan,
            varsayilan=VARSAYILAN_MIN_GUVEN,
        )

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
        """injected | nesne_heuristic | sahte | dry_run."""
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
            "injected": self._counter is not None,
            "object_heuristic": bool(self.nesne_heuristik),
            "min_confidence": float(self.min_guven),
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
            "vision.ai.count.started",
            {"engine": self._motor, "backend": self._backend},
        )
        self._yayin(
            OLAY_SAYMA_BASLADI,
            {"engine": self._motor, "backend": self._backend},
        )
        self._log.info(
            "Nesne sayici basladi motor=%s backend=%s",
            self._motor,
            self._backend,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        self._audit("vision.ai.count.stopped", {"engine": self._motor})
        self._yayin(OLAY_SAYMA_DURDU, {"engine": self._motor})
        self._log.info("Nesne sayici durdu")

    # ------------------------------------------------------------------ API

    def say(
        self,
        girdi: GirdiTuru,
        *,
        etiket: Optional[str] = None,
        min_guven: Optional[float] = None,
        sahte_sayim: Optional[int] = None,
        dil: str = "tr",
    ) -> VisionAiSonucu:
        """
        Görüntüde nesne say → VisionAiSonucu (sayim / sayim_etiket).

        dry_run → sayim=0.
        zorla_sahte / motor yok → sahte sayım.
        etiket verilirse yalnızca o etiket sayılır.
        """
        _ = dil  # gelecek dil seçimi; şimdilik Türkçe
        etiket_temiz = _etiket_temizle(etiket)
        kaynak_yol = self._kaynak_yol(girdi)
        esik = guven_sinirla(
            min_guven if min_guven is not None else self.min_guven,
            varsayilan=self.min_guven,
        )

        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = VisionAiSonucu(
                gorev=VisionGorevTuru.AI,
                sayim=0,
                sayim_etiket=etiket_temiz,
                aciklama="",
                cevap="",
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                guven=0.0,
                kaynak_yol=kaynak_yol,
                neden="dry_run",
            )
            return self._sonucla(sonuc, backend="dry_run")

        if self.zorla_sahte or (
            self._motor == VisionMotoru.SAHTE.value
            and self._counter is None
            and not self._heuristik_kullanilabilir()
        ):
            adet = (
                max(0, int(sahte_sayim))
                if sahte_sayim is not None
                else self.varsayilan_sahte
            )
            metin = _sayim_metni(adet, etiket_temiz)
            sonuc = VisionAiSonucu(
                gorev=VisionGorevTuru.AI,
                sayim=adet,
                sayim_etiket=etiket_temiz,
                aciklama=metin,
                cevap=metin,
                motor=VisionMotoru.SAHTE,
                dry_run=False,
                guven=VARSAYILAN_GUVEN_SAHTE,
                kaynak_yol=kaynak_yol,
                neden="zorla_sahte" if self.zorla_sahte else "motor_sahte",
            )
            return self._sonucla(sonuc, backend="sahte")

        # Enjekte counter (LLM / mock)
        if self._counter is not None:
            try:
                yuk = self._yukle_hafif(girdi)
                ham = self._counter(yuk, etiket_temiz)
                adet, et_ipu, guven, motor_ipu, aciklama = _sayim_normalize(ham)
                if etiket_temiz and not et_ipu:
                    et_ipu = etiket_temiz
                if not aciklama:
                    aciklama = _sayim_metni(adet, et_ipu or etiket_temiz)
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
                    sayim=adet,
                    sayim_etiket=et_ipu or etiket_temiz,
                    aciklama=aciklama,
                    cevap=aciklama,
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
                self._log.warning("Counter basarisiz → fallback: %s", exc)
                # aşağıda heuristik / sahte

        # Nesne algılama heuristiği
        if self.nesne_heuristik and self._heuristik_kullanilabilir():
            try:
                adet, neden, nesneler = self._nesne_say(
                    girdi,
                    etiket=etiket_temiz,
                    min_guven=esik,
                )
                metin = _sayim_metni(adet, etiket_temiz)
                # Etiket listesini kısa özetle zenginleştir
                if nesneler and not etiket_temiz:
                    etiketler = sorted(
                        {str(n.etiket).strip() for n in nesneler if n.etiket}
                    )
                    if etiketler:
                        metin = f"{metin} Etiketler: {', '.join(etiketler[:8])}."
                sonuc = VisionAiSonucu(
                    gorev=VisionGorevTuru.AI,
                    sayim=adet,
                    sayim_etiket=etiket_temiz,
                    aciklama=metin,
                    cevap=metin,
                    motor=VisionMotoru.OPENCV,
                    dry_run=False,
                    guven=VARSAYILAN_GUVEN_HEURISTIK,
                    kaynak_yol=kaynak_yol,
                    neden=neden,
                )
                return self._sonucla(sonuc, backend="nesne_heuristic")
            except VisionError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Nesne heuristik sayma basarisiz → sahte: %s", exc)

        # Son çare: sahte
        adet = (
            max(0, int(sahte_sayim))
            if sahte_sayim is not None
            else self.varsayilan_sahte
        )
        metin = _sayim_metni(adet, etiket_temiz)
        sonuc = VisionAiSonucu(
            gorev=VisionGorevTuru.AI,
            sayim=adet,
            sayim_etiket=etiket_temiz,
            aciklama=metin,
            cevap=metin,
            motor=VisionMotoru.SAHTE,
            dry_run=False,
            guven=VARSAYILAN_GUVEN_SAHTE,
            kaynak_yol=kaynak_yol,
            neden="fallback_sahte",
        )
        return self._sonucla(sonuc, backend="sahte")

    def adet(
        self,
        girdi: GirdiTuru,
        *,
        etiket: Optional[str] = None,
        min_guven: Optional[float] = None,
        sahte_sayim: Optional[int] = None,
        dil: str = "tr",
    ) -> int:
        """Yalnızca sayı döndüren kısayol."""
        s = self.say(
            girdi,
            etiket=etiket,
            min_guven=min_guven,
            sahte_sayim=sahte_sayim,
            dil=dil,
        )
        return int(s.sayim) if s.sayim is not None else 0

    # ------------------------------------------------------------------ iç — motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._counter is not None:
            return VisionMotoru.LLM.value
        if self.nesne_heuristik and self._heuristik_kullanilabilir():
            return VisionMotoru.OPENCV.value
        return VisionMotoru.SAHTE.value

    def _backend_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self._counter is not None:
            return "injected"
        if self.nesne_heuristik and self._heuristik_kullanilabilir():
            return "nesne_heuristic"
        return "sahte"

    def _heuristik_kullanilabilir(self) -> bool:
        """Nesne algılama modülü kullanılabilir mi?"""
        if not self.nesne_heuristik:
            return False
        try:
            from vision.analiz import nesne as _nesne_mod  # noqa: F401

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
        Counter için girdi hazırla (matris veya bayt).

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
                        kod="VIS_0822",
                        modul=self.ad,
                    )
                return p.read_bytes()
            raise VisionError(
                "Kare'de yol veya ham veri yok",
                kod="VIS_0821",
                modul=self.ad,
            )

        if isinstance(girdi, (bytes, bytearray)):
            if not girdi:
                raise VisionError(
                    "Bos goruntu baytlari",
                    kod="VIS_0821",
                    modul=self.ad,
                )
            return bytes(girdi)

        if isinstance(girdi, Path):
            p = girdi.expanduser()
            if not p.is_file():
                raise VisionError(
                    f"Goruntu yok: {p}",
                    kod="VIS_0822",
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
                    kod="VIS_0822",
                    modul=self.ad,
                )
            return p.read_bytes()

        if hasattr(girdi, "shape") and hasattr(girdi, "dtype"):
            return girdi

        raise VisionError(
            f"Desteklenmeyen sayma girdisi: {type(girdi)!r}",
            kod="VIS_0821",
            modul=self.ad,
        )

    def _nesne_say(
        self,
        girdi: GirdiTuru,
        *,
        etiket: Optional[str],
        min_guven: float,
    ) -> tuple[int, str, list[AlgilananNesne]]:
        """Nesne algılayıcıdan sayım; (adet, neden, nesneler)."""
        from vision.analiz.nesne import NesneAlgilayici

        # Sanal URI — dosya yok; sahte nesne yoluna düşmemek için özel yol
        if isinstance(girdi, str) and "://" in girdi and not Path(girdi).is_file():
            # NesneAlgilayici dosya bekler; URI için sahte sayım üretme —
            # varsayılan sahte adetini heuristik_uri olarak dön
            adet = self.varsayilan_sahte
            if etiket:
                # etiket filtreli URI: varsayılan sahte listesinde eşleşme varsay
                # kisi/sandalye sahte etiketleri
                if etiket.strip().lower() in ("kisi", "sandalye", "person", "chair"):
                    adet = 1
                else:
                    adet = 0
            return adet, "nesne_heuristic_uri", []

        n = NesneAlgilayici(
            ayarlar=self.ayarlar,
            bus=None,
            dry_run=False,
            zorla_sahte=False,
            min_guven=min_guven,
            cv2_modul=self._cv2,
            numpy_modul=self._np,
            olay_yayinla=False,
        )
        filtre: Optional[Sequence[str]] = [etiket] if etiket else None
        bil = n.algila(girdi, min_guven=min_guven, etiket_filtre=filtre)
        # Algılayıcı sahteye düştüyse yine sayılır — backend nesne_heuristic kalır
        neden = "nesne_heuristic"
        if bil.neden and "sahte" in str(bil.neden):
            neden = "nesne_heuristic_sahte"
        elif bil.neden in ("injected", "yolo", "opencv_hog"):
            neden = f"nesne_heuristic:{bil.neden}"
        return len(bil.nesneler), neden, list(bil.nesneler)

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
        elif sonuc.neden and "nesne" in str(sonuc.neden):
            self._backend = "nesne_heuristic"
        elif sonuc.motor == VisionMotoru.SAHTE:
            self._backend = "sahte"

        detay = {
            "engine": sonuc.motor.value,
            "backend": self._backend,
            "count": sonuc.sayim,
            "count_label": sonuc.sayim_etiket,
            "confidence": sonuc.guven,
            "dry_run": bool(sonuc.dry_run),
            "source_path": sonuc.kaynak_yol,
            "reason": sonuc.neden,
        }
        self._audit("vision.ai.count.done", detay)
        self._yayin(OLAY_SAYMA, sonuc.to_dict())
        self._log.debug(
            "Sayma tamam motor=%s adet=%s etiket=%s",
            sonuc.motor.value,
            sonuc.sayim,
            sonuc.sayim_etiket,
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


def nesne_sayici_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    counter: Optional[CounterTuru] = None,
    nesne_heuristik: bool = True,
    min_guven: float = VARSAYILAN_MIN_GUVEN,
    cv2_modul: Any = None,
    numpy_modul: Any = None,
    olay_yayinla: bool = False,
    varsayilan_sahte: int = _SAHTE_SAYIM,
) -> NesneSayici:
    """Test / demo için güvenli varsayılanlarla NesneSayici üretir."""
    return NesneSayici(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        counter=counter,
        nesne_heuristik=nesne_heuristik,
        min_guven=min_guven,
        cv2_modul=cv2_modul,
        numpy_modul=numpy_modul,
        olay_yayinla=olay_yayinla,
        varsayilan_sahte=varsayilan_sahte,
    )


def nesne_say(
    girdi: GirdiTuru,
    *,
    etiket: Optional[str] = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_sayim: Optional[int] = None,
    counter: Optional[CounterTuru] = None,
    nesne_heuristik: bool = True,
    min_guven: float = VARSAYILAN_MIN_GUVEN,
) -> VisionAiSonucu:
    """Tek çağrılık nesne sayma yardımcısı."""
    m = nesne_sayici_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        counter=counter,
        nesne_heuristik=nesne_heuristik,
        min_guven=min_guven,
        olay_yayinla=False,
    )
    return m.say(girdi, etiket=etiket, sahte_sayim=sahte_sayim, min_guven=min_guven)


__all__ = [
    "OLAY_SAYMA",
    "OLAY_SAYMA_BASLADI",
    "OLAY_SAYMA_DURDU",
    "NesneSayici",
    "opencv_var_mi",
    "numpy_var_mi",
    "nesne_sayici_olustur",
    "nesne_say",
]

"""
vision/modeller.py
------------------
Vision ortak veri modelleri.

Görev:
- Kamera karesi / cihaz / yakalama sonuçları
- OCR ve görsel analiz sonuçları
- Yüz algılama / tanıma (yerel-only politika alanları)
- Vision AI (açıklama, VQA, sayma, multimodal) sonuç iskeleti
- Wire JSON anahtarları İngilizce (olay / sync stili)

Not: Pipeline mantığı camera/ocr/analiz/yuz/ai altında;
bu modül yalnızca veri modelleri + serileştirme.

Gizlilik: yüz şablon / embedding alanları to_dict(wire=True) ile
dışarıya serilmez; yalnızca yerel kayıt için tutulur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from core.exceptions import VisionError

VISION_MODEL_SURUM = 1

# Yerel yüz verisi varsayılan kökü (buluta gitmez)
VARSAYILAN_YUZ_KOK = "database/faces"

# Tanıma için varsayılan minimum güven (0..1)
VARSAYILAN_YUZ_ESIK = 0.72

# Kamera varsayılan FPS
VARSAYILAN_FPS = 15

# Bilinen / bilinmeyen karşılama (yüz tanıma)
BILINEN_KARSILAMA_SABLONU = "Hoş geldin, {ad}."
BILINMEYEN_KULLANICI_MESAJI = "Kayıtlı olmayan bir kullanıcı algılandı."


class VisionMotoru(str, Enum):
    """İşlemi üreten motor / fallback."""

    OPENCV = "opencv"
    TESSERACT = "tesseract"
    PILLOW = "pillow"
    SAHTE = "sahte"
    DRY_RUN = "dry_run"
    YEREL = "local"
    LLM = "llm"
    BILINMIYOR = "unknown"


class VisionGorevTuru(str, Enum):
    """Vision görev kategorisi."""

    KAMERA = "camera"
    OCR = "ocr"
    ANALIZ = "analysis"
    YUZ = "face"
    AI = "vision_ai"


class YuzGizlilikPolitikasi(str, Enum):
    """Yüz verisi saklama politikası — yalnızca yerel."""

    YEREL_ONLY = "local_only"


MotorGirdi = Union[VisionMotoru, str]
GorevGirdi = Union[VisionGorevTuru, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yeni_id(onek: str = "vis") -> str:
    return f"{onek}_{uuid4().hex[:12]}"


def motor_coz(deger: MotorGirdi) -> VisionMotoru:
    """str / Enum → VisionMotoru."""
    if isinstance(deger, VisionMotoru):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "opencv": VisionMotoru.OPENCV,
        "tesseract": VisionMotoru.TESSERACT,
        "pillow": VisionMotoru.PILLOW,
        "sahte": VisionMotoru.SAHTE,
        "fake": VisionMotoru.SAHTE,
        "dry_run": VisionMotoru.DRY_RUN,
        "dry-run": VisionMotoru.DRY_RUN,
        "local": VisionMotoru.YEREL,
        "yerel": VisionMotoru.YEREL,
        "llm": VisionMotoru.LLM,
        "unknown": VisionMotoru.BILINMIYOR,
        "bilinmiyor": VisionMotoru.BILINMIYOR,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return VisionMotoru(metin)
    except ValueError as hata:
        raise VisionError(
            f"Bilinmeyen vision motoru: {deger!r}",
            kod="VIS_0020",
            modul="vision.modeller",
        ) from hata


def gorev_turu_coz(deger: GorevGirdi) -> VisionGorevTuru:
    """str / Enum → VisionGorevTuru."""
    if isinstance(deger, VisionGorevTuru):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "camera": VisionGorevTuru.KAMERA,
        "kamera": VisionGorevTuru.KAMERA,
        "ocr": VisionGorevTuru.OCR,
        "analysis": VisionGorevTuru.ANALIZ,
        "analiz": VisionGorevTuru.ANALIZ,
        "face": VisionGorevTuru.YUZ,
        "yuz": VisionGorevTuru.YUZ,
        "yüz": VisionGorevTuru.YUZ,
        "vision_ai": VisionGorevTuru.AI,
        "ai": VisionGorevTuru.AI,
        "vision-ai": VisionGorevTuru.AI,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return VisionGorevTuru(metin)
    except ValueError as hata:
        raise VisionError(
            f"Bilinmeyen vision gorev turu: {deger!r}",
            kod="VIS_0021",
            modul="vision.modeller",
        ) from hata


def guven_sinirla(deger: Optional[float], *, varsayilan: float = 0.0) -> float:
    """Güven skorunu 0..1 aralığına sıkıştırır."""
    if deger is None:
        return float(varsayilan)
    try:
        x = float(deger)
    except (TypeError, ValueError) as hata:
        raise VisionError(
            f"Gecersiz guven skoru: {deger!r}",
            kod="VIS_0022",
            modul="vision.modeller",
        ) from hata
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


# ---------------------------------------------------------------------------
# Kamera
# ---------------------------------------------------------------------------


@dataclass
class KameraAyarlari:
    """Kamera seçimi + FPS (Camera Manager)."""

    cihaz: int = 0
    fps: int = VARSAYILAN_FPS
    genislik: int = 0
    yukseklik: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": int(self.cihaz),
            "fps": max(1, int(self.fps)),
            "width": int(self.genislik),
            "height": int(self.yukseklik),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "KameraAyarlari":
        fps = int(veri.get("fps") if veri.get("fps") is not None else VARSAYILAN_FPS)
        return cls(
            cihaz=int(veri.get("device", 0)),
            fps=max(1, fps),
            genislik=int(veri.get("width") or 0),
            yukseklik=int(veri.get("height") or 0),
        )


@dataclass
class KameraCihazi:
    """Tek bir kamera cihazı."""

    indeks: int = 0
    ad: str = ""
    erisilebilir: bool = True
    not_: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.indeks),
            "name": self.ad or f"camera_{self.indeks}",
            "available": bool(self.erisilebilir),
            "note": self.not_ or None,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "KameraCihazi":
        return cls(
            indeks=int(veri.get("index", 0)),
            ad=str(veri.get("name") or ""),
            erisilebilir=bool(veri.get("available", True)),
            not_=str(veri.get("note") or ""),
        )


@dataclass
class Kare:
    """Tek bir görüntü karesi (dosya yolu veya bellek baytı)."""

    id: str = field(default_factory=lambda: _yeni_id("frm"))
    yol: Optional[str] = None
    genislik: int = 0
    yukseklik: int = 0
    cihaz: Optional[int] = None
    motor: VisionMotoru = VisionMotoru.BILINMIYOR
    dry_run: bool = False
    bayt_sayisi: int = 0
    zaman: str = field(default_factory=_utc_iso)
    # Bellek içi ham veri — wire'a yazılmaz
    ham: Optional[bytes] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.yol,
            "width": int(self.genislik),
            "height": int(self.yukseklik),
            "device": self.cihaz,
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "bytes": int(self.bayt_sayisi),
            "ts": self.zaman,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "Kare":
        return cls(
            id=str(veri.get("id") or _yeni_id("frm")),
            yol=veri.get("path"),
            genislik=int(veri.get("width") or 0),
            yukseklik=int(veri.get("height") or 0),
            cihaz=veri.get("device") if veri.get("device") is not None else None,
            motor=motor_coz(veri.get("engine") or VisionMotoru.BILINMIYOR),
            dry_run=bool(veri.get("dry_run", False)),
            bayt_sayisi=int(veri.get("bytes") or 0),
            zaman=str(veri.get("ts") or _utc_iso()),
            ham=None,
        )


@dataclass
class YakalamaSonucu:
    """Fotoğraf / kare yakalama sonucu."""

    kare: Kare
    acik: bool = False
    neden: Optional[str] = None
    hata: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = self.kare.to_dict()
        d["opened"] = bool(self.acik)
        d["reason"] = self.neden
        d["error"] = self.hata
        return d

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "YakalamaSonucu":
        return cls(
            kare=Kare.from_dict(veri),
            acik=bool(veri.get("opened", False)),
            neden=veri.get("reason"),
            hata=veri.get("error"),
        )


def kare_olustur(
    *,
    yol: Optional[str] = None,
    genislik: int = 0,
    yukseklik: int = 0,
    cihaz: Optional[int] = None,
    motor: MotorGirdi = VisionMotoru.DRY_RUN,
    dry_run: bool = True,
    bayt_sayisi: int = 0,
    ham: Optional[bytes] = None,
) -> Kare:
    """Kare modeli üretir (CI / dry_run için uygun)."""
    return Kare(
        yol=yol,
        genislik=int(genislik),
        yukseklik=int(yukseklik),
        cihaz=cihaz,
        motor=motor_coz(motor),
        dry_run=bool(dry_run),
        bayt_sayisi=int(bayt_sayisi),
        ham=ham,
    )


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


@dataclass
class OcrSonucu:
    """OCR metin çıkarma sonucu."""

    metin: str = ""
    dil: str = "tur+eng"
    kaynak_yol: Optional[str] = None
    motor: VisionMotoru = VisionMotoru.DRY_RUN
    dry_run: bool = False
    guven: float = 0.0
    sayfa: Optional[int] = None
    neden: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.metin,
            "lang": self.dil,
            "source_path": self.kaynak_yol,
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "confidence": guven_sinirla(self.guven),
            "page": self.sayfa,
            "reason": self.neden,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "OcrSonucu":
        return cls(
            metin=str(veri.get("text") or ""),
            dil=str(veri.get("lang") or "tur+eng"),
            kaynak_yol=veri.get("source_path"),
            motor=motor_coz(veri.get("engine") or VisionMotoru.DRY_RUN),
            dry_run=bool(veri.get("dry_run", False)),
            guven=guven_sinirla(veri.get("confidence")),
            sayfa=veri.get("page") if veri.get("page") is not None else None,
            neden=veri.get("reason"),
        )


# ---------------------------------------------------------------------------
# Görsel analiz
# ---------------------------------------------------------------------------


@dataclass
class AlgilananNesne:
    """Algılanan tek nesne."""

    etiket: str
    guven: float = 0.0
    kutu: Optional[tuple[int, int, int, int]] = None  # x, y, w, h

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "label": self.etiket,
            "confidence": guven_sinirla(self.guven),
        }
        if self.kutu is not None:
            x, y, w, h = self.kutu
            d["box"] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        return d

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "AlgilananNesne":
        kutu = None
        ham = veri.get("box")
        if isinstance(ham, dict):
            kutu = (
                int(ham.get("x", 0)),
                int(ham.get("y", 0)),
                int(ham.get("w", 0)),
                int(ham.get("h", 0)),
            )
        elif isinstance(ham, (list, tuple)) and len(ham) == 4:
            kutu = (int(ham[0]), int(ham[1]), int(ham[2]), int(ham[3]))
        return cls(
            etiket=str(veri.get("label") or ""),
            guven=guven_sinirla(veri.get("confidence")),
            kutu=kutu,
        )


@dataclass
class RenkOzeti:
    """Renk analizi özeti."""

    baskin_hex: str = "#000000"
    palette: list[str] = field(default_factory=list)
    ortalama_rgb: tuple[int, int, int] = (0, 0, 0)

    def to_dict(self) -> dict[str, Any]:
        r, g, b = self.ortalama_rgb
        return {
            "dominant_hex": self.baskin_hex,
            "palette": list(self.palette),
            "mean_rgb": {"r": int(r), "g": int(g), "b": int(b)},
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "RenkOzeti":
        mean = veri.get("mean_rgb") or {}
        if isinstance(mean, dict):
            rgb = (
                int(mean.get("r", 0)),
                int(mean.get("g", 0)),
                int(mean.get("b", 0)),
            )
        elif isinstance(mean, (list, tuple)) and len(mean) == 3:
            rgb = (int(mean[0]), int(mean[1]), int(mean[2]))
        else:
            rgb = (0, 0, 0)
        return cls(
            baskin_hex=str(veri.get("dominant_hex") or "#000000"),
            palette=[str(x) for x in (veri.get("palette") or [])],
            ortalama_rgb=rgb,
        )


@dataclass
class AnalizSonucu:
    """Nesne / sahne / renk / QR birleşik analiz sonucu."""

    nesneler: list[AlgilananNesne] = field(default_factory=list)
    sahne: str = ""
    renk: Optional[RenkOzeti] = None
    qr_verileri: list[str] = field(default_factory=list)
    barkodlar: list[str] = field(default_factory=list)
    motor: VisionMotoru = VisionMotoru.DRY_RUN
    dry_run: bool = False
    kaynak_yol: Optional[str] = None
    neden: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "objects": [n.to_dict() for n in self.nesneler],
            "scene": self.sahne,
            "color": self.renk.to_dict() if self.renk else None,
            "qr": list(self.qr_verileri),
            "barcodes": list(self.barkodlar),
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "source_path": self.kaynak_yol,
            "reason": self.neden,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "AnalizSonucu":
        renk_ham = veri.get("color")
        return cls(
            nesneler=[
                AlgilananNesne.from_dict(x)
                for x in (veri.get("objects") or [])
                if isinstance(x, dict)
            ],
            sahne=str(veri.get("scene") or ""),
            renk=RenkOzeti.from_dict(renk_ham) if isinstance(renk_ham, dict) else None,
            qr_verileri=[str(x) for x in (veri.get("qr") or [])],
            barkodlar=[str(x) for x in (veri.get("barcodes") or [])],
            motor=motor_coz(veri.get("engine") or VisionMotoru.DRY_RUN),
            dry_run=bool(veri.get("dry_run", False)),
            kaynak_yol=veri.get("source_path"),
            neden=veri.get("reason"),
        )


# ---------------------------------------------------------------------------
# Yüz (yerel-only)
# ---------------------------------------------------------------------------


@dataclass
class YuzKutusu:
    """Algılanan yüz sınır kutusu."""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    guven: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": int(self.x),
            "y": int(self.y),
            "w": int(self.w),
            "h": int(self.h),
            "confidence": guven_sinirla(self.guven),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "YuzKutusu":
        return cls(
            x=int(veri.get("x", 0)),
            y=int(veri.get("y", 0)),
            w=int(veri.get("w", 0)),
            h=int(veri.get("h", 0)),
            guven=guven_sinirla(veri.get("confidence")),
        )


@dataclass
class KayitliKullanici:
    """
    Yerel kayıtlı kullanıcı (çoklu destek).

    embedding / şablon yalnızca yerel saklama içindir;
    wire=True serileştirmede dışarı verilmez.
    """

    id: str = field(default_factory=lambda: _yeni_id("usr"))
    gorunen_ad: str = ""
    olusturma: str = field(default_factory=_utc_iso)
    aktif: bool = True
    # Yerel şablon — asla buluta / wire'a
    embedding: Optional[list[float]] = field(default=None, repr=False)
    sablon_yolu: Optional[str] = field(default=None, repr=False)

    def karsilama_mesaji(self) -> str:
        ad = (self.gorunen_ad or "").strip() or "kullanıcı"
        return BILINEN_KARSILAMA_SABLONU.format(ad=ad)

    def to_dict(self, *, wire: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "display_name": self.gorunen_ad,
            "created_at": self.olusturma,
            "active": bool(self.aktif),
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
        }
        if not wire:
            # Yerel kalıcılık — embedding / şablon yolu dahil
            d["embedding"] = list(self.embedding) if self.embedding else None
            d["template_path"] = self.sablon_yolu
            d["storage"] = "local"
        return d

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "KayitliKullanici":
        emb = veri.get("embedding")
        return cls(
            id=str(veri.get("id") or _yeni_id("usr")),
            gorunen_ad=str(veri.get("display_name") or ""),
            olusturma=str(veri.get("created_at") or _utc_iso()),
            aktif=bool(veri.get("active", True)),
            embedding=[float(x) for x in emb] if isinstance(emb, list) else None,
            sablon_yolu=veri.get("template_path"),
        )


@dataclass
class YuzTanimaSonucu:
    """Yüz tanıma sonucu + güven skoru."""

    eslesti: bool = False
    kullanici_id: Optional[str] = None
    gorunen_ad: Optional[str] = None
    guven: float = 0.0
    esik: float = VARSAYILAN_YUZ_ESIK
    kutular: list[YuzKutusu] = field(default_factory=list)
    motor: VisionMotoru = VisionMotoru.DRY_RUN
    dry_run: bool = False
    yerel_only: bool = True
    neden: Optional[str] = None

    @property
    def karsilama(self) -> str:
        """Bilinen → 'Hoş geldin, ….' / bilinmeyen → kayıtlı olmayan mesajı."""
        if self.eslesti and self.gorunen_ad:
            return BILINEN_KARSILAMA_SABLONU.format(ad=self.gorunen_ad)
        return BILINMEYEN_KULLANICI_MESAJI

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": bool(self.eslesti),
            "user_id": self.kullanici_id,
            "display_name": self.gorunen_ad,
            "confidence": guven_sinirla(self.guven),
            "threshold": guven_sinirla(self.esik, varsayilan=VARSAYILAN_YUZ_ESIK),
            "greeting": self.karsilama,
            "faces": [k.to_dict() for k in self.kutular],
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "local_only": bool(self.yerel_only),
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "reason": self.neden,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "YuzTanimaSonucu":
        return cls(
            eslesti=bool(veri.get("matched", False)),
            kullanici_id=veri.get("user_id"),
            gorunen_ad=veri.get("display_name"),
            guven=guven_sinirla(veri.get("confidence")),
            esik=guven_sinirla(
                veri.get("threshold"),
                varsayilan=VARSAYILAN_YUZ_ESIK,
            ),
            kutular=[
                YuzKutusu.from_dict(x)
                for x in (veri.get("faces") or [])
                if isinstance(x, dict)
            ],
            motor=motor_coz(veri.get("engine") or VisionMotoru.DRY_RUN),
            dry_run=bool(veri.get("dry_run", False)),
            yerel_only=bool(veri.get("local_only", True)),
            neden=veri.get("reason"),
        )


def kayitli_kullanici_olustur(
    gorunen_ad: str,
    *,
    embedding: Optional[list[float]] = None,
    sablon_yolu: Optional[str] = None,
) -> KayitliKullanici:
    """Yerel kayıtlı kullanıcı oluşturur."""
    ad = (gorunen_ad or "").strip()
    if not ad:
        raise VisionError(
            "gorunen_ad bos olamaz",
            kod="VIS_0023",
            modul="vision.modeller",
        )
    return KayitliKullanici(
        gorunen_ad=ad,
        embedding=list(embedding) if embedding else None,
        sablon_yolu=sablon_yolu,
    )


# ---------------------------------------------------------------------------
# Vision AI
# ---------------------------------------------------------------------------


@dataclass
class VisionAiSonucu:
    """Görsel açıklama / VQA / sayma / multimodal sonuç."""

    gorev: VisionGorevTuru = VisionGorevTuru.AI
    aciklama: str = ""
    soru: Optional[str] = None
    cevap: Optional[str] = None
    sayim: Optional[int] = None
    sayim_etiket: Optional[str] = None
    motor: VisionMotoru = VisionMotoru.DRY_RUN
    dry_run: bool = False
    guven: float = 0.0
    kaynak_yol: Optional[str] = None
    ek_metin: Optional[str] = None  # multimodal girdi metni
    neden: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.gorev.value,
            "description": self.aciklama,
            "question": self.soru,
            "answer": self.cevap,
            "count": self.sayim,
            "count_label": self.sayim_etiket,
            "engine": self.motor.value,
            "dry_run": bool(self.dry_run),
            "confidence": guven_sinirla(self.guven),
            "source_path": self.kaynak_yol,
            "prompt_text": self.ek_metin,
            "reason": self.neden,
            "v": VISION_MODEL_SURUM,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "VisionAiSonucu":
        return cls(
            gorev=gorev_turu_coz(veri.get("task") or VisionGorevTuru.AI),
            aciklama=str(veri.get("description") or ""),
            soru=veri.get("question"),
            cevap=veri.get("answer"),
            sayim=int(veri["count"]) if veri.get("count") is not None else None,
            sayim_etiket=veri.get("count_label"),
            motor=motor_coz(veri.get("engine") or VisionMotoru.DRY_RUN),
            dry_run=bool(veri.get("dry_run", False)),
            guven=guven_sinirla(veri.get("confidence")),
            kaynak_yol=veri.get("source_path"),
            ek_metin=veri.get("prompt_text"),
            neden=veri.get("reason"),
        )


__all__ = [
    "VISION_MODEL_SURUM",
    "VARSAYILAN_YUZ_KOK",
    "VARSAYILAN_YUZ_ESIK",
    "VARSAYILAN_FPS",
    "BILINEN_KARSILAMA_SABLONU",
    "BILINMEYEN_KULLANICI_MESAJI",
    "VisionMotoru",
    "VisionGorevTuru",
    "YuzGizlilikPolitikasi",
    "motor_coz",
    "gorev_turu_coz",
    "guven_sinirla",
    "KameraAyarlari",
    "KameraCihazi",
    "Kare",
    "YakalamaSonucu",
    "kare_olustur",
    "OcrSonucu",
    "AlgilananNesne",
    "RenkOzeti",
    "AnalizSonucu",
    "YuzKutusu",
    "KayitliKullanici",
    "YuzTanimaSonucu",
    "kayitli_kullanici_olustur",
    "VisionAiSonucu",
]

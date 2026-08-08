"""
plugins/modeller.py
-------------------
Eklenti (plugin) ortak veri modelleri.

Görev:
- Manifest / kimlik kartı (ad, sürüm, giriş noktası)
- Yükleme / çalışma durumu
- Çalıştırma sonucu (skill YetenekSonucu ile uyumlu stil)
- Wire JSON anahtarları İngilizce (olay / ajan stili)

Not: Yükleme / sandbox `yukleyici.py` ve `guvenlik.py` içinde;
bu modül yalnızca veri modelleri + serileştirme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from core.base import YetenekDurumu, YetenekSonucu
from core.exceptions import PluginError

PLUGIN_MODEL_SURUM = 1

# config.plugins.directory varsayılanı ile uyumlu
VARSAYILAN_PLUGIN_DIZINI = "plugins"

# Manifest zorunlu alanlar
ZORUNLU_MANIFEST_ALANLAR: frozenset[str] = frozenset({"name", "version", "entry"})


class PluginDurumu(str, Enum):
    """Eklentinin yaşam döngüsü durumu."""

    KESFEDILDI = "discovered"
    YUKLENIYOR = "loading"
    HAZIR = "ready"
    CALISIYOR = "running"
    DEVRE_DISI = "disabled"
    HATA = "error"
    KALDIRILDI = "unloaded"


class PluginKaynak(str, Enum):
    """Eklentinin nereden geldiği."""

    DOSYA = "file"
    PAKET = "package"
    ORNEK = "example"
    BELLEK = "memory"
    BILINMIYOR = "unknown"


DurumGirdi = Union[PluginDurumu, str]
KaynakGirdi = Union[PluginKaynak, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yeni_id(onek: str = "plg") -> str:
    return f"{onek}_{uuid4().hex[:12]}"


def durum_coz(deger: DurumGirdi) -> PluginDurumu:
    """str / Enum → PluginDurumu."""
    if isinstance(deger, PluginDurumu):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "kesfedildi": PluginDurumu.KESFEDILDI,
        "discovered": PluginDurumu.KESFEDILDI,
        "yukleniyor": PluginDurumu.YUKLENIYOR,
        "loading": PluginDurumu.YUKLENIYOR,
        "hazir": PluginDurumu.HAZIR,
        "ready": PluginDurumu.HAZIR,
        "calisiyor": PluginDurumu.CALISIYOR,
        "running": PluginDurumu.CALISIYOR,
        "devre_disi": PluginDurumu.DEVRE_DISI,
        "disabled": PluginDurumu.DEVRE_DISI,
        "hata": PluginDurumu.HATA,
        "error": PluginDurumu.HATA,
        "kaldirildi": PluginDurumu.KALDIRILDI,
        "unloaded": PluginDurumu.KALDIRILDI,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return PluginDurumu(metin)
    except ValueError as hata:
        raise PluginError(
            f"Bilinmeyen eklenti durumu: {deger!r}",
            kod="PLG_0020",
            modul="plugins",
        ) from hata


def kaynak_coz(deger: KaynakGirdi) -> PluginKaynak:
    """str / Enum → PluginKaynak."""
    if isinstance(deger, PluginKaynak):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "dosya": PluginKaynak.DOSYA,
        "file": PluginKaynak.DOSYA,
        "paket": PluginKaynak.PAKET,
        "package": PluginKaynak.PAKET,
        "ornek": PluginKaynak.ORNEK,
        "example": PluginKaynak.ORNEK,
        "bellek": PluginKaynak.BELLEK,
        "memory": PluginKaynak.BELLEK,
        "bilinmiyor": PluginKaynak.BILINMIYOR,
        "unknown": PluginKaynak.BILINMIYOR,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return PluginKaynak(metin)
    except ValueError as hata:
        raise PluginError(
            f"Bilinmeyen eklenti kaynagi: {deger!r}",
            kod="PLG_0021",
            modul="plugins",
        ) from hata


def eklenti_adi_dogrula(ad: str) -> str:
    """
    Eklenti adını normalize eder ve doğrular.

    Küçük harf, tire/alt çizgi; boş veya geçersiz → PluginError.
    """
    metin = (ad or "").strip().lower().replace(" ", "_")
    if not metin:
        raise PluginError(
            "Eklenti adi bos olamaz",
            kod="PLG_0022",
            modul="plugins",
        )
    if not all(c.isalnum() or c in "_-" for c in metin):
        raise PluginError(
            f"Eklenti adi gecersiz: {ad!r}",
            kod="PLG_0023",
            modul="plugins",
        )
    if metin.startswith("_") or metin in {"__init__", "modeller", "taban", "yoneticisi"}:
        raise PluginError(
            f"Eklenti adi rezerve: {ad!r}",
            kod="PLG_0024",
            modul="plugins",
        )
    return metin


@dataclass
class PluginManifesto:
    """
    Eklenti kimlik / keşif kartı (manifest).

    Wire: name, version, entry, description, author?, dangerous,
          keywords, permissions, source, path?, meta
    """

    ad: str
    surum: str = "0.1.0"
    giris: str = ""
    aciklama: str = ""
    yazar: str = ""
    tehlikeli: bool = False
    anahtarlar: tuple[str, ...] = ()
    izinler: tuple[str, ...] = ()
    kaynak: PluginKaynak = PluginKaynak.DOSYA
    yol: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ad = eklenti_adi_dogrula(self.ad)
        self.surum = (self.surum or "0.1.0").strip() or "0.1.0"
        if isinstance(self.kaynak, str):
            self.kaynak = kaynak_coz(self.kaynak)
        if not self.giris:
            self.giris = self.ad
        if isinstance(self.anahtarlar, list):
            self.anahtarlar = tuple(self.anahtarlar)
        if isinstance(self.izinler, list):
            self.izinler = tuple(self.izinler)

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "name": self.ad,
            "version": self.surum,
            "entry": self.giris,
            "description": self.aciklama,
            "dangerous": bool(self.tehlikeli),
            "keywords": list(self.anahtarlar),
            "permissions": list(self.izinler),
            "source": self.kaynak.value,
            "meta": dict(self.meta),
            "model_version": PLUGIN_MODEL_SURUM,
        }
        if self.yazar:
            veri["author"] = self.yazar
        if self.yol:
            veri["path"] = self.yol
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "PluginManifesto":
        if not isinstance(veri, dict):
            raise PluginError(
                "Manifest sozluk olmali",
                kod="PLG_0025",
                modul="plugins",
            )
        eksik = [a for a in ("name", "version") if not veri.get(a)]
        if eksik:
            raise PluginError(
                f"Manifest eksik alanlar: {', '.join(eksik)}",
                kod="PLG_0026",
                modul="plugins",
            )
        return cls(
            ad=str(veri["name"]),
            surum=str(veri.get("version") or "0.1.0"),
            giris=str(veri.get("entry") or veri["name"]),
            aciklama=str(veri.get("description") or ""),
            yazar=str(veri.get("author") or ""),
            tehlikeli=bool(veri.get("dangerous", False)),
            anahtarlar=tuple(veri.get("keywords") or ()),
            izinler=tuple(veri.get("permissions") or ()),
            kaynak=kaynak_coz(veri.get("source") or PluginKaynak.DOSYA),
            yol=str(veri["path"]) if veri.get("path") else None,
            meta=dict(veri.get("meta") or {}),
        )


@dataclass
class PluginKayit:
    """
    Yüklü / keşfedilmiş eklenti kayıt satırı.

    Wire: id, manifest, status, loaded_at?, error?, dry_run, meta
    """

    manifesto: PluginManifesto
    durum: PluginDurumu = PluginDurumu.KESFEDILDI
    kayit_id: str = field(default_factory=lambda: _yeni_id())
    yuklenme_zamani: Optional[str] = None
    hata: Optional[str] = None
    dry_run: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.durum, str):
            self.durum = durum_coz(self.durum)

    @property
    def ad(self) -> str:
        return self.manifesto.ad

    @property
    def hazir_mi(self) -> bool:
        return self.durum is PluginDurumu.HAZIR

    def hazir_isaretle(self) -> None:
        """Durumu HAZIR yapar ve yüklenme zamanını yazar."""
        self.durum = PluginDurumu.HAZIR
        self.yuklenme_zamani = _utc_iso()
        self.hata = None

    def hata_isaretle(self, mesaj: str) -> None:
        """Durumu HATA yapar."""
        self.durum = PluginDurumu.HATA
        self.hata = str(mesaj)

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "id": self.kayit_id,
            "manifest": self.manifesto.to_dict(),
            "status": self.durum.value,
            "dry_run": bool(self.dry_run),
            "meta": dict(self.meta),
            "model_version": PLUGIN_MODEL_SURUM,
        }
        if self.yuklenme_zamani:
            veri["loaded_at"] = self.yuklenme_zamani
        if self.hata:
            veri["error"] = self.hata
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "PluginKayit":
        if not isinstance(veri, dict):
            raise PluginError(
                "Plugin kaydi sozluk olmali",
                kod="PLG_0027",
                modul="plugins",
            )
        man_ham = veri.get("manifest") or {}
        if not isinstance(man_ham, dict):
            raise PluginError(
                "manifest sozluk olmali",
                kod="PLG_0028",
                modul="plugins",
            )
        return cls(
            manifesto=PluginManifesto.from_dict(man_ham),
            durum=durum_coz(veri.get("status") or PluginDurumu.KESFEDILDI),
            kayit_id=str(veri.get("id") or _yeni_id()),
            yuklenme_zamani=str(veri["loaded_at"]) if veri.get("loaded_at") else None,
            hata=str(veri["error"]) if veri.get("error") else None,
            dry_run=bool(veri.get("dry_run", False)),
            meta=dict(veri.get("meta") or {}),
        )


@dataclass
class PluginSonucu:
    """
    Eklenti çalıştırma sonucu.

    Wire: ok, status, message, plugin, data, duration_ms?
    YetenekSonucu ile dönüşüm desteklenir (ajan köprüsü).
    """

    durum: YetenekDurumu = YetenekDurumu.BASARILI
    mesaj: str = ""
    eklenti: str = ""
    veri: dict[str, Any] = field(default_factory=dict)
    sure_ms: Optional[float] = None

    def __post_init__(self) -> None:
        if isinstance(self.durum, YetenekDurumu):
            return
        try:
            self.durum = YetenekDurumu(str(self.durum).strip().lower())
        except ValueError as hata:
            raise PluginError(
                f"Bilinmeyen sonuc durumu: {self.durum!r}",
                kod="PLG_0029",
                modul="plugins",
            ) from hata

    @property
    def basarili_mi(self) -> bool:
        return self.durum is YetenekDurumu.BASARILI

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "ok": self.basarili_mi,
            "status": self.durum.value,
            "message": self.mesaj,
            "plugin": self.eklenti,
            "data": dict(self.veri),
            "model_version": PLUGIN_MODEL_SURUM,
        }
        if self.sure_ms is not None:
            veri["duration_ms"] = float(self.sure_ms)
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "PluginSonucu":
        if not isinstance(veri, dict):
            raise PluginError(
                "Plugin sonucu sozluk olmali",
                kod="PLG_0030",
                modul="plugins",
            )
        durum_ham = veri.get("status")
        if durum_ham is None:
            durum_ham = (
                YetenekDurumu.BASARILI.value
                if veri.get("ok", True)
                else YetenekDurumu.BASARISIZ.value
            )
        try:
            durum = YetenekDurumu(str(durum_ham).strip().lower())
        except ValueError as hata:
            raise PluginError(
                f"Bilinmeyen sonuc durumu: {durum_ham!r}",
                kod="PLG_0029",
                modul="plugins",
            ) from hata
        sure = veri.get("duration_ms")
        return cls(
            durum=durum,
            mesaj=str(veri.get("message") or ""),
            eklenti=str(veri.get("plugin") or ""),
            veri=dict(veri.get("data") or {}),
            sure_ms=float(sure) if sure is not None else None,
        )

    def to_yetenek_sonucu(self) -> YetenekSonucu:
        """Ajan / skill zinciri için YetenekSonucu'na çevirir."""
        return YetenekSonucu(
            durum=self.durum,
            mesaj=self.mesaj,
            yetenek=self.eklenti or "plugin",
            veri=dict(self.veri),
        )

    @classmethod
    def ok(
        cls,
        mesaj: str = "ok",
        *,
        eklenti: str = "",
        veri: Optional[dict[str, Any]] = None,
        sure_ms: Optional[float] = None,
    ) -> "PluginSonucu":
        return cls(
            durum=YetenekDurumu.BASARILI,
            mesaj=mesaj,
            eklenti=eklenti,
            veri=veri or {},
            sure_ms=sure_ms,
        )

    @classmethod
    def hata(
        cls,
        mesaj: str,
        *,
        eklenti: str = "",
        veri: Optional[dict[str, Any]] = None,
    ) -> "PluginSonucu":
        return cls(
            durum=YetenekDurumu.BASARISIZ,
            mesaj=mesaj,
            eklenti=eklenti,
            veri=veri or {},
        )


def manifesto_olustur(
    ad: str,
    *,
    surum: str = "0.1.0",
    giris: str = "",
    aciklama: str = "",
    tehlikeli: bool = False,
    kaynak: KaynakGirdi = PluginKaynak.DOSYA,
    yol: Optional[str] = None,
    anahtarlar: Optional[tuple[str, ...]] = None,
) -> PluginManifesto:
    """Kolay manifesto fabrikası."""
    return PluginManifesto(
        ad=ad,
        surum=surum,
        giris=giris or ad,
        aciklama=aciklama,
        tehlikeli=tehlikeli,
        kaynak=kaynak_coz(kaynak),
        yol=yol,
        anahtarlar=tuple(anahtarlar or ()),
    )


def kayit_olustur(
    ad: str,
    *,
    surum: str = "0.1.0",
    durum: DurumGirdi = PluginDurumu.KESFEDILDI,
    dry_run: bool = False,
    yol: Optional[str] = None,
    kaynak: KaynakGirdi = PluginKaynak.DOSYA,
) -> PluginKayit:
    """Kolay kayıt fabrikası."""
    return PluginKayit(
        manifesto=manifesto_olustur(
            ad,
            surum=surum,
            yol=yol,
            kaynak=kaynak,
        ),
        durum=durum_coz(durum),
        dry_run=dry_run,
    )


__all__ = [
    "PLUGIN_MODEL_SURUM",
    "VARSAYILAN_PLUGIN_DIZINI",
    "ZORUNLU_MANIFEST_ALANLAR",
    "PluginDurumu",
    "PluginKaynak",
    "PluginManifesto",
    "PluginKayit",
    "PluginSonucu",
    "durum_coz",
    "kaynak_coz",
    "eklenti_adi_dogrula",
    "manifesto_olustur",
    "kayit_olustur",
]

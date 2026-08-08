"""
vision/yuz/gizlilik.py
----------------------
Yüz gizlilik + izin + local-only + ayarlar toggle.

Görev:
- Yüz tanıma ayarlar toggle (varsayılan: kapalı)
- Kamera / yüz işleminden önce izin kontrolleri (kanca)
- Yüz gömme / şablon verisi yalnızca yerel disk (`database/faces/`)
- Wire / audit / log yüklerinden embedding / şablon temizliği
- Sonraki yüz modüllerinin (algılama / kayıt / tanıma) saygı duyacağı yardımcılar

Gizlilik (zorunlu):
- Buluta, sync'e veya harici API'ye yüz verisi gönderilmez
- Wire JSON'da yalnızca güven skoru + görünen ad (şablon yok)
- Embedding / template asla log veya cloud payload içinde olmaz
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    VARSAYILAN_YUZ_ESIK,
    VARSAYILAN_YUZ_KOK,
    KayitliKullanici,
    YuzGizlilikPolitikasi,
    YuzTanimaSonucu,
    guven_sinirla,
)

log = logger_al("vision.yuz.gizlilik")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_GIZLILIK_BASLADI = "vision.face.privacy.started"
OLAY_GIZLILIK_DURDU = "vision.face.privacy.stopped"
OLAY_YUZ_TOGGLE = "vision.face.privacy.toggle"
OLAY_KAMERA_IZIN = "vision.face.privacy.camera_permission"
OLAY_IZIN_RED = "vision.face.privacy.denied"

# Config anahtarları (config.vision Engine köprüsünde genişler)
CFG_YUZ_AKTIF = "vision.face.enabled"
CFG_KAMERA_IZIN = "vision.face.camera_permission"
CFG_YUZ_KOK = "vision.face.storage_root"
CFG_YUZ_ESIK = "vision.face.min_confidence"
CFG_YEREL_ONLY = "vision.face.local_only"

# Varsayılanlar — yüz tanıma kapalı; kamera izni açıkça verilmeli
VARSAYILAN_YUZ_AKTIF = False
VARSAYILAN_KAMERA_IZIN = False

# Wire / audit / log'dan asla sızmaması gereken anahtarlar
_HASSAS_ANAHTARLAR = frozenset(
    {
        "embedding",
        "embeddings",
        "template",
        "template_path",
        "sablon",
        "sablon_yolu",
        "face_template",
        "face_embedding",
        "descriptor",
        "descriptors",
        "encoding",
        "encodings",
        "feature_vector",
        "feature_vectors",
    }
)

# Kamera izin kancası: () -> bool
KameraIzinKontrolu = Callable[[], bool]
VeriGirdi = Union[Mapping[str, Any], KayitliKullanici, YuzTanimaSonucu, None]


def hassas_anahtar_mi(anahtar: str) -> bool:
    """Anahtar yüz şablonu / embedding içeriyor mu?"""
    if not anahtar:
        return False
    a = str(anahtar).strip().lower()
    if a in _HASSAS_ANAHTARLAR:
        return True
    # alt_anahtar.embedding gibi bileşik yollar
    for hassas in _HASSAS_ANAHTARLAR:
        if a.endswith(f".{hassas}") or a.endswith(f"_{hassas}"):
            return True
    return False


def wire_temizle(veri: Any) -> Any:
    """
    Dict / list yapıdan embedding / şablon alanlarını çıkarır.

    Bulut / sync / EventBus / audit yükleri için güvenli kopya üretir.
    """
    if veri is None:
        return None
    if isinstance(veri, KayitliKullanici):
        return veri.to_dict(wire=True)
    if isinstance(veri, YuzTanimaSonucu):
        return wire_temizle(veri.to_dict())
    if isinstance(veri, Mapping):
        temiz: dict[str, Any] = {}
        for k, v in veri.items():
            if hassas_anahtar_mi(str(k)):
                continue
            temiz[str(k)] = wire_temizle(v)
        return temiz
    if isinstance(veri, (list, tuple)):
        return [wire_temizle(x) for x in veri]
    return veri


def buluta_gonderilebilir_mi(veri: Any = None) -> bool:
    """
    Yüz verisi asla buluta / sync'e gitmez.

    veri verilirse hassas anahtar içeriyorsa yine False (savunma).
    """
    _ = veri
    return False


def yerel_kok_coz(
    ayarlar: Optional[Ayarlar] = None,
    *,
    kok: Optional[Union[str, Path]] = None,
) -> Path:
    """Yerel yüz depolama kökünü çözer (göreli → cwd)."""
    if kok is not None:
        return Path(kok)
    cfg = ayarlar or global_ayarlar
    try:
        ham = cfg.al(CFG_YUZ_KOK, VARSAYILAN_YUZ_KOK)
    except Exception:  # noqa: BLE001 — config yoksa varsayılan
        ham = VARSAYILAN_YUZ_KOK
    yol = Path(str(ham or VARSAYILAN_YUZ_KOK))
    return yol


def _bool_coz(deger: Any, *, varsayilan: bool) -> bool:
    if deger is None:
        return bool(varsayilan)
    if isinstance(deger, bool):
        return deger
    if isinstance(deger, (int, float)):
        return bool(deger)
    metin = str(deger).strip().lower()
    if metin in {"1", "true", "yes", "evet", "on", "açık", "acik"}:
        return True
    if metin in {"0", "false", "no", "hayir", "hayır", "off", "kapalı", "kapali"}:
        return False
    return bool(varsayilan)


class YuzGizlilikYoneticisi(ModulTabani):
    """
    Yüz gizlilik yöneticisi — toggle, kamera izni, local-only, wire temizliği.

    Sonraki modüller (`algilama`, `kayit`, `tanima`) işlem öncesi
    `izin_zorla()` / `islem_izinli_mi()` çağırmalıdır.
    """

    ad = "vision.yuz.gizlilik"
    surum = "0.1.0"
    aciklama = "Yüz gizlilik — izin, toggle, local-only, wire temizliği"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        olay_yayinla: bool = True,
        yuz_aktif: Optional[bool] = None,
        kamera_izin: Optional[bool] = None,
        kamera_izin_kontrol: Optional[KameraIzinKontrolu] = None,
        yerel_kok: Optional[Union[str, Path]] = None,
        min_guven: Optional[float] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.olay_yayinla = bool(olay_yayinla)
        self._kamera_izin_kontrol = kamera_izin_kontrol
        self._yerel_kok_arg = Path(yerel_kok) if yerel_kok is not None else None

        # Runtime override (None → config / varsayılan)
        self._override_aktif: Optional[bool] = (
            bool(yuz_aktif) if yuz_aktif is not None else None
        )
        self._override_kamera: Optional[bool] = (
            bool(kamera_izin) if kamera_izin is not None else None
        )

        self._min_guven = guven_sinirla(
            min_guven
            if min_guven is not None
            else self._cfg_al(CFG_YUZ_ESIK, VARSAYILAN_YUZ_ESIK),
            varsayilan=VARSAYILAN_YUZ_ESIK,
        )
        self._log = logger_al(f"modul.{self.ad}")
        self._son_red: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------------ özellik

    @property
    def politika(self) -> YuzGizlilikPolitikasi:
        """Her zaman yerel-only — config bile değiştirmez."""
        return YuzGizlilikPolitikasi.YEREL_ONLY

    @property
    def yerel_only(self) -> bool:
        return True

    @property
    def min_guven(self) -> float:
        return float(self._min_guven)

    @property
    def son_red(self) -> Optional[dict[str, Any]]:
        return dict(self._son_red) if self._son_red else None

    def yerel_kok(self) -> Path:
        """Yüz şablonlarının tutulacağı yerel kök."""
        return yerel_kok_coz(self.ayarlar, kok=self._yerel_kok_arg)

    def yerel_kok_hazirla(self) -> Path:
        """Yerel kökü oluşturur (yalnızca disk; bulut yok)."""
        yol = self.yerel_kok()
        try:
            yol.mkdir(parents=True, exist_ok=True)
        except OSError as hata:
            raise VisionError(
                f"Yerel yuz koku olusturulamadi: {yol}",
                kod="VIS_0703",
                modul=self.ad,
                detay={"path": str(yol), "error": str(hata)},
            ) from hata
        return yol

    # ------------------------------------------------------------------ toggle / izin

    def yuz_tanima_aktif_mi(self) -> bool:
        """Ayarlar toggle — varsayılan kapalı."""
        if self._override_aktif is not None:
            return bool(self._override_aktif)
        return _bool_coz(
            self._cfg_al(CFG_YUZ_AKTIF, VARSAYILAN_YUZ_AKTIF),
            varsayilan=VARSAYILAN_YUZ_AKTIF,
        )

    def yuz_tanima_ayarla(self, aktif: bool) -> bool:
        """
        Yüz tanımayı runtime'da aç/kapa (sonraki modüller buna uyar).

        Config dosyasını yazmaz; Engine köprüsü kalıcı yazımı ekleyebilir.
        """
        onceki = self.yuz_tanima_aktif_mi()
        self._override_aktif = bool(aktif)
        detay = {
            "enabled": bool(aktif),
            "previous": onceki,
            "privacy": self.politika.value,
            "local_only": True,
        }
        self._audit("vision.face.privacy.toggle", detay)
        self._yayin(OLAY_YUZ_TOGGLE, detay)
        self._log.info("Yuz tanima toggle=%s (onceki=%s)", aktif, onceki)
        return bool(aktif)

    def kamera_izni_var_mi(self) -> bool:
        """
        Kamera / yüz işleminden önce izin.

        Öncelik: runtime override → enjekte kanca → dry_run True →
        config → varsayılan (False).
        dry_run'da kanca/override yoksa True (offline test / demo; global
        config.camera_permission=false dry_run'ı ezmez).
        """
        if self._override_kamera is not None:
            return bool(self._override_kamera)
        if self._kamera_izin_kontrol is not None:
            try:
                return bool(self._kamera_izin_kontrol())
            except Exception as hata:  # noqa: BLE001
                self._log.warning("Kamera izin kancasi hata: %s", hata)
                return False
        if self.dry_run:
            return True
        cfg = self._cfg_al(CFG_KAMERA_IZIN, None)
        if cfg is not None:
            return _bool_coz(cfg, varsayilan=VARSAYILAN_KAMERA_IZIN)
        return VARSAYILAN_KAMERA_IZIN

    def kamera_izni_ayarla(self, izin: bool) -> bool:
        """Kamera iznini runtime'da ayarlar."""
        onceki = self.kamera_izni_var_mi()
        self._override_kamera = bool(izin)
        detay = {
            "camera_permission": bool(izin),
            "previous": onceki,
            "privacy": self.politika.value,
        }
        self._audit("vision.face.privacy.camera_permission", detay)
        self._yayin(OLAY_KAMERA_IZIN, detay)
        self._log.info("Kamera izni=%s (onceki=%s)", izin, onceki)
        return bool(izin)

    def islem_izinli_mi(self, *, tanima_gerekli: bool = True) -> bool:
        """
        Yüz işlemi yapılabilir mi?

        tanima_gerekli=True → toggle + kamera izni
        tanima_gerekli=False → yalnızca kamera izni (ham algılama için)
        """
        if not self.kamera_izni_var_mi():
            return False
        if tanima_gerekli and not self.yuz_tanima_aktif_mi():
            return False
        return True

    def izin_zorla(self, *, tanima_gerekli: bool = True) -> None:
        """İzin yoksa VisionError fırlatır (algılama/kayıt/tanıma çağırır)."""
        if not self.kamera_izni_var_mi():
            self._son_red = {
                "reason": "camera_permission_denied",
                "camera_permission": False,
                "face_enabled": self.yuz_tanima_aktif_mi(),
            }
            self._audit("vision.face.privacy.denied", wire_temizle(self._son_red))
            self._yayin(OLAY_IZIN_RED, wire_temizle(self._son_red))
            raise VisionError(
                "Kamera izni yok; yuz islemi engellendi",
                kod="VIS_0702",
                modul=self.ad,
                detay=dict(self._son_red),
            )
        if tanima_gerekli and not self.yuz_tanima_aktif_mi():
            self._son_red = {
                "reason": "face_recognition_disabled",
                "camera_permission": True,
                "face_enabled": False,
            }
            self._audit("vision.face.privacy.denied", wire_temizle(self._son_red))
            self._yayin(OLAY_IZIN_RED, wire_temizle(self._son_red))
            raise VisionError(
                "Yuz tanima ayarlardan kapali",
                kod="VIS_0701",
                modul=self.ad,
                detay=dict(self._son_red),
            )
        self._son_red = None

    def bulut_gonderimini_engelle(self, veri: Any = None) -> None:
        """Bulut / sync denemesini her zaman engeller."""
        raise VisionError(
            "Yuz verisi buluta / sync'e gonderilemez (local_only)",
            kod="VIS_0704",
            modul=self.ad,
            detay={
                "privacy": self.politika.value,
                "local_only": True,
                "blocked": True,
                "had_payload": veri is not None,
            },
        )

    # ------------------------------------------------------------------ wire / audit

    def wire_icin(self, veri: VeriGirdi) -> dict[str, Any]:
        """Wire / EventBus için güvenli dict (embedding yok)."""
        if veri is None:
            return {
                "privacy": self.politika.value,
                "local_only": True,
            }
        if isinstance(veri, KayitliKullanici):
            d = veri.to_dict(wire=True)
        elif isinstance(veri, YuzTanimaSonucu):
            d = veri.to_dict()
        elif isinstance(veri, Mapping):
            d = dict(veri)
        else:
            raise VisionError(
                f"wire_icin desteklenmeyen tip: {type(veri)!r}",
                kod="VIS_0705",
                modul=self.ad,
            )
        temiz = wire_temizle(d)
        if not isinstance(temiz, dict):
            temiz = {"value": temiz}
        temiz.setdefault("privacy", self.politika.value)
        temiz.setdefault("local_only", True)
        # Savunma: hassas anahtar kalmadığını doğrula
        for k in list(temiz.keys()):
            if hassas_anahtar_mi(k):
                del temiz[k]
        return temiz

    def audit_icin(self, detay: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Audit kaydı için temizlenmiş detay."""
        temel: dict[str, Any] = {
            "privacy": self.politika.value,
            "local_only": True,
            "face_enabled": self.yuz_tanima_aktif_mi(),
            "camera_permission": self.kamera_izni_var_mi(),
        }
        if detay:
            temel.update(wire_temizle(dict(detay)))
        return wire_temizle(temel)

    def kullanici_wire(self, kullanici: KayitliKullanici) -> dict[str, Any]:
        """Kayıtlı kullanıcıyı wire-güvenli serileştirir."""
        return self.wire_icin(kullanici)

    def tanima_wire(self, sonuc: YuzTanimaSonucu) -> dict[str, Any]:
        """Tanıma sonucunu wire-güvenli serileştirir."""
        return self.wire_icin(sonuc)

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "privacy": self.politika.value,
            "local_only": True,
            "face_enabled": self.yuz_tanima_aktif_mi(),
            "camera_permission": self.kamera_izni_var_mi(),
            "storage_root": str(self.yerel_kok()),
            "min_confidence": self.min_guven,
            "dry_run": bool(self.dry_run),
            "cloud_allowed": False,
            "running": bool(self._calisiyor),
            "last_denied": self.son_red,
        }

    def config_ozeti(self) -> dict[str, Any]:
        """Sonraki yüz modüllerinin okuyacağı config özeti (hassas veri yok)."""
        return {
            CFG_YUZ_AKTIF: self.yuz_tanima_aktif_mi(),
            CFG_KAMERA_IZIN: self.kamera_izni_var_mi(),
            CFG_YUZ_KOK: str(self.yerel_kok()),
            CFG_YUZ_ESIK: self.min_guven,
            CFG_YEREL_ONLY: True,
            "privacy": self.politika.value,
        }

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — bellek / test ayarları
                pass
        # Config'ten güncel eşik
        cfg_esik = self._cfg_al(CFG_YUZ_ESIK, None)
        if cfg_esik is not None:
            self._min_guven = guven_sinirla(cfg_esik, varsayilan=VARSAYILAN_YUZ_ESIK)
        self._isaret_basladi()
        detay = self.audit_icin({"engine": "privacy"})
        self._audit("vision.face.privacy.started", detay)
        self._yayin(OLAY_GIZLILIK_BASLADI, detay)
        self._log.info(
            "Yuz gizlilik basladi enabled=%s camera=%s kok=%s",
            self.yuz_tanima_aktif_mi(),
            self.kamera_izni_var_mi(),
            self.yerel_kok(),
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        detay = self.audit_icin()
        self._audit("vision.face.privacy.stopped", detay)
        self._yayin(OLAY_GIZLILIK_DURDU, detay)
        self._log.info("Yuz gizlilik durdu")

    # ------------------------------------------------------------------ iç

    def _cfg_al(self, anahtar: str, varsayilan: Any = None) -> Any:
        try:
            return self.ayarlar.al(anahtar, varsayilan)
        except Exception:  # noqa: BLE001
            return varsayilan

    def _yayin(self, olay: str, veri: Mapping[str, Any]) -> None:
        if not self.olay_yayinla or self.bus is None:
            return
        try:
            # EventBus'a asla embedding sızmasın
            self.bus.publish_sync(olay, wire_temizle(dict(veri)), kaynak=self.ad)
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Olay yayinlanamadi %s: %s", olay, hata)

    def _audit(self, olay: str, detay: Mapping[str, Any]) -> None:
        try:
            audit_yaz(olay, modul=self.ad, detay=wire_temizle(dict(detay)))
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Audit yazilamadi %s: %s", olay, hata)


def yuz_gizlilik_olustur(
    *,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    dry_run: bool = True,
    olay_yayinla: bool = False,
    yuz_aktif: Optional[bool] = None,
    kamera_izin: Optional[bool] = None,
    kamera_izin_kontrol: Optional[KameraIzinKontrolu] = None,
    yerel_kok: Optional[Union[str, Path]] = None,
    min_guven: Optional[float] = None,
) -> YuzGizlilikYoneticisi:
    """Test / demo için güvenli varsayılanlarla YuzGizlilikYoneticisi üretir."""
    return YuzGizlilikYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        olay_yayinla=olay_yayinla,
        yuz_aktif=yuz_aktif,
        kamera_izin=kamera_izin,
        kamera_izin_kontrol=kamera_izin_kontrol,
        yerel_kok=yerel_kok,
        min_guven=min_guven,
    )


def yuz_islemi_izinli_mi(
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    *,
    tanima_gerekli: bool = True,
    ayarlar: Optional[Ayarlar] = None,
) -> bool:
    """Modül örneği olmadan hızlı izin sorgusu (sonraki dosyalar için)."""
    g = gizlilik or yuz_gizlilik_olustur(ayarlar=ayarlar, dry_run=True, olay_yayinla=False)
    return g.islem_izinli_mi(tanima_gerekli=tanima_gerekli)


__all__ = [
    "OLAY_GIZLILIK_BASLADI",
    "OLAY_GIZLILIK_DURDU",
    "OLAY_YUZ_TOGGLE",
    "OLAY_KAMERA_IZIN",
    "OLAY_IZIN_RED",
    "CFG_YUZ_AKTIF",
    "CFG_KAMERA_IZIN",
    "CFG_YUZ_KOK",
    "CFG_YUZ_ESIK",
    "CFG_YEREL_ONLY",
    "VARSAYILAN_YUZ_AKTIF",
    "VARSAYILAN_KAMERA_IZIN",
    "KameraIzinKontrolu",
    "YuzGizlilikYoneticisi",
    "hassas_anahtar_mi",
    "wire_temizle",
    "buluta_gonderilebilir_mi",
    "yerel_kok_coz",
    "yuz_gizlilik_olustur",
    "yuz_islemi_izinli_mi",
]

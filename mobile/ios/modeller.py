"""
mobile/ios/modeller.py
----------------------
iPhone (iOS) cihaz ve oturum veri modelleri.

Görev:
- iOS'a özel cihaz / pil / oturum durumlarını temsil etmek
- network.device.BagliCihaz ile uyumlu dönüşüm
- Wire JSON anahtarları İngilizce (komut sözleşmesi ile aynı stil)

Not: Gerçek bağlantı `mobile/ios/istemci.py` ve `kopru.py` içinde;
bu modül yalnızca veri modelleri + serileştirme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from core.exceptions import MobileBridgeError
from network.device.modeller import BaglantiDurumu, BagliCihaz, PlatformTuru

IOS_MODEL_SURUM = 1

# Varsayılan iOS istemci yetenekleri (config.mobile.features ile uyumlu)
VARSAYILAN_YETENEKLER: frozenset[str] = frozenset(
    {
        "find_phone",
        "battery_status",
        "send_notification",
        "open_camera",
        "request_location",
        "chat_sync",
        "file_share",
        "shortcuts",
    }
)


class IosOturumDurumu(str, Enum):
    """PC ↔ iPhone oturum durumu."""

    BAGLI_DEGIL = "disconnected"
    BAGLANIYOR = "connecting"
    ESLESME = "pairing"
    BAGLI = "connected"
    KOPUK = "dropped"
    HATA = "error"


IosOturumDurumuGirdi = Union[IosOturumDurumu, str]
BaglantiDurumuGirdi = Union[BaglantiDurumu, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def oturum_durumu_coz(deger: IosOturumDurumuGirdi) -> IosOturumDurumu:
    """str / Enum → IosOturumDurumu."""
    if isinstance(deger, IosOturumDurumu):
        return deger
    metin = str(deger).strip().lower()
    try:
        return IosOturumDurumu(metin)
    except ValueError as hata:
        raise MobileBridgeError(
            f"Bilinmeyen iOS oturum durumu: {deger!r}",
            kod="MOB_0020",
            modul="mobile.ios",
        ) from hata


def baglanti_durumu_coz(deger: BaglantiDurumuGirdi) -> BaglantiDurumu:
    """str / Enum → BaglantiDurumu (network.device ile uyumlu)."""
    if isinstance(deger, BaglantiDurumu):
        return deger
    metin = str(deger).strip().lower()
    try:
        return BaglantiDurumu(metin)
    except ValueError as hata:
        raise MobileBridgeError(
            f"Bilinmeyen baglanti durumu: {deger!r}",
            kod="MOB_0021",
            modul="mobile.ios",
        ) from hata


def _yetenek_listesi(ham: Any) -> list[str]:
    if ham is None:
        return sorted(VARSAYILAN_YETENEKLER)
    if not isinstance(ham, (list, tuple, set, frozenset)):
        raise MobileBridgeError(
            "capabilities liste olmali",
            kod="MOB_0022",
            modul="mobile.ios",
        )
    return sorted({str(x).strip().lower() for x in ham if str(x).strip()})


@dataclass
class IosPilBilgisi:
    """
    iPhone pil özeti.

    Wire: percent, charging, low_power, ts?
    """

    yuzde: Optional[int] = None
    sarj_oluyor: bool = False
    dusuk_guc: bool = False
    zaman: str = field(default_factory=_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "percent": self.yuzde,
            "charging": bool(self.sarj_oluyor),
            "low_power": bool(self.dusuk_guc),
            "ts": self.zaman,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> IosPilBilgisi:
        if not isinstance(veri, dict):
            raise MobileBridgeError(
                "Pil bilgisi dict olmali",
                kod="MOB_0023",
                modul="mobile.ios",
            )
        yuzde_ham = veri.get("percent", veri.get("yuzde"))
        yuzde: Optional[int] = None
        if yuzde_ham is not None:
            yuzde = int(yuzde_ham)
            if yuzde < 0 or yuzde > 100:
                raise MobileBridgeError(
                    f"Gecersiz pil yuzdesi: {yuzde}",
                    kod="MOB_0024",
                    modul="mobile.ios",
                )
        return cls(
            yuzde=yuzde,
            sarj_oluyor=bool(veri.get("charging", veri.get("sarj_oluyor", False))),
            dusuk_guc=bool(veri.get("low_power", veri.get("dusuk_guc", False))),
            zaman=str(veri.get("ts") or veri.get("zaman") or _utc_iso()),
        )


@dataclass
class IosCihaz:
    """
    iPhone cihaz kaydı (BagliCihaz üzerine iOS alanları).

    Wire: device_id, name, model, ios_version, app_version,
          status, battery, capabilities, session_id?, last_seen?, meta, v
    """

    cihaz_id: str
    ad: str
    model: str = "iPhone"
    ios_surum: Optional[str] = None
    uygulama_surum: Optional[str] = None
    durum: BaglantiDurumu = BaglantiDurumu.CEVRIMDISI
    pil: Optional[IosPilBilgisi] = None
    yetenekler: list[str] = field(
        default_factory=lambda: sorted(VARSAYILAN_YETENEKLER)
    )
    oturum_id: Optional[str] = None
    son_gorulme: Optional[str] = None
    token_parmak_izi: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)
    surum: int = IOS_MODEL_SURUM

    def cevrimici_mi(self) -> bool:
        return self.durum in {BaglantiDurumu.CEVRIMICI, BaglantiDurumu.SENKRON}

    def dokun(self) -> None:
        """Son görülme zamanını günceller."""
        self.son_gorulme = _utc_iso()

    def yetenek_var_mi(self, yetenek: str) -> bool:
        return str(yetenek).strip().lower() in self.yetenekler

    def pil_guncelle(
        self,
        yuzde: Optional[int] = None,
        *,
        sarj_oluyor: Optional[bool] = None,
        dusuk_guc: Optional[bool] = None,
    ) -> IosPilBilgisi:
        """Pil bilgisini günceller ve döner."""
        mevcut = self.pil or IosPilBilgisi()
        self.pil = IosPilBilgisi(
            yuzde=mevcut.yuzde if yuzde is None else yuzde,
            sarj_oluyor=(
                mevcut.sarj_oluyor if sarj_oluyor is None else bool(sarj_oluyor)
            ),
            dusuk_guc=mevcut.dusuk_guc if dusuk_guc is None else bool(dusuk_guc),
        )
        self.dokun()
        return self.pil

    def bagli_cihaza(self) -> BagliCihaz:
        """Ortak network.device.BagliCihaz temsiline dönüştürür."""
        meta = dict(self.meta)
        meta.setdefault("ios_model", self.model)
        if self.ios_surum:
            meta.setdefault("ios_version", self.ios_surum)
        if self.uygulama_surum:
            meta.setdefault("app_version", self.uygulama_surum)
        if self.oturum_id:
            meta.setdefault("session_id", self.oturum_id)
        meta.setdefault("capabilities", list(self.yetenekler))
        return BagliCihaz(
            cihaz_id=self.cihaz_id,
            ad=self.ad,
            platform=PlatformTuru.IOS,
            durum=self.durum,
            pil_yuzde=self.pil.yuzde if self.pil else None,
            son_gorulme=self.son_gorulme,
            token_parmak_izi=self.token_parmak_izi,
            meta=meta,
        )

    @classmethod
    def bagli_cihazdan(cls, cihaz: BagliCihaz) -> IosCihaz:
        """BagliCihaz → IosCihaz (platform ios/ipados beklenir)."""
        if cihaz.platform not in {PlatformTuru.IOS, PlatformTuru.IPADOS}:
            raise MobileBridgeError(
                f"IosCihaz yalnizca ios/ipados kabul eder: {cihaz.platform.value}",
                kod="MOB_0025",
                modul="mobile.ios",
                detay={"platform": cihaz.platform.value},
            )
        meta = dict(cihaz.meta or {})
        pil = None
        if cihaz.pil_yuzde is not None:
            pil = IosPilBilgisi(yuzde=int(cihaz.pil_yuzde))
        return cls(
            cihaz_id=cihaz.cihaz_id,
            ad=cihaz.ad,
            model=str(meta.get("ios_model") or meta.get("model") or "iPhone"),
            ios_surum=meta.get("ios_version"),
            uygulama_surum=meta.get("app_version"),
            durum=cihaz.durum,
            pil=pil,
            yetenekler=_yetenek_listesi(meta.get("capabilities")),
            oturum_id=meta.get("session_id"),
            son_gorulme=cihaz.son_gorulme,
            token_parmak_izi=cihaz.token_parmak_izi,
            meta={
                k: v
                for k, v in meta.items()
                if k
                not in {
                    "ios_model",
                    "model",
                    "ios_version",
                    "app_version",
                    "session_id",
                    "capabilities",
                }
            },
        )

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "v": int(self.surum),
            "device_id": self.cihaz_id,
            "name": self.ad,
            "platform": PlatformTuru.IOS.value,
            "model": self.model,
            "status": self.durum.value,
            "capabilities": list(self.yetenekler),
            "meta": dict(self.meta),
        }
        if self.ios_surum:
            veri["ios_version"] = self.ios_surum
        if self.uygulama_surum:
            veri["app_version"] = self.uygulama_surum
        if self.pil is not None:
            veri["battery"] = self.pil.to_dict()
        if self.oturum_id:
            veri["session_id"] = self.oturum_id
        if self.son_gorulme:
            veri["last_seen"] = self.son_gorulme
        if self.token_parmak_izi:
            veri["token_fingerprint"] = self.token_parmak_izi
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> IosCihaz:
        if not isinstance(veri, dict):
            raise MobileBridgeError(
                "IosCihaz dict olmali",
                kod="MOB_0026",
                modul="mobile.ios",
            )
        cihaz_id = str(veri.get("device_id") or veri.get("cihaz_id") or "").strip()
        if not cihaz_id:
            raise MobileBridgeError(
                "device_id zorunlu",
                kod="MOB_0027",
                modul="mobile.ios",
            )
        pil_ham = veri.get("battery")
        pil = IosPilBilgisi.from_dict(pil_ham) if isinstance(pil_ham, dict) else None
        if pil is None and veri.get("battery_percent") is not None:
            pil = IosPilBilgisi(yuzde=int(veri["battery_percent"]))
        return cls(
            cihaz_id=cihaz_id,
            ad=str(veri.get("name") or veri.get("ad") or "iPhone"),
            model=str(veri.get("model") or "iPhone"),
            ios_surum=veri.get("ios_version") or veri.get("ios_surum"),
            uygulama_surum=veri.get("app_version") or veri.get("uygulama_surum"),
            durum=baglanti_durumu_coz(
                veri.get("status") or veri.get("durum") or BaglantiDurumu.CEVRIMDISI
            ),
            pil=pil,
            yetenekler=_yetenek_listesi(veri.get("capabilities")),
            oturum_id=veri.get("session_id") or veri.get("oturum_id"),
            son_gorulme=veri.get("last_seen") or veri.get("son_gorulme"),
            token_parmak_izi=(
                veri.get("token_fingerprint") or veri.get("token_parmak_izi")
            ),
            meta=dict(veri.get("meta") or {}),
            surum=int(veri.get("v", IOS_MODEL_SURUM)),
        )


@dataclass
class IosOturum:
    """
    PC ↔ iPhone köprü oturumu.

    Wire: session_id, device_id?, status, host, authenticated,
          shortcuts_enabled, created, last_activity, token_fingerprint?, meta, v
    """

    oturum_id: str = field(default_factory=lambda: uuid4().hex)
    cihaz_id: Optional[str] = None
    durum: IosOturumDurumu = IosOturumDurumu.BAGLI_DEGIL
    host: str = "127.0.0.1"
    kimlikli: bool = False
    shortcuts_aktif: bool = False
    token_parmak_izi: Optional[str] = None
    olusturma: str = field(default_factory=_utc_iso)
    son_aktivite: str = field(default_factory=_utc_iso)
    meta: dict[str, Any] = field(default_factory=dict)
    surum: int = IOS_MODEL_SURUM

    def bagli_mi(self) -> bool:
        return self.durum is IosOturumDurumu.BAGLI and self.kimlikli

    def dokun(self) -> None:
        """Son aktivite zamanını günceller."""
        self.son_aktivite = _utc_iso()

    def baglan(
        self,
        cihaz_id: str,
        *,
        token_parmak_izi: Optional[str] = None,
        shortcuts_aktif: bool = False,
    ) -> None:
        """Oturumu bağlı / kimlikli duruma getirir."""
        self.cihaz_id = cihaz_id
        self.durum = IosOturumDurumu.BAGLI
        self.kimlikli = True
        if token_parmak_izi is not None:
            self.token_parmak_izi = token_parmak_izi
        self.shortcuts_aktif = bool(shortcuts_aktif)
        self.dokun()

    def kopar(self, *, hata: bool = False) -> None:
        """Oturumu kopuk veya hata durumuna alır."""
        self.durum = IosOturumDurumu.HATA if hata else IosOturumDurumu.KOPUK
        self.kimlikli = False
        self.dokun()

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "v": int(self.surum),
            "session_id": self.oturum_id,
            "status": self.durum.value,
            "host": self.host,
            "authenticated": bool(self.kimlikli),
            "shortcuts_enabled": bool(self.shortcuts_aktif),
            "created": self.olusturma,
            "last_activity": self.son_aktivite,
            "meta": dict(self.meta),
        }
        if self.cihaz_id:
            veri["device_id"] = self.cihaz_id
        if self.token_parmak_izi:
            veri["token_fingerprint"] = self.token_parmak_izi
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> IosOturum:
        if not isinstance(veri, dict):
            raise MobileBridgeError(
                "IosOturum dict olmali",
                kod="MOB_0028",
                modul="mobile.ios",
            )
        return cls(
            oturum_id=str(veri.get("session_id") or veri.get("oturum_id") or uuid4().hex),
            cihaz_id=veri.get("device_id") or veri.get("cihaz_id"),
            durum=oturum_durumu_coz(
                veri.get("status") or veri.get("durum") or IosOturumDurumu.BAGLI_DEGIL
            ),
            host=str(veri.get("host") or "127.0.0.1"),
            kimlikli=bool(veri.get("authenticated", veri.get("kimlikli", False))),
            shortcuts_aktif=bool(
                veri.get("shortcuts_enabled", veri.get("shortcuts_aktif", False))
            ),
            token_parmak_izi=(
                veri.get("token_fingerprint") or veri.get("token_parmak_izi")
            ),
            olusturma=str(veri.get("created") or veri.get("olusturma") or _utc_iso()),
            son_aktivite=str(
                veri.get("last_activity") or veri.get("son_aktivite") or _utc_iso()
            ),
            meta=dict(veri.get("meta") or {}),
            surum=int(veri.get("v", IOS_MODEL_SURUM)),
        )


def ios_cihaz_olustur(
    cihaz_id: Optional[str] = None,
    *,
    ad: str = "iPhone",
    model: str = "iPhone",
    ios_surum: Optional[str] = None,
) -> IosCihaz:
    """Yeni IosCihaz üretir (test / sahte istemci için)."""
    return IosCihaz(
        cihaz_id=cihaz_id or uuid4().hex,
        ad=ad,
        model=model,
        ios_surum=ios_surum,
        durum=BaglantiDurumu.CEVRIMDISI,
    )


def ios_oturum_olustur(
    *,
    host: str = "127.0.0.1",
    cihaz_id: Optional[str] = None,
) -> IosOturum:
    """Yeni IosOturum üretir."""
    oturum = IosOturum(host=host, cihaz_id=cihaz_id)
    if cihaz_id:
        oturum.durum = IosOturumDurumu.BAGLANIYOR
    return oturum


__all__ = [
    "IOS_MODEL_SURUM",
    "VARSAYILAN_YETENEKLER",
    "IosOturumDurumu",
    "IosPilBilgisi",
    "IosCihaz",
    "IosOturum",
    "oturum_durumu_coz",
    "baglanti_durumu_coz",
    "ios_cihaz_olustur",
    "ios_oturum_olustur",
]

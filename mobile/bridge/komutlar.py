"""
mobile/bridge/komutlar.py
-------------------------
Windows ↔ iPhone (mobil) komut sözleşmesi.

Görev:
- PC→telefon / telefon→PC komut tiplerini sabitlenmek
- İstek / yanıt veri modelleri (wire JSON anahtarları İngilizce)
- config.mobile.commands ile yön doğrulama
- Tehlikeli remote komutları işaretlemek

Not: Gerçek iletim `mobile/ios/kopru.py` ve WebSocket COMMAND mesajında;
bu modül yalnızca sözleşme + serileştirme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import MobileBridgeError
from core.logger import logger_al

log = logger_al("mobile.bridge.komutlar")

KOMUT_SOZLESME_SURUM = 1

# phone_to_pc komutlarından Windows onayı gerektirenler
TEHLIKELI_KOMUTLAR: frozenset[str] = frozenset(
    {
        "shutdown_pc",
    }
)


class KomutYon(str, Enum):
    """Komut yönü."""

    PC_TO_PHONE = "pc_to_phone"
    PHONE_TO_PC = "phone_to_pc"


class MobilKomut(str, Enum):
    """Bilinen mobil köprü komutları (config.mobile.commands ile uyumlu)."""

    # PC → telefon
    FIND_PHONE = "find_phone"
    BATTERY_STATUS = "battery_status"
    SEND_NOTIFICATION = "send_notification"
    OPEN_CAMERA = "open_camera"
    REQUEST_LOCATION = "request_location"

    # Telefon → PC
    SHUTDOWN_PC = "shutdown_pc"
    OPEN_VSCODE = "open_vscode"
    OPEN_CHROME = "open_chrome"
    SEND_FILE = "send_file"
    TAKE_SCREENSHOT = "take_screenshot"


class KomutDurum(str, Enum):
    """Komut yanıt durumu."""

    OK = "ok"
    HATA = "error"
    REDDEDILDI = "denied"
    BEKLIYOR = "pending"
    DESTEKLENMIYOR = "unsupported"


# Varsayılan yön haritası (config yoksa)
_VARSAYILAN_YON: dict[MobilKomut, KomutYon] = {
    MobilKomut.FIND_PHONE: KomutYon.PC_TO_PHONE,
    MobilKomut.BATTERY_STATUS: KomutYon.PC_TO_PHONE,
    MobilKomut.SEND_NOTIFICATION: KomutYon.PC_TO_PHONE,
    MobilKomut.OPEN_CAMERA: KomutYon.PC_TO_PHONE,
    MobilKomut.REQUEST_LOCATION: KomutYon.PC_TO_PHONE,
    MobilKomut.SHUTDOWN_PC: KomutYon.PHONE_TO_PC,
    MobilKomut.OPEN_VSCODE: KomutYon.PHONE_TO_PC,
    MobilKomut.OPEN_CHROME: KomutYon.PHONE_TO_PC,
    MobilKomut.SEND_FILE: KomutYon.PHONE_TO_PC,
    MobilKomut.TAKE_SCREENSHOT: KomutYon.PHONE_TO_PC,
}

MobilKomutGirdi = Union[MobilKomut, str]
KomutYonGirdi = Union[KomutYon, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def komut_coz(deger: MobilKomutGirdi) -> MobilKomut:
    """str / Enum → MobilKomut; bilinmeyenlerde MobileBridgeError."""
    if isinstance(deger, MobilKomut):
        return deger
    metin = str(deger).strip().lower()
    try:
        return MobilKomut(metin)
    except ValueError as hata:
        raise MobileBridgeError(
            f"Bilinmeyen mobil komut: {deger!r}",
            kod="MOB_0010",
            modul="mobile.bridge",
        ) from hata


def yon_coz(deger: KomutYonGirdi) -> KomutYon:
    """str / Enum → KomutYon."""
    if isinstance(deger, KomutYon):
        return deger
    metin = str(deger).strip().lower()
    try:
        return KomutYon(metin)
    except ValueError as hata:
        raise MobileBridgeError(
            f"Bilinmeyen komut yonu: {deger!r}",
            kod="MOB_0011",
            modul="mobile.bridge",
        ) from hata


def komut_yonu(komut: MobilKomutGirdi) -> KomutYon:
    """Komutun varsayılan yönünü döner."""
    k = komut_coz(komut)
    return _VARSAYILAN_YON[k]


def tehlikeli_mi(komut: MobilKomutGirdi) -> bool:
    """Windows tarafında onay gerektiren remote komut mu?"""
    return komut_coz(komut).value in TEHLIKELI_KOMUTLAR


@dataclass
class MobilKomutIstegi:
    """
    Tek bir mobil komut isteği.

    Wire JSON anahtarları İngilizce:
      v, command, direction, id, ts, device_id?, corr_id?, args, require_confirm
    """

    komut: MobilKomut
    yon: KomutYon
    args: dict[str, Any] = field(default_factory=dict)
    istek_id: str = field(default_factory=lambda: uuid4().hex)
    zaman: str = field(default_factory=_utc_iso)
    cihaz_id: Optional[str] = None
    corr_id: Optional[str] = None
    onay_gerekli: bool = False
    surum: int = KOMUT_SOZLESME_SURUM

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "v": int(self.surum),
            "command": self.komut.value,
            "direction": self.yon.value,
            "id": self.istek_id,
            "ts": self.zaman,
            "args": dict(self.args),
            "require_confirm": bool(self.onay_gerekli),
        }
        if self.cihaz_id:
            veri["device_id"] = self.cihaz_id
        if self.corr_id:
            veri["corr_id"] = self.corr_id
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> MobilKomutIstegi:
        if not isinstance(veri, dict):
            raise MobileBridgeError(
                "Komut istegi dict olmali",
                kod="MOB_0012",
                modul="mobile.bridge",
            )
        komut = komut_coz(veri.get("command", ""))
        yon_ham = veri.get("direction")
        yon = yon_coz(yon_ham) if yon_ham else komut_yonu(komut)
        args = veri.get("args") or {}
        if not isinstance(args, dict):
            raise MobileBridgeError(
                "Komut args dict olmali",
                kod="MOB_0013",
                modul="mobile.bridge",
            )
        return cls(
            komut=komut,
            yon=yon,
            args=dict(args),
            istek_id=str(veri.get("id") or uuid4().hex),
            zaman=str(veri.get("ts") or _utc_iso()),
            cihaz_id=veri.get("device_id"),
            corr_id=veri.get("corr_id"),
            onay_gerekli=bool(
                veri.get("require_confirm", tehlikeli_mi(komut))
            ),
            surum=int(veri.get("v", KOMUT_SOZLESME_SURUM)),
        )


@dataclass
class MobilKomutYaniti:
    """Komut sonucu."""

    komut: MobilKomut
    durum: KomutDurum
    mesaj: str = ""
    veri: dict[str, Any] = field(default_factory=dict)
    istek_id: Optional[str] = None
    zaman: str = field(default_factory=_utc_iso)
    cihaz_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        sonuc: dict[str, Any] = {
            "command": self.komut.value,
            "status": self.durum.value,
            "message": self.mesaj,
            "data": dict(self.veri),
            "ts": self.zaman,
        }
        if self.istek_id:
            sonuc["id"] = self.istek_id
        if self.cihaz_id:
            sonuc["device_id"] = self.cihaz_id
        return sonuc

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> MobilKomutYaniti:
        if not isinstance(veri, dict):
            raise MobileBridgeError(
                "Komut yaniti dict olmali",
                kod="MOB_0014",
                modul="mobile.bridge",
            )
        durum_ham = str(veri.get("status", "error")).strip().lower()
        try:
            durum = KomutDurum(durum_ham)
        except ValueError as hata:
            raise MobileBridgeError(
                f"Bilinmeyen komut durumu: {durum_ham!r}",
                kod="MOB_0015",
                modul="mobile.bridge",
            ) from hata
        data = veri.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        return cls(
            komut=komut_coz(veri.get("command", "")),
            durum=durum,
            mesaj=str(veri.get("message") or ""),
            veri=dict(data),
            istek_id=veri.get("id"),
            zaman=str(veri.get("ts") or _utc_iso()),
            cihaz_id=veri.get("device_id"),
        )

    @property
    def basarili_mi(self) -> bool:
        return self.durum is KomutDurum.OK


class MobilKomutSozlesmesi:
    """
    config.mobile.commands listelerine göre komut doğrulama ve istek üretimi.
    """

    def __init__(self, ayarlar: Optional[Ayarlar] = None) -> None:
        self.ayarlar = ayarlar or global_ayarlar

    def pc_to_phone_listesi(self) -> list[str]:
        ham = self.ayarlar.al("mobile.commands.pc_to_phone", None)
        if isinstance(ham, list) and ham:
            return [str(x).strip().lower() for x in ham]
        return [
            k.value
            for k, y in _VARSAYILAN_YON.items()
            if y is KomutYon.PC_TO_PHONE
        ]

    def phone_to_pc_listesi(self) -> list[str]:
        ham = self.ayarlar.al("mobile.commands.phone_to_pc", None)
        if isinstance(ham, list) and ham:
            return [str(x).strip().lower() for x in ham]
        return [
            k.value
            for k, y in _VARSAYILAN_YON.items()
            if y is KomutYon.PHONE_TO_PC
        ]

    def izinli_mi(self, komut: MobilKomutGirdi, yon: Optional[KomutYonGirdi] = None) -> bool:
        """Komut config listesinde ve yönü tutarlı mı?"""
        k = komut_coz(komut)
        beklenen = komut_yonu(k)
        if yon is not None and yon_coz(yon) is not beklenen:
            return False
        if beklenen is KomutYon.PC_TO_PHONE:
            return k.value in self.pc_to_phone_listesi()
        return k.value in self.phone_to_pc_listesi()

    def istek_olustur(
        self,
        komut: MobilKomutGirdi,
        *,
        cihaz_id: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        corr_id: Optional[str] = None,
        dogrula: bool = True,
    ) -> MobilKomutIstegi:
        """Doğrulanmış MobilKomutIstegi üretir."""
        k = komut_coz(komut)
        yon = komut_yonu(k)
        if dogrula and not self.izinli_mi(k, yon):
            raise MobileBridgeError(
                f"Komut config ile izinli degil: {k.value} ({yon.value})",
                kod="MOB_0016",
                modul="mobile.bridge",
                detay={"command": k.value, "direction": yon.value},
            )
        istek = MobilKomutIstegi(
            komut=k,
            yon=yon,
            args=dict(args or {}),
            cihaz_id=cihaz_id,
            corr_id=corr_id,
            onay_gerekli=tehlikeli_mi(k),
        )
        log.debug(
            "Mobil komut istegi: %s yon=%s cihaz=%s onay=%s",
            k.value,
            yon.value,
            cihaz_id,
            istek.onay_gerekli,
        )
        return istek

    def yanit_ok(
        self,
        komut: MobilKomutGirdi,
        *,
        mesaj: str = "OK",
        veri: Optional[dict[str, Any]] = None,
        istek_id: Optional[str] = None,
        cihaz_id: Optional[str] = None,
    ) -> MobilKomutYaniti:
        return MobilKomutYaniti(
            komut=komut_coz(komut),
            durum=KomutDurum.OK,
            mesaj=mesaj,
            veri=dict(veri or {}),
            istek_id=istek_id,
            cihaz_id=cihaz_id,
        )

    def yanit_hata(
        self,
        komut: MobilKomutGirdi,
        mesaj: str,
        *,
        durum: KomutDurum = KomutDurum.HATA,
        istek_id: Optional[str] = None,
        cihaz_id: Optional[str] = None,
        veri: Optional[dict[str, Any]] = None,
    ) -> MobilKomutYaniti:
        return MobilKomutYaniti(
            komut=komut_coz(komut),
            durum=durum,
            mesaj=mesaj,
            veri=dict(veri or {}),
            istek_id=istek_id,
            cihaz_id=cihaz_id,
        )


def istek_olustur(
    komut: MobilKomutGirdi,
    *,
    cihaz_id: Optional[str] = None,
    args: Optional[dict[str, Any]] = None,
    ayarlar: Optional[Ayarlar] = None,
    dogrula: bool = True,
) -> MobilKomutIstegi:
    """Kısayol: MobilKomutSozlesmesi.istek_olustur."""
    return MobilKomutSozlesmesi(ayarlar).istek_olustur(
        komut,
        cihaz_id=cihaz_id,
        args=args,
        dogrula=dogrula,
    )


__all__ = [
    "KOMUT_SOZLESME_SURUM",
    "TEHLIKELI_KOMUTLAR",
    "KomutYon",
    "MobilKomut",
    "KomutDurum",
    "MobilKomutIstegi",
    "MobilKomutYaniti",
    "MobilKomutSozlesmesi",
    "komut_coz",
    "yon_coz",
    "komut_yonu",
    "tehlikeli_mi",
    "istek_olustur",
]

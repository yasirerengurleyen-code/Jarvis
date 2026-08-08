"""
core/base.py
------------
WhiteCore AI çekirdek taban yapıları.

Görev:
- Tüm modüller için ortak arayüz (ModulTabani)
- Mesaj ve yetenek sonuç veri modelleri
- Sistem durumu enumerasyonları
- Platform bilinci olan genişletilebilir tabanlar

Bu dosya olay motorundan (events) ve uygulama motorundan (engine)
bağımsız tutulur; yalnızca veri + sözleşme katmanıdır.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from core.logger import logger_al

log = logger_al("core.base")


def _utc_iso() -> str:
    """UTC zaman damgası (ISO-8601)."""
    return datetime.now(timezone.utc).isoformat()


class SistemDurumu(str, Enum):
    """J.A.R.V.I.S. çalışma durumu."""

    KAPALI = "kapali"
    BASLIYOR = "basliyor"
    HAZIR = "hazir"
    DINLIYOR = "dinliyor"          # wake word bekleniyor
    DINLEMEDE = "dinlemede"        # kullanıcı konuşuyor
    DUSUNUYOR = "dusunuyor"
    KONUSUYOR = "konusuyor"
    SENKRON = "senkron"
    HATA = "hata"


class MesajRolu(str, Enum):
    """Sohbet mesajı rolü."""

    SISTEM = "system"
    KULLANICI = "user"
    ASISTAN = "assistant"
    ARAC = "tool"


class YetenekDurumu(str, Enum):
    """Skill / otomasyon adımı sonucu."""

    BASARILI = "basarili"
    BASARISIZ = "basarisiz"
    IPTAL = "iptal"
    ONAY_BEKLIYOR = "onay_bekliyor"
    DESTEKLENMIYOR = "desteklenmiyor"


@dataclass
class Mesaj:
    """Tek bir sohbet / olay mesajı."""

    icerik: str
    rol: MesajRolu = MesajRolu.KULLANICI
    mesaj_id: str = field(default_factory=lambda: str(uuid4()))
    zaman: str = field(default_factory=_utc_iso)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.mesaj_id,
            "role": self.rol.value,
            "content": self.icerik,
            "timestamp": self.zaman,
            "meta": self.meta,
        }

    @classmethod
    def kullanici(cls, icerik: str, **meta: Any) -> "Mesaj":
        return cls(icerik=icerik, rol=MesajRolu.KULLANICI, meta=dict(meta))

    @classmethod
    def asistan(cls, icerik: str, **meta: Any) -> "Mesaj":
        return cls(icerik=icerik, rol=MesajRolu.ASISTAN, meta=dict(meta))

    @classmethod
    def sistem(cls, icerik: str, **meta: Any) -> "Mesaj":
        return cls(icerik=icerik, rol=MesajRolu.SISTEM, meta=dict(meta))


@dataclass
class YetenekSonucu:
    """Bir skill veya ajan adımının sonucu."""

    durum: YetenekDurumu
    mesaj: str = ""
    veri: dict[str, Any] = field(default_factory=dict)
    yetenek: Optional[str] = None
    zaman: str = field(default_factory=_utc_iso)

    @property
    def basarili(self) -> bool:
        return self.durum == YetenekDurumu.BASARILI

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.durum.value,
            "message": self.mesaj,
            "data": self.veri,
            "skill": self.yetenek,
            "timestamp": self.zaman,
            "ok": self.basarili,
        }

    @classmethod
    def ok(
        cls,
        mesaj: str = "Tamam",
        *,
        yetenek: Optional[str] = None,
        veri: Optional[dict[str, Any]] = None,
    ) -> "YetenekSonucu":
        return cls(
            durum=YetenekDurumu.BASARILI,
            mesaj=mesaj,
            yetenek=yetenek,
            veri=veri or {},
        )

    @classmethod
    def hata(
        cls,
        mesaj: str,
        *,
        yetenek: Optional[str] = None,
        veri: Optional[dict[str, Any]] = None,
    ) -> "YetenekSonucu":
        return cls(
            durum=YetenekDurumu.BASARISIZ,
            mesaj=mesaj,
            yetenek=yetenek,
            veri=veri or {},
        )

    @classmethod
    def onay_gerekli(
        cls,
        mesaj: str,
        *,
        yetenek: Optional[str] = None,
        veri: Optional[dict[str, Any]] = None,
    ) -> "YetenekSonucu":
        return cls(
            durum=YetenekDurumu.ONAY_BEKLIYOR,
            mesaj=mesaj,
            yetenek=yetenek,
            veri=veri or {},
        )


@dataclass
class ModulBilgisi:
    """Modül kimlik kartı (GUI / web / mobil durum panelleri için)."""

    ad: str
    surum: str = "0.1.0"
    aciklama: str = ""
    platformlar: tuple[str, ...] = ("windows",)
    hazir: bool = False


class ModulTabani(ABC):
    """
    Tüm WhiteCore modülleri için ortak yaşam döngüsü sözleşmesi.

    Örnek: beyin, ses, hafıza, ağ, GUI eklentileri.
    """

    ad: str = "modul"
    surum: str = "0.1.0"
    aciklama: str = ""

    def __init__(self) -> None:
        self._calisiyor = False
        self._log = logger_al(f"modul.{self.ad}")

    @property
    def calisiyor(self) -> bool:
        return self._calisiyor

    def bilgi(self) -> ModulBilgisi:
        return ModulBilgisi(
            ad=self.ad,
            surum=self.surum,
            aciklama=self.aciklama,
            hazir=self._calisiyor,
        )

    @abstractmethod
    async def baslat(self) -> None:
        """Modülü başlatır."""

    @abstractmethod
    async def durdur(self) -> None:
        """Modülü güvenli şekilde durdurur."""

    async def yeniden_baslat(self) -> None:
        """Durdurup yeniden başlatır."""
        await self.durdur()
        await self.baslat()

    def _isaret_basladi(self) -> None:
        self._calisiyor = True
        self._log.info("Modül başlatıldı: %s", self.ad)

    def _isaret_durdu(self) -> None:
        self._calisiyor = False
        self._log.info("Modül durduruldu: %s", self.ad)


class YetenekTabani(ABC):
    """
    Skill (yetenek) taban sınıfı.

    Her yetenek tek bir işi yapar; ajan birden fazla yeteneği planlar.
    """

    ad: str = "yetenek"
    aciklama: str = ""
    tehlikeli: bool = False

    @abstractmethod
    async def calistir(self, komut: str, **kwargs: Any) -> YetenekSonucu:
        """Yeteneği çalıştırır."""

    def eslesir_mi(self, komut: str) -> bool:
        """
        Basit anahtar kelime kontrolü.

        Alt sınıflar daha akıllı eşleştirme uygulayabilir.
        """
        return self.ad.lower() in komut.lower()


class PlatformIstemciTabani(ABC):
    """
    Uzak istemci (iOS / iPadOS / Web / ileride Android) için ince sözleşme.

    Tam uygulama platform paketlerinde (mobile/ios vb.) yapılır.
    """

    platform: str = "unknown"

    @abstractmethod
    async def baglan(self, host: str, token: str) -> bool:
        """Çekirdek sunucuya bağlanır."""

    @abstractmethod
    async def baglantiyi_kes(self) -> None:
        """Bağlantıyı kapatır."""

    @abstractmethod
    async def durum(self) -> dict[str, Any]:
        """İstemci durum özetini döner."""


__all__ = [
    "SistemDurumu",
    "MesajRolu",
    "YetenekDurumu",
    "Mesaj",
    "YetenekSonucu",
    "ModulBilgisi",
    "ModulTabani",
    "YetenekTabani",
    "PlatformIstemciTabani",
]

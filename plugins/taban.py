"""
plugins/taban.py
----------------
Eklenti (plugin) ortak taban ve yaşam döngüsü.

Görev:
- PluginTabani sözleşmesini netleştirmek (yukle / kaldir / calistir)
- Manifest / kayıt ile durum takibi (PluginDurumu)
- Tehlikeli işlemler için onay bayrağı kontrolü
- dry_run ve ajan köprüsü yardımcıları

Not: Keşif / sandbox / yönetici `yukleyici.py`, `guvenlik.py`, `yoneticisi.py`
içinde; bu modül yalnızca eklenti örneği sözleşmesi + yaşam döngüsü.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from core.base import YetenekDurumu
from core.exceptions import PluginError
from core.logger import logger_al
from plugins.modeller import (
    PluginDurumu,
    PluginKaynak,
    PluginKayit,
    PluginManifesto,
    PluginSonucu,
    eklenti_adi_dogrula,
)
from skills.taban import anahtar_eslesir, tehlikeli_onay_gerekli

log = logger_al("plugins.taban")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PluginBaglam:
    """Eklenti çalıştırma bağlamı (yönetici / ajan iletir)."""

    kullanici_id: Optional[str] = None
    onaylandi: bool = False
    dry_run: bool = False
    ayar_yonetici: Any = None
    ekstra: dict[str, Any] = field(default_factory=dict)


class PluginTabani(ABC):
    """
    Tüm WhiteCore eklentilerinin tabanı.

    Alt sınıflar:
    - ad / surum / aciklama / tehlikeli / anahtarlar tanımlar
    - gerekirse ``_yukle`` / ``_kaldir`` özelleştirir
    - ``calistir()`` uygular
    """

    ad: str = "plugin"
    surum: str = "0.1.0"
    aciklama: str = ""
    yazar: str = ""
    tehlikeli: bool = False
    anahtarlar: Sequence[str] = ()
    izinler: Sequence[str] = ()
    kaynak: PluginKaynak = PluginKaynak.DOSYA
    yol: Optional[str] = None
    # config.security.dangerous_actions ile eşleşecek kimlik (opsiyonel)
    tehlike_eylemi: Optional[str] = None

    def __init__(self) -> None:
        self._ad = eklenti_adi_dogrula(self.ad)
        self._durum = PluginDurumu.KESFEDILDI
        self._hata: Optional[str] = None
        self._yuklenme_zamani: Optional[str] = None
        self._log = logger_al(f"plugins.{self._ad}")
        self._meta: dict[str, Any] = {}

    # --- durum / kimlik -------------------------------------------------

    @property
    def eklenti_adi(self) -> str:
        """Normalize edilmiş eklenti adı."""
        return self._ad

    @property
    def durum(self) -> PluginDurumu:
        return self._durum

    @property
    def hazir_mi(self) -> bool:
        return self._durum is PluginDurumu.HAZIR

    @property
    def calisiyor_mu(self) -> bool:
        return self._durum is PluginDurumu.CALISIYOR

    def manifesto(self) -> PluginManifesto:
        """Eklenti kimlik kartı (modeller.PluginManifesto)."""
        return PluginManifesto(
            ad=self._ad,
            surum=self.surum,
            giris=self._ad,
            aciklama=self.aciklama,
            yazar=self.yazar,
            tehlikeli=bool(self.tehlikeli),
            anahtarlar=tuple(self.anahtarlar) if self.anahtarlar else (self._ad,),
            izinler=tuple(self.izinler),
            kaynak=self.kaynak,
            yol=self.yol,
            meta=dict(self._meta),
        )

    def kayit(self) -> PluginKayit:
        """Güncel durumlu PluginKayit satırı."""
        return PluginKayit(
            manifesto=self.manifesto(),
            durum=self._durum,
            yuklenme_zamani=self._yuklenme_zamani,
            hata=self._hata,
            meta=dict(self._meta),
        )

    def eslesir_mi(self, komut: str) -> bool:
        """Komut / anahtar eşleşmesi (skill stili)."""
        anahtarlar = list(self.anahtarlar) if self.anahtarlar else [self._ad]
        if anahtar_eslesir(komut, anahtarlar):
            return True
        return self._ad.lower() in (komut or "").lower()

    # --- yaşam döngüsü --------------------------------------------------

    async def yukle(self) -> None:
        """
        Eklentiyi yükler: KESFEDILDI / HATA / KALDIRILDI → HAZIR.

        Zaten HAZIR ise no-op.
        """
        if self._durum is PluginDurumu.HAZIR:
            return
        if self._durum is PluginDurumu.CALISIYOR:
            raise PluginError(
                f"Eklenti calisirken yuklenemez: {self._ad}",
                kod="PLG_0031",
                modul="plugins",
                detay={"status": self._durum.value},
            )
        if self._durum is PluginDurumu.DEVRE_DISI:
            raise PluginError(
                f"Eklenti devre disi: {self._ad}",
                kod="PLG_0032",
                modul="plugins",
                detay={"status": self._durum.value},
            )

        self._durum = PluginDurumu.YUKLENIYOR
        self._hata = None
        try:
            await self._yukle()
        except PluginError:
            self._durum = PluginDurumu.HATA
            raise
        except Exception as hata:
            self._durum = PluginDurumu.HATA
            self._hata = str(hata)
            raise PluginError(
                f"Eklenti yuklenemedi: {self._ad}: {hata}",
                kod="PLG_0033",
                modul="plugins",
                detay={"plugin": self._ad},
            ) from hata

        self._durum = PluginDurumu.HAZIR
        self._yuklenme_zamani = _utc_iso()
        self._hata = None
        self._log.info("Eklenti yuklendi: %s v%s", self._ad, self.surum)

    async def kaldir(self) -> None:
        """Eklentiyi kaldırır → KALDIRILDI."""
        if self._durum is PluginDurumu.KALDIRILDI:
            return
        if self._durum is PluginDurumu.CALISIYOR:
            raise PluginError(
                f"Eklenti calisirken kaldirilamaz: {self._ad}",
                kod="PLG_0034",
                modul="plugins",
                detay={"status": self._durum.value},
            )
        try:
            await self._kaldir()
        except PluginError:
            self._durum = PluginDurumu.HATA
            raise
        except Exception as hata:
            self._durum = PluginDurumu.HATA
            self._hata = str(hata)
            raise PluginError(
                f"Eklenti kaldirilamadi: {self._ad}: {hata}",
                kod="PLG_0035",
                modul="plugins",
                detay={"plugin": self._ad},
            ) from hata

        self._durum = PluginDurumu.KALDIRILDI
        self._hata = None
        self._log.info("Eklenti kaldirildi: %s", self._ad)

    def devre_disi_birak(self) -> None:
        """Eklentiyi DEVRE_DISI yapar (yönetici / güvenlik)."""
        if self._durum is PluginDurumu.CALISIYOR:
            raise PluginError(
                f"Eklenti calisirken devre disi birakilamaz: {self._ad}",
                kod="PLG_0036",
                modul="plugins",
            )
        self._durum = PluginDurumu.DEVRE_DISI
        self._log.info("Eklenti devre disi: %s", self._ad)

    async def _yukle(self) -> None:
        """Alt sınıflar kaynak açma vb. için özelleştirir."""
        return None

    async def _kaldir(self) -> None:
        """Alt sınıflar kaynak kapatma vb. için özelleştirir."""
        return None

    # --- çalıştırma -----------------------------------------------------

    @abstractmethod
    async def calistir(self, komut: str, **kwargs: Any) -> PluginSonucu:
        """Eklenti işini yürütür; alt sınıf uygular."""

    async def guvenli_calistir(self, komut: str, **kwargs: Any) -> PluginSonucu:
        """
        Hazırlık + onay + durum geçişleriyle ``calistir`` sarmalayıcısı.

        Yönetici / ajan bu metodu tercih edebilir.
        """
        if not self.hazir_mi:
            return PluginSonucu.hata(
                f"Eklenti hazir degil: {self._ad} ({self._durum.value})",
                eklenti=self._ad,
                veri={"status": self._durum.value},
            )

        baglam: Optional[PluginBaglam] = kwargs.get("baglam")
        onaylandi = bool(kwargs.get("onaylandi", False))
        ayar = kwargs.get("ayar_yonetici")
        if baglam is not None:
            onaylandi = onaylandi or bool(baglam.onaylandi)
            if ayar is None:
                ayar = baglam.ayar_yonetici
            if baglam.dry_run and "dry_run" not in kwargs:
                kwargs = {**kwargs, "dry_run": True}

        engel = self.onay_kontrol(onaylandi=onaylandi, ayar_yonetici=ayar)
        if engel is not None:
            return engel

        # Alt sinif calistir() icin onay / ayar bayraklarini ilet
        kwargs = {
            **kwargs,
            "onaylandi": onaylandi,
            "ayar_yonetici": ayar,
        }

        if bool(kwargs.get("dry_run", False)):
            return self.dry_run_sonucu(komut, **kwargs)

        onceki = self._durum
        self._durum = PluginDurumu.CALISIYOR
        try:
            sonuc = await self.calistir(komut, **kwargs)
        except PluginError as hata:
            self._durum = PluginDurumu.HATA
            self._hata = hata.mesaj
            return PluginSonucu.hata(
                hata.mesaj,
                eklenti=self._ad,
                veri={"code": hata.kod, **(hata.detay or {})},
            )
        except Exception as hata:
            self._durum = PluginDurumu.HATA
            self._hata = str(hata)
            return PluginSonucu.hata(
                f"Eklenti hatasi: {hata}",
                eklenti=self._ad,
            )
        else:
            if not isinstance(sonuc, PluginSonucu):
                self._durum = PluginDurumu.HATA
                self._hata = "gecersiz sonuc tipi"
                return PluginSonucu.hata(
                    "calistir PluginSonucu donmeli",
                    eklenti=self._ad,
                )
            self._durum = PluginDurumu.HAZIR if onceki is PluginDurumu.HAZIR else onceki
            self._hata = None if sonuc.basarili_mi else (sonuc.mesaj or "hata")
            if not sonuc.eklenti:
                sonuc.eklenti = self._ad
            return sonuc

    # --- yardımcılar ----------------------------------------------------

    def onay_kontrol(
        self,
        *,
        onaylandi: bool = False,
        ayar_yonetici: Any = None,
    ) -> Optional[PluginSonucu]:
        """
        Tehlikeli eklenti için onay yoksa ONAY_BEKLIYOR sonucu döner.
        Güvenliyse None (devam et).
        """
        if not self.tehlikeli:
            return None
        if onaylandi:
            return None
        if not tehlikeli_onay_gerekli(
            ayar_yonetici, eylem=self.tehlike_eylemi or self._ad
        ):
            return None
        return PluginSonucu(
            durum=YetenekDurumu.ONAY_BEKLIYOR,
            mesaj=f"'{self._ad}' tehlikeli bir eklenti; kullanici onayi gerekli.",
            eklenti=self._ad,
            veri={"action": self.tehlike_eylemi or self._ad},
        )

    def dry_run_sonucu(self, komut: str, **kwargs: Any) -> PluginSonucu:
        """dry_run kabul stub'ı (gerçek yan etki yok)."""
        return PluginSonucu.ok(
            "dry_run",
            eklenti=self._ad,
            veri={
                "dry_run": True,
                "command": komut,
                "plugin": self._ad,
                "kwargs": {
                    k: v
                    for k, v in kwargs.items()
                    if k not in {"baglam", "ayar_yonetici"} and not callable(v)
                },
            },
        )

    def ok(
        self,
        mesaj: str = "ok",
        *,
        veri: Optional[dict[str, Any]] = None,
        sure_ms: Optional[float] = None,
    ) -> PluginSonucu:
        return PluginSonucu.ok(
            mesaj,
            eklenti=self._ad,
            veri=veri,
            sure_ms=sure_ms,
        )

    def hata(
        self,
        mesaj: str,
        *,
        veri: Optional[dict[str, Any]] = None,
    ) -> PluginSonucu:
        return PluginSonucu.hata(mesaj, eklenti=self._ad, veri=veri)

    def desteklenmiyor(self, mesaj: str = "Bu islem desteklenmiyor") -> PluginSonucu:
        return PluginSonucu(
            durum=YetenekDurumu.DESTEKLENMIYOR,
            mesaj=mesaj,
            eklenti=self._ad,
        )


__all__ = [
    "PluginBaglam",
    "PluginTabani",
    "PluginSonucu",
    "PluginDurumu",
    "PluginManifesto",
    "PluginKayit",
    "anahtar_eslesir",
    "tehlikeli_onay_gerekli",
]

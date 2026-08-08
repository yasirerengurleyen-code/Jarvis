"""
memory/hafiza.py
----------------
Hafıza yöneticisi — tüm bellek katmanlarının orkestratörü.

Görev:
- SQLite deposunu açmak / kapatmak
- Sohbet, kullanıcı, uzun süreli hafıza ve aramayı birleştirmek
- AI Manager için PromptBaglami üretmek
- EventBus ile hafıza olaylarını yayınlamak
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from brain.prompts.yonetici import PromptBaglami
from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import Mesaj, ModulTabani
from core.events import (
    OLAY_HAFIZA_OKUNDU,
    OLAY_HAFIZA_YAZILDI,
    OLAY_PREFERANS_DEGISTI,
    EventBus,
    olay_yolu,
)
from core.logger import logger_al
from memory.arama import AramaSonucu, HafizaArama
from memory.stores.kullanici import KullaniciDeposu
from memory.stores.sohbet import SohbetDeposu
from memory.stores.sqlite_depo import SqliteDepo
from memory.stores.uzun_sureli import UzunSureliHafiza

log = logger_al("memory.hafiza")


class HafizaYoneticisi(ModulTabani):
    """WhiteCore merkezi hafıza yöneticisi."""

    ad = "memory"
    surum = "0.1.0"
    aciklama = "SQLite sohbet / profil / uzun süreli hafıza"

    def __init__(
        self,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        db_yolu: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.bus = bus or olay_yolu
        self.depo = SqliteDepo(db_yolu, ayar_yonetici=self.ayarlar)
        self.sohbet = SohbetDeposu(self.depo)
        self.kullanici = KullaniciDeposu(self.depo)
        self.uzun_sureli = UzunSureliHafiza(self.depo)
        self.arama = HafizaArama(
            self.depo,
            sohbet=self.sohbet,
            kullanici=self.kullanici,
            uzun_sureli=self.uzun_sureli,
        )
        self._aktif_oturum: Optional[str] = None

    async def baslat(self) -> None:
        if not self.ayarlar.yuklendi:
            self.ayarlar.yukle()
        await self.depo.abaglan()
        # Aktif oturum yoksa oluştur
        if self._aktif_oturum is None:
            self._aktif_oturum = self.sohbet.oturum_olustur(
                baslik="J.A.R.V.I.S. oturumu"
            )
        self._isaret_basladi()
        log.info(
            "Hafıza hazır (db=%s oturum=%s)",
            self.depo.db_yolu,
            self._aktif_oturum,
        )

    async def durdur(self) -> None:
        await self.depo.akapat()
        self._isaret_durdu()

    @property
    def aktif_oturum(self) -> Optional[str]:
        return self._aktif_oturum

    def oturum_sec(self, oturum_id: str) -> None:
        if not self.sohbet.oturum_var_mi(oturum_id):
            self.sohbet.oturum_olustur(oturum_id=oturum_id)
        self._aktif_oturum = oturum_id

    def yeni_oturum(self, baslik: str = "Yeni sohbet") -> str:
        self._aktif_oturum = self.sohbet.oturum_olustur(baslik=baslik)
        return self._aktif_oturum

    # --- Sohbet ---

    def mesaj_kaydet(
        self,
        mesaj: Mesaj,
        *,
        oturum_id: Optional[str] = None,
    ) -> int:
        oid = oturum_id or self._aktif_oturum
        if oid is None:
            oid = self.yeni_oturum()
        rid = self.sohbet.mesaj_ekle(oid, mesaj)
        self.bus.publish_sync(
            OLAY_HAFIZA_YAZILDI,
            {"tur": "sohbet", "oturum_id": oid, "rol": mesaj.rol.value},
            kaynak="memory",
        )
        return rid

    def sohbet_gecmisi(
        self,
        *,
        oturum_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Mesaj]:
        oid = oturum_id or self._aktif_oturum
        if oid is None:
            return []
        if limit is None:
            limit = int(self.ayarlar.al("memory.max_short_term_messages", 50))
        mesajlar = self.sohbet.son_mesajlar(oid, limit)
        self.bus.publish_sync(
            OLAY_HAFIZA_OKUNDU,
            {"tur": "sohbet", "oturum_id": oid, "adet": len(mesajlar)},
            kaynak="memory",
        )
        return mesajlar

    # --- Kullanıcı ---

    def kullanici_adi_ogren(self, ad: str) -> None:
        self.kullanici.adi_ayarla(ad)
        self.bus.publish_sync(
            OLAY_PREFERANS_DEGISTI,
            {"alan": "user.name", "deger": ad},
            kaynak="memory",
        )

    def kullanici_adi(self) -> Optional[str]:
        return self.kullanici.adi_al()

    def tercih_ayarla(self, ad: str, deger: Any) -> None:
        self.kullanici.tercih_ayarla(ad, deger)
        self.bus.publish_sync(
            OLAY_PREFERANS_DEGISTI,
            {"alan": ad, "deger": deger},
            kaynak="memory",
        )

    # --- Uzun süreli ---

    def hatirla(
        self,
        icerik: str,
        *,
        anahtar: Optional[str] = None,
        etiketler: Optional[list[str] | str] = None,
        onem: int = 0,
    ) -> int:
        hid = self.uzun_sureli.ekle(
            icerik, anahtar=anahtar, etiketler=etiketler, onem=onem
        )
        self.bus.publish_sync(
            OLAY_HAFIZA_YAZILDI,
            {"tur": "uzun_sureli", "id": hid},
            kaynak="memory",
        )
        return hid

    def ara(self, sorgu: str, *, limit: int = 20) -> list[AramaSonucu]:
        sonuclar = self.arama.ara(sorgu, limit=limit, oturum_id=self._aktif_oturum)
        self.bus.publish_sync(
            OLAY_HAFIZA_OKUNDU,
            {"tur": "arama", "sorgu": sorgu, "adet": len(sonuclar)},
            kaynak="memory",
        )
        return sonuclar

    # --- AI entegrasyonu ---

    def prompt_baglami(
        self,
        *,
        hafiza_limit: int = 8,
        arama_sorgusu: Optional[str] = None,
    ) -> PromptBaglami:
        """AI Manager için PromptBaglami üretir."""
        notlar = self.uzun_sureli.prompt_notlari(limit=hafiza_limit)
        if arama_sorgusu:
            ekstra = self.arama.ozet_metinleri(arama_sorgusu, limit=4)
            for e in ekstra:
                if e not in notlar:
                    notlar.append(e)

        asistan = self.ayarlar.bolum("assistant")
        return PromptBaglami(
            kullanici_adi=self.kullanici.adi_al(),
            dil=self.kullanici.dil_al(asistan.get("language") or "tr"),
            kisilik=asistan.get("personality"),
            hafiza_notlari=notlar,
            ekstra={"profil": self.kullanici.profil_ozeti()},
        )

    def konusma_kaydet(
        self,
        kullanici_metni: str,
        asistan_metni: str,
        *,
        oturum_id: Optional[str] = None,
    ) -> None:
        """Kullanıcı + asistan çiftini kaydeder."""
        self.mesaj_kaydet(Mesaj.kullanici(kullanici_metni), oturum_id=oturum_id)
        self.mesaj_kaydet(Mesaj.asistan(asistan_metni), oturum_id=oturum_id)


# Paylaşılan örnek
hafiza_yoneticisi = HafizaYoneticisi()

__all__ = ["HafizaYoneticisi", "hafiza_yoneticisi"]

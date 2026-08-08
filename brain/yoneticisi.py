"""
brain/yoneticisi.py
-------------------
AI Manager — WhiteCore düşünme orkestratörü.

Görev:
- Sağlayıcı fabrikasından LLM seçmek / değiştirmek
- Prompt yöneticisi ile sistem mesajı hazırlamak
- Sohbet isteklerini EventBus üzerinden duyurmak
- Standart Mesaj / SaglayiciYaniti döndürmek

Hafıza modülü Aşama 2'nin ikinci yarısında bağlanacak;
şimdilik PromptBaglami ile dışarıdan bağlam enjekte edilebilir.
"""

from __future__ import annotations

from typing import Optional, Sequence

from brain.prompts.yonetici import PromptBaglami, PromptYoneticisi, prompt_yoneticisi
from brain.providers.fabrika import desteklenen_saglayicilar, saglayici_olustur
from brain.providers.taban import LLMSaglayici, SaglayiciYaniti
from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import Mesaj, ModulTabani
from core.events import (
    OLAY_DUSUNME_BASLADI,
    OLAY_YANIT_HAZIR,
    EventBus,
    olay_yolu,
)
from core.exceptions import AIProviderError
from core.logger import logger_al

log = logger_al("brain.yoneticisi")


class AIYoneticisi(ModulTabani):
    """J.A.R.V.I.S. yapay zekâ yöneticisi."""

    ad = "brain"
    surum = "0.1.0"
    aciklama = "AI Manager — LLM orkestrasyonu"

    def __init__(
        self,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
        promptlar: Optional[PromptYoneticisi] = None,
        bus: Optional[EventBus] = None,
        saglayici: Optional[LLMSaglayici] = None,
        saglayici_adi: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.promptlar = promptlar or prompt_yoneticisi
        self.bus = bus or olay_yolu
        self._saglayici_adi = saglayici_adi
        self.saglayici: Optional[LLMSaglayici] = saglayici
        self._varsayilan_baglam = PromptBaglami()

    async def baslat(self) -> None:
        if not self.ayarlar.yuklendi:
            self.ayarlar.yukle()
        if self.saglayici is None:
            self.saglayici = saglayici_olustur(
                self._saglayici_adi,
                ayar_yonetici=self.ayarlar,
            )
        self._isaret_basladi()
        log.info(
            "AI Manager hazır (sağlayıcı=%s model=%s)",
            self.saglayici.ad,
            self.saglayici.model,
        )

    async def durdur(self) -> None:
        self._isaret_durdu()

    @property
    def aktif_saglayici(self) -> str:
        if self.saglayici is None:
            return ""
        return self.saglayici.ad

    def saglayici_degistir(self, ad: str) -> LLMSaglayici:
        """Tek satır sağlayıcı değişimi."""
        self.saglayici = saglayici_olustur(ad, ayar_yonetici=self.ayarlar)
        self._saglayici_adi = ad
        log.info("Sağlayıcı değiştirildi: %s", ad)
        return self.saglayici

    def baglam_ayarla(self, baglam: PromptBaglami) -> None:
        """Varsayılan prompt bağlamını günceller (kullanıcı adı, hafıza notları)."""
        self._varsayilan_baglam = baglam

    def desteklenenler(self) -> list[str]:
        return desteklenen_saglayicilar()

    async def dusun(
        self,
        kullanici_metni: str,
        *,
        gecmis: Optional[Sequence[Mesaj]] = None,
        baglam: Optional[PromptBaglami] = None,
        sistem_promptu: Optional[str] = None,
    ) -> SaglayiciYaniti:
        """
        Kullanıcı metnine yanıt üretir.

        Args:
            kullanici_metni: Kullanıcı sorusu / komutu
            gecmis: Önceki Mesaj listesi (opsiyonel)
            baglam: Prompt bağlamı (yoksa varsayılan)
            sistem_promptu: Verilirse prompt yöneticisini atlar
        """
        if self.saglayici is None:
            await self.baslat()
        assert self.saglayici is not None

        metin = (kullanici_metni or "").strip()
        if not metin:
            raise AIProviderError(
                "Boş kullanıcı mesajı",
                modul="brain.yoneticisi",
            )

        kullanilan_baglam = baglam or self._varsayilan_baglam
        sistem = sistem_promptu or self.promptlar.sistem_promptu_olustur(
            kullanilan_baglam
        )

        mesajlar: list[Mesaj] = list(gecmis or [])
        mesajlar.append(Mesaj.kullanici(metin))

        await self.bus.publish(
            OLAY_DUSUNME_BASLADI,
            {
                "provider": self.saglayici.ad,
                "model": self.saglayici.model,
                "text": metin,
            },
            kaynak="brain",
        )

        yanit = await self.saglayici.sohbet(mesajlar, sistem_promptu=sistem)

        await self.bus.publish(
            OLAY_YANIT_HAZIR,
            {
                "provider": yanit.saglayici,
                "model": yanit.model,
                "text": yanit.icerik,
            },
            kaynak="brain",
        )
        return yanit

    async def sohbet(
        self,
        mesajlar: Sequence[Mesaj],
        *,
        baglam: Optional[PromptBaglami] = None,
        sistem_promptu: Optional[str] = None,
    ) -> SaglayiciYaniti:
        """Hazır Mesaj listesi ile sohbet."""
        if self.saglayici is None:
            await self.baslat()
        assert self.saglayici is not None

        if not mesajlar:
            raise AIProviderError(
                "Boş mesaj listesi",
                modul="brain.yoneticisi",
            )

        kullanilan_baglam = baglam or self._varsayilan_baglam
        sistem = sistem_promptu or self.promptlar.sistem_promptu_olustur(
            kullanilan_baglam
        )

        await self.bus.publish(
            OLAY_DUSUNME_BASLADI,
            {
                "provider": self.saglayici.ad,
                "model": self.saglayici.model,
                "message_count": len(mesajlar),
            },
            kaynak="brain",
        )

        yanit = await self.saglayici.sohbet(mesajlar, sistem_promptu=sistem)

        await self.bus.publish(
            OLAY_YANIT_HAZIR,
            {
                "provider": yanit.saglayici,
                "model": yanit.model,
                "text": yanit.icerik,
            },
            kaynak="brain",
        )
        return yanit


# Kolay import
ai_yoneticisi = AIYoneticisi()

__all__ = ["AIYoneticisi", "ai_yoneticisi"]

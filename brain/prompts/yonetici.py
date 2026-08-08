"""
brain/prompts/yonetici.py
-------------------------
Prompt yöneticisi.

Görev:
- Sistem promptunu config ve kullanıcı bağlamından oluşturmak
- Şablonları (selamlama, özet, araç vb.) yönetmek
- Hafıza / kullanıcı adı gibi bağlam parçalarını enjekte etmek
- J.A.R.V.I.S. kişiliğini tutarlı tutmak
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import Template
from typing import Any, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.logger import logger_al

log = logger_al("brain.prompts")


# Varsayılan şablonlar (config yoksa)
_VARSAYILAN_SISTEM = (
    "Sen WhiteCore AI ekosistemindeki J.A.R.V.I.S. asistanısın. "
    "Türkçe konuşursun, net ve profesyonel yardımcı olursun."
)

_SABLONLAR: dict[str, str] = {
    "sistem_taban": "$sistem_promptu",
    "kullanici_baglami": (
        "Kullanıcı adı: $kullanici_adi\n"
        "Tercih edilen dil: $dil\n"
        "Kişilik: $kisilik"
    ),
    "hafiza_ozeti": "Uzun süreli hafıza notları:\n$hafiza_notlari",
    "arac_kurallari": (
        "Tehlikeli işlemlerde kullanıcıdan onay iste. "
        "Bilmediğin konularda uydurma; emin değilsen söyle."
    ),
}


@dataclass
class PromptBaglami:
    """Sistem promptuna eklenecek dinamik bağlam."""

    kullanici_adi: Optional[str] = None
    dil: str = "tr"
    kisilik: Optional[str] = None
    hafiza_notlari: list[str] = field(default_factory=list)
    ekstra: dict[str, Any] = field(default_factory=dict)


class PromptYoneticisi:
    """
    Sistem ve yardımcı promptları üretir.

    AI Manager bu sınıfı kullanarak LLM'e giden system mesajını hazırlar.
    """

    def __init__(self, ayar_yonetici: Optional[Ayarlar] = None) -> None:
        self.ayarlar = ayar_yonetici or global_ayarlar
        self._ozel_sablonlar: dict[str, str] = {}

    def _ai(self) -> dict[str, Any]:
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:
                return {}
        return self.ayarlar.bolum("ai")

    def _asistan(self) -> dict[str, Any]:
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:
                return {}
        return self.ayarlar.bolum("assistant")

    def sablon_kaydet(self, ad: str, metin: str) -> None:
        """Özel şablon ekler / günceller."""
        self._ozel_sablonlar[ad] = metin
        log.debug("Şablon kaydedildi: %s", ad)

    def sablon_al(self, ad: str) -> str:
        """Şablon metnini döner (özel > varsayılan)."""
        if ad in self._ozel_sablonlar:
            return self._ozel_sablonlar[ad]
        if ad in _SABLONLAR:
            return _SABLONLAR[ad]
        raise KeyError(f"Bilinmeyen şablon: {ad}")

    def sablon_doldur(self, sablon_adi: str, **kwargs: Any) -> str:
        """Template güvenli doldurma ($degisken)."""
        ham = self.sablon_al(sablon_adi)
        # Eksik anahtarları boş bırak
        class _Safe(dict):
            def __missing__(self, key: str) -> str:
                return ""

        return Template(ham).safe_substitute(_Safe(**kwargs))

    def taban_sistem_promptu(self) -> str:
        """config.ai.system_prompt veya varsayılan."""
        ai = self._ai()
        metin = ai.get("system_prompt") or _VARSAYILAN_SISTEM
        return str(metin).strip()

    def sistem_promptu_olustur(
        self,
        baglam: Optional[PromptBaglami] = None,
        *,
        arac_kurallari: bool = True,
    ) -> str:
        """
        Tam sistem promptunu birleştirir.

        Sıra:
        1) Taban sistem promptu (config)
        2) Asistan kimliği / kişilik
        3) Kullanıcı bağlamı
        4) Hafıza özeti
        5) Araç kuralları
        """
        baglam = baglam or PromptBaglami()
        asistan = self._asistan()
        parcalar: list[str] = [self.taban_sistem_promptu()]

        ad = asistan.get("name") or "J.A.R.V.I.S."
        kisilik = baglam.kisilik or asistan.get("personality") or ""
        dil = baglam.dil or asistan.get("language") or "tr"

        parcalar.append(
            f"Asistan adı: {ad}. "
            f"Kişilik: {kisilik}. "
            f"Yanıt dili: {dil}."
        )

        if baglam.kullanici_adi or kisilik:
            parcalar.append(
                self.sablon_doldur(
                    "kullanici_baglami",
                    kullanici_adi=baglam.kullanici_adi or "bilinmiyor",
                    dil=dil,
                    kisilik=kisilik,
                )
            )

        if baglam.hafiza_notlari:
            notlar = "\n".join(f"- {n}" for n in baglam.hafiza_notlari if n)
            if notlar:
                parcalar.append(
                    self.sablon_doldur("hafiza_ozeti", hafiza_notlari=notlar)
                )

        if arac_kurallari:
            parcalar.append(self.sablon_al("arac_kurallari"))

        # ekstra serbest metin
        ekstra_metin = baglam.ekstra.get("ek_sistem")
        if ekstra_metin:
            parcalar.append(str(ekstra_metin))

        sonuc = "\n\n".join(p.strip() for p in parcalar if p and str(p).strip())
        log.debug("Sistem promptu uzunluğu: %s karakter", len(sonuc))
        return sonuc

    def kullanici_mesaji_zarfla(
        self,
        metin: str,
        *,
        onek: Optional[str] = None,
        sonek: Optional[str] = None,
    ) -> str:
        """Kullanıcı mesajına isteğe bağlı önek/sonek ekler."""
        parcalar = []
        if onek:
            parcalar.append(onek.strip())
        parcalar.append(metin.strip())
        if sonek:
            parcalar.append(sonek.strip())
        return "\n".join(parcalar)


# Paylaşılan örnek
prompt_yoneticisi = PromptYoneticisi()

__all__ = [
    "PromptBaglami",
    "PromptYoneticisi",
    "prompt_yoneticisi",
]

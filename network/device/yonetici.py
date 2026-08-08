"""
network/device/yonetici.py
--------------------------
Bağlı cihaz yöneticisi.

Görev:
- Cihaz kaydı oluşturmak / güncellemek / silmek
- Çevrimiçi / çevrimdışı durumunu tutmak
- JSON dosyasına kalıcı saklamak
- EventBus üzerinden eşleşme ve durum olayları yayınlamak
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import (
    OLAY_CIHAZ_DURUM,
    OLAY_CIHAZ_ESLESTI,
    EventBus,
    olay_yolu,
)
from core.exceptions import NetworkError
from core.logger import audit_yaz, logger_al
from network.device.modeller import BaglantiDurumu, BagliCihaz, PlatformTuru

log = logger_al("network.device.yonetici")

PlatformGirdi = Union[PlatformTuru, str]
DurumGirdi = Union[BaglantiDurumu, str]


def _platform_coz(deger: PlatformGirdi) -> PlatformTuru:
    if isinstance(deger, PlatformTuru):
        return deger
    try:
        return PlatformTuru(str(deger).lower().strip())
    except ValueError as hata:
        raise NetworkError(
            f"Bilinmeyen platform: {deger!r}",
            kod="NET_0002",
            modul="network.device",
        ) from hata


def _durum_coz(deger: DurumGirdi) -> BaglantiDurumu:
    if isinstance(deger, BaglantiDurumu):
        return deger
    metin = str(deger).lower().strip()
    # İngilizce / Türkçe eşlemeler
    esleme = {
        "online": BaglantiDurumu.CEVRIMICI,
        "offline": BaglantiDurumu.CEVRIMDISI,
        "pairing": BaglantiDurumu.ESLESME,
        "syncing": BaglantiDurumu.SENKRON,
        "error": BaglantiDurumu.HATA,
        "cevrimici": BaglantiDurumu.CEVRIMICI,
        "cevrimdisi": BaglantiDurumu.CEVRIMDISI,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return BaglantiDurumu(metin)
    except ValueError as hata:
        raise NetworkError(
            f"Bilinmeyen baglanti durumu: {deger!r}",
            kod="NET_0003",
            modul="network.device",
        ) from hata


def _cihaz_from_dict(veri: dict[str, Any]) -> BagliCihaz:
    return BagliCihaz(
        cihaz_id=str(veri.get("device_id") or veri.get("cihaz_id") or ""),
        ad=str(veri.get("name") or veri.get("ad") or "Cihaz"),
        platform=_platform_coz(veri.get("platform", "ios")),
        durum=_durum_coz(veri.get("status") or veri.get("durum") or "offline"),
        pil_yuzde=veri.get("battery_percent", veri.get("pil_yuzde")),
        son_gorulme=veri.get("last_seen") or veri.get("son_gorulme"),
        token_parmak_izi=veri.get("token_fingerprint") or veri.get("token_parmak_izi"),
        meta=dict(veri.get("meta") or {}),
    )


class CihazYoneticisi(ModulTabani):
    """Bağlı cihazların bellek + disk kayıt yöneticisi."""

    ad = "network.device"
    surum = "0.1.0"
    aciklama = "Bagli cihaz yoneticisi"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        *,
        kayit_yolu: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.max_cihaz = int(self.ayarlar.al("mobile.max_devices", 5))
        if kayit_yolu is not None:
            self.kayit_yolu = Path(kayit_yolu)
        else:
            data_dir = Path(str(self.ayarlar.al("project.data_dir", "database")))
            if not data_dir.is_absolute():
                data_dir = Path(__file__).resolve().parents[2] / data_dir
            self.kayit_yolu = data_dir / "devices.json"
        self._cihazlar: dict[str, BagliCihaz] = {}

    async def baslat(self) -> None:
        self.kayit_yolu.parent.mkdir(parents=True, exist_ok=True)
        self._yukle()
        self._calisiyor = True
        log.info(
            "Cihaz yoneticisi hazir (%d kayit, max=%d) -> %s",
            self.adet(),
            self.max_cihaz,
            self.kayit_yolu,
        )

    async def durdur(self) -> None:
        if self._calisiyor:
            self._kaydet()
        self._calisiyor = False
        log.info("Cihaz yoneticisi durduruldu")

    def adet(self) -> int:
        return len(self._cihazlar)

    def al(self, cihaz_id: str) -> BagliCihaz:
        cihaz = self._cihazlar.get(cihaz_id)
        if cihaz is None:
            raise NetworkError(
                f"Cihaz bulunamadi: {cihaz_id}",
                kod="NET_0004",
                modul="network.device",
            )
        return cihaz

    def listele(
        self,
        *,
        sadece_cevrimici: bool = False,
        platform: Optional[PlatformGirdi] = None,
    ) -> list[BagliCihaz]:
        sonuc = list(self._cihazlar.values())
        if sadece_cevrimici:
            sonuc = [c for c in sonuc if c.cevrimici_mi()]
        if platform is not None:
            hedef = _platform_coz(platform)
            sonuc = [c for c in sonuc if c.platform == hedef]
        return sonuc

    def olustur(
        self,
        ad: str,
        platform: PlatformGirdi,
        *,
        durum: DurumGirdi = BaglantiDurumu.CEVRIMICI,
        pil_yuzde: Optional[int] = None,
        token_parmak_izi: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        cihaz_id: Optional[str] = None,
    ) -> BagliCihaz:
        if self.adet() >= self.max_cihaz:
            raise NetworkError(
                f"Maksimum cihaz sayisina ulasildi ({self.max_cihaz})",
                kod="NET_0005",
                modul="network.device",
            )
        ad_temiz = (ad or "").strip() or "Cihaz"
        cihaz = BagliCihaz(
            cihaz_id=cihaz_id or str(uuid4()),
            ad=ad_temiz,
            platform=_platform_coz(platform),
            durum=_durum_coz(durum),
            pil_yuzde=pil_yuzde,
            token_parmak_izi=token_parmak_izi,
            meta=dict(meta or {}),
        )
        cihaz.dokun()
        self._cihazlar[cihaz.cihaz_id] = cihaz
        self._kaydet()
        veri = cihaz.to_dict()
        self.bus.publish_sync(OLAY_CIHAZ_ESLESTI, veri, kaynak=self.ad)
        self.bus.publish_sync(OLAY_CIHAZ_DURUM, veri, kaynak=self.ad)
        audit_yaz(
            "device.paired",
            modul=self.ad,
            detay={
                "device_id": cihaz.cihaz_id,
                "name": cihaz.ad,
                "platform": cihaz.platform.value,
            },
        )
        log.info("Cihaz eklendi: %s (%s)", cihaz.ad, cihaz.platform.value)
        return cihaz

    def durum_ayarla(
        self,
        cihaz_id: str,
        durum: DurumGirdi,
        *,
        pil_yuzde: Optional[int] = None,
    ) -> BagliCihaz:
        cihaz = self.al(cihaz_id)
        cihaz.durum = _durum_coz(durum)
        if pil_yuzde is not None:
            cihaz.pil_yuzde = int(pil_yuzde)
        cihaz.dokun()
        self._kaydet()
        self.bus.publish_sync(OLAY_CIHAZ_DURUM, cihaz.to_dict(), kaynak=self.ad)
        return cihaz

    def yeniden_adlandir(self, cihaz_id: str, yeni_ad: str) -> BagliCihaz:
        cihaz = self.al(cihaz_id)
        temiz = (yeni_ad or "").strip()
        if not temiz:
            raise NetworkError(
                "Cihaz adi bos olamaz",
                kod="NET_0006",
                modul="network.device",
            )
        cihaz.ad = temiz
        cihaz.dokun()
        self._kaydet()
        self.bus.publish_sync(OLAY_CIHAZ_DURUM, cihaz.to_dict(), kaynak=self.ad)
        return cihaz

    def kaldir(self, cihaz_id: str) -> bool:
        if cihaz_id not in self._cihazlar:
            return False
        silinen = self._cihazlar.pop(cihaz_id)
        self._kaydet()
        audit_yaz(
            "device.removed",
            modul=self.ad,
            detay={"device_id": cihaz_id, "name": silinen.ad},
        )
        log.info("Cihaz kaldirildi: %s", silinen.ad)
        return True

    def ozet(self) -> dict[str, Any]:
        liste = self.listele()
        return {
            "count": len(liste),
            "online": sum(1 for c in liste if c.cevrimici_mi()),
            "max_devices": self.max_cihaz,
            "devices": [c.to_dict() for c in liste],
        }

    def _yukle(self) -> None:
        self._cihazlar.clear()
        if not self.kayit_yolu.exists():
            return
        try:
            ham = json.loads(self.kayit_yolu.read_text(encoding="utf-8"))
            kayitlar = ham.get("devices", ham if isinstance(ham, list) else [])
            for satir in kayitlar:
                cihaz = _cihaz_from_dict(dict(satir))
                if cihaz.cihaz_id:
                    self._cihazlar[cihaz.cihaz_id] = cihaz
        except (OSError, json.JSONDecodeError, NetworkError) as hata:
            log.warning("Cihaz kaydi okunamadi: %s", hata)

    def _kaydet(self) -> None:
        self.kayit_yolu.parent.mkdir(parents=True, exist_ok=True)
        veri = {
            "version": 1,
            "devices": [c.to_dict() for c in self._cihazlar.values()],
        }
        self.kayit_yolu.write_text(
            json.dumps(veri, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

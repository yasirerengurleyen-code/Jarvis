"""
sync/yoneticisi.py
------------------
Sync Manager — sohbet / dosya / bildirim / bulut orkestrasyonu.

Görev:
- Alt sync modüllerini (chat / files / notifications / cloud) birleştirmek
- start/stop yaşam döngüsü ve özet API sağlamak
- NetworkYoneticisi.sync_bagla ile kanca bağlamak (döngüsel import yok)
- protokol mesajlarını alt modüllere yönlendirmek
- dry_run / sahte modda ağ ve disk olmadan test edilebilir olmak

Not: Engine `sync.runtime` köprüsü `core/engine.py` üzerinden bağlanır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import WhiteCoreError
from core.logger import audit_yaz, logger_al
from network.websocket.protokol import MesajTipi, WsMesaj
from sync.chat.senkron import SohbetSenkron
from sync.cloud.yedek import BulutYedek
from sync.files.paylasim import DosyaPaylasim
from sync.notifications.bildirim import BildirimKopru

log = logger_al("sync.yoneticisi")

MesajYuku = Union[WsMesaj, dict[str, Any]]


class SyncYoneticisi(ModulTabani):
    """
    J.A.R.V.I.S. sync yöneticisi (host tarafı facade).

    Alt bileşenler:
      sohbet → dosya → bildirim → bulut yedek
    """

    ad = "sync"
    surum = "0.1.0"
    aciklama = "Sync Manager — sohbet / dosya / bildirim / bulut"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        sohbet: Optional[SohbetSenkron] = None,
        dosya: Optional[DosyaPaylasim] = None,
        bildirim: Optional[BildirimKopru] = None,
        yedek: Optional[BulutYedek] = None,
        depo_kok: Optional[Path] = None,
        olustur: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(self.ayarlar.al("sync.enabled", True))

        kok = Path(depo_kok) if depo_kok else None
        self.depo_kok = kok
        self.sohbet = sohbet
        self.dosya = dosya
        self.bildirim = bildirim
        self.yedek = yedek
        self._network: Any = None  # NetworkYoneticisi (opsiyonel, lazy)

        if olustur:
            if self.sohbet is None:
                self.sohbet = SohbetSenkron(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "chat" / "messages.json") if kok else None,
                )
            if self.dosya is None:
                self.dosya = DosyaPaylasim(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "files") if kok else None,
                )
            if self.bildirim is None:
                self.bildirim = BildirimKopru(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "notifications" / "notifications.json")
                    if kok
                    else None,
                )
            if self.yedek is None:
                self.yedek = BulutYedek(
                    self.ayarlar,
                    dry_run=self.dry_run,
                    zorla_sahte=self.zorla_sahte,
                    depo_yolu=(kok / "cloud") if kok else None,
                )

        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ fabrika

    @classmethod
    def agdan(
        cls,
        network: Any,
        *,
        bus: Optional[EventBus] = None,
        depo_kok: Optional[Path] = None,
    ) -> SyncYoneticisi:
        """
        NetworkYoneticisi sync kancalarından SyncYoneticisi üretir.

        Mevcut sohbet/dosya/bildirim/yedek örneklerini yeniden kullanır;
        yoksa dry_run bayraklarıyla yeni oluşturur.
        """
        dry = bool(getattr(network, "dry_run", False))
        sahte = bool(getattr(network, "zorla_sahte", False))
        ayar = getattr(network, "ayarlar", None)
        yonetici = cls(
            ayarlar=ayar,
            bus=bus or getattr(network, "bus", None),
            dry_run=dry,
            zorla_sahte=sahte,
            sohbet=getattr(network, "sohbet", None),
            dosya=getattr(network, "dosya", None),
            bildirim=getattr(network, "bildirim", None),
            yedek=getattr(network, "yedek", None),
            depo_kok=depo_kok,
            olustur=True,
        )
        yonetici.ag_bagla(network)
        return yonetici

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — test / bellek ayarları
                pass

        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise WhiteCoreError(
                "Sync config ile kapali (sync.enabled=false)",
                kod="SYNC_0060",
                modul=self.ad,
            )

        self._motor = self._motor_sec()

        for ad, modul in self._moduller():
            try:
                await modul.baslat()
            except Exception as exc:  # noqa: BLE001 — tek modül tümünü kırmaz
                log.warning("Sync alt modul baslatilamadi (%s): %s", ad, exc)

        # Ağ tarafına kancaları yenile (örnekler değişmiş olabilir)
        if self._network is not None:
            self.ag_bagla(self._network)

        self._isaret_basladi()
        audit_yaz(
            "sync.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "modules": [ad for ad, _ in self._moduller()],
                "store_root": str(self.depo_kok) if self.depo_kok else None,
            },
        )
        log.info(
            "Sync Manager hazir (motor=%s, moduller=%s)",
            self._motor,
            ",".join(ad for ad, _ in self._moduller()) or "-",
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return

        for ad, modul in reversed(self._moduller()):
            try:
                await modul.durdur()
            except Exception as exc:  # noqa: BLE001
                log.warning("Sync alt modul durdurma (%s): %s", ad, exc)

        self._isaret_durdu()
        audit_yaz(
            "sync.stopped",
            modul=self.ad,
            detay={"engine": self._motor},
        )
        log.info("Sync Manager durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ özellikler

    @property
    def motor(self) -> str:
        return self._motor

    def ag_bagla(self, network: Any) -> None:
        """
        NetworkYoneticisi.sync_bagla ile bu sync örneklerini bağlar.

        Döngüsel import yok: duck-typing (sync_bagla metodu aranır).
        """
        self._network = network
        bagla = getattr(network, "sync_bagla", None)
        if callable(bagla):
            bagla(
                sohbet=self.sohbet,
                dosya=self.dosya,
                bildirim=self.bildirim,
                yedek=self.yedek,
            )
            log.debug("Sync kancalari Network Manager'a baglandi")

    def modul_bagla(
        self,
        *,
        sohbet: Optional[SohbetSenkron] = None,
        dosya: Optional[DosyaPaylasim] = None,
        bildirim: Optional[BildirimKopru] = None,
        yedek: Optional[BulutYedek] = None,
    ) -> None:
        """Dışarıdan sync alt örneklerini bağlar / değiştirir."""
        if sohbet is not None:
            self.sohbet = sohbet
        if dosya is not None:
            self.dosya = dosya
        if bildirim is not None:
            self.bildirim = bildirim
        if yedek is not None:
            self.yedek = yedek
        if self._network is not None:
            self.ag_bagla(self._network)

    # ------------------------------------------------------------------ sohbet

    async def sohbet_gonder(
        self,
        cihaz_id: str,
        mesajlar: list[dict[str, Any]],
    ) -> None:
        self._calisiyor_mi()
        if self.sohbet is None:
            raise WhiteCoreError(
                "Sohbet senkronu bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        await self.sohbet.gonder(cihaz_id, mesajlar)

    async def sohbet_cek(
        self,
        cihaz_id: str,
        son_sonra: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self._calisiyor_mi()
        if self.sohbet is None:
            raise WhiteCoreError(
                "Sohbet senkronu bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.sohbet.cek(cihaz_id, son_sonra)

    # ------------------------------------------------------------------ dosya

    async def dosya_gonder(
        self,
        cihaz_id: str,
        yerel_yol: str,
        uzak_ad: Optional[str] = None,
    ) -> str:
        self._calisiyor_mi()
        if self.dosya is None:
            raise WhiteCoreError(
                "Dosya paylasimi bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.dosya.gonder(cihaz_id, yerel_yol, uzak_ad)

    async def dosya_al(self, transfer_id: str, hedef_yol: str) -> str:
        self._calisiyor_mi()
        if self.dosya is None:
            raise WhiteCoreError(
                "Dosya paylasimi bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.dosya.al(transfer_id, hedef_yol)

    # ------------------------------------------------------------------ bildirim

    async def bildirim_ilet(
        self,
        cihaz_id: str,
        baslik: str,
        govde: str,
        *,
        veri: Optional[dict[str, Any]] = None,
        oncelik: str = "normal",
    ) -> None:
        self._calisiyor_mi()
        if self.bildirim is None:
            raise WhiteCoreError(
                "Bildirim koprusu bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        await self.bildirim.ilet(
            cihaz_id,
            baslik,
            govde,
            veri=veri,
            oncelik=oncelik,
        )

    # ------------------------------------------------------------------ bulut

    async def yedekle(
        self,
        veri: dict[str, Any],
        *,
        etiket: str = "backup",
        cihaz_id: Optional[str] = None,
        tur: str = "snapshot",
        buluta_yukle: bool = False,
    ) -> str:
        self._calisiyor_mi()
        if self.yedek is None:
            raise WhiteCoreError(
                "Bulut yedek bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.yedek.yedekle(
            veri,
            etiket=etiket,
            cihaz_id=cihaz_id,
            tur=tur,
            buluta_yukle=buluta_yukle,
        )

    async def yedek_yukle(self, yedek_id: str) -> Any:
        self._calisiyor_mi()
        if self.yedek is None:
            raise WhiteCoreError(
                "Bulut yedek bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.yedek.yukle(yedek_id)

    async def yedek_indir(self, cloud_id: str) -> str:
        self._calisiyor_mi()
        if self.yedek is None:
            raise WhiteCoreError(
                "Bulut yedek bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.yedek.indir(cloud_id)

    async def yedek_geri_yukle(self, yedek_id: str) -> dict[str, Any]:
        self._calisiyor_mi()
        if self.yedek is None:
            raise WhiteCoreError(
                "Bulut yedek bagli degil",
                kod="SYNC_0062",
                modul=self.ad,
            )
        return await self.yedek.geri_yukle(yedek_id)

    # ------------------------------------------------------------------ protokol

    def protokol_isle(
        self,
        mesaj: MesajYuku,
        *,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        WS sync mesajını ilgili alt modüle yönlendirir.

        Destek: chat_sync, file_share, notification, event(kind=cloud_backup)
        """
        self._calisiyor_mi()
        tip, yuk, cid = self._mesaj_coz(mesaj, cihaz_id=cihaz_id)

        if tip is MesajTipi.CHAT_SYNC:
            if self.sohbet is None:
                raise WhiteCoreError(
                    "Sohbet senkronu bagli degil",
                    kod="SYNC_0062",
                    modul=self.ad,
                )
            return self.sohbet.chat_sync_isle(mesaj, cihaz_id=cid)

        if tip is MesajTipi.FILE_SHARE:
            if self.dosya is None:
                raise WhiteCoreError(
                    "Dosya paylasimi bagli degil",
                    kod="SYNC_0062",
                    modul=self.ad,
                )
            return self.dosya.file_share_isle(mesaj, cihaz_id=cid)

        if tip is MesajTipi.NOTIFICATION:
            if self.bildirim is None:
                raise WhiteCoreError(
                    "Bildirim koprusu bagli degil",
                    kod="SYNC_0062",
                    modul=self.ad,
                )
            return self.bildirim.notification_isle(mesaj, cihaz_id=cid)

        if tip is MesajTipi.EVENT:
            kind = str(yuk.get("kind") or yuk.get("tur") or "").lower()
            if kind in {"cloud_backup", "backup", "yedek", ""}:
                if self.yedek is None:
                    raise WhiteCoreError(
                        "Bulut yedek bagli degil",
                        kod="SYNC_0062",
                        modul=self.ad,
                    )
                # kind boşsa cloud_backup varsay (yedek protokolü)
                if not kind:
                    if isinstance(mesaj, WsMesaj):
                        mesaj.yuk.setdefault("kind", "cloud_backup")
                    elif isinstance(mesaj, dict):
                        mesaj.setdefault("kind", "cloud_backup")
                return self.yedek.cloud_backup_isle(mesaj, cihaz_id=cid)

        raise WhiteCoreError(
            f"Sync protokolu desteklemiyor: {tip.value if isinstance(tip, MesajTipi) else tip}",
            kod="SYNC_0063",
            modul=self.ad,
            detay={"type": tip.value if isinstance(tip, MesajTipi) else str(tip)},
        )

    # ------------------------------------------------------------------ özet

    def ozet(self) -> dict[str, Any]:
        alt: dict[str, Any] = {}
        for ad, modul in self._moduller():
            try:
                alt[ad] = modul.ozet()
            except Exception as exc:  # noqa: BLE001
                alt[ad] = {"error": str(exc)}

        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "store_root": str(self.depo_kok) if self.depo_kok else None,
            "network_bound": self._network is not None,
            "modules": alt,
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "live"

    def _calisiyor_mi(self) -> None:
        if not self._calisiyor:
            raise WhiteCoreError(
                "Sync Manager calismiyor; once baslat() cagirin",
                kod="SYNC_0061",
                modul=self.ad,
            )

    def _moduller(self) -> list[tuple[str, Any]]:
        adaylar: list[tuple[str, Any]] = [
            ("chat", self.sohbet),
            ("files", self.dosya),
            ("notifications", self.bildirim),
            ("cloud", self.yedek),
        ]
        return [(ad, m) for ad, m in adaylar if m is not None]

    def _mesaj_coz(
        self,
        mesaj: MesajYuku,
        *,
        cihaz_id: Optional[str],
    ) -> tuple[MesajTipi, dict[str, Any], Optional[str]]:
        if isinstance(mesaj, WsMesaj):
            return mesaj.tip, dict(mesaj.yuk), cihaz_id or mesaj.cihaz_id

        if not isinstance(mesaj, dict):
            raise WhiteCoreError(
                "Sync mesaji WsMesaj veya sozluk olmali",
                kod="SYNC_0063",
                modul=self.ad,
            )
        tip_ham = mesaj.get("type") or mesaj.get("tip") or ""
        try:
            tip = MesajTipi(str(tip_ham).lower().strip())
        except ValueError as hata:
            raise WhiteCoreError(
                f"Bilinmeyen sync mesaj tipi: {tip_ham!r}",
                kod="SYNC_0063",
                modul=self.ad,
            ) from hata
        yuk = mesaj.get("payload") or mesaj.get("yuk") or mesaj
        if not isinstance(yuk, dict):
            yuk = {}
        cid = (
            cihaz_id
            or mesaj.get("device_id")
            or mesaj.get("cihaz_id")
            or yuk.get("device_id")
            or yuk.get("cihaz_id")
        )
        return tip, dict(yuk), str(cid) if cid else None


__all__ = [
    "SyncYoneticisi",
]

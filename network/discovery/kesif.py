"""
network/discovery/kesif.py
--------------------------
Yerel ağ keşfi (LAN / UDP broadcast / isteğe bağlı mDNS).

Görev:
- Host'u LAN üzerinde ilan etmek (UDP broadcast)
- Diğer WhiteCore düğümlerini dinlemek / listelemek
- zeroconf yoksa veya dry_run / sahte modda bellek içi keşif
- Audit: keşif başlat / durdur olayları
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.exceptions import NetworkError
from core.logger import audit_yaz, logger_al

log = logger_al("network.discovery.kesif")

_MAGIC = "WHITECORE"
_PROTOKOL_SURUM = 1
_VARSAYILAN_UDP_PORT = 8743
_PEER_TTL_CARPAN = 3


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zeroconf_var_mi() -> bool:
    try:
        import zeroconf  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass
class KesifKaydi:
    """Keşfedilen (veya sahte) bir düğüm kaydı."""

    instance_id: str
    ad: str
    host: str
    http_port: int
    websocket_port: int
    mdns_service: str = "_whitecore._tcp.local."
    kaynak: str = "udp"  # udp | mdns | sahte | dry_run | manuel
    son_gorulme_unix: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def son_gorulme(self) -> str:
        return datetime.fromtimestamp(self.son_gorulme_unix, tz=timezone.utc).isoformat()

    def dokun(self) -> None:
        self.son_gorulme_unix = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "name": self.ad,
            "host": self.host,
            "http_port": self.http_port,
            "websocket_port": self.websocket_port,
            "mdns_service": self.mdns_service,
            "source": self.kaynak,
            "last_seen": self.son_gorulme,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "KesifKaydi":
        return cls(
            instance_id=str(veri.get("instance_id") or uuid4().hex),
            ad=str(veri.get("name") or veri.get("ad") or "WhiteCore"),
            host=str(veri.get("host") or "127.0.0.1"),
            http_port=int(veri.get("http_port", 8741)),
            websocket_port=int(veri.get("websocket_port", 8742)),
            mdns_service=str(
                veri.get("mdns_service") or "_whitecore._tcp.local."
            ),
            kaynak=str(veri.get("source") or veri.get("kaynak") or "manuel"),
            son_gorulme_unix=float(
                veri.get("last_seen_unix") or veri.get("son_gorulme_unix") or time.time()
            ),
            meta=dict(veri.get("meta") or {}),
        )


class KesifServisi(ModulTabani):
    """
    Yerel ağ keşif uygulaması.

    Gerçek mod: UDP broadcast + dinleme (stdlib).
    mDNS: zeroconf varsa isteğe bağlı (yoksa atlanır).
    dry_run / zorla_sahte: soket açmadan bellek içi keşif (test güvenli).
    """

    ad = "network.discovery"
    surum = "0.1.0"
    aciklama = "Yerel ag kesfi (LAN / UDP / mDNS)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        instance_id: Optional[str] = None,
        udp_port: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.instance_id = instance_id or uuid4().hex

        self.enabled = bool(self.ayarlar.al("network.discovery.enabled", True))
        self.mdns_service = str(
            self.ayarlar.al(
                "network.discovery.mdns_service",
                "_whitecore._tcp.local.",
            )
        )
        self.broadcast_interval = float(
            self.ayarlar.al("network.discovery.broadcast_interval_seconds", 5)
        )
        self.host = str(self.ayarlar.al("network.host", "0.0.0.0"))
        self.http_port = int(self.ayarlar.al("network.http_port", 8741))
        self.websocket_port = int(self.ayarlar.al("network.websocket_port", 8742))
        self.udp_port = int(
            udp_port
            if udp_port is not None
            else self.ayarlar.al("network.discovery.udp_port", _VARSAYILAN_UDP_PORT)
        )
        self.asistan_adi = str(self.ayarlar.al("assistant.name", "J.A.R.V.I.S."))

        self._kayitlar: dict[str, KesifKaydi] = {}
        self._sock: Optional[socket.socket] = None
        self._gorevler: list[asyncio.Task[Any]] = []
        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise NetworkError(
                "Ag kesfi config ile kapali (network.discovery.enabled=false)",
                kod="NET_0020",
                modul=self.ad,
            )

        self._motor = self._motor_sec()
        if self._motor in {"dry_run", "sahte"}:
            # Bellek içi — soket yok
            if self._motor == "sahte" and not self._kayitlar:
                self._sahte_ornek_yukle()
        else:
            try:
                self._sock = self._udp_soket_ac()
            except OSError as exc:
                log.warning("UDP soket acilamadi, sahte moda dusuluyor: %s", exc)
                self._motor = "sahte"
                self.zorla_sahte = True
                if not self._kayitlar:
                    self._sahte_ornek_yukle()

        if self._sock is not None:
            loop = asyncio.get_running_loop()
            self._gorevler = [
                loop.create_task(self._dinle_dongusu(), name="kesif-dinle"),
                loop.create_task(self._ilan_dongusu(), name="kesif-ilan"),
            ]

        self._calisiyor = True
        audit_yaz(
            "discovery.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "instance_id": self.instance_id,
                "udp_port": self.udp_port,
                "mdns_service": self.mdns_service,
                "zeroconf": _zeroconf_var_mi(),
            },
        )
        log.info(
            "Kesif basladi (motor=%s, udp=%s, interval=%ss)",
            self._motor,
            self.udp_port,
            self.broadcast_interval,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        for gorev in self._gorevler:
            gorev.cancel()
        if self._gorevler:
            await asyncio.gather(*self._gorevler, return_exceptions=True)
        self._gorevler.clear()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._calisiyor = False
        audit_yaz(
            "discovery.stopped",
            modul=self.ad,
            detay={"engine": self._motor, "instance_id": self.instance_id},
        )
        log.info("Kesif durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ API

    @property
    def motor(self) -> str:
        return self._motor

    def ilan_yuku(self) -> dict[str, Any]:
        """LAN'a yayınlanacak keşif yükü."""
        return {
            "magic": _MAGIC,
            "v": _PROTOKOL_SURUM,
            "instance_id": self.instance_id,
            "name": self.asistan_adi,
            "host": self._ilan_host(),
            "http_port": self.http_port,
            "websocket_port": self.websocket_port,
            "mdns_service": self.mdns_service,
            "ts": time.time(),
        }

    def ilan_et(self) -> dict[str, Any]:
        """
        Tek seferlik ilan.

        dry_run / sahte: yükü döner, ağ yok.
        Gerçek: UDP broadcast gönderir (servis çalışıyorsa).
        """
        yuk = self.ilan_yuku()
        if self._motor in {"dry_run", "sahte"}:
            return {**yuk, "engine": self._motor, "sent": False}
        if self._sock is None or not self._calisiyor:
            raise NetworkError(
                "Kesif servisi calismiyor; once baslat() cagirin",
                kod="NET_0021",
                modul=self.ad,
            )
        self._udp_gonder(yuk)
        return {**yuk, "engine": self._motor, "sent": True}

    async def tara(self, *, bekle_saniye: float = 0.0) -> list[KesifKaydi]:
        """
        Bilinen düğümleri döner; isteğe bağlı kısa bekleme (UDP dinleme için).
        """
        if not self._calisiyor:
            raise NetworkError(
                "Kesif servisi calismiyor; once baslat() cagirin",
                kod="NET_0021",
                modul=self.ad,
            )
        if bekle_saniye > 0 and self._motor == "udp":
            await asyncio.sleep(float(bekle_saniye))
        self._suresi_dolanlari_temizle()
        return self.listele()

    def listele(self) -> list[KesifKaydi]:
        self._suresi_dolanlari_temizle()
        return list(self._kayitlar.values())

    def adet(self) -> int:
        return len(self.listele())

    def kayit_ekle(
        self,
        kayit: KesifKaydi | dict[str, Any],
        *,
        kaynak: Optional[str] = None,
    ) -> KesifKaydi:
        """Manuel / sahte / test kaydı ekler veya günceller."""
        if isinstance(kayit, dict):
            nesne = KesifKaydi.from_dict(kayit)
        else:
            nesne = kayit
        if kaynak:
            nesne.kaynak = kaynak
        nesne.dokun()
        # Kendi instance'ımızı peer listesine koyma
        if nesne.instance_id == self.instance_id:
            raise NetworkError(
                "Kendi instance_id peer olarak eklenemez",
                kod="NET_0022",
                modul=self.ad,
            )
        mevcut = self._kayitlar.get(nesne.instance_id)
        if mevcut is not None:
            mevcut.ad = nesne.ad
            mevcut.host = nesne.host
            mevcut.http_port = nesne.http_port
            mevcut.websocket_port = nesne.websocket_port
            mevcut.mdns_service = nesne.mdns_service
            mevcut.kaynak = nesne.kaynak
            mevcut.meta = dict(nesne.meta)
            mevcut.dokun()
            return mevcut
        self._kayitlar[nesne.instance_id] = nesne
        log.debug("Kesif kaydi eklendi: %s (%s)", nesne.ad, nesne.host)
        return nesne

    def kayit_kaldir(self, instance_id: str) -> bool:
        return self._kayitlar.pop(instance_id, None) is not None

    def ozet(self) -> dict[str, Any]:
        liste = self.listele()
        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "instance_id": self.instance_id,
            "udp_port": self.udp_port,
            "mdns_service": self.mdns_service,
            "broadcast_interval_seconds": self.broadcast_interval,
            "zeroconf_available": _zeroconf_var_mi(),
            "count": len(liste),
            "peers": [k.to_dict() for k in liste],
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "udp"

    def _ilan_host(self) -> str:
        if self.host in {"0.0.0.0", "::", ""}:
            return "127.0.0.1"
        return self.host

    def _peer_ttl(self) -> float:
        return max(5.0, self.broadcast_interval * _PEER_TTL_CARPAN)

    def _sahte_ornek_yukle(self) -> None:
        """Offline / sahte mod için örnek peer."""
        self.kayit_ekle(
            KesifKaydi(
                instance_id="sahte-" + uuid4().hex[:8],
                ad="Sahte iPhone",
                host="192.168.1.50",
                http_port=self.http_port,
                websocket_port=self.websocket_port,
                mdns_service=self.mdns_service,
                kaynak="sahte",
                meta={"note": "zorla_sahte veya soket yok"},
            ),
            kaynak="sahte",
        )

    def _udp_soket_ac(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        sock.bind(("0.0.0.0", self.udp_port))
        sock.setblocking(False)
        return sock

    def _udp_gonder(self, yuk: dict[str, Any]) -> None:
        if self._sock is None:
            return
        veri = json.dumps(yuk, ensure_ascii=False).encode("utf-8")
        try:
            self._sock.sendto(veri, ("255.255.255.255", self.udp_port))
        except OSError as exc:
            log.debug("Broadcast gonderilemedi: %s", exc)
            # Yerel loopback yedek
            try:
                self._sock.sendto(veri, ("127.0.0.1", self.udp_port))
            except OSError as exc2:
                log.warning("UDP ilan basarisiz: %s", exc2)

    async def _ilan_dongusu(self) -> None:
        try:
            while True:
                try:
                    self._udp_gonder(self.ilan_yuku())
                except Exception as exc:  # noqa: BLE001 — döngü kırılmasın
                    log.debug("Ilan hatasi: %s", exc)
                await asyncio.sleep(max(1.0, self.broadcast_interval))
        except asyncio.CancelledError:
            raise

    async def _dinle_dongusu(self) -> None:
        assert self._sock is not None
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:
                    veri, adres = await loop.sock_recvfrom(self._sock, 4096)
                except (OSError, asyncio.CancelledError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.debug("Dinleme hatasi: %s", exc)
                    await asyncio.sleep(0.1)
                    continue
                self._paket_isle(veri, adres[0] if adres else "")
        except asyncio.CancelledError:
            raise

    def _paket_isle(self, veri: bytes, uzak_host: str) -> None:
        try:
            yuk = json.loads(veri.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(yuk, dict):
            return
        if yuk.get("magic") != _MAGIC:
            return
        instance_id = str(yuk.get("instance_id") or "")
        if not instance_id or instance_id == self.instance_id:
            return
        host = str(yuk.get("host") or uzak_host or "0.0.0.0")
        if host in {"0.0.0.0", "::"}:
            host = uzak_host or "127.0.0.1"
        kayit = KesifKaydi(
            instance_id=instance_id,
            ad=str(yuk.get("name") or "WhiteCore"),
            host=host,
            http_port=int(yuk.get("http_port", self.http_port)),
            websocket_port=int(yuk.get("websocket_port", self.websocket_port)),
            mdns_service=str(yuk.get("mdns_service") or self.mdns_service),
            kaynak="udp",
            meta={"remote": uzak_host, "v": yuk.get("v")},
        )
        self.kayit_ekle(kayit)

    def _suresi_dolanlari_temizle(self) -> None:
        ttl = self._peer_ttl()
        simdi = time.time()
        silinecek = [
            iid
            for iid, k in self._kayitlar.items()
            if k.kaynak == "udp" and (simdi - k.son_gorulme_unix) > ttl
        ]
        for iid in silinecek:
            self._kayitlar.pop(iid, None)


__all__ = ["KesifKaydi", "KesifServisi"]

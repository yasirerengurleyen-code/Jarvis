"""
network/websocket/sunucu.py
---------------------------
WhiteCore WebSocket sunucusu (host tarafı).

Görev:
- protokol.py mesaj çerçevesini konuşmak (hello / auth / ping / bye / …)
- Bağlı oturumları bellekte tutmak
- dry_run / sahte modda gerçek ağ olmadan test edilebilmek
- `websockets` varsa isteğe bağlı gerçek WS dinleyici; yoksa sahte moda düşmek

Not: iOS / Web istemci sonraki aşamada; burada yalnızca sunucu / host.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.exceptions import NetworkError
from core.logger import audit_yaz, logger_al
from network.websocket.protokol import (
    PROTOKOL_SURUM,
    MesajTipi,
    WsMesaj,
    ack_mesaji,
    decode_mesaj,
    encode_mesaj,
    hata_mesaji,
    hello_mesaji,
    mesaj_olustur,
    pong_mesaji,
)

log = logger_al("network.websocket.sunucu")

# Kimlik doğrulayıcı: (token, cihaz_id_istege_bagli) → cihaz_id veya None
TokenDogrulayici = Callable[[str, Optional[str]], Optional[str]]
MesajYuku = Union[WsMesaj, dict[str, Any], str, bytes]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _websockets_var_mi() -> bool:
    try:
        import websockets  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass
class WsOturum:
    """Tek bir istemci oturumu (gerçek veya sahte)."""

    oturum_id: str = field(default_factory=lambda: uuid4().hex)
    cihaz_id: Optional[str] = None
    kimlikli: bool = False
    uzak_adres: str = "memory"
    olusturma: str = field(default_factory=_utc_iso)
    son_aktivite: str = field(default_factory=_utc_iso)
    giden_kuyruk: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def dokun(self) -> None:
        self.son_aktivite = _utc_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.oturum_id,
            "device_id": self.cihaz_id,
            "authenticated": self.kimlikli,
            "remote": self.uzak_adres,
            "created": self.olusturma,
            "last_activity": self.son_aktivite,
            "outbound_queued": len(self.giden_kuyruk),
            "meta": dict(self.meta),
        }


class WsSunucu(ModulTabani):
    """
    Host WebSocket sunucusu.

    Motorlar:
      - dry_run: ağ yok, bellek içi oturum + mesaj işleme
      - sahte: websockets yok / zorla_sahte / bind hatası
      - websockets: gerçek dinleyici (paket kuruluysa)
    """

    ad = "network.websocket"
    surum = "0.1.0"
    aciklama = "WebSocket sunucusu (protokol + oturum)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token_dogrulayici: Optional[TokenDogrulayici] = None,
        auth_zorunlu: bool = True,
        asistan_adi: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.host = str(
            host if host is not None else self.ayarlar.al("network.host", "0.0.0.0")
        )
        self.port = int(
            port
            if port is not None
            else self.ayarlar.al("network.websocket_port", 8742)
        )
        self.enabled = bool(self.ayarlar.al("network.enabled", True))
        self.asistan_adi = str(
            asistan_adi
            if asistan_adi is not None
            else self.ayarlar.al("assistant.name", "J.A.R.V.I.S.")
        )
        self.auth_zorunlu = bool(auth_zorunlu)
        self.token_dogrulayici = token_dogrulayici

        self._oturumlar: dict[str, WsOturum] = {}
        self._ws_sunucu: Any = None  # websockets.Server | None
        self._gorevler: list[asyncio.Task[Any]] = []
        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise NetworkError(
                "Ag config ile kapali (network.enabled=false)",
                kod="NET_0040",
                modul=self.ad,
            )

        self._motor = self._motor_sec()
        if self._motor == "websockets":
            try:
                await self._gercek_dinleyici_ac()
            except Exception as exc:  # noqa: BLE001 — sahteye düş
                log.warning("WS dinleyici acilamadi, sahte moda dusuluyor: %s", exc)
                self._motor = "sahte"
                self.zorla_sahte = True
                self._ws_sunucu = None

        self._calisiyor = True
        audit_yaz(
            "websocket.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "host": self.host,
                "port": self.port,
                "websockets_available": _websockets_var_mi(),
            },
        )
        log.info(
            "WS sunucu basladi (motor=%s, %s:%s)",
            self._motor,
            self.host,
            self.port,
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return

        for gorev in self._gorevler:
            gorev.cancel()
        if self._gorevler:
            await asyncio.gather(*self._gorevler, return_exceptions=True)
        self._gorevler.clear()

        if self._ws_sunucu is not None:
            try:
                self._ws_sunucu.close()
                await self._ws_sunucu.wait_closed()
            except Exception as exc:  # noqa: BLE001
                log.debug("WS kapatma: %s", exc)
            self._ws_sunucu = None

        # Oturumları kapat
        for oid in list(self._oturumlar.keys()):
            self._oturum_kapat_ic(oid, neden="server_stop")
        self._oturumlar.clear()

        self._calisiyor = False
        audit_yaz(
            "websocket.stopped",
            modul=self.ad,
            detay={"engine": self._motor},
        )
        log.info("WS sunucu durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ API

    @property
    def motor(self) -> str:
        return self._motor

    def oturum_ac(
        self,
        *,
        uzak_adres: str = "memory",
        meta: Optional[dict[str, Any]] = None,
    ) -> WsOturum:
        """
        Bellek içi / sahte istemci oturumu açar.

        dry_run ve birim testlerde gerçek WS gerekmez.
        """
        if not self._calisiyor:
            raise NetworkError(
                "WS sunucu calismiyor; once baslat() cagirin",
                kod="NET_0041",
                modul=self.ad,
            )
        oturum = WsOturum(uzak_adres=uzak_adres, meta=dict(meta or {}))
        self._oturumlar[oturum.oturum_id] = oturum
        # Host hello gönder
        self._kuyruga_yaz(oturum, hello_mesaji(rol="host", ad=self.asistan_adi))
        log.debug("WS oturum acildi: %s (%s)", oturum.oturum_id[:12], uzak_adres)
        return oturum

    def oturum_kapat(self, oturum_id: str, *, neden: str = "client") -> bool:
        """Oturumu kapatır; yoksa False."""
        return self._oturum_kapat_ic(oturum_id, neden=neden)

    def oturum_al(self, oturum_id: str) -> WsOturum:
        oturum = self._oturumlar.get(oturum_id)
        if oturum is None:
            raise NetworkError(
                f"WS oturumu bulunamadi: {oturum_id}",
                kod="NET_0042",
                modul=self.ad,
            )
        return oturum

    def oturum_listele(self, *, sadece_kimlikli: bool = False) -> list[WsOturum]:
        liste = list(self._oturumlar.values())
        if sadece_kimlikli:
            liste = [o for o in liste if o.kimlikli]
        return liste

    def giden_cek(self, oturum_id: str) -> list[str]:
        """Kuyruktaki giden JSON mesajlarını alıp temizler (test / dry_run)."""
        oturum = self.oturum_al(oturum_id)
        cikisan = list(oturum.giden_kuyruk)
        oturum.giden_kuyruk.clear()
        return cikisan

    def gonder(self, oturum_id: str, mesaj: MesajYuku) -> str:
        """Tek oturuma mesaj yazar (kuyruk / ileride gerçek WS)."""
        if not self._calisiyor:
            raise NetworkError(
                "WS sunucu calismiyor; once baslat() cagirin",
                kod="NET_0041",
                modul=self.ad,
            )
        oturum = self.oturum_al(oturum_id)
        nesne = self._mesaja_cevir(mesaj)
        ham = encode_mesaj(nesne)
        assert isinstance(ham, str)
        self._kuyruga_yaz(oturum, nesne, ham=ham)
        return ham

    def yayinla(
        self,
        mesaj: MesajYuku,
        *,
        sadece_kimlikli: bool = True,
    ) -> int:
        """Bağlı oturumlara yayınlar; gönderilen oturum sayısı."""
        if not self._calisiyor:
            raise NetworkError(
                "WS sunucu calismiyor; once baslat() cagirin",
                kod="NET_0041",
                modul=self.ad,
            )
        nesne = self._mesaja_cevir(mesaj)
        ham = encode_mesaj(nesne)
        assert isinstance(ham, str)
        adet = 0
        for oturum in self._oturumlar.values():
            if sadece_kimlikli and not oturum.kimlikli:
                continue
            self._kuyruga_yaz(oturum, nesne, ham=ham)
            adet += 1
        return adet

    def mesaj_isle(self, oturum_id: str, ham: MesajYuku) -> list[WsMesaj]:
        """
        Gelen mesajı işler; yanıt listesini döner (ve kuyruğa yazar).

        Canlı WebSocket olmadan protokol akışını test etmek için ana giriş.
        """
        if not self._calisiyor:
            raise NetworkError(
                "WS sunucu calismiyor; once baslat() cagirin",
                kod="NET_0041",
                modul=self.ad,
            )
        oturum = self.oturum_al(oturum_id)
        oturum.dokun()

        try:
            gelen = self._mesaja_cevir(ham)
        except NetworkError as hata:
            yanit = hata_mesaji(
                hata.kod or "NET_0031",
                str(hata),
                cihaz_id=oturum.cihaz_id,
            )
            self._kuyruga_yaz(oturum, yanit)
            return [yanit]

        yanitlar = self._protokol_isle(oturum, gelen)
        for y in yanitlar:
            self._kuyruga_yaz(oturum, y)
        return yanitlar

    def ozet(self) -> dict[str, Any]:
        oturumlar = self.oturum_listele()
        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "auth_required": self.auth_zorunlu,
            "websockets_available": _websockets_var_mi(),
            "session_count": len(oturumlar),
            "authenticated_count": sum(1 for o in oturumlar if o.kimlikli),
            "sessions": [o.to_dict() for o in oturumlar],
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ protokol

    def _protokol_isle(self, oturum: WsOturum, gelen: WsMesaj) -> list[WsMesaj]:
        tip = gelen.tip

        if tip is MesajTipi.HELLO:
            # İstemci merhaba → host merhaba + ack
            host_hello = hello_mesaji(
                rol="host",
                ad=self.asistan_adi,
                cihaz_id=oturum.cihaz_id,
                ekstra={"peer_protocol": gelen.yuk.get("protocol", PROTOKOL_SURUM)},
            )
            host_hello.corr_id = gelen.mesaj_id
            return [host_hello, ack_mesaji(gelen, detay={"stage": "hello"})]

        if tip is MesajTipi.AUTH:
            return [self._auth_isle(oturum, gelen)]

        if tip is MesajTipi.PING:
            if self.auth_zorunlu and not oturum.kimlikli:
                return [
                    hata_mesaji(
                        "NET_0044",
                        "Once AUTH gerekli",
                        corr_id=gelen.mesaj_id,
                        cihaz_id=oturum.cihaz_id,
                    )
                ]
            return [pong_mesaji(gelen)]

        if tip is MesajTipi.BYE:
            # Kimliği düş; oturumu açık bırak (giden kuyruk okunabilsin)
            oturum.kimlikli = False
            return [ack_mesaji(gelen, detay={"stage": "bye"})]

        if tip is MesajTipi.PONG:
            return []  # istemci pong — yanıt yok

        # Kimlik gerektiren uygulama mesajları
        if self.auth_zorunlu and not oturum.kimlikli:
            return [
                hata_mesaji(
                    "NET_0044",
                    "Once AUTH gerekli",
                    corr_id=gelen.mesaj_id,
                    cihaz_id=oturum.cihaz_id,
                )
            ]

        # Sync / komut / olay — bu aşamada ack (üst katman sonra bağlanır)
        if tip in {
            MesajTipi.CHAT_SYNC,
            MesajTipi.FILE_SHARE,
            MesajTipi.NOTIFICATION,
            MesajTipi.DEVICE_STATUS,
            MesajTipi.BATTERY,
            MesajTipi.FIND_PHONE,
            MesajTipi.COMMAND,
            MesajTipi.EVENT,
            MesajTipi.ACK,
        }:
            return [ack_mesaji(gelen, detay={"type": tip.value})]

        return [
            hata_mesaji(
                "NET_0045",
                f"Sunucu bu mesaj tipini islemiyor: {tip.value}",
                corr_id=gelen.mesaj_id,
                cihaz_id=oturum.cihaz_id,
            )
        ]

    def _auth_isle(self, oturum: WsOturum, gelen: WsMesaj) -> WsMesaj:
        token = str(gelen.yuk.get("token") or "").strip()
        istenen_cihaz = gelen.cihaz_id or (
            str(gelen.yuk["device_id"]) if gelen.yuk.get("device_id") else None
        )

        if not token:
            oturum.kimlikli = False
            return mesaj_olustur(
                MesajTipi.AUTH_FAIL,
                {"ok": False, "code": "NET_0043", "message": "Token bos"},
                cihaz_id=istenen_cihaz,
                corr_id=gelen.mesaj_id,
            )

        cihaz_id = self._token_dogrula(token, istenen_cihaz)
        if cihaz_id is None:
            oturum.kimlikli = False
            audit_yaz(
                "websocket.auth_fail",
                modul=self.ad,
                detay={"session_id": oturum.oturum_id, "device_id": istenen_cihaz},
            )
            return mesaj_olustur(
                MesajTipi.AUTH_FAIL,
                {
                    "ok": False,
                    "code": "NET_0043",
                    "message": "Token dogrulanamadi",
                },
                cihaz_id=istenen_cihaz,
                corr_id=gelen.mesaj_id,
            )

        oturum.kimlikli = True
        oturum.cihaz_id = cihaz_id
        oturum.dokun()
        audit_yaz(
            "websocket.auth_ok",
            modul=self.ad,
            detay={"session_id": oturum.oturum_id, "device_id": cihaz_id},
        )
        log.info("WS auth ok: oturum=%s cihaz=%s", oturum.oturum_id[:12], cihaz_id)
        return mesaj_olustur(
            MesajTipi.AUTH_OK,
            {
                "ok": True,
                "device_id": cihaz_id,
                "protocol": PROTOKOL_SURUM,
                "name": self.asistan_adi,
            },
            cihaz_id=cihaz_id,
            corr_id=gelen.mesaj_id,
        )

    def _token_dogrula(self, token: str, cihaz_id: Optional[str]) -> Optional[str]:
        """
        Token doğrula → cihaz_id.

        - Özel doğrulayıcı varsa onu kullanır
        - Yoksa dry_run/sahte: boş olmayan token kabul (cihaz_id veya sahte-*)
        """
        if self.token_dogrulayici is not None:
            try:
                return self.token_dogrulayici(token, cihaz_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("Token dogrulayici hata: %s", exc)
                return None

        # Varsayılan: dry_run / sahte / test — boş olmayan token
        if self._motor in {"dry_run", "sahte"}:
            return cihaz_id or ("sahte-" + uuid4().hex[:8])

        # Gerçek motor + doğrulayıcı yok → reddet (güvenlik)
        log.warning("Token dogrulayici tanimli degil; AUTH reddedildi")
        return None

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if _websockets_var_mi():
            return "websockets"
        return "sahte"

    def _mesaja_cevir(self, ham: MesajYuku) -> WsMesaj:
        if isinstance(ham, WsMesaj):
            return ham
        return decode_mesaj(ham)

    def _kuyruga_yaz(
        self,
        oturum: WsOturum,
        mesaj: WsMesaj,
        *,
        ham: Optional[str] = None,
    ) -> None:
        if ham is None:
            encoded = encode_mesaj(mesaj)
            assert isinstance(encoded, str)
            ham = encoded
        oturum.giden_kuyruk.append(ham)
        oturum.dokun()

    def _oturum_kapat_ic(self, oturum_id: str, *, neden: str) -> bool:
        oturum = self._oturumlar.pop(oturum_id, None)
        if oturum is None:
            return False
        audit_yaz(
            "websocket.session_closed",
            modul=self.ad,
            detay={
                "session_id": oturum_id,
                "device_id": oturum.cihaz_id,
                "reason": neden,
            },
        )
        log.debug("WS oturum kapandi: %s (%s)", oturum_id[:12], neden)
        return True

    async def _gercek_dinleyici_ac(self) -> None:
        """İsteğe bağlı websockets dinleyicisi."""
        import websockets

        async def _handler(websocket: Any) -> None:
            uzak = "unknown"
            try:
                uzak = "%s:%s" % (
                    websocket.remote_address[0],
                    websocket.remote_address[1],
                )
            except Exception:  # noqa: BLE001
                pass
            oturum = self.oturum_ac(uzak_adres=uzak, meta={"transport": "websockets"})
            try:
                for ham in self.giden_cek(oturum.oturum_id):
                    await websocket.send(ham)
                async for veri in websocket:
                    self.mesaj_isle(oturum.oturum_id, veri)
                    for ham in self.giden_cek(oturum.oturum_id):
                        await websocket.send(ham)
            except Exception as exc:  # noqa: BLE001
                log.debug("WS handler: %s", exc)
            finally:
                self._oturum_kapat_ic(oturum.oturum_id, neden="disconnect")

        bind_host = self.host if self.host else "0.0.0.0"
        self._ws_sunucu = await websockets.serve(_handler, bind_host, self.port)


__all__ = ["WsOturum", "WsSunucu"]

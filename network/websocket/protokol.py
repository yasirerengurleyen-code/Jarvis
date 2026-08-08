"""
network/websocket/protokol.py
-----------------------------
WebSocket mesaj çerçevesi (framing) ve protokol sözleşmesi.

Görev:
- Sürüm bilinen JSON mesaj zarfı tanımlamak
- Mesaj tiplerini (auth, heartbeat, sync, komut, hata) sabitlenmek
- encode / decode (canlı WS soketi olmadan test edilebilir)
- Sürüm uyumluluğu ve temel doğrulama

Not: Gerçek WS sunucu/istemci `sunucu.py` / sonraki dosyalarda;
bu modül yalnızca çerçeve + serileştirme.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from core.exceptions import NetworkError
from core.logger import logger_al

log = logger_al("network.websocket.protokol")

# Keşif UDP ile aynı sihirli işaret; WS zarfında da kullanılır
MAGIC = "WHITECORE"
PROTOKOL_SURUM = 1
# Bu host'un anlayabildiği en düşük / en yüksek sürüm
MIN_DESTEKLENEN_SURUM = 1
MAX_DESTEKLENEN_SURUM = 1


class MesajTipi(str, Enum):
    """WebSocket uygulama mesaj tipleri."""

    # Oturum
    HELLO = "hello"
    AUTH = "auth"
    AUTH_OK = "auth_ok"
    AUTH_FAIL = "auth_fail"
    BYE = "bye"

    # Heartbeat
    PING = "ping"
    PONG = "pong"

    # Genel yanıt
    ACK = "ack"
    ERROR = "error"

    # Sync / özellikler (PLAN + mobile.features)
    CHAT_SYNC = "chat_sync"
    FILE_SHARE = "file_share"
    NOTIFICATION = "notification"
    DEVICE_STATUS = "device_status"
    BATTERY = "battery"
    FIND_PHONE = "find_phone"
    COMMAND = "command"
    EVENT = "event"


MesajTipiGirdi = Union[MesajTipi, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tip_coz(deger: MesajTipiGirdi) -> MesajTipi:
    """str / Enum → MesajTipi; bilinmeyenlerde NetworkError."""
    if isinstance(deger, MesajTipi):
        return deger
    metin = str(deger).strip().lower()
    try:
        return MesajTipi(metin)
    except ValueError as hata:
        raise NetworkError(
            f"Bilinmeyen WS mesaj tipi: {deger!r}",
            kod="NET_0030",
            modul="network.websocket",
        ) from hata


def surum_uyumlu_mu(surum: int) -> bool:
    """Gelen protokol sürümü bu host tarafından destekleniyor mu?"""
    try:
        v = int(surum)
    except (TypeError, ValueError):
        return False
    return MIN_DESTEKLENEN_SURUM <= v <= MAX_DESTEKLENEN_SURUM


@dataclass
class WsMesaj:
    """
    Tek bir WhiteCore WebSocket uygulama mesajı.

    Zarf alanları (wire JSON anahtarları İngilizce):
      magic, v, type, id, ts, device_id?, corr_id?, payload
    """

    tip: MesajTipi
    yuk: dict[str, Any] = field(default_factory=dict)
    mesaj_id: str = field(default_factory=lambda: uuid4().hex)
    zaman: str = field(default_factory=_utc_iso)
    cihaz_id: Optional[str] = None
    corr_id: Optional[str] = None  # yanıtın hangi isteğe ait olduğu
    surum: int = PROTOKOL_SURUM
    magic: str = MAGIC

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "magic": self.magic,
            "v": int(self.surum),
            "type": self.tip.value if isinstance(self.tip, MesajTipi) else str(self.tip),
            "id": self.mesaj_id,
            "ts": self.zaman,
            "payload": dict(self.yuk),
        }
        if self.cihaz_id:
            veri["device_id"] = self.cihaz_id
        if self.corr_id:
            veri["corr_id"] = self.corr_id
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "WsMesaj":
        if not isinstance(veri, dict):
            raise NetworkError(
                "WS mesaj sozluk olmali",
                kod="NET_0031",
                modul="network.websocket",
            )
        magic = str(veri.get("magic") or "")
        if magic and magic != MAGIC:
            raise NetworkError(
                f"Gecersiz WS magic: {magic!r}",
                kod="NET_0032",
                modul="network.websocket",
            )
        try:
            surum = int(veri.get("v", PROTOKOL_SURUM))
        except (TypeError, ValueError) as hata:
            raise NetworkError(
                "WS protokol surumu gecersiz",
                kod="NET_0033",
                modul="network.websocket",
            ) from hata
        if not surum_uyumlu_mu(surum):
            raise NetworkError(
                f"Desteklenmeyen WS protokol surumu: {surum}",
                kod="NET_0034",
                modul="network.websocket",
            )
        tip_ham = veri.get("type") or veri.get("tip")
        if not tip_ham:
            raise NetworkError(
                "WS mesaj tipi eksik",
                kod="NET_0035",
                modul="network.websocket",
            )
        tip = tip_coz(tip_ham)
        yuk = veri.get("payload")
        if yuk is None:
            yuk = veri.get("yuk") or {}
        if not isinstance(yuk, dict):
            raise NetworkError(
                "WS payload sozluk olmali",
                kod="NET_0036",
                modul="network.websocket",
            )
        return cls(
            tip=tip,
            yuk=dict(yuk),
            mesaj_id=str(veri.get("id") or veri.get("mesaj_id") or uuid4().hex),
            zaman=str(veri.get("ts") or veri.get("zaman") or _utc_iso()),
            cihaz_id=(
                str(veri["device_id"])
                if veri.get("device_id") is not None
                else (str(veri["cihaz_id"]) if veri.get("cihaz_id") is not None else None)
            ),
            corr_id=(
                str(veri["corr_id"]) if veri.get("corr_id") is not None else None
            ),
            surum=surum,
            magic=magic or MAGIC,
        )


def encode_mesaj(mesaj: WsMesaj | dict[str, Any], *, bytes_mu: bool = False) -> str | bytes:
    """
    Mesajı JSON metnine (veya UTF-8 bayta) çevirir.

    Canlı WebSocket gerekmez — birim testlerde doğrudan kullanılabilir.
    """
    if isinstance(mesaj, dict):
        nesne = WsMesaj.from_dict(mesaj)
    else:
        nesne = mesaj
    if not isinstance(nesne.tip, MesajTipi):
        nesne.tip = tip_coz(nesne.tip)
    if not surum_uyumlu_mu(nesne.surum):
        raise NetworkError(
            f"Desteklenmeyen WS protokol surumu: {nesne.surum}",
            kod="NET_0034",
            modul="network.websocket",
        )
    metin = json.dumps(nesne.to_dict(), ensure_ascii=False, separators=(",", ":"))
    if bytes_mu:
        return metin.encode("utf-8")
    return metin


def decode_mesaj(veri: str | bytes | dict[str, Any]) -> WsMesaj:
    """
    JSON metni / bayt / sözlük → WsMesaj.

    Magic, sürüm ve tip doğrulanır.
    """
    if isinstance(veri, dict):
        return WsMesaj.from_dict(veri)
    if isinstance(veri, bytes):
        try:
            metin = veri.decode("utf-8")
        except UnicodeDecodeError as hata:
            raise NetworkError(
                "WS mesaj UTF-8 degil",
                kod="NET_0037",
                modul="network.websocket",
            ) from hata
    else:
        metin = str(veri)
    try:
        yuk = json.loads(metin)
    except json.JSONDecodeError as hata:
        raise NetworkError(
            "WS mesaj JSON degil",
            kod="NET_0038",
            modul="network.websocket",
        ) from hata
    if not isinstance(yuk, dict):
        raise NetworkError(
            "WS mesaj kok nesnesi sozluk olmali",
            kod="NET_0031",
            modul="network.websocket",
        )
    return WsMesaj.from_dict(yuk)


# ------------------------------------------------------------------ fabrika yardımcılar


def mesaj_olustur(
    tip: MesajTipiGirdi,
    yuk: Optional[dict[str, Any]] = None,
    *,
    cihaz_id: Optional[str] = None,
    corr_id: Optional[str] = None,
    mesaj_id: Optional[str] = None,
) -> WsMesaj:
    """Yeni WsMesaj üretir (varsayılan sürüm / magic)."""
    return WsMesaj(
        tip=tip_coz(tip),
        yuk=dict(yuk or {}),
        mesaj_id=mesaj_id or uuid4().hex,
        cihaz_id=cihaz_id,
        corr_id=corr_id,
    )


def hello_mesaji(
    *,
    rol: str = "host",
    ad: str = "J.A.R.V.I.S.",
    cihaz_id: Optional[str] = None,
    ekstra: Optional[dict[str, Any]] = None,
) -> WsMesaj:
    yuk: dict[str, Any] = {"role": rol, "name": ad, "protocol": PROTOKOL_SURUM}
    if ekstra:
        yuk.update(ekstra)
    return mesaj_olustur(MesajTipi.HELLO, yuk, cihaz_id=cihaz_id)


def auth_mesaji(token: str, *, cihaz_id: Optional[str] = None) -> WsMesaj:
    return mesaj_olustur(MesajTipi.AUTH, {"token": token}, cihaz_id=cihaz_id)


def ping_mesaji(*, cihaz_id: Optional[str] = None) -> WsMesaj:
    return mesaj_olustur(MesajTipi.PING, {"t": _utc_iso()}, cihaz_id=cihaz_id)


def pong_mesaji(istek: WsMesaj) -> WsMesaj:
    return mesaj_olustur(
        MesajTipi.PONG,
        {"t": _utc_iso(), "echo_id": istek.mesaj_id},
        cihaz_id=istek.cihaz_id,
        corr_id=istek.mesaj_id,
    )


def ack_mesaji(istek: WsMesaj, *, detay: Optional[dict[str, Any]] = None) -> WsMesaj:
    yuk = {"ok": True}
    if detay:
        yuk.update(detay)
    return mesaj_olustur(
        MesajTipi.ACK,
        yuk,
        cihaz_id=istek.cihaz_id,
        corr_id=istek.mesaj_id,
    )


def hata_mesaji(
    kod: str,
    mesaj: str,
    *,
    corr_id: Optional[str] = None,
    cihaz_id: Optional[str] = None,
    detay: Optional[dict[str, Any]] = None,
) -> WsMesaj:
    yuk: dict[str, Any] = {"code": kod, "message": mesaj}
    if detay:
        yuk["detail"] = detay
    return mesaj_olustur(
        MesajTipi.ERROR,
        yuk,
        cihaz_id=cihaz_id,
        corr_id=corr_id,
    )


__all__ = [
    "MAGIC",
    "PROTOKOL_SURUM",
    "MIN_DESTEKLENEN_SURUM",
    "MAX_DESTEKLENEN_SURUM",
    "MesajTipi",
    "WsMesaj",
    "tip_coz",
    "surum_uyumlu_mu",
    "encode_mesaj",
    "decode_mesaj",
    "mesaj_olustur",
    "hello_mesaji",
    "auth_mesaji",
    "ping_mesaji",
    "pong_mesaji",
    "ack_mesaji",
    "hata_mesaji",
]

"""network/websocket/protokol.py birim testleri (canlı WS yok)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import NetworkError
from network.websocket.protokol import (
    MAGIC,
    PROTOKOL_SURUM,
    MesajTipi,
    WsMesaj,
    ack_mesaji,
    auth_mesaji,
    decode_mesaj,
    encode_mesaj,
    hata_mesaji,
    hello_mesaji,
    mesaj_olustur,
    ping_mesaji,
    pong_mesaji,
    surum_uyumlu_mu,
    tip_coz,
)


def test_tip_coz_ve_bilinmeyen() -> None:
    assert tip_coz("ping") is MesajTipi.PING
    assert tip_coz(MesajTipi.PONG) is MesajTipi.PONG
    try:
        tip_coz("bilinmeyen_tip")
        raise AssertionError("NetworkError beklenirdi")
    except NetworkError as exc:
        assert exc.kod == "NET_0030"


def test_surum_uyumlu() -> None:
    assert surum_uyumlu_mu(PROTOKOL_SURUM) is True
    assert surum_uyumlu_mu(0) is False
    assert surum_uyumlu_mu(99) is False


def test_encode_decode_roundtrip() -> None:
    m = mesaj_olustur(
        MesajTipi.CHAT_SYNC,
        {"messages": [{"role": "user", "text": "merhaba"}]},
        cihaz_id="iphone-1",
    )
    ham = encode_mesaj(m)
    assert isinstance(ham, str)
    geri = decode_mesaj(ham)
    assert geri.tip is MesajTipi.CHAT_SYNC
    assert geri.cihaz_id == "iphone-1"
    assert geri.yuk["messages"][0]["text"] == "merhaba"
    assert geri.magic == MAGIC
    assert geri.surum == PROTOKOL_SURUM
    assert geri.mesaj_id == m.mesaj_id


def test_encode_bytes_decode() -> None:
    m = ping_mesaji(cihaz_id="d1")
    bayt = encode_mesaj(m, bytes_mu=True)
    assert isinstance(bayt, bytes)
    geri = decode_mesaj(bayt)
    assert geri.tip is MesajTipi.PING
    assert geri.cihaz_id == "d1"


def test_from_dict_to_dict_wire_keys() -> None:
    m = hello_mesaji(rol="client", ad="iPhone", cihaz_id="c1")
    d = m.to_dict()
    assert d["magic"] == MAGIC
    assert d["v"] == PROTOKOL_SURUM
    assert d["type"] == "hello"
    assert d["device_id"] == "c1"
    assert "payload" in d
    assert "corr_id" not in d  # boşsa yazılmaz

    geri = WsMesaj.from_dict(d)
    assert geri.tip is MesajTipi.HELLO
    assert geri.yuk["role"] == "client"


def test_auth_ping_pong_ack_hata_fabrikalari() -> None:
    a = auth_mesaji("secret-token", cihaz_id="c2")
    assert a.tip is MesajTipi.AUTH
    assert a.yuk["token"] == "secret-token"

    p = ping_mesaji(cihaz_id="c2")
    r = pong_mesaji(p)
    assert r.tip is MesajTipi.PONG
    assert r.corr_id == p.mesaj_id
    assert r.yuk["echo_id"] == p.mesaj_id

    ack = ack_mesaji(a, detay={"session": "ok"})
    assert ack.tip is MesajTipi.ACK
    assert ack.corr_id == a.mesaj_id
    assert ack.yuk["ok"] is True

    err = hata_mesaji("NET_0030", "kotu tip", corr_id=a.mesaj_id, cihaz_id="c2")
    assert err.tip is MesajTipi.ERROR
    assert err.yuk["code"] == "NET_0030"


def test_gecersiz_magic() -> None:
    try:
        decode_mesaj({"magic": "OTHER", "v": 1, "type": "ping", "payload": {}})
        raise AssertionError("NetworkError beklenirdi")
    except NetworkError as exc:
        assert exc.kod == "NET_0032"


def test_desteklenmeyen_surum() -> None:
    try:
        decode_mesaj(
            {
                "magic": MAGIC,
                "v": 99,
                "type": "ping",
                "id": "x",
                "ts": "t",
                "payload": {},
            }
        )
        raise AssertionError("NetworkError beklenirdi")
    except NetworkError as exc:
        assert exc.kod == "NET_0034"


def test_eksik_tip_ve_bozuk_json() -> None:
    try:
        decode_mesaj({"magic": MAGIC, "v": 1, "payload": {}})
        raise AssertionError("NetworkError beklenirdi")
    except NetworkError as exc:
        assert exc.kod == "NET_0035"

    try:
        decode_mesaj("{degil-json")
        raise AssertionError("NetworkError beklenirdi")
    except NetworkError as exc:
        assert exc.kod == "NET_0038"


def test_dict_encode_yolu() -> None:
    ham = encode_mesaj(
        {
            "magic": MAGIC,
            "v": 1,
            "type": "notification",
            "payload": {"title": "Jarvis", "body": "selam"},
            "device_id": "web-1",
        }
    )
    veri = json.loads(ham)
    assert veri["type"] == "notification"
    geri = decode_mesaj(veri)
    assert geri.tip is MesajTipi.NOTIFICATION


print("TEST_OK")

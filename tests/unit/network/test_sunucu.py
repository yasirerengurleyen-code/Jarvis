"""network/websocket/sunucu.py birim testleri (canlı WS yok)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import NetworkError
from network.websocket.protokol import (
    MesajTipi,
    auth_mesaji,
    decode_mesaj,
    hello_mesaji,
    mesaj_olustur,
    ping_mesaji,
)
from network.websocket.sunucu import WsSunucu, _websockets_var_mi


def test_dry_run_baslat_oturum_hello() -> None:
    async def _run() -> None:
        srv = WsSunucu(dry_run=True, asistan_adi="J.A.R.V.I.S.")
        assert srv.motor == "dry_run"
        await srv.baslat()
        assert srv.calisiyor

        oturum = srv.oturum_ac(uzak_adres="test-client")
        assert oturum.oturum_id
        assert not oturum.kimlikli

        giden = srv.giden_cek(oturum.oturum_id)
        assert len(giden) == 1
        hello = decode_mesaj(giden[0])
        assert hello.tip is MesajTipi.HELLO
        assert hello.yuk["role"] == "host"
        assert hello.yuk["name"] == "J.A.R.V.I.S."

        ozet = srv.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["session_count"] == 1
        assert ozet["websockets_available"] is _websockets_var_mi()

        await srv.durdur()
        assert not srv.calisiyor
        assert srv.oturum_listele() == []

    asyncio.run(_run())


def test_auth_ping_pong_ve_yayin() -> None:
    async def _run() -> None:
        def dogrula(token: str, cihaz_id: str | None) -> str | None:
            if token == "gizli-token":
                return cihaz_id or "iphone-1"
            return None

        srv = WsSunucu(dry_run=True, token_dogrulayici=dogrula)
        await srv.baslat()
        oturum = srv.oturum_ac()
        srv.giden_cek(oturum.oturum_id)  # hello temizle

        # Auth zorunlu — ping reddedilir
        yanitlar = srv.mesaj_isle(oturum.oturum_id, ping_mesaji())
        assert len(yanitlar) == 1
        assert yanitlar[0].tip is MesajTipi.ERROR
        assert yanitlar[0].yuk["code"] == "NET_0044"

        # Başarısız auth
        fail = srv.mesaj_isle(
            oturum.oturum_id, auth_mesaji("yanlis", cihaz_id="iphone-1")
        )
        assert fail[0].tip is MesajTipi.AUTH_FAIL
        assert not oturum.kimlikli

        # Başarılı auth
        ok = srv.mesaj_isle(
            oturum.oturum_id, auth_mesaji("gizli-token", cihaz_id="iphone-1")
        )
        assert ok[0].tip is MesajTipi.AUTH_OK
        assert oturum.kimlikli
        assert oturum.cihaz_id == "iphone-1"

        # Ping → Pong
        srv.giden_cek(oturum.oturum_id)
        ponglar = srv.mesaj_isle(oturum.oturum_id, ping_mesaji(cihaz_id="iphone-1"))
        assert ponglar[0].tip is MesajTipi.PONG

        # Yayın
        adet = srv.yayinla(mesaj_olustur(MesajTipi.NOTIFICATION, {"title": "t"}))
        assert adet == 1
        kuyruk = srv.giden_cek(oturum.oturum_id)
        assert any(decode_mesaj(h).tip is MesajTipi.NOTIFICATION for h in kuyruk)

        await srv.durdur()

    asyncio.run(_run())


def test_istemci_hello_ve_chat_ack() -> None:
    async def _run() -> None:
        srv = WsSunucu(dry_run=True, auth_zorunlu=False)
        await srv.baslat()
        oturum = srv.oturum_ac()
        srv.giden_cek(oturum.oturum_id)

        yanit = srv.mesaj_isle(
            oturum.oturum_id,
            hello_mesaji(rol="client", ad="iPhone", cihaz_id="c1"),
        )
        assert len(yanit) == 2
        assert yanit[0].tip is MesajTipi.HELLO
        assert yanit[1].tip is MesajTipi.ACK

        chat = srv.mesaj_isle(
            oturum.oturum_id,
            mesaj_olustur(MesajTipi.CHAT_SYNC, {"messages": []}, cihaz_id="c1"),
        )
        assert chat[0].tip is MesajTipi.ACK
        assert chat[0].yuk.get("type") == "chat_sync"

        await srv.durdur()

    asyncio.run(_run())


def test_zorla_sahte_ve_bos_token() -> None:
    async def _run() -> None:
        srv = WsSunucu(zorla_sahte=True)
        await srv.baslat()
        assert srv.motor == "sahte"
        oturum = srv.oturum_ac()
        srv.giden_cek(oturum.oturum_id)

        fail = srv.mesaj_isle(oturum.oturum_id, auth_mesaji(""))
        assert fail[0].tip is MesajTipi.AUTH_FAIL
        assert fail[0].yuk["code"] == "NET_0043"

        # Varsayılan sahte doğrulayıcı: dolu token kabul
        ok = srv.mesaj_isle(
            oturum.oturum_id, auth_mesaji("herhangi", cihaz_id="dev-9")
        )
        assert ok[0].tip is MesajTipi.AUTH_OK
        assert oturum.cihaz_id == "dev-9"

        await srv.durdur()

    asyncio.run(_run())


def test_baslatmadan_oturum_hatasi() -> None:
    srv = WsSunucu(dry_run=True)
    try:
        srv.oturum_ac()
        raise AssertionError("NetworkError beklenirdi")
    except NetworkError as exc:
        assert exc.kod == "NET_0041"


def test_gecersiz_json_error_yaniti() -> None:
    async def _run() -> None:
        srv = WsSunucu(dry_run=True, auth_zorunlu=False)
        await srv.baslat()
        oturum = srv.oturum_ac()
        srv.giden_cek(oturum.oturum_id)

        yanit = srv.mesaj_isle(oturum.oturum_id, "{degil-json")
        assert yanit[0].tip is MesajTipi.ERROR
        assert yanit[0].yuk["code"] == "NET_0038"

        await srv.durdur()

    asyncio.run(_run())


def test_bye_ack() -> None:
    async def _run() -> None:
        srv = WsSunucu(dry_run=True, auth_zorunlu=False)
        await srv.baslat()
        oturum = srv.oturum_ac()
        oid = oturum.oturum_id
        srv.giden_cek(oid)

        yanit = srv.mesaj_isle(oid, mesaj_olustur(MesajTipi.BYE, {}))
        assert yanit[0].tip is MesajTipi.ACK
        assert yanit[0].yuk.get("stage") == "bye"
        assert srv.oturum_al(oid).kimlikli is False

        assert srv.oturum_kapat(oid) is True
        await srv.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_dry_run_baslat_oturum_hello()
    test_auth_ping_pong_ve_yayin()
    test_istemci_hello_ve_chat_ack()
    test_zorla_sahte_ve_bos_token()
    test_baslatmadan_oturum_hatasi()
    test_gecersiz_json_error_yaniti()
    test_bye_ack()
    print("TEST_OK")

"""network/yoneticisi.py birim testleri (dry_run / ağsız)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.events import OLAY_AG_BAGLANDI, OLAY_AG_KOPTU, EventBus
from core.exceptions import NetworkError
from network.device.modeller import PlatformTuru
from network.websocket.protokol import MesajTipi, auth_mesaji, decode_mesaj
from network.yoneticisi import NetworkYoneticisi


def _yonetici() -> NetworkYoneticisi:
    tmp = Path(tempfile.mkdtemp())
    bus = EventBus(ad="test.network")
    return NetworkYoneticisi(
        bus=bus,
        dry_run=True,
        kayit_yolu=tmp / "devices.json",
        sync_depo_kok=tmp / "sync",
        sync_olustur=True,
    )


def test_dry_run_baslat_durdur_ozet() -> None:
    async def _run() -> None:
        olaylar: list[str] = []
        net = _yonetici()
        net.bus.subscribe(OLAY_AG_BAGLANDI, lambda e: olaylar.append(e.ad))
        net.bus.subscribe(OLAY_AG_KOPTU, lambda e: olaylar.append(e.ad))

        assert net.motor == "dry_run"
        assert net.sohbet is not None
        assert net.dosya is not None
        assert net.bildirim is not None
        assert net.yedek is not None

        await net.baslat()
        assert net.calisiyor
        assert net.cihazlar.calisiyor
        assert net.kesif.calisiyor
        assert net.ws.calisiyor
        assert net.sohbet.calisiyor
        assert OLAY_AG_BAGLANDI in olaylar

        ozet = net.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["discovery"]["engine"] == "dry_run"
        assert ozet["websocket"]["engine"] == "dry_run"
        assert "chat" in ozet["sync"]
        assert "cloud" in ozet["sync"]

        await net.durdur()
        assert not net.calisiyor
        assert OLAY_AG_KOPTU in olaylar

    asyncio.run(_run())


def test_eslestirme_ve_cihaz_api() -> None:
    async def _run() -> None:
        net = _yonetici()
        await net.baslat()

        oturum = await net.eslestirme_baslat(PlatformTuru.IOS)
        assert len(oturum.kod) == 6
        assert "code=" in oturum.qr_payload
        assert oturum.qr_payload.startswith("http://")

        cihaz = await net.kod_ile_eslestir(
            oturum.kod,
            "Test iPhone",
            PlatformTuru.IOS,
        )
        assert cihaz.ad == "Test iPhone"
        assert cihaz.token_parmak_izi
        assert len(net.cihaz_listele()) == 1
        assert net.cihaz_al(cihaz.cihaz_id).cihaz_id == cihaz.cihaz_id

        net.cihaz_durum_ayarla(cihaz.cihaz_id, "offline")
        assert net.cihaz_al(cihaz.cihaz_id).durum.value == "offline"
        assert net.cihaz_kaldir(cihaz.cihaz_id) is True
        assert net.cihaz_listele() == []

        await net.durdur()

    asyncio.run(_run())


def test_kesif_ve_ws_kancalari() -> None:
    async def _run() -> None:
        net = _yonetici()
        await net.baslat()

        ilan = net.kesif_ilan()
        assert ilan["magic"] == "WHITECORE"
        assert ilan["sent"] is False
        peers = await net.kesif_tara()
        assert isinstance(peers, list)

        oturum = net.ws_oturum_ac(uzak_adres="unit-test")
        giden = net.ws.giden_cek(oturum.oturum_id)
        assert len(giden) == 1
        hello = decode_mesaj(giden[0])
        assert hello.tip is MesajTipi.HELLO

        # dry_run: boş olmayan token kabul
        yanit = net.ws_mesaj_isle(
            oturum.oturum_id,
            auth_mesaji("test-token", cihaz_id="dev-1"),
        )
        assert yanit[0].tip is MesajTipi.AUTH_OK
        assert oturum.kimlikli

        await net.durdur()

    asyncio.run(_run())


def test_baslatmadan_api_hata() -> None:
    net = _yonetici()
    try:
        net.kesif_ilan()
        raise AssertionError("NetworkError bekleniyordu")
    except NetworkError as exc:
        assert exc.kod == "NET_0051"


def test_ws_auth_parmak_izi() -> None:
    """Eşleştirme token'ı WS AUTH ile doğrulanır."""

    async def _run() -> None:
        net = _yonetici()
        await net.baslat()
        oturum_p = await net.eslestirme_baslat("ios")
        # QR'dan ham token
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(oturum_p.qr_payload).query)
        token = q["token"][0]
        cihaz = await net.kod_ile_eslestir(
            oturum_p.kod,
            "Auth Phone",
            "ios",
        )

        ws = net.ws_oturum_ac()
        net.ws.giden_cek(ws.oturum_id)
        yanit = net.ws_mesaj_isle(
            ws.oturum_id,
            auth_mesaji(token, cihaz_id=cihaz.cihaz_id),
        )
        assert yanit[0].tip is MesajTipi.AUTH_OK
        assert ws.cihaz_id == cihaz.cihaz_id

        await net.durdur()

    asyncio.run(_run())


def test_sync_bagla() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        net = NetworkYoneticisi(
            dry_run=True,
            sync_olustur=False,
            kayit_yolu=tmp / "devices.json",
        )
        assert net.sohbet is None
        from sync.chat.senkron import SohbetSenkron

        s = SohbetSenkron(dry_run=True, depo_yolu=tmp / "chat.json")
        net.sync_bagla(sohbet=s)
        assert net.sohbet is s
        await net.baslat()
        assert s.calisiyor
        await net.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_dry_run_baslat_durdur_ozet()
    print("OK test_dry_run_baslat_durdur_ozet")
    test_eslestirme_ve_cihaz_api()
    print("OK test_eslestirme_ve_cihaz_api")
    test_kesif_ve_ws_kancalari()
    print("OK test_kesif_ve_ws_kancalari")
    test_baslatmadan_api_hata()
    print("OK test_baslatmadan_api_hata")
    test_ws_auth_parmak_izi()
    print("OK test_ws_auth_parmak_izi")
    test_sync_bagla()
    print("OK test_sync_bagla")
    print("OK test_yoneticisi")

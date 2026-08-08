"""network/discovery/kesif.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import NetworkError
from network.discovery.kesif import KesifKaydi, KesifServisi


def test_dry_run_baslat_ilan_tara() -> None:
    async def _run() -> None:
        srv = KesifServisi(dry_run=True, instance_id="host-dry-1")
        assert srv.motor == "dry_run"
        await srv.baslat()
        assert srv.calisiyor
        assert srv.adet() == 0

        yuk = srv.ilan_et()
        assert yuk["magic"] == "WHITECORE"
        assert yuk["instance_id"] == "host-dry-1"
        assert yuk["sent"] is False
        assert yuk["engine"] == "dry_run"
        assert "http_port" in yuk
        assert "websocket_port" in yuk

        peer = srv.kayit_ekle(
            {
                "instance_id": "peer-1",
                "name": "Test iPhone",
                "host": "192.168.1.10",
                "http_port": 8741,
                "websocket_port": 8742,
            },
            kaynak="manuel",
        )
        assert peer.ad == "Test iPhone"
        assert srv.adet() == 1

        liste = await srv.tara()
        assert len(liste) == 1
        assert liste[0].instance_id == "peer-1"

        ozet = srv.ozet()
        assert ozet["running"] is True
        assert ozet["engine"] == "dry_run"
        assert ozet["count"] == 1

        await srv.durdur()
        assert not srv.calisiyor

    asyncio.run(_run())


def test_zorla_sahte_ornek_peer() -> None:
    async def _run() -> None:
        srv = KesifServisi(zorla_sahte=True, instance_id="host-sahte-1")
        await srv.baslat()
        assert srv.motor == "sahte"
        assert srv.adet() >= 1
        assert all(k.kaynak == "sahte" for k in srv.listele())
        yuk = srv.ilan_et()
        assert yuk["sent"] is False
        await srv.durdur()

    asyncio.run(_run())


def test_kendi_instance_eklenemez() -> None:
    srv = KesifServisi(dry_run=True, instance_id="benim")
    try:
        srv.kayit_ekle(
            KesifKaydi(
                instance_id="benim",
                ad="Kendim",
                host="127.0.0.1",
                http_port=8741,
                websocket_port=8742,
            )
        )
        raise AssertionError("NetworkError bekleniyordu")
    except NetworkError as exc:
        assert exc.kod == "NET_0022"


def test_tara_calismadan_hata() -> None:
    async def _run() -> None:
        srv = KesifServisi(dry_run=True)
        try:
            await srv.tara()
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError as exc:
            assert exc.kod == "NET_0021"

    asyncio.run(_run())


def test_kayit_guncelle_ve_kaldir() -> None:
    srv = KesifServisi(dry_run=True, instance_id="host-x")
    a = srv.kayit_ekle(
        {
            "instance_id": "p1",
            "name": "Eski",
            "host": "10.0.0.1",
            "http_port": 8741,
            "websocket_port": 8742,
        }
    )
    assert a.ad == "Eski"
    b = srv.kayit_ekle(
        {
            "instance_id": "p1",
            "name": "Yeni",
            "host": "10.0.0.2",
            "http_port": 8741,
            "websocket_port": 8742,
        }
    )
    assert b.ad == "Yeni"
    assert b.host == "10.0.0.2"
    assert srv.adet() == 1
    assert srv.kayit_kaldir("p1") is True
    assert srv.adet() == 0
    assert srv.kayit_kaldir("yok") is False


def test_paket_isle_udp_yuku() -> None:
    srv = KesifServisi(dry_run=True, instance_id="host-paket")
    ham = (
        b'{"magic":"WHITECORE","v":1,"instance_id":"uzak-1",'
        b'"name":"LAN Peer","host":"192.168.0.5",'
        b'"http_port":8741,"websocket_port":8742,'
        b'"mdns_service":"_whitecore._tcp.local.","ts":1}'
    )
    srv._paket_isle(ham, "192.168.0.5")
    assert srv.adet() == 1
    peer = srv.listele()[0]
    assert peer.instance_id == "uzak-1"
    assert peer.kaynak == "udp"
    assert peer.host == "192.168.0.5"

    # Kendi paketini yoksay
    kendi = (
        b'{"magic":"WHITECORE","v":1,"instance_id":"host-paket",'
        b'"name":"Me","host":"127.0.0.1","http_port":8741,'
        b'"websocket_port":8742}'
    )
    srv._paket_isle(kendi, "127.0.0.1")
    assert srv.adet() == 1

    # Gecersiz magic
    srv._paket_isle(b'{"magic":"NOPE","instance_id":"x"}', "1.1.1.1")
    assert srv.adet() == 1


def test_kesif_kaydi_to_dict() -> None:
    k = KesifKaydi(
        instance_id="abc",
        ad="Pad",
        host="1.2.3.4",
        http_port=1,
        websocket_port=2,
        kaynak="manuel",
    )
    d = k.to_dict()
    assert d["instance_id"] == "abc"
    assert d["name"] == "Pad"
    assert d["source"] == "manuel"
    assert "last_seen" in d


if __name__ == "__main__":
    test_dry_run_baslat_ilan_tara()
    test_zorla_sahte_ornek_peer()
    test_kendi_instance_eklenemez()
    test_tara_calismadan_hata()
    test_kayit_guncelle_ve_kaldir()
    test_paket_isle_udp_yuku()
    test_kesif_kaydi_to_dict()
    print("TEST_OK")

"""network/pairing/servis.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.events import EventBus
from core.exceptions import NetworkError
from network.device.modeller import PlatformTuru
from network.device.yonetici import CihazYoneticisi
from network.pairing.servis import EslestirmeServisi
from network.pairing.token import TokenYoneticisi


def _hazirla() -> tuple[EslestirmeServisi, CihazYoneticisi]:
    tmp = Path(tempfile.mkdtemp()) / "devices.json"
    cihazlar = CihazYoneticisi(bus=EventBus(ad="test.pair"), kayit_yolu=tmp)
    cihazlar.max_cihaz = 5
    servis = EslestirmeServisi(cihazlar, TokenYoneticisi())
    return servis, cihazlar


def test_kod_ile_eslestirme() -> None:
    async def _run() -> None:
        servis, cihazlar = _hazirla()
        await cihazlar.baslat()
        oturum = await servis.oturum_baslat(PlatformTuru.IOS)
        assert len(oturum.kod) == 6
        assert oturum.kod.isdigit()
        assert "code=" in oturum.qr_payload
        assert "token=" in oturum.qr_payload
        assert oturum.qr_payload.startswith("http://")
        assert servis.aktif_oturum_sayisi() == 1

        cihaz = await servis.kod_ile_eslestir(oturum.kod, "Yasir iPhone", PlatformTuru.IOS)
        assert cihaz.ad == "Yasir iPhone"
        assert cihaz.platform == PlatformTuru.IOS
        assert cihaz.token_parmak_izi
        assert cihazlar.adet() == 1
        assert servis.aktif_oturum_sayisi() == 0

        # Tek kullanımlık — aynı kod tekrar işe yaramaz
        try:
            await servis.kod_ile_eslestir(oturum.kod, "Tekrar", PlatformTuru.IOS)
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError as exc:
            assert "Gecersiz" in str(exc) or "kullanildi" in str(exc).lower()

        await cihazlar.durdur()

    asyncio.run(_run())


def test_qr_ile_eslestirme() -> None:
    async def _run() -> None:
        servis, cihazlar = _hazirla()
        await cihazlar.baslat()
        oturum = await servis.oturum_baslat(PlatformTuru.IPADOS)
        cihaz = await servis.qr_ile_eslestir(
            oturum.qr_payload,
            "Yasir iPad",
            PlatformTuru.IPADOS,
        )
        assert cihaz.ad == "Yasir iPad"
        assert cihazlar.adet() == 1
        await cihazlar.durdur()

    asyncio.run(_run())


def test_oturum_iptal() -> None:
    async def _run() -> None:
        servis, cihazlar = _hazirla()
        await cihazlar.baslat()
        oturum = await servis.oturum_baslat(PlatformTuru.WEB)
        await servis.oturum_iptal(oturum.oturum_id)
        assert servis.aktif_oturum_sayisi() == 0
        try:
            await servis.kod_ile_eslestir(oturum.kod, "X", PlatformTuru.WEB)
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError:
            pass
        await cihazlar.durdur()

    asyncio.run(_run())


def test_gecersiz_kod() -> None:
    async def _run() -> None:
        servis, cihazlar = _hazirla()
        await cihazlar.baslat()
        await servis.oturum_baslat(PlatformTuru.IOS)
        try:
            await servis.kod_ile_eslestir("000000", "Yok", PlatformTuru.IOS)
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError as exc:
            assert exc.kod == "NET_0013"
        await cihazlar.durdur()

    asyncio.run(_run())


def test_ttl_dolmus_oturum() -> None:
    async def _run() -> None:
        servis, cihazlar = _hazirla()
        await cihazlar.baslat()
        # Çok kısa TTL
        servis.tokenlar.ttl_saniye = 1
        oturum = await servis.oturum_baslat(PlatformTuru.IOS)
        kayit = servis._oturumlar[oturum.oturum_id]
        kayit.son_gecerlilik_unix = time.time() - 1
        kayit.token_paketi = kayit.token_paketi.__class__(
            token=kayit.token_paketi.token,
            parmak_izi=kayit.token_paketi.parmak_izi,
            olusturma_unix=kayit.token_paketi.olusturma_unix,
            son_gecerlilik_unix=kayit.son_gecerlilik_unix,
        )
        try:
            await servis.kod_ile_eslestir(oturum.kod, "Gec", PlatformTuru.IOS)
            raise AssertionError("NetworkError bekleniyordu")
        except NetworkError as exc:
            assert "dolmus" in str(exc).lower() or exc.kod in {"NET_0013", "NET_0019"}
        await cihazlar.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_kod_ile_eslestirme()
    test_qr_ile_eslestirme()
    test_oturum_iptal()
    test_gecersiz_kod()
    test_ttl_dolmus_oturum()
    print("OK test_eslestirme_servis")

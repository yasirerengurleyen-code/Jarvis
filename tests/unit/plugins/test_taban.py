"""plugins/taban.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from core.exceptions import PluginError
from plugins.modeller import PluginDurumu, PluginKaynak
from plugins.taban import PluginBaglam, PluginTabani


class _SahtePlugin(PluginTabani):
    ad = "merhaba"
    surum = "0.2.0"
    aciklama = "Ornek eklenti"
    anahtarlar = ("selam", "hello", "merhaba")
    kaynak = PluginKaynak.ORNEK

    async def calistir(self, komut: str, **kwargs: Any):
        engel = self.onay_kontrol(onaylandi=bool(kwargs.get("onaylandi")))
        if engel is not None:
            return engel
        if kwargs.get("dry_run"):
            return self.dry_run_sonucu(komut, **kwargs)
        return self.ok("selam", veri={"komut": komut})


class _TehlikeliPlugin(PluginTabani):
    ad = "tehlike_demo"
    tehlikeli = True
    tehlike_eylemi = "terminal_command"
    anahtarlar = ("tehlike",)

    async def calistir(self, komut: str, **kwargs: Any):
        engel = self.onay_kontrol(onaylandi=bool(kwargs.get("onaylandi")))
        if engel is not None:
            return engel
        return self.ok("calisti")


class _HataliYukle(PluginTabani):
    ad = "bozuk_yukle"

    async def _yukle(self) -> None:
        raise RuntimeError("yukleme patladi")

    async def calistir(self, komut: str, **kwargs: Any):
        return self.ok("x")


def test_manifesto_ve_eslesme() -> None:
    p = _SahtePlugin()
    assert p.eklenti_adi == "merhaba"
    assert p.durum is PluginDurumu.KESFEDILDI
    assert not p.hazir_mi

    man = p.manifesto()
    assert man.ad == "merhaba"
    assert man.surum == "0.2.0"
    assert man.kaynak is PluginKaynak.ORNEK
    assert "selam" in man.anahtarlar
    assert man.to_dict()["name"] == "merhaba"

    assert p.eslesir_mi("selam ver")
    assert p.eslesir_mi("hello world")
    assert not p.eslesir_mi("hava nasil")


def test_yasam_dongusu_yukle_kaldir() -> None:
    async def _run() -> None:
        p = _SahtePlugin()
        await p.yukle()
        assert p.hazir_mi
        assert p.durum is PluginDurumu.HAZIR
        assert p.kayit().yuklenme_zamani is not None

        # tekrar yukle no-op
        await p.yukle()
        assert p.hazir_mi

        await p.kaldir()
        assert p.durum is PluginDurumu.KALDIRILDI
        assert not p.hazir_mi

    asyncio.run(_run())


def test_yukle_hata_durumu() -> None:
    async def _run() -> None:
        p = _HataliYukle()
        try:
            await p.yukle()
            raise AssertionError("PluginError beklenirdi")
        except PluginError as exc:
            assert exc.kod == "PLG_0033"
        assert p.durum is PluginDurumu.HATA
        assert p._hata  # noqa: SLF001

    asyncio.run(_run())


def test_devre_disi() -> None:
    async def _run() -> None:
        p = _SahtePlugin()
        p.devre_disi_birak()
        assert p.durum is PluginDurumu.DEVRE_DISI
        try:
            await p.yukle()
            raise AssertionError("PluginError beklenirdi")
        except PluginError as exc:
            assert exc.kod == "PLG_0032"

    asyncio.run(_run())


def test_calistir_ve_guvenli() -> None:
    async def _run() -> None:
        p = _SahtePlugin()
        r0 = await p.guvenli_calistir("selam")
        assert not r0.basarili_mi
        assert "hazir degil" in r0.mesaj

        await p.yukle()
        r1 = await p.calistir("selam jarvis")
        assert r1.basarili_mi
        assert r1.eklenti == "merhaba"
        assert r1.veri["komut"] == "selam jarvis"

        r2 = await p.guvenli_calistir("selam", dry_run=True)
        assert r2.basarili_mi
        assert r2.veri.get("dry_run") is True
        assert p.durum is PluginDurumu.HAZIR

        r3 = await p.guvenli_calistir("selam tekrar")
        assert r3.basarili_mi
        assert p.durum is PluginDurumu.HAZIR

        assert p.ok("x").eklenti == "merhaba"
        assert p.hata("y").basarili_mi is False
        assert p.desteklenmiyor().durum is YetenekDurumu.DESTEKLENMIYOR

    asyncio.run(_run())


def test_tehlikeli_onay() -> None:
    from config.ayarlar import Ayarlar

    async def _run() -> None:
        t = _TehlikeliPlugin()
        await t.yukle()
        ayar = Ayarlar()
        ayar.yukle()

        r1 = await t.guvenli_calistir("tehlike", ayar_yonetici=ayar)
        assert r1.durum is YetenekDurumu.ONAY_BEKLIYOR

        r2 = await t.guvenli_calistir(
            "tehlike", onaylandi=True, ayar_yonetici=ayar
        )
        assert r2.basarili_mi

        baglam = PluginBaglam(onaylandi=True, ayar_yonetici=ayar)
        r3 = await t.guvenli_calistir("tehlike", baglam=baglam)
        assert r3.basarili_mi

    asyncio.run(_run())


def test_baglam_dry_run() -> None:
    async def _run() -> None:
        p = _SahtePlugin()
        await p.yukle()
        b = PluginBaglam(dry_run=True)
        r = await p.guvenli_calistir("selam", baglam=b)
        assert r.veri.get("dry_run") is True

    asyncio.run(_run())


if __name__ == "__main__":
    test_manifesto_ve_eslesme()
    test_yasam_dongusu_yukle_kaldir()
    test_yukle_hata_durumu()
    test_devre_disi()
    test_calistir_ve_guvenli()
    test_tehlikeli_onay()
    test_baglam_dry_run()
    print("OK test_taban")

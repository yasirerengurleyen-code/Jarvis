"""skills/yoneticisi.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from core.events import EventBus
from skills.taban import SkillTabani
from skills.yoneticisi import (
    OLAY_SKILL_CALISTI,
    OLAY_SKILL_ONAY,
    SkillYoneticisi,
)


class _Notepad(SkillTabani):
    ad = "program_ac"
    kategori = "system"
    anahtarlar = ("notepad", "program aç")

    async def calistir(self, komut: str, **kwargs):  # noqa: ANN003
        return self.ok("notepad", veri={"komut": komut})


class _Terminal(SkillTabani):
    ad = "terminal"
    kategori = "system"
    tehlikeli = True
    tehlike_eylemi = "terminal_command"
    anahtarlar = ("terminal", "komut çalıştır")

    async def calistir(self, komut: str, **kwargs):  # noqa: ANN003
        return self.ok("cmd", veri={"komut": komut})


def test_kayit_eslesme_calistir() -> None:
    async def _run() -> None:
        bus = EventBus(ad="test.skills")
        olaylar: list[str] = []
        bus.subscribe(OLAY_SKILL_CALISTI, lambda e: olaylar.append(e.ad))

        y = SkillYoneticisi(bus=bus)
        await y.baslat()
        y.kaydet(_Notepad())
        y.kaydet(_Terminal())
        assert y.adet == 2
        assert "program_ac" in y.adlar()
        assert y.sec("notepad aç") is not None
        assert y.sec("notepad aç").ad == "program_ac"

        r = await y.calistir("lütfen notepad aç")
        assert r.basarili
        assert r.yetenek == "program_ac"
        assert OLAY_SKILL_CALISTI in olaylar

        metas = y.listele(kategori="system")
        assert len(metas) == 2
        assert y.ozet()["count"] == 2
        await y.durdur()
        assert y.adet == 0

    asyncio.run(_run())


def test_onay_ve_bulunamadi() -> None:
    async def _run() -> None:
        from config.ayarlar import Ayarlar

        bus = EventBus(ad="test.skills2")
        onaylar: list = []
        bus.subscribe(OLAY_SKILL_ONAY, lambda e: onaylar.append(e.veri))

        ayar = Ayarlar()
        ayar.yukle()
        y = SkillYoneticisi(ayar_yonetici=ayar, bus=bus, skilller=[_Terminal()])
        await y.baslat()

        r1 = await y.calistir("terminal dir")
        assert r1.durum == YetenekDurumu.ONAY_BEKLIYOR
        assert onaylar

        r2 = await y.calistir("terminal dir", onaylandi=True)
        assert r2.basarili

        r3 = await y.calistir("uzay gemisi fırlat")
        assert r3.durum == YetenekDurumu.DESTEKLENMIYOR

        await y.durdur()

    asyncio.run(_run())


def test_acik_skill_adi() -> None:
    async def _run() -> None:
        y = SkillYoneticisi(skilller=[_Notepad()])
        await y.baslat()
        r = await y.calistir("herhangi bir şey", skill_adi="program_ac")
        assert r.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_kayit_eslesme_calistir()
    test_onay_ve_bulunamadi()
    test_acik_skill_adi()
    print("OK test_yoneticisi")

"""skills/taban.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from skills.taban import (
    SkillBaglam,
    SkillTabani,
    anahtar_eslesir,
    komut_normalize,
    tehlikeli_onay_gerekli,
)


class _SahteSkill(SkillTabani):
    ad = "program_ac"
    aciklama = "Program açar"
    kategori = "system"
    anahtarlar = ("program aç", "uygulama aç", "notepad")
    ornekler = ("Notepad aç",)

    async def calistir(self, komut: str, **kwargs):  # noqa: ANN003
        engel = self.onay_kontrol(onaylandi=bool(kwargs.get("onaylandi")))
        if engel is not None:
            return engel
        return self.ok("açıldı", veri={"komut": komut})


class _TehlikeliSkill(SkillTabani):
    ad = "terminal"
    tehlikeli = True
    tehlike_eylemi = "terminal_command"
    anahtarlar = ("terminal", "komut çalıştır")

    async def calistir(self, komut: str, **kwargs):  # noqa: ANN003
        engel = self.onay_kontrol(onaylandi=bool(kwargs.get("onaylandi")))
        if engel is not None:
            return engel
        return self.ok("çalıştı")


def test_normalize_ve_anahtar() -> None:
    assert komut_normalize("  Merhaba   Dünya  ") == "merhaba dünya"
    assert anahtar_eslesir("Lütfen notepad aç", ["notepad"])
    assert anahtar_eslesir("program aç lütfen", ["program aç"])
    assert not anahtar_eslesir("hava nasıl", ["notepad"])


def test_meta_ve_eslesme() -> None:
    s = _SahteSkill()
    m = s.meta()
    assert m.ad == "program_ac"
    assert m.kategori == "system"
    assert "notepad" in m.anahtarlar
    assert s.eslesir_mi("Notepad ile yazı yaz")
    assert s.eslesir_mi("program aç chrome")


def test_tehlikeli_onay() -> None:
    import asyncio

    from config.ayarlar import Ayarlar

    t = _TehlikeliSkill()
    ayar = Ayarlar()
    ayar.yukle()
    assert tehlikeli_onay_gerekli(ayar, eylem="terminal_command") is True

    async def _run() -> None:
        r1 = await t.calistir("terminal dir")
        assert r1.durum == YetenekDurumu.ONAY_BEKLIYOR
        r2 = await t.calistir("terminal dir", onaylandi=True)
        assert r2.basarili is True

    asyncio.run(_run())


def test_ok_hata_baglam() -> None:
    s = _SahteSkill()
    assert s.ok("x").yetenek == "program_ac"
    assert s.hata("y").basarili is False
    assert s.desteklenmiyor().durum == YetenekDurumu.DESTEKLENMIYOR
    b = SkillBaglam(onaylandi=True)
    assert b.onaylandi is True


if __name__ == "__main__":
    test_normalize_ve_anahtar()
    test_meta_ve_eslesme()
    test_tehlikeli_onay()
    test_ok_hata_baglam()
    print("OK test_taban")

"""core/base.py birim testi."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.base import (
    Mesaj,
    MesajRolu,
    ModulTabani,
    PlatformIstemciTabani,
    SistemDurumu,
    YetenekDurumu,
    YetenekSonucu,
    YetenekTabani,
)
from core.logger import logger_yapilandir
from mobile.bridge.arayuzler import MobilKopruIskelet
from network.device.modeller import BagliCihaz, BaglantiDurumu, PlatformTuru
from network.pairing.arayuzler import EslestirmeServisiIskelet
from sync.arayuzler import SohbetSenkronuIskelet


class _OrnekModul(ModulTabani):
    ad = "ornek"
    aciklama = "Test modülü"

    async def baslat(self) -> None:
        self._isaret_basladi()

    async def durdur(self) -> None:
        self._isaret_durdu()


class _OrnekYetenek(YetenekTabani):
    ad = "chrome"
    aciklama = "Chrome açar"

    async def calistir(self, komut: str, **kwargs):
        return YetenekSonucu.ok("Chrome açıldı", yetenek=self.ad)


async def _async_testler() -> None:
    modul = _OrnekModul()
    assert not modul.calisiyor
    await modul.baslat()
    assert modul.calisiyor
    assert modul.bilgi().hazir is True
    await modul.durdur()
    assert not modul.calisiyor

    yetenek = _OrnekYetenek()
    assert yetenek.eslesir_mi("Chrome'u aç")
    sonuc = await yetenek.calistir("chrome aç")
    assert sonuc.basarili
    assert sonuc.yetenek == "chrome"

    # Platform iskeletleri NotImplementedError vermeli
    kopru = MobilKopruIskelet()
    try:
        await kopru.telefonumu_bul("c1")
        raise AssertionError("MobilKopruIskelet exception vermeliydi")
    except NotImplementedError:
        pass

    eslesme = EslestirmeServisiIskelet()
    try:
        await eslesme.oturum_baslat(PlatformTuru.IOS)
        raise AssertionError("Eslestirme iskelet exception vermeliydi")
    except NotImplementedError:
        pass

    sync = SohbetSenkronuIskelet()
    try:
        await sync.gonder("c1", [])
        raise AssertionError("Sync iskelet exception vermeliydi")
    except NotImplementedError:
        pass


def test_base() -> None:
    logger_yapilandir(zorla=True)

    # Enumlar
    assert SistemDurumu.HAZIR.value == "hazir"
    assert MesajRolu.ASISTAN.value == "assistant"

    # Mesaj
    m = Mesaj.kullanici("Merhaba Jarvis", kaynak="test")
    assert m.rol == MesajRolu.KULLANICI
    assert m.meta["kaynak"] == "test"
    assert m.to_dict()["content"] == "Merhaba Jarvis"

    a = Mesaj.asistan("Sistemler çevrimiçi.")
    assert a.rol == MesajRolu.ASISTAN

    # Yetenek sonucu
    ok = YetenekSonucu.ok("Tamam", yetenek="test", veri={"x": 1})
    assert ok.basarili
    assert ok.to_dict()["ok"] is True

    hata = YetenekSonucu.hata("Olmadı")
    assert hata.durum == YetenekDurumu.BASARISIZ

    onay = YetenekSonucu.onay_gerekli("Silinsin mi?")
    assert onay.durum == YetenekDurumu.ONAY_BEKLIYOR

    # Cihaz modeli
    cihaz = BagliCihaz(
        cihaz_id="iphone-1",
        ad="Yasir iPhone",
        platform=PlatformTuru.IOS,
        durum=BaglantiDurumu.CEVRIMICI,
        pil_yuzde=86,
    )
    cihaz.dokun()
    assert cihaz.cevrimici_mi()
    assert cihaz.to_dict()["platform"] == "ios"
    assert PlatformTuru.ANDROID.value == "android"

    # ABC kontrolü
    assert issubclass(ModulTabani, object)
    assert issubclass(YetenekTabani, object)
    assert issubclass(PlatformIstemciTabani, object)

    asyncio.run(_async_testler())

    print("TEST_OK")
    print("sistem_durumlari:", [s.value for s in SistemDurumu])
    print("mesaj_ornek:", m.to_dict()["role"], m.icerik)
    print("cihaz:", cihaz.ad, cihaz.platform.value, cihaz.pil_yuzde)


if __name__ == "__main__":
    test_base()

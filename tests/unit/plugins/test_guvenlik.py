"""plugins/guvenlik.py birim testleri."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.exceptions import PluginError
from plugins.guvenlik import (
    TEHLIKELI_IZINLER,
    GuvenlikKarari,
    PluginGuvenlik,
    guvenlik_olustur,
)
from plugins.modeller import PluginKaynak, PluginManifesto


class _SahteAyar:
    """Minimal ayar stub (Ayarlar.al uyumlu)."""

    def __init__(self, veri: dict[str, Any]) -> None:
        self._veri = veri
        self.yuklendi = True

    def al(self, anahtar: str, varsayilan: Any = None) -> Any:
        dugum: Any = self._veri
        for parca in anahtar.split("."):
            if not isinstance(dugum, dict) or parca not in dugum:
                return varsayilan
            dugum = dugum[parca]
        return dugum


def _ayar(**overrides: Any) -> _SahteAyar:
    taban: dict[str, Any] = {
        "plugins": {
            "enabled": True,
            "directory": "plugins",
            "autoload": True,
            "allow_list": [],
            "deny_list": [],
        },
        "security": {
            "sandbox_plugins": True,
            "require_confirmation_for_dangerous": True,
            "dangerous_actions": ["terminal_command", "file_delete"],
        },
    }
    for k, v in overrides.items():
        # "plugins.allow_list" → iç içe yaz
        parcalar = k.split(".")
        dugum = taban
        for p in parcalar[:-1]:
            dugum = dugum.setdefault(p, {})
        dugum[parcalar[-1]] = v
    return _SahteAyar(taban)


def test_allow_deny_listesi() -> None:
    g = PluginGuvenlik(_ayar(**{"plugins.allow_list": ["merhaba"], "plugins.deny_list": ["kotu"]}))
    assert g.izinli_mi("merhaba")
    assert not g.izinli_mi("kotu")
    karar = g.listede_izinli_mi("baska")
    assert not karar.izinli
    assert karar.kod == "PLG_0043"

    g2 = PluginGuvenlik(_ayar(**{"plugins.deny_list": ["kotu"]}))
    assert g2.izinli_mi("herhangi")
    assert not g2.izinli_mi("kotu")
    assert g2.listede_izinli_mi("kotu").kod == "PLG_0042"


def test_plugins_kapali() -> None:
    g = PluginGuvenlik(_ayar(**{"plugins.enabled": False}))
    karar = g.listede_izinli_mi("merhaba")
    assert not karar.izinli
    assert karar.kod == "PLG_0041"


def test_sandbox_tehlikeli_izin() -> None:
    g = PluginGuvenlik(_ayar(**{"security.sandbox_plugins": True}))
    man = PluginManifesto(
        ad="tehlike_eklenti",
        izinler=("fs.read", "system.exec"),
    )
    karar = g.izin_kontrol(man)
    assert not karar.izinli
    assert karar.kod == "PLG_0044"
    assert "system.exec" in TEHLIKELI_IZINLER

    g2 = PluginGuvenlik(_ayar(**{"security.sandbox_plugins": False}))
    assert g2.izin_kontrol(man).izinli


def test_istenen_izin_eksik() -> None:
    g = PluginGuvenlik(_ayar())
    man = PluginManifesto(ad="okuyucu", izinler=("fs.read",))
    karar = g.izin_kontrol(man, istenen=("fs.read", "network.http"))
    assert not karar.izinli
    assert karar.kod == "PLG_0045"
    assert g.izin_beyan_edildi_mi(man, "fs.read")
    assert not g.izin_beyan_edildi_mi(man, "network.http")


def test_yol_sandbox() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp)
        ic = kok / "alt" / "eklenti.py"
        ic.parent.mkdir(parents=True)
        ic.write_text("# ok\n", encoding="utf-8")
        dis = Path(tmp).parent / "disarida.py"

        g = PluginGuvenlik(
            _ayar(**{"security.sandbox_plugins": True}),
            plugin_kok=kok,
        )
        assert g.yol_sandbox_ici_mi(ic)
        assert g.yol_kontrol(ic).izinli
        # kök dışı
        karar = g.yol_kontrol(kok.parent / "x.py")
        assert not karar.izinli
        assert karar.kod == "PLG_0046"

        g_off = PluginGuvenlik(
            _ayar(**{"security.sandbox_plugins": False}),
            plugin_kok=kok,
        )
        assert g_off.yol_kontrol(dis).izinli


def test_imza_hash_dogrulama() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp)
        dosya = kok / "imzali.py"
        icerik = b"print('merhaba')\n"
        dosya.write_bytes(icerik)
        ozet = hashlib.sha256(icerik).hexdigest()

        g = PluginGuvenlik(_ayar(), plugin_kok=kok)
        man_ok = PluginManifesto(
            ad="imzali",
            yol=str(dosya),
            meta={"sha256": ozet},
        )
        assert g.imza_kontrol(man_ok).izinli
        assert not g.imza_kontrol(man_ok).imzasiz

        man_kotu = PluginManifesto(
            ad="bozuk",
            yol=str(dosya),
            meta={"sha256": "0" * 64},
        )
        karar = g.imza_kontrol(man_kotu)
        assert not karar.izinli
        assert karar.kod == "PLG_0049"

        man_yok = PluginManifesto(ad="imzasiz", kaynak=PluginKaynak.DOSYA)
        k2 = g.imza_kontrol(man_yok)
        assert k2.izinli
        assert k2.imzasiz

        g_zor = PluginGuvenlik(_ayar(), plugin_kok=kok, imza_zorunlu=True)
        k3 = g_zor.imza_kontrol(PluginManifesto(ad="zorunlu", kaynak=PluginKaynak.DOSYA))
        assert not k3.izinli
        assert k3.kod == "PLG_0047"
        # örnek kaynak muaf
        k4 = g_zor.imza_kontrol(
            PluginManifesto(ad="ornek_plg", kaynak=PluginKaynak.ORNEK)
        )
        assert k4.izinli


def test_yukleme_kontrol_birlesik() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp)
        dosya = kok / "merhaba.py"
        dosya.write_text("x=1\n", encoding="utf-8")
        ozet = hashlib.sha256(dosya.read_bytes()).hexdigest()

        ayar = _ayar(
            **{
                "plugins.allow_list": ["merhaba"],
                "security.sandbox_plugins": True,
            }
        )
        g = guvenlik_olustur(ayar, plugin_kok=kok)
        man = PluginManifesto(
            ad="merhaba",
            izinler=("fs.read", "ui.notify"),
            yol=str(dosya),
            meta={"sha256": ozet},
        )
        karar = g.yukleme_kontrol(man)
        assert karar.izinli
        assert karar.to_dict()["allowed"] is True

        # deny
        g2 = PluginGuvenlik(
            _ayar(**{"plugins.deny_list": ["merhaba"]}),
            plugin_kok=kok,
        )
        try:
            g2.yukleme_kontrol(man, zorunlu=True)
            raise AssertionError("PluginError beklenirdi")
        except PluginError as exc:
            assert exc.kod == "PLG_0042"

        soft = g2.yukleme_kontrol(man, zorunlu=False)
        assert not soft.izinli


def test_tehlikeli_onay_ve_karar() -> None:
    g = PluginGuvenlik(_ayar())
    man = PluginManifesto(ad="tehlike_demo", tehlikeli=True)
    assert g.tehlikeli_onay_gerekir_mi(man, eylem="terminal_command")
    man2 = PluginManifesto(ad="guvenli")
    assert not g.tehlikeli_onay_gerekir_mi(man2)

    k = GuvenlikKarari(izinli=True, neden="ok")
    assert k.zorunlu() is k
    try:
        GuvenlikKarari(izinli=False, neden="engel", kod="PLG_0040").zorunlu()
        raise AssertionError("PluginError beklenirdi")
    except PluginError as exc:
        assert exc.kod == "PLG_0040"

    assert g.sandbox_aktif_mi()
    assert g.plugins_etkin_mi()


if __name__ == "__main__":
    test_allow_deny_listesi()
    test_plugins_kapali()
    test_sandbox_tehlikeli_izin()
    test_istenen_izin_eksik()
    test_yol_sandbox()
    test_imza_hash_dogrulama()
    test_yukleme_kontrol_birlesik()
    test_tehlikeli_onay_ve_karar()
    print("OK test_guvenlik")

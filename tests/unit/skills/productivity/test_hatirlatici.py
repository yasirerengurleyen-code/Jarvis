"""skills/productivity/hatirlatici.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from skills.productivity.hatirlatici import (
    HatirlaticiSkill,
    baslik_ayikla,
    hatirlatici_ekle,
    hatirlatici_listele,
    hatirlatici_sil,
    hatirlatici_sorgula,
    hatirlatici_tamamla,
    id_ayikla,
    islem_ayikla,
    tarih_ayikla,
)
from skills.yoneticisi import SkillYoneticisi


def test_ayiklayicilar() -> None:
    assert islem_ayikla("hatırlatıcı listele") == "listele"
    assert islem_ayikla('hatırlatıcı ekle "Su iç"') == "ekle"
    assert islem_ayikla("hatırlatıcı sorgula su") == "sorgula"
    assert islem_ayikla("hatırlatıcı tamamla id:rem-1") == "tamamla"
    assert islem_ayikla("hatırlatıcı sil id:rem-1") == "sil"
    assert islem_ayikla("hatırlat") == "listele"
    assert baslik_ayikla('hatırlatıcı ekle "Su iç" 2026-08-10 14:00') == "Su iç"
    assert id_ayikla("hatırlatıcı sil id:rem-abc123") == "rem-abc123"
    assert id_ayikla("hatırlatıcı tamamla id:rem-xyz") == "rem-xyz"
    assert tarih_ayikla("hatırlatıcı 2026-08-10") is not None


def test_crud_tmp_ve_dry_sahte() -> None:
    tmp = Path(tempfile.mkdtemp()) / "reminders.json"

    bil = hatirlatici_listele(depo=tmp, dry_run=True)
    assert bil["dry_run"] is True
    assert bil["engine"] == "dry_run"

    bil_s = hatirlatici_listele(depo=tmp, zorla_sahte=True)
    assert bil_s["engine"] == "sahte"
    assert bil_s["count"] >= 1

    ek = hatirlatici_ekle(
        "Test Hatırlatma",
        depo=tmp,
        zaman="2026-08-10T14:00:00+00:00",
    )
    assert ek["engine"] == "local_json"
    assert tmp.is_file()
    rid = ek["reminder"]["id"]

    lst = hatirlatici_listele(depo=tmp)
    assert lst["count"] == 1
    assert lst["reminders"][0]["baslik"] == "Test Hatırlatma"
    assert lst["reminders"][0]["tamamlandi"] is False

    q = hatirlatici_sorgula("hatırlat", depo=tmp)
    assert q["count"] == 1

    dry_tam = hatirlatici_tamamla(rid, depo=tmp, dry_run=True)
    assert dry_tam["dry_run"] is True
    assert hatirlatici_listele(depo=tmp)["reminders"][0]["tamamlandi"] is False

    tam = hatirlatici_tamamla(rid, depo=tmp)
    assert tam["completed"] is True
    assert hatirlatici_listele(depo=tmp)["reminders"][0]["tamamlandi"] is True

    bek = hatirlatici_listele(depo=tmp, sadece_bekleyen=True)
    assert bek["count"] == 0

    dry_sil = hatirlatici_sil(rid, depo=tmp, dry_run=True)
    assert dry_sil["dry_run"] is True
    assert hatirlatici_listele(depo=tmp)["count"] == 1

    sil = hatirlatici_sil(rid, depo=tmp)
    assert sil["deleted"] is True
    assert hatirlatici_listele(depo=tmp)["count"] == 0


def test_skill_ve_sil_onay() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "rem.json"
        s = HatirlaticiSkill()
        assert s.eslesir_mi("hatırlatıcı listele")
        assert s.eslesir_mi("hatirlat")
        assert s.eslesir_mi("reminder")

        r = await s.calistir("hatırlatıcı listele", depo=tmp, dry_run=True)
        assert r.basarili
        assert r.veri["dry_run"] is True

        r2 = await s.calistir("hatırlatıcı listele", depo=tmp, zorla_sahte=True)
        assert r2.basarili
        assert r2.veri["engine"] == "sahte"

        r3 = await s.calistir(
            'hatırlatıcı ekle "Demo" 2026-08-11 10:00',
            depo=tmp,
        )
        assert r3.basarili
        rid = r3.veri["reminder"]["id"]

        r4 = await s.calistir(f"hatırlatıcı sil id:{rid}", depo=tmp, onaylandi=False)
        assert r4.durum == YetenekDurumu.ONAY_BEKLIYOR

        r5 = await s.calistir(
            f"hatırlatıcı sil id:{rid}",
            depo=tmp,
            onaylandi=True,
            dry_run=True,
        )
        assert r5.basarili
        assert r5.veri["dry_run"] is True

        r6 = await s.calistir(
            f"hatırlatıcı tamamla id:{rid}",
            depo=tmp,
        )
        assert r6.basarili
        assert r6.veri["completed"] is True

        r7 = await s.calistir(
            f"hatırlatıcı sil id:{rid}",
            depo=tmp,
            onaylandi=True,
        )
        assert r7.basarili

        r8 = await s.calistir("hatırlatıcı ekle", depo=tmp)
        assert not r8.basarili

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r9 = await y.calistir("hatırlatıcı listele", depo=tmp, zorla_sahte=True)
        assert r9.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_ayiklayicilar()
    test_crud_tmp_ve_dry_sahte()
    test_skill_ve_sil_onay()
    print("OK test_hatirlatici")

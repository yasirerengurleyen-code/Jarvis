"""skills/productivity/takvim.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from skills.productivity.takvim import (
    TakvimSkill,
    baslik_ayikla,
    etkinlik_ekle,
    etkinlik_listele,
    etkinlik_sil,
    etkinlik_sorgula,
    id_ayikla,
    islem_ayikla,
    tarih_ayikla,
)
from skills.yoneticisi import SkillYoneticisi


def test_ayiklayicilar() -> None:
    assert islem_ayikla("takvim listele") == "listele"
    assert islem_ayikla('takvim ekle "Toplantı"') == "ekle"
    assert islem_ayikla("takvim sorgula demo") == "sorgula"
    assert islem_ayikla("takvim sil id:evt-1") == "sil"
    assert islem_ayikla("bugün ne var") == "listele"
    assert baslik_ayikla('takvim ekle "Standup" 2026-08-10 14:00') == "Standup"
    assert id_ayikla("takvim sil id:evt-abc123") == "evt-abc123"
    assert tarih_ayikla("takvim 2026-08-10") is not None


def test_crud_tmp_ve_dry_sahte() -> None:
    tmp = Path(tempfile.mkdtemp()) / "events.json"

    bil = etkinlik_listele(depo=tmp, dry_run=True)
    assert bil["dry_run"] is True
    assert bil["engine"] == "dry_run"

    bil_s = etkinlik_listele(depo=tmp, zorla_sahte=True)
    assert bil_s["engine"] == "sahte"
    assert bil_s["count"] >= 1

    ek = etkinlik_ekle("Test Toplantı", depo=tmp, baslangic="2026-08-10T14:00:00+00:00")
    assert ek["engine"] == "local_json"
    assert tmp.is_file()
    eid = ek["event"]["id"]

    lst = etkinlik_listele(depo=tmp)
    assert lst["count"] == 1
    assert lst["events"][0]["baslik"] == "Test Toplantı"

    q = etkinlik_sorgula("toplantı", depo=tmp)
    assert q["count"] == 1

    dry_sil = etkinlik_sil(eid, depo=tmp, dry_run=True)
    assert dry_sil["dry_run"] is True
    assert etkinlik_listele(depo=tmp)["count"] == 1

    sil = etkinlik_sil(eid, depo=tmp)
    assert sil["deleted"] is True
    assert etkinlik_listele(depo=tmp)["count"] == 0


def test_skill_ve_sil_onay() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp()) / "cal.json"
        s = TakvimSkill()
        assert s.eslesir_mi("takvim listele")
        assert s.eslesir_mi("bugün ne var")
        assert s.eslesir_mi("ajanda")

        r = await s.calistir("takvim listele", depo=tmp, dry_run=True)
        assert r.basarili
        assert r.veri["dry_run"] is True

        r2 = await s.calistir("takvim listele", depo=tmp, zorla_sahte=True)
        assert r2.basarili
        assert r2.veri["engine"] == "sahte"

        r3 = await s.calistir(
            'takvim ekle "Demo" 2026-08-11 10:00',
            depo=tmp,
        )
        assert r3.basarili
        eid = r3.veri["event"]["id"]

        r4 = await s.calistir(f"takvim sil id:{eid}", depo=tmp, onaylandi=False)
        assert r4.durum == YetenekDurumu.ONAY_BEKLIYOR

        r5 = await s.calistir(
            f"takvim sil id:{eid}",
            depo=tmp,
            onaylandi=True,
            dry_run=True,
        )
        assert r5.basarili
        assert r5.veri["dry_run"] is True

        r6 = await s.calistir(
            f"takvim sil id:{eid}",
            depo=tmp,
            onaylandi=True,
        )
        assert r6.basarili

        r7 = await s.calistir("takvim ekle", depo=tmp)
        assert not r7.basarili

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r8 = await y.calistir("takvim listele", depo=tmp, zorla_sahte=True)
        assert r8.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_ayiklayicilar()
    test_crud_tmp_ve_dry_sahte()
    test_skill_ve_sil_onay()
    print("OK test_takvim")

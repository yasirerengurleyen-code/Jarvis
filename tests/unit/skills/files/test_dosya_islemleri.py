"""skills/files/dosya_islemleri.py birim testleri."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from core.base import YetenekDurumu
from skills.files.dosya_islemleri import (
    DosyaIslemleriSkill,
    dosya_listele,
    dosya_oku,
    dosya_sil,
    dosya_yaz,
    islem_ayikla,
    klasor_olustur,
)
from skills.yoneticisi import SkillYoneticisi


def test_islem_ayikla() -> None:
    assert islem_ayikla("dosya listele") == "listele"
    assert islem_ayikla("dosya oku x.txt") == "oku"
    assert islem_ayikla("şunu sil") == "sil"


def test_dosya_crud_tmp() -> None:
    tmp = Path(tempfile.mkdtemp())
    f = tmp / "a.txt"
    bil = dosya_yaz(f, "merhaba", dry_run=False)
    assert Path(bil["path"]).exists()
    assert dosya_oku(f) == "merhaba"
    assert "a.txt" in dosya_listele(tmp)
    d = tmp / "alt"
    klasor_olustur(d)
    assert d.is_dir()
    sil = dosya_sil(f, dry_run=True)
    assert sil["dry_run"] is True
    dosya_sil(f, dry_run=False)
    assert not f.exists()


def test_skill_liste_ve_sil_onay() -> None:
    async def _run() -> None:
        tmp = Path(tempfile.mkdtemp())
        f = tmp / "b.txt"
        f.write_text("x", encoding="utf-8")

        s = DosyaIslemleriSkill()
        r = await s.calistir(f'dosya listele "{tmp}"')
        assert r.basarili
        assert "b.txt" in r.veri["items"]

        r2 = await s.calistir(f'dosya sil "{f}"', onaylandi=False)
        assert r2.durum == YetenekDurumu.ONAY_BEKLIYOR

        r3 = await s.calistir(f'dosya sil "{f}"', onaylandi=True, dry_run=True)
        assert r3.basarili
        assert f.exists()  # dry_run

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r4 = await y.calistir(f'dosya oku "{f}"')
        assert r4.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_islem_ayikla()
    test_dosya_crud_tmp()
    test_skill_liste_ve_sil_onay()
    print("OK test_dosya_islemleri")

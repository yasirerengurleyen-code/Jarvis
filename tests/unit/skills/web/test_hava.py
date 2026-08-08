"""skills/web/hava.py birim testleri."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.web.hava import HavaSkill, sehir_ayikla, sehir_koordinat
from skills.yoneticisi import SkillYoneticisi


class _SahteYanit:
    def __init__(self, veri: dict) -> None:
        self._ham = json.dumps(veri).encode("utf-8")

    def read(self) -> bytes:
        return self._ham

    def __enter__(self) -> "_SahteYanit":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_sehir_ayikla() -> None:
    assert sehir_ayikla("hava istanbul") == "İstanbul"
    assert sehir_ayikla("Ankara hava durumu") == "Ankara"
    assert sehir_koordinat("izmir") is not None


def test_skill_sahte_ve_mock() -> None:
    async def _run() -> None:
        s = HavaSkill()
        assert s.eslesir_mi("hava durumu nasıl")
        r = await s.calistir("hava ankara", zorla_sahte=True)
        assert r.basarili
        assert "Ankara" in r.mesaj or r.veri.get("city") == "Ankara"

        def fake_urlopen(req, timeout=0):  # noqa: ANN001
            return _SahteYanit(
                {
                    "current": {
                        "temperature_2m": 21.0,
                        "weather_code": 0,
                        "wind_speed_10m": 10.0,
                        "relative_humidity_2m": 40.0,
                    }
                }
            )

        r2 = await s.calistir("hava istanbul", urlac=fake_urlopen)
        assert r2.basarili
        assert r2.veri.get("temp_c") == 21.0
        assert r2.veri.get("source") == "open-meteo"

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r3 = await y.calistir("hava izmir", zorla_sahte=True)
        assert r3.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_sehir_ayikla()
    test_skill_sahte_ve_mock()
    print("OK test_hava")

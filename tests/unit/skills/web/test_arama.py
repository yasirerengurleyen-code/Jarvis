"""skills/web/arama.py birim testleri."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[4]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from skills.web.arama import WebAramaSkill, sorgu_ayikla, web_ara
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


def test_sorgu_ayikla() -> None:
    assert sorgu_ayikla("web ara python asyncio") == "python asyncio"
    assert sorgu_ayikla("search: OpenAI") == "OpenAI"
    assert sorgu_ayikla("jarvis nedir ara") == "jarvis nedir"
    assert sorgu_ayikla("") is None


def test_web_ara_mock_ve_sahte() -> None:
    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        return _SahteYanit(
            {
                "Heading": "Python",
                "AbstractText": "Python bir programlama dilidir.",
                "AbstractURL": "https://www.python.org/",
                "RelatedTopics": [
                    {
                        "Text": "Asyncio - eşzamanlılık kütüphanesi",
                        "FirstURL": "https://docs.python.org/3/library/asyncio.html",
                    }
                ],
            }
        )

    bil = web_ara("python", urlac=fake_urlopen)
    assert bil["source"] == "duckduckgo"
    assert bil["count"] >= 1
    assert "Python" in bil["abstract"] or bil["results"]

    sahte = web_ara("offline", zorla_sahte=True)
    assert sahte["source"] == "sahte"
    assert sahte["count"] >= 1

    def patla(req, timeout=0):  # noqa: ANN001
        raise TimeoutError("zaman aşımı")

    dus = web_ara("x", urlac=patla)
    assert dus["source"] == "sahte"


def test_skill_yonetici() -> None:
    async def _run() -> None:
        s = WebAramaSkill()
        assert s.eslesir_mi("web ara test")
        r = await s.calistir("web ara WhiteCore", zorla_sahte=True)
        assert r.basarili
        assert r.veri["query"] == "WhiteCore"

        y = SkillYoneticisi(skilller=[s])
        await y.baslat()
        r2 = await y.calistir("search: jarvis", zorla_sahte=True)
        assert r2.basarili
        await y.durdur()

    asyncio.run(_run())


if __name__ == "__main__":
    test_sorgu_ayikla()
    test_web_ara_mock_ve_sahte()
    test_skill_yonetici()
    print("OK test_arama")

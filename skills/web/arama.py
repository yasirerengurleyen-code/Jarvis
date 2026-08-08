"""
skills/web/arama.py
------------------
Web arama skill'i.

Görev:
- Komuttan arama sorgusunu ayıklamak
- DuckDuckGo Instant Answer API (anahtar gerekmez)
- Ağ yoksa / hata olursa sahte sonuç (test / offline)
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from skills.taban import SkillTabani

_DDG = "https://api.duckduckgo.com/"


def sorgu_ayikla(komut: str) -> Optional[str]:
    """'web ara python', 'search: openai', 'google'da jarvis' vb."""
    n = (komut or "").strip()
    if not n:
        return None

    kaliplar = [
        r"(?i)^(?:web\s+ara|internet\s+ara|ara(?:ma)?|search|google(?:'da)?|bing)\s*[:：]?\s*(.+)$",
        r"(?i)^(.+)\s+(?:ara|search)\s*$",
    ]
    for k in kaliplar:
        m = re.search(k, n)
        if m:
            q = m.group(1).strip(" .\"'")
            # dolgu
            q = re.sub(r"(?i)^(lütfen|please|bana)\s+", "", q).strip()
            if q and q.lower() not in {"web", "internet", "google"}:
                return q
    return None


def web_ara(
    sorgu: str,
    *,
    max_sonuc: int = 5,
    timeout: float = 8.0,
    zorla_sahte: bool = False,
    urlac: Any = None,
) -> dict[str, Any]:
    """
    DuckDuckGo Instant Answer + RelatedTopics.

    zorla_sahte / ağ hatasında sahte sonuç döner.
    """
    sorgu = (sorgu or "").strip()
    if not sorgu:
        raise ValueError("Boş arama sorgusu")

    if zorla_sahte:
        return _sahte_sonuc(sorgu, max_sonuc)

    params = urllib.parse.urlencode(
        {
            "q": sorgu,
            "format": "json",
            "no_redirect": 1,
            "no_html": 1,
            "skip_disambig": 1,
        }
    )
    url = f"{_DDG}?{params}"
    ac = urlac or urllib.request.urlopen

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "WhiteCoreAI/0.1"},
        )
        with ac(req, timeout=timeout) as yanit:
            ham = yanit.read()
        veri = json.loads(ham.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        sonuc = _sahte_sonuc(sorgu, max_sonuc)
        sonuc["error"] = str(exc)
        sonuc["source"] = "sahte"
        return sonuc

    ozet = (veri.get("AbstractText") or "").strip()
    kaynak = (veri.get("AbstractURL") or "").strip()
    baslik = (veri.get("Heading") or sorgu).strip()

    maddeler: list[dict[str, str]] = []
    if ozet:
        maddeler.append({"title": baslik, "snippet": ozet, "url": kaynak})

    for konu in veri.get("RelatedTopics") or []:
        if len(maddeler) >= max_sonuc:
            break
        if isinstance(konu, dict) and "Topics" in konu:
            for alt in konu.get("Topics") or []:
                if len(maddeler) >= max_sonuc:
                    break
                _madde_ekle(maddeler, alt)
        else:
            _madde_ekle(maddeler, konu)

    if not maddeler:
        # DDG bazen boş döner
        return _sahte_sonuc(sorgu, max_sonuc) | {"source": "duckduckgo_empty"}

    return {
        "query": sorgu,
        "source": "duckduckgo",
        "abstract": ozet,
        "results": maddeler[:max_sonuc],
        "count": len(maddeler[:max_sonuc]),
    }


def _madde_ekle(maddeler: list[dict[str, str]], konu: Any) -> None:
    if not isinstance(konu, dict):
        return
    metin = (konu.get("Text") or "").strip()
    url = (konu.get("FirstURL") or "").strip()
    if not metin:
        return
    baslik = metin.split(" - ")[0][:120]
    maddeler.append({"title": baslik, "snippet": metin, "url": url})


def _sahte_sonuc(sorgu: str, max_sonuc: int) -> dict[str, Any]:
    maddeler = [
        {
            "title": f"Sonuç {i+1}: {sorgu}",
            "snippet": f"'{sorgu}' için örnek / offline sonuç #{i+1}.",
            "url": f"https://example.com/search?q={urllib.parse.quote(sorgu)}&n={i+1}",
        }
        for i in range(min(max_sonuc, 3))
    ]
    return {
        "query": sorgu,
        "source": "sahte",
        "abstract": maddeler[0]["snippet"] if maddeler else "",
        "results": maddeler,
        "count": len(maddeler),
    }


class WebAramaSkill(SkillTabani):
    """İnternette arama yapar."""

    ad = "web_arama"
    aciklama = "Web'de arama yapar (DuckDuckGo)"
    kategori = "web"
    tehlikeli = False
    anahtarlar = (
        "web ara",
        "internet ara",
        "ara",
        "arama",
        "search",
        "google",
        "bing",
    )
    ornekler = (
        "web ara python asyncio",
        "search: OpenAI API",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        sorgu = kwargs.get("sorgu") or sorgu_ayikla(komut)
        if not sorgu:
            return self.hata(
                "Arama sorgusu gerekli. Örnek: web ara python",
                veri={"komut": komut},
            )
        max_sonuc = int(kwargs.get("max_sonuc", 5))
        zorla_sahte = bool(kwargs.get("zorla_sahte", False))
        timeout = float(kwargs.get("timeout", 8.0))
        try:
            bil = web_ara(
                str(sorgu),
                max_sonuc=max_sonuc,
                timeout=timeout,
                zorla_sahte=zorla_sahte,
                urlac=kwargs.get("urlac"),
            )
        except Exception as exc:
            return self.hata(str(exc), veri={"query": sorgu})

        return self.ok(
            f"{bil.get('count', 0)} sonuç — {sorgu}",
            veri=bil,
        )


web_arama_skill = WebAramaSkill()

"""
memory/arama.py
---------------
Hafıza arama sistemi.

Görev:
- Sohbet geçmişi, kullanıcı profili ve uzun süreli hafızada arama
- Birleşik sonuç listesi (kaynak + skor)
- AI Manager / hafıza yöneticisi için tek giriş noktası
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from core.logger import logger_al
from memory.stores.kullanici import KullaniciDeposu
from memory.stores.sohbet import SohbetDeposu
from memory.stores.sqlite_depo import SqliteDepo
from memory.stores.uzun_sureli import UzunSureliHafiza

log = logger_al("memory.arama")


@dataclass(order=True)
class AramaSonucu:
    """Tek bir arama isabeti."""

    skor: float
    kaynak: str = field(compare=False)  # sohbet | kullanici | uzun_sureli
    icerik: str = field(compare=False)
    meta: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.skor,
            "source": self.kaynak,
            "content": self.icerik,
            "meta": self.meta,
        }


class HafizaArama:
    """Çok kaynaklı hafıza araması."""

    def __init__(
        self,
        depo: SqliteDepo,
        *,
        sohbet: Optional[SohbetDeposu] = None,
        kullanici: Optional[KullaniciDeposu] = None,
        uzun_sureli: Optional[UzunSureliHafiza] = None,
    ) -> None:
        self.depo = depo
        self.sohbet = sohbet or SohbetDeposu(depo)
        self.kullanici = kullanici or KullaniciDeposu(depo)
        self.uzun_sureli = uzun_sureli or UzunSureliHafiza(depo)

    def ara(
        self,
        sorgu: str,
        *,
        limit: int = 20,
        kaynaklar: Optional[list[str]] = None,
        oturum_id: Optional[str] = None,
    ) -> list[AramaSonucu]:
        """
        Tüm (veya seçilen) kaynaklarda ara; skora göre sırala.

        Args:
            sorgu: Arama metni
            limit: Maksimum sonuç
            kaynaklar: ['sohbet', 'kullanici', 'uzun_sureli'] veya None=hepsi
            oturum_id: Verilirse sohbet araması bu oturumla sınırlanır
        """
        q = (sorgu or "").strip()
        if not q:
            return []

        izinli = set(kaynaklar or ["sohbet", "kullanici", "uzun_sureli"])
        sonuclar: list[AramaSonucu] = []

        if "uzun_sureli" in izinli:
            sonuclar.extend(self._ara_uzun_sureli(q))
        if "kullanici" in izinli:
            sonuclar.extend(self._ara_kullanici(q))
        if "sohbet" in izinli:
            sonuclar.extend(self._ara_sohbet(q, oturum_id=oturum_id))

        # Yüksek skor önce (dataclass order=True skor üzerinde)
        sonuclar.sort(reverse=True)
        birlesik = sonuclar[:limit]
        log.debug("Arama '%s' → %s sonuç", q, len(birlesik))
        return birlesik

    def ozet_metinleri(self, sorgu: str, *, limit: int = 8) -> list[str]:
        """Prompt / özet için yalnızca içerik listesi."""
        return [s.icerik for s in self.ara(sorgu, limit=limit)]

    def _ara_uzun_sureli(self, sorgu: str) -> list[AramaSonucu]:
        kayitlar = self.uzun_sureli.metin_ara(sorgu, limit=50)
        sonuclar = []
        for k in kayitlar:
            skor = self._skor(sorgu, str(k.get("icerik", "")))
            skor += min(int(k.get("onem") or 0) * 0.1, 1.0)
            sonuclar.append(
                AramaSonucu(
                    skor=skor,
                    kaynak="uzun_sureli",
                    icerik=str(k["icerik"]),
                    meta={
                        "id": k.get("id"),
                        "anahtar": k.get("anahtar"),
                        "etiketler": k.get("etiketler"),
                        "onem": k.get("onem"),
                    },
                )
            )
        return sonuclar

    def _ara_kullanici(self, sorgu: str) -> list[AramaSonucu]:
        sonuclar = []
        for anahtar, deger in self.kullanici.tumu().items():
            metin = f"{anahtar}: {deger}"
            if self._eslesir(sorgu, metin):
                sonuclar.append(
                    AramaSonucu(
                        skor=self._skor(sorgu, metin) + 0.2,
                        kaynak="kullanici",
                        icerik=metin,
                        meta={"anahtar": anahtar, "deger": deger},
                    )
                )
        return sonuclar

    def _ara_sohbet(
        self,
        sorgu: str,
        *,
        oturum_id: Optional[str] = None,
    ) -> list[AramaSonucu]:
        like = f"%{sorgu}%"
        if oturum_id:
            rows = self.depo.getir_all(
                "SELECT id, oturum_id, rol, icerik, zaman FROM sohbet_mesajlari "
                "WHERE oturum_id = ? AND icerik LIKE ? "
                "ORDER BY id DESC LIMIT 50",
                (oturum_id, like),
            )
        else:
            rows = self.depo.getir_all(
                "SELECT id, oturum_id, rol, icerik, zaman FROM sohbet_mesajlari "
                "WHERE icerik LIKE ? ORDER BY id DESC LIMIT 50",
                (like,),
            )
        sonuclar = []
        for r in rows:
            icerik = str(r["icerik"])
            sonuclar.append(
                AramaSonucu(
                    skor=self._skor(sorgu, icerik),
                    kaynak="sohbet",
                    icerik=icerik,
                    meta={
                        "id": r["id"],
                        "oturum_id": r["oturum_id"],
                        "rol": r["rol"],
                        "zaman": r["zaman"],
                    },
                )
            )
        return sonuclar

    @staticmethod
    def _eslesir(sorgu: str, metin: str) -> bool:
        return sorgu.lower() in metin.lower()

    @staticmethod
    def _skor(sorgu: str, metin: str) -> float:
        """Basit alaka skoru: tam eşleşme > kelime örtüşmesi."""
        s = sorgu.lower().strip()
        t = metin.lower()
        if not s or not t:
            return 0.0
        if s == t:
            return 3.0
        if s in t:
            # Kısa metinde geçiyorsa daha yüksek
            oran = len(s) / max(len(t), 1)
            return 2.0 + min(oran, 0.9)
        kelimeler = [k for k in re.split(r"\s+", s) if k]
        if not kelimeler:
            return 0.0
        isabet = sum(1 for k in kelimeler if k in t)
        return isabet / len(kelimeler)


__all__ = ["AramaSonucu", "HafizaArama"]

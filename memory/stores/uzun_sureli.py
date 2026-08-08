"""
memory/stores/uzun_sureli.py
----------------------------
Uzun süreli hafıza deposu.

Görev:
- Kalıcı bilgi notları saklamak (tercihler, gerçekler, hatırlatmalar)
- Etiket ve önem skoru ile sınıflandırmak
- Basit metin araması (LIKE) sunmak — gelişmiş arama memory/arama.py'de
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.exceptions import MemoryError
from core.logger import logger_al
from memory.stores.sqlite_depo import SqliteDepo

log = logger_al("memory.stores.uzun_sureli")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class UzunSureliHafiza:
    """Kalıcı bilgi notları (SQLite)."""

    def __init__(self, depo: SqliteDepo) -> None:
        self.depo = depo

    def ekle(
        self,
        icerik: str,
        *,
        anahtar: Optional[str] = None,
        etiketler: Optional[list[str] | str] = None,
        onem: int = 0,
    ) -> int:
        """Not ekler; satır id döner."""
        metin = (icerik or "").strip()
        if not metin:
            raise MemoryError(
                "Hafıza içeriği boş olamaz",
                detay={},
            )
        etiket_metin = self._etiket_serilestir(etiketler)
        simdi = _utc()
        cur = self.depo.calistir(
            "INSERT INTO uzun_sureli_hafiza "
            "(anahtar, icerik, etiketler, onem, olusturma, guncelleme) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (anahtar, metin, etiket_metin, int(onem), simdi, simdi),
        )
        hid = int(cur.lastrowid)
        log.debug("Uzun süreli hafıza eklendi: id=%s", hid)
        return hid

    def getir(self, kayit_id: int) -> Optional[dict[str, Any]]:
        row = self.depo.getir_one(
            "SELECT id, anahtar, icerik, etiketler, onem, olusturma, guncelleme "
            "FROM uzun_sureli_hafiza WHERE id = ?",
            (kayit_id,),
        )
        return self._satir_dict(row) if row else None

    def anahtarla_getir(self, anahtar: str) -> list[dict[str, Any]]:
        rows = self.depo.getir_all(
            "SELECT id, anahtar, icerik, etiketler, onem, olusturma, guncelleme "
            "FROM uzun_sureli_hafiza WHERE anahtar = ? ORDER BY onem DESC, id DESC",
            (anahtar,),
        )
        return [self._satir_dict(r) for r in rows]

    def guncelle(
        self,
        kayit_id: int,
        *,
        icerik: Optional[str] = None,
        etiketler: Optional[list[str] | str] = None,
        onem: Optional[int] = None,
        anahtar: Optional[str] = None,
    ) -> None:
        mevcut = self.getir(kayit_id)
        if mevcut is None:
            raise MemoryError(
                "Hafıza kaydı bulunamadı",
                detay={"id": kayit_id},
            )
        yeni_icerik = icerik if icerik is not None else mevcut["icerik"]
        yeni_etiket = (
            self._etiket_serilestir(etiketler)
            if etiketler is not None
            else self._etiket_serilestir(mevcut["etiketler"])
        )
        yeni_onem = int(onem) if onem is not None else int(mevcut["onem"])
        yeni_anahtar = anahtar if anahtar is not None else mevcut["anahtar"]
        self.depo.calistir(
            "UPDATE uzun_sureli_hafiza SET anahtar = ?, icerik = ?, etiketler = ?, "
            "onem = ?, guncelleme = ? WHERE id = ?",
            (yeni_anahtar, yeni_icerik, yeni_etiket, yeni_onem, _utc(), kayit_id),
        )

    def sil(self, kayit_id: int) -> bool:
        cur = self.depo.calistir(
            "DELETE FROM uzun_sureli_hafiza WHERE id = ?",
            (kayit_id,),
        )
        return cur.rowcount > 0

    def listele(
        self,
        *,
        limit: int = 50,
        etiket: Optional[str] = None,
        min_onem: int = 0,
    ) -> list[dict[str, Any]]:
        if etiket:
            rows = self.depo.getir_all(
                "SELECT id, anahtar, icerik, etiketler, onem, olusturma, guncelleme "
                "FROM uzun_sureli_hafiza "
                "WHERE onem >= ? AND (etiketler = ? OR etiketler LIKE ? OR "
                "etiketler LIKE ? OR etiketler LIKE ?) "
                "ORDER BY onem DESC, id DESC LIMIT ?",
                (
                    min_onem,
                    etiket,
                    f"{etiket},%",
                    f"%,{etiket},%",
                    f"%,{etiket}",
                    limit,
                ),
            )
        else:
            rows = self.depo.getir_all(
                "SELECT id, anahtar, icerik, etiketler, onem, olusturma, guncelleme "
                "FROM uzun_sureli_hafiza WHERE onem >= ? "
                "ORDER BY onem DESC, id DESC LIMIT ?",
                (min_onem, limit),
            )
        return [self._satir_dict(r) for r in rows]

    def metin_ara(self, sorgu: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Basit LIKE araması (gelişmiş arama için memory/arama.py)."""
        q = (sorgu or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        rows = self.depo.getir_all(
            "SELECT id, anahtar, icerik, etiketler, onem, olusturma, guncelleme "
            "FROM uzun_sureli_hafiza "
            "WHERE icerik LIKE ? OR anahtar LIKE ? OR etiketler LIKE ? "
            "ORDER BY onem DESC, id DESC LIMIT ?",
            (like, like, like, limit),
        )
        return [self._satir_dict(r) for r in rows]

    def prompt_notlari(self, *, limit: int = 8) -> list[str]:
        """AI sistem promptuna eklenecek kısa not listesi."""
        kayitlar = self.listele(limit=limit, min_onem=0)
        return [str(k["icerik"]) for k in kayitlar if k.get("icerik")]

    @staticmethod
    def _etiket_serilestir(etiketler: Optional[list[str] | str]) -> str:
        if etiketler is None:
            return ""
        if isinstance(etiketler, str):
            return etiketler.strip()
        return ",".join(e.strip() for e in etiketler if e and str(e).strip())

    @staticmethod
    def _etiket_listesi(metin: str) -> list[str]:
        if not metin:
            return []
        return [p for p in str(metin).split(",") if p]

    def _satir_dict(self, row: Any) -> dict[str, Any]:
        d = dict(row)
        d["etiketler"] = self._etiket_listesi(d.get("etiketler") or "")
        return d


__all__ = ["UzunSureliHafiza"]

"""
memory/stores/sohbet.py
-----------------------
Sohbet geçmişi deposu.

Görev:
- Oturum oluşturmak / listelemek
- Mesaj eklemek ve oturuma göre okumak
- core.base.Mesaj ile uyumlu çalışmak
- Son N mesajı kısa dönem bağlam için vermek
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from core.base import Mesaj, MesajRolu
from core.exceptions import MemoryError
from core.logger import logger_al
from memory.stores.sqlite_depo import SqliteDepo

log = logger_al("memory.stores.sohbet")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class SohbetDeposu:
    """SQLite üzerinde sohbet oturumları ve mesajlar."""

    def __init__(self, depo: SqliteDepo) -> None:
        self.depo = depo

    def oturum_olustur(
        self,
        *,
        baslik: Optional[str] = None,
        oturum_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> str:
        """Yeni sohbet oturumu; oturum_id döner."""
        oid = oturum_id or str(uuid4())
        simdi = _utc()
        self.depo.calistir(
            "INSERT INTO sohbet_oturumlari (id, baslik, olusturma, guncelleme, meta) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                oid,
                baslik or "Sohbet",
                simdi,
                simdi,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        log.debug("Oturum oluşturuldu: %s", oid)
        return oid

    def oturum_var_mi(self, oturum_id: str) -> bool:
        row = self.depo.getir_one(
            "SELECT id FROM sohbet_oturumlari WHERE id = ?",
            (oturum_id,),
        )
        return row is not None

    def oturum_guncelle(
        self,
        oturum_id: str,
        *,
        baslik: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        if not self.oturum_var_mi(oturum_id):
            raise MemoryError(
                "Oturum bulunamadı",
                detay={"oturum_id": oturum_id},
            )
        if baslik is not None:
            self.depo.calistir(
                "UPDATE sohbet_oturumlari SET baslik = ?, guncelleme = ? WHERE id = ?",
                (baslik, _utc(), oturum_id),
            )
        if meta is not None:
            self.depo.calistir(
                "UPDATE sohbet_oturumlari SET meta = ?, guncelleme = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), _utc(), oturum_id),
            )

    def oturumlari_listele(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.depo.getir_all(
            "SELECT id, baslik, olusturma, guncelleme, meta "
            "FROM sohbet_oturumlari ORDER BY guncelleme DESC LIMIT ?",
            (limit,),
        )
        sonuc = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d.get("meta") or "{}")
            except json.JSONDecodeError:
                d["meta"] = {}
            sonuc.append(d)
        return sonuc

    def mesaj_ekle(
        self,
        oturum_id: str,
        mesaj: Mesaj,
    ) -> int:
        """Mesajı kaydeder; satır id döner."""
        if not self.oturum_var_mi(oturum_id):
            raise MemoryError(
                "Oturum bulunamadı",
                detay={"oturum_id": oturum_id},
            )
        rol = mesaj.rol.value if isinstance(mesaj.rol, MesajRolu) else str(mesaj.rol)
        cur = self.depo.calistir(
            "INSERT INTO sohbet_mesajlari "
            "(oturum_id, mesaj_id, rol, icerik, zaman, meta) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                oturum_id,
                mesaj.mesaj_id,
                rol,
                mesaj.icerik,
                mesaj.zaman,
                json.dumps(mesaj.meta or {}, ensure_ascii=False),
            ),
        )
        self.depo.calistir(
            "UPDATE sohbet_oturumlari SET guncelleme = ? WHERE id = ?",
            (_utc(), oturum_id),
        )
        return int(cur.lastrowid)

    def mesajlari_getir(
        self,
        oturum_id: str,
        *,
        limit: Optional[int] = None,
        sondan: bool = True,
    ) -> list[Mesaj]:
        """Oturum mesajlarını Mesaj listesi olarak döner."""
        if limit is not None and sondan:
            # Son N mesajı zaman sırasıyla almak için alt sorgu
            sql = (
                "SELECT mesaj_id, rol, icerik, zaman, meta FROM ("
                "  SELECT mesaj_id, rol, icerik, zaman, meta, id "
                "  FROM sohbet_mesajlari WHERE oturum_id = ? "
                "  ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC"
            )
            rows = self.depo.getir_all(sql, (oturum_id, limit))
        elif limit is not None:
            rows = self.depo.getir_all(
                "SELECT mesaj_id, rol, icerik, zaman, meta "
                "FROM sohbet_mesajlari WHERE oturum_id = ? "
                "ORDER BY id ASC LIMIT ?",
                (oturum_id, limit),
            )
        else:
            rows = self.depo.getir_all(
                "SELECT mesaj_id, rol, icerik, zaman, meta "
                "FROM sohbet_mesajlari WHERE oturum_id = ? "
                "ORDER BY id ASC",
                (oturum_id,),
            )

        mesajlar: list[Mesaj] = []
        for r in rows:
            try:
                rol = MesajRolu(r["rol"])
            except ValueError:
                rol = MesajRolu.KULLANICI
            try:
                meta = json.loads(r["meta"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            mesajlar.append(
                Mesaj(
                    icerik=r["icerik"],
                    rol=rol,
                    mesaj_id=r["mesaj_id"] or str(uuid4()),
                    zaman=r["zaman"],
                    meta=meta if isinstance(meta, dict) else {},
                )
            )
        return mesajlar

    def son_mesajlar(self, oturum_id: str, n: int = 20) -> list[Mesaj]:
        """Kısa dönem bağlam için son N mesaj."""
        return self.mesajlari_getir(oturum_id, limit=n, sondan=True)

    def mesaj_sayisi(self, oturum_id: str) -> int:
        row = self.depo.getir_one(
            "SELECT COUNT(*) AS c FROM sohbet_mesajlari WHERE oturum_id = ?",
            (oturum_id,),
        )
        return int(row["c"]) if row else 0

    def oturum_sil(self, oturum_id: str) -> None:
        """Oturumu ve mesajlarını siler (CASCADE)."""
        self.depo.calistir(
            "DELETE FROM sohbet_oturumlari WHERE id = ?",
            (oturum_id,),
        )
        log.info("Oturum silindi: %s", oturum_id)


__all__ = ["SohbetDeposu"]

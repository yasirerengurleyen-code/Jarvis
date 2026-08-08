"""
memory/stores/sqlite_depo.py
----------------------------
SQLite bağlantı ve şema yöneticisi.

Görev:
- database/whitecore.db dosyasını oluşturmak / açmak
- Temel tabloları kurmak (sohbet, kullanıcı, uzun süreli hafıza)
- Async-dostu senkron bağlantıyı thread pool ile sarmak
- Bağlantı ömrünü yönetmek

Üst katmanlar (sohbet / kullanıcı / uzun_sureli) bu depoyu kullanır.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import MemoryError
from core.logger import logger_al

log = logger_al("memory.stores.sqlite")

_PROJE_KOKU = Path(__file__).resolve().parents[2]

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS kullanicilar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anahtar TEXT NOT NULL UNIQUE,
    deger TEXT,
    guncelleme TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sohbet_oturumlari (
    id TEXT PRIMARY KEY,
    baslik TEXT,
    olusturma TEXT NOT NULL,
    guncelleme TEXT NOT NULL,
    meta TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sohbet_mesajlari (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oturum_id TEXT NOT NULL,
    mesaj_id TEXT,
    rol TEXT NOT NULL,
    icerik TEXT NOT NULL,
    zaman TEXT NOT NULL,
    meta TEXT DEFAULT '{}',
    FOREIGN KEY (oturum_id) REFERENCES sohbet_oturumlari(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sohbet_mesaj_oturum
    ON sohbet_mesajlari(oturum_id, zaman);

CREATE TABLE IF NOT EXISTS uzun_sureli_hafiza (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anahtar TEXT,
    icerik TEXT NOT NULL,
    etiketler TEXT DEFAULT '',
    onem INTEGER DEFAULT 0,
    olusturma TEXT NOT NULL,
    guncelleme TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hafiza_icerik
    ON uzun_sureli_hafiza(icerik);

CREATE INDEX IF NOT EXISTS idx_hafiza_etiket
    ON uzun_sureli_hafiza(etiketler);
"""


class SqliteDepo:
    """
    WhiteCore SQLite depo.

    Thread-safe değil; tek bağlantı + asyncio.to_thread ile kullanın.
    """

    def __init__(
        self,
        db_yolu: Optional[Path | str] = None,
        *,
        ayar_yonetici: Optional[Ayarlar] = None,
    ) -> None:
        self.ayarlar = ayar_yonetici or global_ayarlar
        self.db_yolu = Path(db_yolu) if db_yolu else self._varsayilan_yol()
        self._conn: Optional[sqlite3.Connection] = None

    def _varsayilan_yol(self) -> Path:
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:
                pass
        yol = self.ayarlar.al("memory.database_path", "database/whitecore.db")
        p = Path(str(yol))
        if not p.is_absolute():
            p = _PROJE_KOKU / p
        return p

    @property
    def acik_mi(self) -> bool:
        return self._conn is not None

    def baglan(self) -> sqlite3.Connection:
        """Senkron bağlantı açar ve şemayı uygular."""
        if self._conn is not None:
            return self._conn
        try:
            self.db_yolu.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_yolu),
                check_same_thread=False,
                isolation_level=None,  # autocommit; biz transaction yönetiriz
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(_SCHEMA_SQL)
            self._conn = conn
            log.info("SQLite bağlandı: %s", self.db_yolu)
            return conn
        except sqlite3.Error as exc:
            raise MemoryError(
                f"SQLite bağlantı hatası: {exc}",
                detay={"path": str(self.db_yolu), "hata": str(exc)},
            ) from exc

    def kapat(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            log.info("SQLite kapatıldı: %s", self.db_yolu)

    def _baglanti(self) -> sqlite3.Connection:
        if self._conn is None:
            return self.baglan()
        return self._conn

    def calistir(
        self,
        sql: str,
        parametreler: Sequence[Any] | None = None,
    ) -> sqlite3.Cursor:
        """INSERT/UPDATE/DELETE."""
        try:
            conn = self._baglanti()
            return conn.execute(sql, parametreler or [])
        except sqlite3.Error as exc:
            raise MemoryError(
                f"SQLite yazma hatası: {exc}",
                detay={"sql": sql[:120], "hata": str(exc)},
            ) from exc

    def many(
        self,
        sql: str,
        satırlar: Iterable[Sequence[Any]],
    ) -> None:
        try:
            conn = self._baglanti()
            conn.executemany(sql, list(satırlar))
        except sqlite3.Error as exc:
            raise MemoryError(
                f"SQLite toplu yazma hatası: {exc}",
                detay={"sql": sql[:120], "hata": str(exc)},
            ) from exc

    def getir_one(
        self,
        sql: str,
        parametreler: Sequence[Any] | None = None,
    ) -> Optional[sqlite3.Row]:
        try:
            cur = self._baglanti().execute(sql, parametreler or [])
            return cur.fetchone()
        except sqlite3.Error as exc:
            raise MemoryError(
                f"SQLite okuma hatası: {exc}",
                detay={"sql": sql[:120], "hata": str(exc)},
            ) from exc

    def getir_all(
        self,
        sql: str,
        parametreler: Sequence[Any] | None = None,
    ) -> list[sqlite3.Row]:
        try:
            cur = self._baglanti().execute(sql, parametreler or [])
            return list(cur.fetchall())
        except sqlite3.Error as exc:
            raise MemoryError(
                f"SQLite okuma hatası: {exc}",
                detay={"sql": sql[:120], "hata": str(exc)},
            ) from exc

    def transaction(self) -> sqlite3.Connection:
        """
        Manuel transaction için bağlantı.

        Kullanım:
            conn = depo.transaction()
            conn.execute('BEGIN')
            ...
            conn.execute('COMMIT')
        """
        return self._baglanti()

    # --- Async sarmalayıcılar ---

    async def abaglan(self) -> sqlite3.Connection:
        return await asyncio.to_thread(self.baglan)

    async def akapat(self) -> None:
        await asyncio.to_thread(self.kapat)

    async def acalistir(
        self,
        sql: str,
        parametreler: Sequence[Any] | None = None,
    ) -> None:
        await asyncio.to_thread(self.calistir, sql, parametreler)

    async def agetir_one(
        self,
        sql: str,
        parametreler: Sequence[Any] | None = None,
    ) -> Optional[dict[str, Any]]:
        row = await asyncio.to_thread(self.getir_one, sql, parametreler)
        return dict(row) if row is not None else None

    async def agetir_all(
        self,
        sql: str,
        parametreler: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self.getir_all, sql, parametreler)
        return [dict(r) for r in rows]


__all__ = ["SqliteDepo"]

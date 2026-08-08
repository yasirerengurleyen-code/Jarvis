"""
memory/stores/kullanici.py
--------------------------
Kullanıcı bilgileri ve tercih deposu.

Görev:
- Anahtar/değer olarak kullanıcı profili saklamak (ad, dil, tercihler…)
- config memory.user_profile ile uyumlu çalışmak
- JSON değerleri desteklemek
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from core.exceptions import MemoryError
from core.logger import logger_al
from memory.stores.sqlite_depo import SqliteDepo

log = logger_al("memory.stores.kullanici")

# Bilinen profil anahtarları
ANAHTAR_AD = "user.name"
ANAHTAR_DIL = "user.language"
ANAHTAR_TERCIHLER = "user.preferences"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class KullaniciDeposu:
    """SQLite anahtar-değer kullanıcı profili."""

    def __init__(self, depo: SqliteDepo) -> None:
        self.depo = depo

    def ayarla(self, anahtar: str, deger: Any) -> None:
        """Değer yazar (varsa günceller)."""
        if not anahtar or not str(anahtar).strip():
            raise MemoryError(
                "Kullanıcı anahtarı boş olamaz",
                detay={"anahtar": anahtar},
            )
        metin = self._serilestir(deger)
        simdi = _utc()
        self.depo.calistir(
            "INSERT INTO kullanicilar (anahtar, deger, guncelleme) VALUES (?, ?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger, "
            "guncelleme = excluded.guncelleme",
            (str(anahtar), metin, simdi),
        )
        log.debug("Kullanıcı ayarı yazıldı: %s", anahtar)

    def al(self, anahtar: str, varsayilan: Any = None) -> Any:
        """Değer okur; yoksa varsayılan."""
        row = self.depo.getir_one(
            "SELECT deger FROM kullanicilar WHERE anahtar = ?",
            (str(anahtar),),
        )
        if row is None or row["deger"] is None:
            return varsayilan
        return self._deserilestir(row["deger"])

    def sil(self, anahtar: str) -> bool:
        """Anahtarı siler; silindiyse True."""
        cur = self.depo.calistir(
            "DELETE FROM kullanicilar WHERE anahtar = ?",
            (str(anahtar),),
        )
        return cur.rowcount > 0

    def tumu(self) -> dict[str, Any]:
        """Tüm profil anahtarlarını dict olarak döner."""
        rows = self.depo.getir_all(
            "SELECT anahtar, deger FROM kullanicilar ORDER BY anahtar"
        )
        return {r["anahtar"]: self._deserilestir(r["deger"]) for r in rows}

    def var_mi(self, anahtar: str) -> bool:
        row = self.depo.getir_one(
            "SELECT 1 FROM kullanicilar WHERE anahtar = ?",
            (str(anahtar),),
        )
        return row is not None

    # --- Kolaylık API ---

    def adi_ayarla(self, ad: str) -> None:
        self.ayarla(ANAHTAR_AD, ad.strip())

    def adi_al(self) -> Optional[str]:
        deger = self.al(ANAHTAR_AD)
        return str(deger) if deger is not None else None

    def dil_ayarla(self, dil: str) -> None:
        self.ayarla(ANAHTAR_DIL, dil)

    def dil_al(self, varsayilan: str = "tr") -> str:
        deger = self.al(ANAHTAR_DIL, varsayilan)
        return str(deger) if deger is not None else varsayilan

    def tercih_ayarla(self, tercih_adi: str, deger: Any) -> None:
        tercihler = self.al(ANAHTAR_TERCIHLER, {})
        if not isinstance(tercihler, dict):
            tercihler = {}
        tercihler[tercih_adi] = deger
        self.ayarla(ANAHTAR_TERCIHLER, tercihler)

    def tercih_al(self, tercih_adi: str, varsayilan: Any = None) -> Any:
        tercihler = self.al(ANAHTAR_TERCIHLER, {})
        if not isinstance(tercihler, dict):
            return varsayilan
        return tercihler.get(tercih_adi, varsayilan)

    def profil_ozeti(self) -> dict[str, Any]:
        """AI prompt bağlamı için özet."""
        return {
            "name": self.adi_al(),
            "language": self.dil_al(),
            "preferences": self.al(ANAHTAR_TERCIHLER, {}) or {},
        }

    @staticmethod
    def _serilestir(deger: Any) -> str:
        if isinstance(deger, str):
            return deger
        return json.dumps(deger, ensure_ascii=False)

    @staticmethod
    def _deserilestir(metin: str) -> Any:
        if metin is None:
            return None
        s = str(metin)
        # JSON dene; değilse düz string
        if s[:1] in {"{", "[", '"'} or s in {"true", "false", "null"} or (
            s[:1].isdigit() or (s[:1] == "-" and len(s) > 1)
        ):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
        return s


__all__ = [
    "KullaniciDeposu",
    "ANAHTAR_AD",
    "ANAHTAR_DIL",
    "ANAHTAR_TERCIHLER",
]

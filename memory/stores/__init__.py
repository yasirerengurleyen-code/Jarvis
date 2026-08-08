# WhiteCore AI paketi: memory.stores
"""Hafıza depoları."""

from memory.stores.kullanici import (
    ANAHTAR_AD,
    ANAHTAR_DIL,
    ANAHTAR_TERCIHLER,
    KullaniciDeposu,
)
from memory.stores.sohbet import SohbetDeposu
from memory.stores.sqlite_depo import SqliteDepo
from memory.stores.uzun_sureli import UzunSureliHafiza

__all__ = [
    "SqliteDepo",
    "SohbetDeposu",
    "KullaniciDeposu",
    "UzunSureliHafiza",
    "ANAHTAR_AD",
    "ANAHTAR_DIL",
    "ANAHTAR_TERCIHLER",
]

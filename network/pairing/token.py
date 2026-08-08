"""
network/pairing/token.py
------------------------
Eşleştirme token üreticisi ve doğrulayıcısı.

Görev:
- Güvenli rastgele token üretmek
- SHA-256 parmak izi (hash) saklamak (ham token diskte tutulmaz)
- Süre (TTL) ve tek kullanımlık oturum doğrulaması
- 6 haneli sayısal eşleştirme kodu üretmek
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import NetworkError, SecurityError
from core.logger import logger_al

log = logger_al("network.pairing.token")


@dataclass(frozen=True)
class TokenPaketi:
    """Ham token + saklanabilir parmak izi."""

    token: str
    parmak_izi: str
    olusturma_unix: float
    son_gecerlilik_unix: float

    @property
    def gecerli_mi(self) -> bool:
        return time.time() <= self.son_gecerlilik_unix


class TokenYoneticisi:
    """
    Token ve 6 haneli kod üretimi / doğrulama.

    Ham token yalnızca eşleşme anında istemciye verilir;
    diskte yalnızca parmak izi saklanır.
    """

    def __init__(self, ayarlar: Optional[Ayarlar] = None) -> None:
        self.ayarlar = ayarlar or global_ayarlar
        self.kod_uzunlugu = int(self.ayarlar.al("network.pairing.code_length", 6))
        self.ttl_saniye = int(self.ayarlar.al("network.pairing.code_ttl_seconds", 300))
        # İsteğe bağlı HMAC tuzu (yoksa düz SHA-256)
        self._tuz = str(self.ayarlar.al("network.pairing.token_pepper", "") or "")

    def token_uret(self, *, bayt: int = 32, ttl_saniye: Optional[int] = None) -> TokenPaketi:
        """Kriptografik rastgele token üretir."""
        if bayt < 16:
            raise SecurityError(
                "Token en az 16 bayt olmali",
                kod="SEC_0010",
                modul="network.pairing",
            )
        ham = secrets.token_urlsafe(bayt)
        ttl = int(ttl_saniye if ttl_saniye is not None else self.ttl_saniye)
        simdi = time.time()
        paket = TokenPaketi(
            token=ham,
            parmak_izi=self.parmak_izi(ham),
            olusturma_unix=simdi,
            son_gecerlilik_unix=simdi + max(30, ttl),
        )
        log.debug("Token uretildi (ttl=%ss)", ttl)
        return paket

    def parmak_izi(self, token: str) -> str:
        """Ham token için saklanabilir SHA-256 (veya HMAC) özeti."""
        veri = token.encode("utf-8")
        if self._tuz:
            return hmac.new(self._tuz.encode("utf-8"), veri, hashlib.sha256).hexdigest()
        return hashlib.sha256(veri).hexdigest()

    def dogrula(self, token: str, beklenen_parmak_izi: str) -> bool:
        """Zaman-sabit karşılaştırmalı doğrulama."""
        if not token or not beklenen_parmak_izi:
            return False
        hesap = self.parmak_izi(token)
        return hmac.compare_digest(hesap, beklenen_parmak_izi)

    def kod_uret(self, uzunluk: Optional[int] = None) -> str:
        """Yalnızca rakamlardan oluşan eşleştirme kodu (varsayılan 6 hane)."""
        n = int(uzunluk if uzunluk is not None else self.kod_uzunlugu)
        if n < 4 or n > 12:
            raise NetworkError(
                "Eslesme kodu 4-12 hane olmali",
                kod="NET_0010",
                modul="network.pairing",
            )
        # secrets ile güvenli sayı; baştaki sıfırlar korunur
        ust = 10 ** n
        deger = secrets.randbelow(ust)
        return f"{deger:0{n}d}"

    def ttl_dolmus_mu(self, son_gecerlilik_unix: float) -> bool:
        return time.time() > float(son_gecerlilik_unix)

"""
network/pairing/servis.py
-------------------------
QR kod + 6 haneli kod ile cihaz eşleştirme servisi.

Görev:
- Kısa ömürlü eşleştirme oturumu başlatmak
- Token + 6 haneli kod üretmek
- Kod veya QR yükü ile cihazı CihazYoneticisi'ne kaydetmek
- Tek kullanımlık oturum ve TTL doğrulaması
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import NetworkError
from core.logger import audit_yaz, logger_al
from network.device.modeller import BagliCihaz, BaglantiDurumu, PlatformTuru
from network.device.yonetici import CihazYoneticisi
from network.http.sunucu import lan_ip_al
from network.pairing.arayuzler import (
    EslestirmeOturumu,
    EslestirmeServisi as EslestirmeServisiArayuz,
)
from network.pairing.token import TokenPaketi, TokenYoneticisi

log = logger_al("network.pairing.servis")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class _OturumKaydi:
    """Bellekte tutulan aktif eşleştirme oturumu."""

    oturum: EslestirmeOturumu
    token_paketi: TokenPaketi
    platform: PlatformTuru
    son_gecerlilik_unix: float


class EslestirmeServisi(EslestirmeServisiArayuz):
    """
    Yerel (host) eşleştirme uygulaması.

    Ham token yalnızca oturum süresince bellekte tutulur;
    cihaza saklanan değer token parmak izidir.
    """

    def __init__(
        self,
        cihaz_yoneticisi: CihazYoneticisi,
        token_yoneticisi: Optional[TokenYoneticisi] = None,
        *,
        ayarlar: Optional[Ayarlar] = None,
    ) -> None:
        self.cihazlar = cihaz_yoneticisi
        self.ayarlar = ayarlar or global_ayarlar
        self.tokenlar = token_yoneticisi or TokenYoneticisi(self.ayarlar)
        self.host = str(self.ayarlar.al("network.host", "0.0.0.0"))
        self.http_port = int(self.ayarlar.al("network.http_port", 8741))
        self.ws_port = int(self.ayarlar.al("network.websocket_port", 8742))
        self._oturumlar: dict[str, _OturumKaydi] = {}

    async def oturum_baslat(self, platform: PlatformTuru) -> EslestirmeOturumu:
        """Yeni QR + 6 haneli kod oturumu açar."""
        self._suresi_dolanlari_temizle()
        paket = self.tokenlar.token_uret()
        kod = self.tokenlar.kod_uret()
        # Aynı kod çakışmasını önle
        while any(k.oturum.kod == kod and not k.oturum.kullanildi for k in self._oturumlar.values()):
            kod = self.tokenlar.kod_uret()

        oturum_id = uuid4().hex
        simdi = _utc_now()
        bitis = datetime.fromtimestamp(paket.son_gecerlilik_unix, tz=timezone.utc)
        qr = self._qr_yuku(kod=kod, oturum_id=oturum_id, token=paket.token)
        oturum = EslestirmeOturumu(
            oturum_id=oturum_id,
            kod=kod,
            qr_payload=qr,
            olusturma=_iso(simdi),
            son_gecerlilik=_iso(bitis),
            kullanildi=False,
        )
        self._oturumlar[oturum_id] = _OturumKaydi(
            oturum=oturum,
            token_paketi=paket,
            platform=platform,
            son_gecerlilik_unix=paket.son_gecerlilik_unix,
        )
        audit_yaz(
            "pairing.session_started",
            modul="network.pairing",
            detay={
                "session_id": oturum_id,
                "platform": platform.value,
                "expires": oturum.son_gecerlilik,
            },
        )
        log.info("Eslesme oturumu acildi: %s (platform=%s)", oturum_id[:12], platform.value)
        return oturum

    async def kod_ile_eslestir(
        self,
        kod: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        """6 haneli kod ile bekleyen oturumu tamamlar."""
        cihaz, _token = self.kod_ile_eslestir_token(kod, cihaz_adi, platform)
        return cihaz

    def kod_ile_eslestir_token(
        self,
        kod: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> tuple[BagliCihaz, str]:
        """
        Kod ile eşleştirir ve ham oturum token'ını döner.

        HTTP telefon paneli / WS AUTH için senkron API
        (oturum bellekten düşmeden önce token kopyalanır).
        """
        kayit = self._kod_ile_bul(kod)
        token = kayit.token_paketi.token
        cihaz = self._eslestir(kayit, cihaz_adi=cihaz_adi, platform=platform)
        return cihaz, token

    async def qr_ile_eslestir(
        self,
        qr_payload: str,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        """QR içeriği (URI veya ham oturum eşleşmesi) ile bağlar."""
        kayit = self._qr_ile_bul(qr_payload)
        return self._eslestir(kayit, cihaz_adi=cihaz_adi, platform=platform)

    async def oturum_iptal(self, oturum_id: str) -> None:
        """Bekleyen oturumu iptal eder."""
        kayit = self._oturumlar.pop(oturum_id, None)
        if kayit is None:
            raise NetworkError(
                f"Eslesme oturumu bulunamadi: {oturum_id}",
                kod="NET_0011",
                modul="network.pairing",
            )
        kayit.oturum.kullanildi = True
        audit_yaz(
            "pairing.session_cancelled",
            modul="network.pairing",
            detay={"session_id": oturum_id},
        )
        log.info("Eslesme oturumu iptal: %s", oturum_id[:12])

    def aktif_oturum_sayisi(self) -> int:
        self._suresi_dolanlari_temizle()
        return sum(1 for k in self._oturumlar.values() if not k.oturum.kullanildi)

    def _eslestir(
        self,
        kayit: _OturumKaydi,
        *,
        cihaz_adi: str,
        platform: PlatformTuru,
    ) -> BagliCihaz:
        self._oturum_gecerli_mi(kayit)
        cihaz = self.cihazlar.olustur(
            cihaz_adi,
            platform,
            durum=BaglantiDurumu.CEVRIMICI,
            token_parmak_izi=kayit.token_paketi.parmak_izi,
            meta={
                "pairing_session_id": kayit.oturum.oturum_id,
                "pairing_method": "code_or_qr",
                "requested_platform": kayit.platform.value,
            },
        )
        kayit.oturum.kullanildi = True
        # Tek kullanımlık: oturumu bellekten düş
        self._oturumlar.pop(kayit.oturum.oturum_id, None)
        audit_yaz(
            "pairing.completed",
            modul="network.pairing",
            detay={
                "session_id": kayit.oturum.oturum_id,
                "device_id": cihaz.cihaz_id,
                "name": cihaz.ad,
                "platform": cihaz.platform.value,
            },
        )
        log.info(
            "Cihaz eslesti: %s (%s) oturum=%s",
            cihaz.ad,
            cihaz.platform.value,
            kayit.oturum.oturum_id[:12],
        )
        return cihaz

    def _kod_ile_bul(self, kod: str) -> _OturumKaydi:
        temiz = (kod or "").strip()
        if not temiz:
            raise NetworkError(
                "Eslesme kodu bos olamaz",
                kod="NET_0012",
                modul="network.pairing",
            )
        self._suresi_dolanlari_temizle()
        for kayit in self._oturumlar.values():
            if kayit.oturum.kullanildi:
                continue
            if kayit.oturum.kod == temiz:
                return kayit
        raise NetworkError(
            "Gecersiz veya suresi dolmus eslesme kodu",
            kod="NET_0013",
            modul="network.pairing",
        )

    def _qr_ile_bul(self, qr_payload: str) -> _OturumKaydi:
        yuk = (qr_payload or "").strip()
        if not yuk:
            raise NetworkError(
                "QR yuklu bos olamaz",
                kod="NET_0014",
                modul="network.pairing",
            )
        self._suresi_dolanlari_temizle()

        # Tam payload eşleşmesi
        for kayit in self._oturumlar.values():
            if kayit.oturum.kullanildi:
                continue
            if kayit.oturum.qr_payload == yuk:
                return kayit

        # URI parametrelerinden kod / sid / token
        kod, sid, token = self._qr_ayikla(yuk)
        if sid and sid in self._oturumlar:
            kayit = self._oturumlar[sid]
            if kayit.oturum.kullanildi:
                raise NetworkError(
                    "Eslesme oturumu zaten kullanildi",
                    kod="NET_0015",
                    modul="network.pairing",
                )
            if token and not self.tokenlar.dogrula(token, kayit.token_paketi.parmak_izi):
                raise NetworkError(
                    "QR token dogrulanamadi",
                    kod="NET_0016",
                    modul="network.pairing",
                )
            if kod and kod != kayit.oturum.kod:
                raise NetworkError(
                    "QR kodu oturum ile uyusmuyor",
                    kod="NET_0017",
                    modul="network.pairing",
                )
            return kayit

        if kod:
            return self._kod_ile_bul(kod)

        raise NetworkError(
            "QR yukunden eslesme oturumu bulunamadi",
            kod="NET_0018",
            modul="network.pairing",
        )

    def _oturum_gecerli_mi(self, kayit: _OturumKaydi) -> None:
        if kayit.oturum.kullanildi:
            raise NetworkError(
                "Eslesme oturumu zaten kullanildi",
                kod="NET_0015",
                modul="network.pairing",
            )
        if self.tokenlar.ttl_dolmus_mu(kayit.son_gecerlilik_unix):
            self._oturumlar.pop(kayit.oturum.oturum_id, None)
            raise NetworkError(
                "Eslesme oturumunun suresi dolmus",
                kod="NET_0019",
                modul="network.pairing",
            )

    def _suresi_dolanlari_temizle(self) -> None:
        silinecek = [
            oid
            for oid, k in self._oturumlar.items()
            if k.oturum.kullanildi or self.tokenlar.ttl_dolmus_mu(k.son_gecerlilik_unix)
        ]
        for oid in silinecek:
            self._oturumlar.pop(oid, None)

    def _qr_yuku(self, *, kod: str, oturum_id: str, token: str) -> str:
        """
        Telefon Safari'nin açabileceği HTTP panel URL'si.

        Parametreler: code, sid, token, host, port, ws_port.
        Eski whitecore://pair URI de aynı sorgu anahtarlarıyla parse edilir.
        """
        lan = lan_ip_al()
        # 0.0.0.0 / localhost QR için işe yaramaz — LAN IP kullan
        host = lan if self.host in {"0.0.0.0", "::", ""} else self.host
        if host.startswith("127."):
            host = lan
        return (
            f"http://{host}:{self.http_port}/"
            f"?code={kod}&sid={oturum_id}&token={token}"
            f"&host={host}&port={self.http_port}&ws_port={self.ws_port}"
        )

    @staticmethod
    def _qr_ayikla(yuk: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """QR URI'sinden code / sid / token çıkarır."""
        if "://" not in yuk and "?" not in yuk:
            return None, None, None
        try:
            parsed = urlparse(yuk)
            q = parse_qs(parsed.query)
        except ValueError:
            return None, None, None

        def _tek(anahtar: str) -> Optional[str]:
            degerler = q.get(anahtar) or q.get(anahtar.upper())
            if not degerler:
                return None
            return str(degerler[0])

        return _tek("code"), _tek("sid"), _tek("token")


__all__ = ["EslestirmeServisi"]

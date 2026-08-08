"""
gui/widgets/cihaz_paneli.py
---------------------------
Bağlı cihazlar / eşleştirme UI paneli.

Görev:
- Cihaz Bağla, Bağlı Cihazlar, Senkronizasyon, Bulut, Ayarlar butonları
- 6 haneli kod + QR yükü gösterimi
- Engine NetworkYoneticisi / SyncYoneticisi köprüsü (Aşama 6)
- network.device modelleri ile uyumlu cihaz listesi
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from network.device.modeller import BaglantiDurumu, BagliCihaz, PlatformTuru

AsyncZamanlayici = Callable[[Awaitable[Any]], None]

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    Signal = None  # type: ignore[misc, assignment]


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def kod_uret(uzunluk: int = 6) -> str:
    """6 haneli sayısal eşleştirme kodu."""
    uzunluk = max(4, min(8, int(uzunluk)))
    return "".join(secrets.choice(string.digits) for _ in range(uzunluk))


def qr_yuku_uret(
    kod: str,
    *,
    host: str = "0.0.0.0",
    http_port: int = 8741,
    oturum_id: str = "",
    ws_port: int = 8742,
    token: str = "",
) -> str:
    """QR içeriği — telefon Safari paneli (ağ servisi kendi yükünü üretir)."""
    oid = oturum_id or uuid4().hex[:12]
    try:
        from network.http.sunucu import lan_ip_al

        lan = lan_ip_al()
    except Exception:
        lan = "127.0.0.1"
    hedef = lan if host in {"0.0.0.0", "::", ""} or str(host).startswith("127.") else host
    q = (
        f"http://{hedef}:{http_port}/"
        f"?code={kod}&sid={oid}&host={hedef}&port={http_port}&ws_port={ws_port}"
    )
    if token:
        q += f"&token={token}"
    return q


@dataclass
class EslestirmeGosterim:
    """UI'da gösterilecek eşleştirme oturumu."""

    oturum_id: str
    kod: str
    qr_payload: str
    olusturma: str
    son_gecerlilik: str
    ttl_saniye: int = 300

    @classmethod
    def olustur(
        cls,
        *,
        kod_uzunluk: int = 6,
        ttl_saniye: int = 300,
        host: str = "0.0.0.0",
        http_port: int = 8741,
    ) -> "EslestirmeGosterim":
        """Ağ yokken yerel iskelet oturumu (offline / test)."""
        oid = uuid4().hex
        kod = kod_uret(kod_uzunluk)
        simdi = _utc()
        bitis = simdi + timedelta(seconds=ttl_saniye)
        return cls(
            oturum_id=oid,
            kod=kod,
            qr_payload=qr_yuku_uret(
                kod, host=host, http_port=http_port, oturum_id=oid[:12]
            ),
            olusturma=simdi.isoformat(),
            son_gecerlilik=bitis.isoformat(),
            ttl_saniye=ttl_saniye,
        )

    @classmethod
    def agdan(
        cls,
        oturum: Any,
        *,
        ttl_saniye: int = 300,
    ) -> "EslestirmeGosterim":
        """NetworkYoneticisi / EslestirmeOturumu → UI modeli."""
        return cls(
            oturum_id=str(getattr(oturum, "oturum_id", "") or ""),
            kod=str(getattr(oturum, "kod", "") or ""),
            qr_payload=str(getattr(oturum, "qr_payload", "") or ""),
            olusturma=str(getattr(oturum, "olusturma", "") or ""),
            son_gecerlilik=str(getattr(oturum, "son_gecerlilik", "") or ""),
            ttl_saniye=int(ttl_saniye),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.oturum_id,
            "code": self.kod,
            "qr_payload": self.qr_payload,
            "created": self.olusturma,
            "expires": self.son_gecerlilik,
            "ttl_seconds": self.ttl_saniye,
        }


@dataclass
class CihazPaneliModel:
    """Bağlı cihaz listesi + son eşleştirme oturumu."""

    cihazlar: list[BagliCihaz] = field(default_factory=list)
    son_oturum: Optional[EslestirmeGosterim] = None
    kod_uzunluk: int = 6
    ttl_saniye: int = 300
    host: str = "0.0.0.0"
    http_port: int = 8741

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "CihazPaneliModel":
        model = cls()
        if ayar_yonetici is None:
            try:
                from config.ayarlar import ayarlar as global_ayarlar

                ayar_yonetici = global_ayarlar
            except Exception:
                return model
        try:
            if not getattr(ayar_yonetici, "yuklendi", False):
                ayar_yonetici.yukle()
            model.kod_uzunluk = int(ayar_yonetici.al("network.pairing.code_length", 6))
            model.ttl_saniye = int(ayar_yonetici.al("network.pairing.code_ttl_seconds", 300))
            model.host = str(ayar_yonetici.al("network.host", "0.0.0.0"))
            model.http_port = int(ayar_yonetici.al("network.http_port", 8741))
        except Exception:
            pass
        return model

    def oturum_baslat(self) -> EslestirmeGosterim:
        self.son_oturum = EslestirmeGosterim.olustur(
            kod_uzunluk=self.kod_uzunluk,
            ttl_saniye=self.ttl_saniye,
            host=self.host,
            http_port=self.http_port,
        )
        return self.son_oturum

    def cihaz_ekle(self, cihaz: BagliCihaz) -> None:
        self.cihazlar = [c for c in self.cihazlar if c.cihaz_id != cihaz.cihaz_id]
        self.cihazlar.append(cihaz)

    def cihaz_kaldir(self, cihaz_id: str) -> bool:
        once = len(self.cihazlar)
        self.cihazlar = [c for c in self.cihazlar if c.cihaz_id != cihaz_id]
        return len(self.cihazlar) < once

    def demo_cihaz_ekle(self) -> BagliCihaz:
        """UI testi için örnek cihaz."""
        c = BagliCihaz(
            cihaz_id=uuid4().hex[:10],
            ad="iPhone (demo)",
            platform=PlatformTuru.IOS,
            durum=BaglantiDurumu.CEVRIMICI,
            pil_yuzde=84,
        )
        c.dokun()
        self.cihaz_ekle(c)
        return c

    def ozet_satirlari(self) -> list[str]:
        if not self.cihazlar:
            return ["Bağlı cihaz yok"]
        satirlar = []
        for c in self.cihazlar:
            pil = f" · %{c.pil_yuzde}" if c.pil_yuzde is not None else ""
            satirlar.append(f"{c.ad} [{c.platform.value}] — {c.durum.value}{pil}")
        return satirlar


class CihazPaneli(QFrame):  # type: ignore[misc, valid-type]
    """
    Bağlı cihazlar paneli.

    Sinyaller:
    - cihaz_bagla_istedi
    - senkron_istedi
    - bulut_istedi
    - ayarlar_istedi
    """

    if _PYSIDE_VAR:
        cihaz_bagla_istedi = Signal(object)  # EslestirmeGosterim
        senkron_istedi = Signal()
        bulut_istedi = Signal()
        ayarlar_istedi = Signal()
    else:  # pragma: no cover
        cihaz_bagla_istedi = None  # type: ignore[assignment]
        senkron_istedi = None  # type: ignore[assignment]
        bulut_istedi = None  # type: ignore[assignment]
        ayarlar_istedi = None  # type: ignore[assignment]

    # Sayfa indeksleri
    SAYFA_LISTE = 0
    SAYFA_BAGLA = 1
    SAYFA_SENKRON = 2
    SAYFA_BULUT = 3
    SAYFA_AYARLAR = 4

    def __init__(
        self,
        model: Optional[CihazPaneliModel] = None,
        parent: Any = None,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.model = model or CihazPaneliModel.ayarlardan()
        self._network: Any = None
        self._sync: Any = None
        self._mobile: Any = None
        self._async_zamanla: Optional[AsyncZamanlayici] = None
        self._bus: Any = None
        self._bus_abonelikleri: list[tuple[str, Any]] = []

        self.setObjectName("CamPanel")
        self.setProperty("cam", True)

        baslik = QLabel("BAĞLI CİHAZLAR")
        baslik.setObjectName("Baslik")

        # Buton şeridi
        self._btn_bagla = QPushButton("Cihaz Bağla")
        self._btn_liste = QPushButton("Bağlı Cihazlar")
        self._btn_senkron = QPushButton("Senkronizasyon")
        self._btn_bulut = QPushButton("Bulut Yedekleme")
        self._btn_ayarlar = QPushButton("Bağlantı Ayarları")

        self._btn_bagla.clicked.connect(self.cihaz_bagla)
        self._btn_liste.clicked.connect(lambda: self.sayfa_goster(self.SAYFA_LISTE))
        self._btn_senkron.clicked.connect(self._senkron)
        self._btn_bulut.clicked.connect(self._bulut)
        self._btn_ayarlar.clicked.connect(self._ayarlar)

        dugmeler = QHBoxLayout()
        dugmeler.setSpacing(6)
        for b in (
            self._btn_bagla,
            self._btn_liste,
            self._btn_senkron,
            self._btn_bulut,
            self._btn_ayarlar,
        ):
            dugmeler.addWidget(b)

        self._yigin = QStackedWidget()
        self._yigin.addWidget(self._sayfa_liste_kur())
        self._yigin.addWidget(self._sayfa_bagla_kur())
        self._senkron_etiket = QLabel("Sync henüz bağlanmadı.")
        self._bulut_etiket = QLabel("Bulut yedek henüz bağlanmadı.")
        self._ayarlar_etiket = QLabel("Ağ yöneticisi henüz bağlanmadı.")
        self._yigin.addWidget(
            self._bilgi_sayfa("Senkronizasyon", self._senkron_etiket)
        )
        self._yigin.addWidget(
            self._bilgi_sayfa("Bulut Yedekleme", self._bulut_etiket)
        )
        self._yigin.addWidget(
            self._bilgi_sayfa("Bağlantı Ayarları", self._ayarlar_etiket)
        )

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(12, 10, 12, 10)
        yerlesim.setSpacing(8)
        yerlesim.addWidget(baslik)
        yerlesim.addLayout(dugmeler)
        yerlesim.addWidget(self._yigin, stretch=1)

        self.liste_yenile()

    def _bilgi_sayfa(self, baslik: str, govde: QLabel) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        t = QLabel(baslik)
        t.setObjectName("AltBaslik")
        govde.setWordWrap(True)
        govde.setObjectName("AltBaslik")
        lay.addWidget(t)
        lay.addWidget(govde)
        lay.addStretch(1)
        return w

    def _sayfa_liste_kur(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._liste = QListWidget()
        self._bos_etiket = QLabel("Bağlı cihaz yok — «Cihaz Bağla» ile başlayın.")
        self._bos_etiket.setObjectName("AltBaslik")
        self._bos_etiket.setWordWrap(True)
        lay.addWidget(self._bos_etiket)
        lay.addWidget(self._liste, stretch=1)
        return w

    def _sayfa_bagla_kur(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._kod_etiket = QLabel("——————")
        self._kod_etiket.setObjectName("NeonMetrik")
        self._kod_etiket.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._kod_etiket.setStyleSheet("font-size: 28px; letter-spacing: 8px;")

        self._qr_gorsel = QLabel("")
        self._qr_gorsel.setObjectName("KarekodGorsel")
        self._qr_gorsel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_gorsel.setMinimumSize(180, 180)
        self._qr_gorsel.setStyleSheet(
            "background:#FFFFFF; border:1px solid #00A894; border-radius:6px;"
        )

        self._qr_etiket = QLabel("")
        self._qr_etiket.setObjectName("AltBaslik")
        self._qr_etiket.setWordWrap(True)
        self._qr_etiket.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._ttl_etiket = QLabel("")
        self._ttl_etiket.setObjectName("AltBaslik")

        yenile = QPushButton("Yeni karekod / kod üret")
        yenile.clicked.connect(self.cihaz_bagla)

        self._bagla_bilgi = QLabel(
            "Telefon kamerası ile karekodu okutun (Safari açılır) "
            "veya panelde 6 haneli kodu girin. API key gerekmez."
        )
        self._bagla_bilgi.setWordWrap(True)
        self._bagla_bilgi.setObjectName("AltBaslik")

        lay.addWidget(QLabel("Eşleştirme kodu"))
        lay.addWidget(self._kod_etiket)
        lay.addWidget(self._ttl_etiket)
        lay.addWidget(QLabel("KAREKOD"))
        lay.addWidget(self._qr_gorsel, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._qr_etiket)
        lay.addWidget(yenile)
        lay.addWidget(self._bagla_bilgi)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------------------ Engine köprüsü

    def network_bagla(
        self,
        network: Any,
        *,
        async_zamanla: Optional[AsyncZamanlayici] = None,
        bus: Any = None,
    ) -> None:
        """NetworkYoneticisi bağlar; cihaz listesi ve eşleştirme canlı olur."""
        self._network = network
        if async_zamanla is not None:
            self._async_zamanla = async_zamanla
        if bus is not None:
            self.bus_bagla(bus)
        self.agdan_yenile()
        self._ozet_sayfalarini_guncelle()

    def sync_bagla(self, sync: Any) -> None:
        """SyncYoneticisi bağlar; senkron / bulut özet sayfalarını günceller."""
        self._sync = sync
        self._ozet_sayfalarini_guncelle()

    def mobile_bagla(self, mobile: Any) -> None:
        """MobilYoneticisi (iPhone köprüsü) bağlar; ayarlar özetini günceller."""
        self._mobile = mobile
        self._ozet_sayfalarini_guncelle()

    def bus_bagla(self, bus: Any) -> None:
        """Cihaz olaylarında listeyi yenile."""
        self.bus_coz()
        self._bus = bus
        if bus is None:
            return
        from core.events import (
            OLAY_CIHAZ_DURUM,
            OLAY_CIHAZ_ESLESTI,
            OLAY_IPHONE_BAGLANDI,
            OLAY_IPHONE_KOPTU,
        )

        def _yenile(_event: Any = None) -> None:
            self._ui(self.agdan_yenile)

        for olay in (
            OLAY_CIHAZ_ESLESTI,
            OLAY_CIHAZ_DURUM,
            OLAY_IPHONE_BAGLANDI,
            OLAY_IPHONE_KOPTU,
        ):
            bus.subscribe(olay, _yenile, priority=5)
            self._bus_abonelikleri.append((olay, _yenile))

    def bus_coz(self) -> None:
        if self._bus is None:
            self._bus_abonelikleri.clear()
            return
        for olay, fn in self._bus_abonelikleri:
            try:
                self._bus.unsubscribe(olay, fn)
            except Exception:
                pass
        self._bus_abonelikleri.clear()
        self._bus = None

    def agdan_yenile(self) -> None:
        """Network cihaz listesini modele çeker ve UI yeniler."""
        if self._network is not None and hasattr(self._network, "cihaz_listele"):
            try:
                self.model.cihazlar = list(self._network.cihaz_listele())
            except Exception:
                pass
        self.liste_yenile()

    def _ui(self, fn: Callable[[], None]) -> None:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, fn)

    def _ozet_sayfalarini_guncelle(self) -> None:
        if self._network is not None and hasattr(self._network, "ozet"):
            try:
                o = self._network.ozet()
                self._ayarlar_etiket.setText(
                    f"Motor: {o.get('engine')} · "
                    f"host={o.get('host')}:{o.get('http_port')} · "
                    f"ws={o.get('websocket_port')} · "
                    f"cihaz={o.get('devices', {}).get('count', o.get('devices', {}).get('total', '?'))}"
                )
                self._bagla_bilgi.setText(
                    "Telefon bu kodu veya QR yükünü kullanarak bağlanabilir. "
                    f"(Network motor={o.get('engine')})"
                )
            except Exception:
                self._ayarlar_etiket.setText("Network bağlı (özet alınamadı).")
        else:
            self._ayarlar_etiket.setText("Ağ yöneticisi henüz bağlanmadı.")

        if self._mobile is not None and hasattr(self._mobile, "ozet"):
            try:
                m = self._mobile.ozet()
                mevcut = self._ayarlar_etiket.text()
                self._ayarlar_etiket.setText(
                    f"{mevcut}\n"
                    f"Mobile: motor={m.get('engine')} · "
                    f"primary={m.get('primary_mobile')} · "
                    f"çalışıyor={m.get('running')} · "
                    f"ağ={m.get('network_bound')}"
                )
            except Exception:
                mevcut = self._ayarlar_etiket.text()
                self._ayarlar_etiket.setText(
                    f"{mevcut}\nMobile bağlı (özet alınamadı)."
                )

        if self._sync is not None and hasattr(self._sync, "ozet"):
            try:
                s = self._sync.ozet()
                moduller = ", ".join(sorted((s.get("modules") or {}).keys())) or "-"
                self._senkron_etiket.setText(
                    f"Sync motor={s.get('engine')} · "
                    f"çalışıyor={s.get('running')} · "
                    f"modüller: {moduller}"
                )
                bulut = (s.get("modules") or {}).get("cloud") or {}
                self._bulut_etiket.setText(
                    f"Bulut yedek motor={bulut.get('engine', s.get('engine'))} · "
                    f"adet={bulut.get('count', bulut.get('backup_count', '?'))}"
                )
            except Exception:
                self._senkron_etiket.setText("Sync bağlı (özet alınamadı).")
                self._bulut_etiket.setText("Bulut yedek bağlı (özet alınamadı).")
        else:
            self._senkron_etiket.setText("Sync henüz bağlanmadı.")
            self._bulut_etiket.setText("Bulut yedek henüz bağlanmadı.")

    def _oturum_goster(
        self,
        oturum: EslestirmeGosterim,
        *,
        kaynak: str = "iskelet",
    ) -> None:
        self.model.son_oturum = oturum
        self._kod_etiket.setText(oturum.kod)
        self._qr_etiket.setText(oturum.qr_payload)
        self._ttl_etiket.setText(
            f"Geçerlilik: {oturum.ttl_saniye} sn · ONLINE ({kaynak})"
        )
        self._karekod_gorsel_ayarla(oturum.qr_payload)
        self.sayfa_goster(self.SAYFA_BAGLA)
        if self.cihaz_bagla_istedi is not None:
            self.cihaz_bagla_istedi.emit(oturum)

    def _karekod_gorsel_ayarla(self, payload: str) -> None:
        """QR yükünden görsel karekod üretir."""
        gorsel = getattr(self, "_qr_gorsel", None)
        if gorsel is None:
            return
        try:
            from gui.widgets.karekod import qr_pixmap

            pm = qr_pixmap(payload, piksel=200)
            if pm is not None and not pm.isNull():
                gorsel.setPixmap(pm)
                gorsel.setText("")
                return
        except Exception:
            pass
        gorsel.clear()
        gorsel.setText("QR kütüphanesi yok\n(pip install qrcode[pil])")

    async def _agdan_oturum_baslat(self) -> None:
        assert self._network is not None
        try:
            oturum = await self._network.eslestirme_baslat(PlatformTuru.WEB)
            gosterim = EslestirmeGosterim.agdan(
                oturum,
                ttl_saniye=self.model.ttl_saniye,
            )

            def _uygula() -> None:
                self._oturum_goster(gosterim, kaynak="network")

            self._ui(_uygula)
        except Exception as exc:
            def _hata() -> None:
                self._ttl_etiket.setText(f"Eşleştirme hatası: {exc}")
                self.sayfa_goster(self.SAYFA_BAGLA)

            self._ui(_hata)

    def sayfa_goster(self, indeks: int) -> None:
        self._yigin.setCurrentIndex(max(0, min(4, int(indeks))))
        if indeks == self.SAYFA_LISTE:
            self.liste_yenile()
        elif indeks in (
            self.SAYFA_SENKRON,
            self.SAYFA_BULUT,
            self.SAYFA_AYARLAR,
        ):
            self._ozet_sayfalarini_guncelle()

    def liste_yenile(self) -> None:
        self._liste.clear()
        bos = not self.model.cihazlar
        self._bos_etiket.setVisible(bos)
        self._liste.setVisible(not bos)
        for c in self.model.cihazlar:
            pil = f" · pil %{c.pil_yuzde}" if c.pil_yuzde is not None else ""
            metin = f"{c.ad}  [{c.platform.value}]  {c.durum.value}{pil}"
            item = QListWidgetItem(metin)
            self._liste.addItem(item)

    def cihaz_bagla(self) -> Optional[EslestirmeGosterim]:
        """Yeni eşleştirme oturumu üretir ve bağla sayfasını açar."""
        # Ağ bağlıysa gerçek NetworkYoneticisi oturumu (async)
        if self._network is not None and self._async_zamanla is not None:
            self._kod_etiket.setText("……")
            self._qr_etiket.setText("Oturum açılıyor…")
            self._ttl_etiket.setText("Network eşleştirme…")
            gorsel = getattr(self, "_qr_gorsel", None)
            if gorsel is not None:
                gorsel.clear()
                gorsel.setText("Karekod üretiliyor…")
            self.sayfa_goster(self.SAYFA_BAGLA)
            self._async_zamanla(self._agdan_oturum_baslat())
            return self.model.son_oturum

        oturum = self.model.oturum_baslat()
        self._oturum_goster(oturum, kaynak="iskelet")
        return oturum

    def _senkron(self) -> None:
        self.sayfa_goster(self.SAYFA_SENKRON)
        if self.senkron_istedi is not None:
            self.senkron_istedi.emit()

    def _bulut(self) -> None:
        self.sayfa_goster(self.SAYFA_BULUT)
        if self.bulut_istedi is not None:
            self.bulut_istedi.emit()

    def _ayarlar(self) -> None:
        self.sayfa_goster(self.SAYFA_AYARLAR)
        if self.ayarlar_istedi is not None:
            self.ayarlar_istedi.emit()

    def aktif_sayfa(self) -> int:
        return self._yigin.currentIndex()

    def son_kod(self) -> str:
        return self.model.son_oturum.kod if self.model.son_oturum else ""

    def durdur(self) -> None:
        """Bus aboneliklerini temizler (AnaPencere kapanışında)."""
        self.bus_coz()

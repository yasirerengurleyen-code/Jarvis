"""
gui/windows/ana_pencere.py
--------------------------
J.A.R.V.I.S. HUD ana pencere.

Düzen (referans HUD):
- Sol: saat · hava · sistem (CPU/RAM/DISK/BATARYA)
- Orta: Jarvis çekirdek + LIVE/PAUSE/CAM/SHUTDOWN
- Sağ: sohbet + cihaz
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPushButton,
        QStatusBar,
        QVBoxLayout,
        QWidget,
    )

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QMainWindow = object  # type: ignore[misc, assignment]
    Signal = None  # type: ignore[misc, assignment]

from gui.themes.stil import StilUretici
from gui.themes.tony_stark import TonyStarkTema
from gui.widgets.ai_animasyon import AiAnimasyonWidget
from gui.widgets.cihaz_paneli import CihazPaneli
from gui.widgets.hava_durumu import HavaDurumuWidget
from gui.widgets.marka_buton import MarkaButon
from gui.widgets.medya_kontrolleri import MedyaKontrolleri
from gui.widgets.mikrofon_animasyon import MikrofonAnimasyonWidget
from gui.widgets.saat_tarih import SaatTarihWidget
from gui.widgets.sohbet_paneli import SohbetPaneli
from gui.widgets.sistem_metrikleri import SistemMetrikleriWidget
from gui.windows.ayarlar_dialog import AyarlarDialog


def pencere_ayarlari(gui_bolumu: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """config.gui.window + proje adından pencere ayarları."""
    bolum = dict(gui_bolumu or {})
    win = bolum.get("window") if isinstance(bolum.get("window"), dict) else {}
    return {
        "width": int(win.get("width", 1280)),
        "height": int(win.get("height", 780)),
        "frameless": bool(win.get("frameless", False)),
        "always_on_top": bool(win.get("always_on_top", False)),
        "start_maximized": bool(win.get("start_maximized", False)),
        "start_fullscreen": bool(win.get("start_fullscreen", True)),
        "theme": str(bolum.get("theme") or "tony_stark"),
    }


class AnaPencere(QMainWindow):  # type: ignore[misc, valid-type]
    """J.A.R.V.I.S. HUD ana pencere."""

    if _PYSIDE_VAR:
        mesaj_gonderildi = Signal(str)
        kapanis_istedi = Signal()
        ses_notu_istedi = Signal()
    else:  # pragma: no cover
        mesaj_gonderildi = None  # type: ignore[assignment]
        kapanis_istedi = None  # type: ignore[assignment]
        ses_notu_istedi = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        tema: Optional[TonyStarkTema] = None,
        ayar_yonetici: Any = None,
        bus: Any = None,
        baslik: Optional[str] = None,
        parent: Any = None,
        hava_zorla_sahte: bool = False,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)

        self._ayar = ayar_yonetici
        self._bus = bus
        self.tema = tema or TonyStarkTema.ayarlardan(ayar_yonetici)

        gui_bolum: dict[str, Any] = {}
        proje_adi = "WhiteCore AI"
        asistan = "J.A.R.V.I.S."
        if ayar_yonetici is not None:
            try:
                if not getattr(ayar_yonetici, "yuklendi", False):
                    ayar_yonetici.yukle()
                g = ayar_yonetici.bolum("gui")
                gui_bolum = g if isinstance(g, dict) else {}
                proje_adi = str(ayar_yonetici.al("project.name", proje_adi))
                asistan = str(ayar_yonetici.al("assistant.name", asistan))
            except Exception:
                pass
        else:
            try:
                from config.ayarlar import ayarlar as global_ayarlar

                if not global_ayarlar.yuklendi:
                    global_ayarlar.yukle()
                self._ayar = global_ayarlar
                g = global_ayarlar.bolum("gui")
                gui_bolum = g if isinstance(g, dict) else {}
                proje_adi = str(global_ayarlar.al("project.name", proje_adi))
                asistan = str(global_ayarlar.al("assistant.name", asistan))
                if tema is None:
                    self.tema = TonyStarkTema.ayarlardan(global_ayarlar)
            except Exception:
                pass

        self._win = pencere_ayarlari(gui_bolum)
        self.setWindowTitle(baslik or f"{proje_adi} — {asistan}")
        self.resize(self._win["width"], self._win["height"])
        if self._win["frameless"]:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        if self._win["always_on_top"]:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self._kur_ui(hava_zorla_sahte=hava_zorla_sahte)
        self.stil_uygula()

        if bus is not None:
            self.bus_bagla(bus)

        # Tam ekran / maximize GuiYoneticisi.show sonrası da uygulanır
        self._fullscreen_hedef = bool(self._win.get("start_fullscreen"))
        self._maximize_hedef = bool(self._win.get("start_maximized"))
        self.kapandi = False

    def baslangic_gorunumu(self) -> None:
        """İlk gösterimde tam ekran veya maximize uygular."""
        if self._fullscreen_hedef:
            self.showFullScreen()
        elif self._maximize_hedef:
            self.showMaximized()

    def tam_ekran_degistir(self) -> None:
        """F11: tam ekran aç/kapa."""
        if self.isFullScreen():
            self.showNormal()
            self.resize(self._win["width"], self._win["height"])
        else:
            self.showFullScreen()

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        try:
            from PySide6.QtCore import Qt as _Qt

            if event.key() == _Qt.Key.Key_F11:
                self.tam_ekran_degistir()
                return
            if event.key() == _Qt.Key.Key_Escape and self.isFullScreen():
                self.showNormal()
                self.resize(self._win["width"], self._win["height"])
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def _kur_ui(self, *, hava_zorla_sahte: bool = False) -> None:
        merkez = QWidget()
        self.setCentralWidget(merkez)

        kok = QVBoxLayout(merkez)
        kok.setContentsMargins(16, 12, 16, 10)
        kok.setSpacing(10)

        # --- Üst: dikdörtgen marka · karekod · ONLINE ---
        ust = QHBoxLayout()
        self.marka = MarkaButon(genislik=360, yukseklik=78)
        self.marka.tiklandi.connect(self.ayarlari_ac)

        self.btn_karekod = QPushButton("⬛ KAREKOD")
        self.btn_karekod.setObjectName("KarekodBtn")
        self.btn_karekod.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_karekod.setToolTip("Bağlantı için karekod oluştur")
        self.btn_karekod.clicked.connect(self.karekod_ac)

        self.online = QLabel("● ONLINE")
        self.online.setObjectName("OnlineRozet")
        self.online_ayarla(True, detay="sistem hazır")

        ust.addWidget(self.marka, alignment=Qt.AlignmentFlag.AlignLeft)
        ust.addStretch(1)
        ust.addWidget(self.btn_karekod, alignment=Qt.AlignmentFlag.AlignTop)
        ust.addWidget(self.online, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        kok.addLayout(ust)

        # --- Ana üç kolon ---
        govde = QHBoxLayout()
        govde.setSpacing(14)

        # Sol
        sol = QVBoxLayout()
        sol.setSpacing(10)
        self.saat = SaatTarihWidget()
        self.hava = HavaDurumuWidget(zorla_sahte=hava_zorla_sahte)
        self.metrikler = SistemMetrikleriWidget(cpu_aralik=0.05)
        sol.addWidget(self.saat)
        sol.addWidget(self.hava)
        sol.addWidget(self.metrikler, stretch=1)

        # Orta: Jarvis
        orta = QVBoxLayout()
        orta.setSpacing(12)
        orta.addStretch(1)
        self.ai = AiAnimasyonWidget(boyut=380)
        # Gizli mikrofon animasyonu — bus olayları için (görünmez)
        self.mikrofon = MikrofonAnimasyonWidget(boyut=40)
        self.mikrofon.hide()
        orta.addWidget(self.ai, alignment=Qt.AlignmentFlag.AlignHCenter)
        orta.addWidget(self.mikrofon)
        self.medya = MedyaKontrolleri()
        self.medya.kapat_istedi.connect(self.close)
        orta.addWidget(self.medya)
        orta.addStretch(1)

        # Sağ: sohbet + cihaz
        sag = QVBoxLayout()
        sag.setSpacing(10)
        self.sohbet = SohbetPaneli()
        self.sohbet.mesaj_gonderildi.connect(self._mesaj_ilet)
        self.sohbet.ses_notu_istedi.connect(self._ses_notu_iste)
        greeting = "SYS: JARVIS hazır. Dinliyorum…"
        if self._ayar is not None:
            try:
                greeting = str(
                    self._ayar.al(
                        "assistant.greeting",
                        "Sistemler çevrimiçi. Size nasıl yardımcı olabilirim?",
                    )
                )
            except Exception:
                pass
        self.sohbet.sistem_mesaji_ekle(greeting)
        self.cihazlar = CihazPaneli()
        sag.addWidget(self.sohbet, stretch=3)
        sag.addWidget(self.cihazlar, stretch=2)

        govde.addLayout(sol, stretch=2)
        govde.addLayout(orta, stretch=3)
        govde.addLayout(sag, stretch=2)
        kok.addLayout(govde, stretch=1)

        durum = QStatusBar()
        self.setStatusBar(durum)
        durum.showMessage(
            "JARVIS HUD  |  F11 tam ekran  |  ESC pencere  |  LIVE mic · PAUSE ses · CAM"
        )

    def stil_uygula(self) -> None:
        stil = StilUretici(self.tema).qss()
        self.setStyleSheet(stil)

    def bus_bagla(self, bus: Any) -> None:
        self._bus = bus
        self.mikrofon.bus_bagla(bus)
        self.ai.bus_bagla(bus)

    def bus_coz(self) -> None:
        self.mikrofon.bus_coz()
        self.ai.bus_coz()
        cihaz = getattr(self, "cihazlar", None)
        if cihaz is not None and hasattr(cihaz, "bus_coz"):
            cihaz.bus_coz()

    def _mesaj_ilet(self, metin: str) -> None:
        if self.mesaj_gonderildi is not None:
            self.mesaj_gonderildi.emit(metin)

    def asistan_yaniti_goster(self, metin: str) -> None:
        self.sohbet.asistan_mesaji_ekle(metin)

    def durum_mesaji(self, metin: str, sure_ms: int = 4000) -> None:
        if self.statusBar():
            self.statusBar().showMessage(metin, sure_ms)

    def ayarlari_ac(self) -> None:
        """Kare marka / Voice Core → Ayarlar (masaüstünde API key + konuşurken)."""
        # Konuşurken ayar kapalıysa ve AI konuşuyorsa engelle
        try:
            izin = True
            if self._ayar is not None:
                izin = bool(
                    self._ayar.al("voice.speaking.settings_while_speaking", True)
                )
            ai = getattr(self, "ai", None)
            if (
                not izin
                and ai is not None
                and getattr(ai.model, "durum", None) is not None
            ):
                from gui.widgets.ai_animasyon import AiDurum

                if ai.model.durum == AiDurum.KONUSUYOR:
                    self.durum_mesaji("Konuşurken ayarlar kapalı")
                    return
        except Exception:
            pass

        dlg = AyarlarDialog(self, ayar_yonetici=self._ayar)
        if dlg.exec():
            self.durum_mesaji("Ayarlar kaydedildi")
            medya = getattr(self, "medya", None)
            if medya is not None and hasattr(medya, "durumlari_ayarla"):
                medya.durumlari_ayarla(
                    ses=bool(dlg.chk_ses.isChecked()),
                    mikrofon=bool(dlg.chk_mikrofon.isChecked()),
                )
                if hasattr(medya, "ses_degisti") and medya.ses_degisti is not None:
                    medya.ses_degisti.emit(bool(dlg.chk_ses.isChecked()))
                if hasattr(medya, "mikrofon_degisti") and medya.mikrofon_degisti is not None:
                    medya.mikrofon_degisti.emit(bool(dlg.chk_mikrofon.isChecked()))

    def _ses_notu_iste(self) -> None:
        if self.ses_notu_istedi is not None:
            self.ses_notu_istedi.emit()

    def online_ayarla(self, online: bool, *, detay: str = "") -> None:
        """Üst sağ ONLINE rozetini günceller."""
        rozet = getattr(self, "online", None)
        if rozet is None:
            return
        if online:
            rozet.setText("● ONLINE" + (f"  {detay}" if detay else ""))
            rozet.setStyleSheet(
                "color:#00FF88; border:1px solid #00A894; padding:6px 12px; "
                "border-radius:4px; font-weight:700; background:transparent;"
            )
        else:
            rozet.setText("○ OFFLINE" + (f"  {detay}" if detay else ""))
            rozet.setStyleSheet(
                "color:#FF3B4A; border:1px solid #FF3B4A; padding:6px 12px; "
                "border-radius:4px; font-weight:700; background:transparent;"
            )

    def karekod_ac(self) -> None:
        """Cihaz paneli → karekod / eşleştirme oturumu."""
        cihaz = getattr(self, "cihazlar", None)
        if cihaz is None:
            self.durum_mesaji("Cihaz paneli yok")
            return
        self.durum_mesaji("Karekod üretiliyor…")
        if hasattr(cihaz, "cihaz_bagla"):
            cihaz.cihaz_bagla()
        self.online_ayarla(True, detay="eşleştirme açık")

    def kapat_hazirlik(self) -> None:
        for w in (
            getattr(self, "saat", None),
            getattr(self, "metrikler", None),
            getattr(self, "hava", None),
            getattr(self, "mikrofon", None),
            getattr(self, "ai", None),
            getattr(self, "cihazlar", None),
        ):
            if w is not None and hasattr(w, "durdur"):
                w.durdur()
        self.bus_coz()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.kapandi = True
        if self.kapanis_istedi is not None:
            self.kapanis_istedi.emit()
        self.kapat_hazirlik()
        super().closeEvent(event)

"""
gui/widgets/saat_tarih.py
-------------------------
Saat ve tarih gösterge widget'ı.

Görev:
- Canlı saat / tarih metni üretmek (TR biçim)
- config.gui.widgets.show_clock / show_date bayraklarını uygulamak
- PySide6 ile neon stil etiketler göstermek
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    QLabel = object  # type: ignore[misc, assignment]


# Türkçe ay / gün adları (locale bağımsız)
_AYLAR_TR = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
_GUNLER_TR = (
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)


def saat_metni(an: Optional[datetime] = None, saniye: bool = True) -> str:
    """HH:MM veya HH:MM:SS."""
    dt = an or datetime.now()
    if saniye:
        return dt.strftime("%H:%M:%S")
    return dt.strftime("%H:%M")


def tarih_metni(an: Optional[datetime] = None, dil: str = "tr") -> str:
    """Örn: Perşembe, 6 Ağustos 2026."""
    dt = an or datetime.now()
    if dil.lower().startswith("tr"):
        gun = _GUNLER_TR[dt.weekday()]
        ay = _AYLAR_TR[dt.month - 1]
        return f"{gun}, {dt.day} {ay} {dt.year}"
    return dt.strftime("%A, %d %B %Y")


def simdi_timezone(tz_adi: str = "Europe/Istanbul") -> datetime:
    """Belirtilen timezone için şimdiki zaman."""
    try:
        return datetime.now(ZoneInfo(tz_adi))
    except Exception:
        return datetime.now().astimezone()


class SaatTarihModel:
    """Widget'tan bağımsız saat/tarih durumu."""

    def __init__(
        self,
        *,
        saat_goster: bool = True,
        tarih_goster: bool = True,
        saniye_goster: bool = True,
        dil: str = "tr",
        timezone: str = "Europe/Istanbul",
    ) -> None:
        self.saat_goster = saat_goster
        self.tarih_goster = tarih_goster
        self.saniye_goster = saniye_goster
        self.dil = dil
        self.timezone = timezone

    @classmethod
    def from_config(cls, gui_bolumu: Optional[dict[str, Any]] = None) -> "SaatTarihModel":
        bolum = dict(gui_bolumu or {})
        widgets = bolum.get("widgets") if isinstance(bolum.get("widgets"), dict) else {}
        dil = str(bolum.get("language") or "tr")
        return cls(
            saat_goster=bool(widgets.get("show_clock", True)),
            tarih_goster=bool(widgets.get("show_date", True)),
            dil=dil,
        )

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "SaatTarihModel":
        if ayar_yonetici is None:
            try:
                from config.ayarlar import ayarlar as global_ayarlar

                ayar_yonetici = global_ayarlar
            except Exception:
                return cls()
        try:
            if not getattr(ayar_yonetici, "yuklendi", False):
                ayar_yonetici.yukle()
            gui = ayar_yonetici.bolum("gui")
            tz = str(ayar_yonetici.al("project.timezone", "Europe/Istanbul"))
            model = cls.from_config(gui if isinstance(gui, dict) else {})
            model.timezone = tz
            return model
        except Exception:
            return cls()

    def an(self) -> datetime:
        return simdi_timezone(self.timezone)

    def saat(self) -> str:
        if not self.saat_goster:
            return ""
        return saat_metni(self.an(), saniye=self.saniye_goster)

    def tarih(self) -> str:
        if not self.tarih_goster:
            return ""
        return tarih_metni(self.an(), dil=self.dil)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock": self.saat(),
            "date": self.tarih(),
            "show_clock": self.saat_goster,
            "show_date": self.tarih_goster,
            "timezone": self.timezone,
        }


class SaatTarihWidget(QFrame):  # type: ignore[misc, valid-type]
    """
    Canlı saat + tarih paneli.

    objectName: CamPanel (tema QSS ile uyumlu)
    """

    def __init__(
        self,
        model: Optional[SaatTarihModel] = None,
        parent: Any = None,
        guncelleme_ms: int = 1000,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.model = model or SaatTarihModel.ayarlardan()
        self.setObjectName("HudPanel")
        self.setProperty("cam", True)

        self._ust = QLabel("TIME")
        self._ust.setObjectName("HudBaslik")

        self._saat_etiket = QLabel("")
        self._saat_etiket.setObjectName("HudBuyuk")
        self._saat_etiket.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._tarih_etiket = QLabel("")
        self._tarih_etiket.setObjectName("AltBaslik")
        self._tarih_etiket.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._gun_etiket = QLabel("")
        self._gun_etiket.setObjectName("NeonMetrik")
        self._gun_etiket.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(14, 12, 14, 12)
        yerlesim.setSpacing(2)
        yerlesim.addWidget(self._ust)
        yerlesim.addWidget(self._saat_etiket)
        yerlesim.addWidget(self._tarih_etiket)
        yerlesim.addWidget(self._gun_etiket)

        self._saat_etiket.setVisible(self.model.saat_goster)
        self._tarih_etiket.setVisible(self.model.tarih_goster)

        self._timer = QTimer(self)
        self._timer.setInterval(max(200, int(guncelleme_ms)))
        self._timer.timeout.connect(self.yenile)
        self.yenile()
        self._timer.start()

    def yenile(self) -> None:
        """Etiketleri günceller."""
        an = self.model.an()
        self._saat_etiket.setText(saat_metni(an, saniye=False))
        if self.model.saniye_goster:
            self._saat_etiket.setText(
                f"{saat_metni(an, saniye=False)}  "
                f"<span style='font-size:18px;opacity:0.7'>:{an.strftime('%S')}</span>"
            )
            # QLabel rich text
            self._saat_etiket.setTextFormat(Qt.TextFormat.RichText)
            self._saat_etiket.setText(
                f"{an.strftime('%H:%M')}<span style='font-size:20px; color:#00A894;'>:{an.strftime('%S')}</span>"
            )
        else:
            self._saat_etiket.setText(self.model.saat())
        ay_en = (
            "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
            "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
        )
        gun_en = (
            "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
            "FRIDAY", "SATURDAY", "SUNDAY",
        )
        self._tarih_etiket.setText(
            f"{an.day:02d} {ay_en[an.month - 1]} {an.year}"
        )
        self._gun_etiket.setText(gun_en[an.weekday()])
        self._saat_etiket.setVisible(self.model.saat_goster)
        self._tarih_etiket.setVisible(self.model.tarih_goster)
        self._gun_etiket.setVisible(self.model.tarih_goster)

    def durdur(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()

    def baslat(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.start()
            self.yenile()

    @property
    def saat_metni_gosterilen(self) -> str:
        return self._saat_etiket.text()

    @property
    def tarih_metni_gosterilen(self) -> str:
        return self._tarih_etiket.text()

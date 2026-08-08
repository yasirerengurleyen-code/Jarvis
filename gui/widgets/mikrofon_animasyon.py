"""
gui/widgets/mikrofon_animasyon.py
---------------------------------
Mikrofon / dinleme neon animasyon widget'ı.

Görev:
- Wake / dinleme / seviye durumlarını görsel olarak göstermek
- config.gui.effects.microphone_animation bayrağına uymak
- EventBus ses olaylarına bağlanabilmek (isteğe bağlı)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

try:
    from PySide6.QtCore import QPointF, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
    from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    Signal = None  # type: ignore[misc, assignment]


class MikrofonDurum(str, Enum):
    """Mikrofon görsel durumu."""

    KAPALI = "kapali"
    BEKLEMEDE = "beklemede"  # wake word bekleniyor
    DINLIYOR = "dinliyor"
    ISIK = "isik"  # kısa flaş (wake tetik)


def pulse_olcek(faz: float, durum: MikrofonDurum, seviye: float = 0.0) -> float:
    """
    Animasyon fazı (0..2π) ve duruma göre halka ölçeği (0.55..1.35).
    Saf fonksiyon — birim test için.
    """
    seviye = max(0.0, min(1.0, float(seviye)))
    if durum == MikrofonDurum.KAPALI:
        return 0.55
    if durum == MikrofonDurum.BEKLEMEDE:
        return 0.75 + 0.08 * math.sin(faz)
    if durum == MikrofonDurum.ISIK:
        return 1.05 + 0.25 * abs(math.sin(faz * 2))
    # DINLIYOR
    return 0.85 + 0.35 * seviye + 0.12 * math.sin(faz * 1.5)


def durum_etiketi(durum: MikrofonDurum) -> str:
    return {
        MikrofonDurum.KAPALI: "Mikrofon kapalı",
        MikrofonDurum.BEKLEMEDE: "Jarvis dinliyor…",
        MikrofonDurum.DINLIYOR: "Dinleniyor",
        MikrofonDurum.ISIK: "Wake!",
    }.get(durum, durum.value)


@dataclass
class MikrofonAnimasyonModel:
    """Animasyon durumu (Qt bağımsız)."""

    durum: MikrofonDurum = MikrofonDurum.BEKLEMEDE
    seviye: float = 0.0  # 0..1 ses enerjisi
    animasyon_acik: bool = True
    faz: float = 0.0
    accent: str = "#00FF88"
    accent_dim: str = "#00C86A"
    background: str = "#0A0A0A"

    @classmethod
    def from_config(cls, gui_bolumu: Optional[dict[str, Any]] = None) -> "MikrofonAnimasyonModel":
        bolum = dict(gui_bolumu or {})
        efekt = bolum.get("effects") if isinstance(bolum.get("effects"), dict) else {}
        renk = bolum.get("colors") if isinstance(bolum.get("colors"), dict) else {}
        return cls(
            animasyon_acik=bool(efekt.get("microphone_animation", True)),
            accent=str(renk.get("accent") or "#00FF88"),
            accent_dim=str(renk.get("accent_dim") or "#00C86A"),
            background=str(renk.get("background") or "#0A0A0A"),
        )

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "MikrofonAnimasyonModel":
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
            return cls.from_config(gui if isinstance(gui, dict) else {})
        except Exception:
            return cls()

    def seviye_ayarla(self, deger: float) -> None:
        self.seviye = max(0.0, min(1.0, float(deger)))

    def durum_ayarla(self, durum: MikrofonDurum | str) -> None:
        if isinstance(durum, str):
            self.durum = MikrofonDurum(durum)
        else:
            self.durum = durum

    def adim(self, delta_faz: float = 0.18) -> float:
        """Fazı ilerletir; güncel ölçeği döner."""
        if not self.animasyon_acik or self.durum == MikrofonDurum.KAPALI:
            self.faz = 0.0
            return pulse_olcek(0.0, self.durum, self.seviye)
        self.faz = (self.faz + delta_faz) % (math.pi * 2)
        return pulse_olcek(self.faz, self.durum, self.seviye)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.durum.value,
            "level": self.seviye,
            "animation": self.animasyon_acik,
            "scale": pulse_olcek(self.faz, self.durum, self.seviye),
            "label": durum_etiketi(self.durum),
        }


class MikrofonAnimasyonWidget(QFrame):  # type: ignore[misc, valid-type]
    """
    Neon mikrofon halkası.

    Sinyaller:
    - tiklandi: kullanıcı panele tıkladığında
    """

    if _PYSIDE_VAR:
        tiklandi = Signal()
    else:  # pragma: no cover
        tiklandi = None  # type: ignore[assignment]

    def __init__(
        self,
        model: Optional[MikrofonAnimasyonModel] = None,
        parent: Any = None,
        *,
        boyut: int = 140,
        fps: int = 30,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.model = model or MikrofonAnimasyonModel.ayarlardan()
        self._boyut = max(80, int(boyut))
        self._olcek = 0.8
        self._bus: Any = None
        self._bus_aboneler: list[tuple[str, str]] = []  # (olay_adi, handler_id)

        self.setObjectName("CamPanel")
        self.setProperty("cam", True)
        self.setFixedSize(self._boyut + 24, self._boyut + 48)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._etiket = QLabel(durum_etiketi(self.model.durum))
        self._etiket.setObjectName("AltBaslik")
        self._etiket.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(8, 8, 8, 8)
        yerlesim.addStretch(1)
        yerlesim.addWidget(self._etiket)

        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(1000 / max(1, fps))))
        self._timer.timeout.connect(self._tik)
        if self.model.animasyon_acik:
            self._timer.start()
        self._tik()

    def _tik(self) -> None:
        self._olcek = self.model.adim()
        self._etiket.setText(durum_etiketi(self.model.durum))
        self.update()

    def durum_ayarla(self, durum: MikrofonDurum | str) -> None:
        self.model.durum_ayarla(durum)
        self._etiket.setText(durum_etiketi(self.model.durum))
        self.update()

    def seviye_ayarla(self, deger: float) -> None:
        self.model.seviye_ayarla(deger)
        if self.model.durum == MikrofonDurum.BEKLEMEDE and deger > 0.05:
            self.model.durum = MikrofonDurum.DINLIYOR
        self.update()

    def wake_flas(self, sure_ms: int = 900) -> None:
        """Kısa wake word flaşı, sonra beklemede'ye döner."""
        onceki = self.model.durum
        self.durum_ayarla(MikrofonDurum.ISIK)

        def geri() -> None:
            if self.model.durum == MikrofonDurum.ISIK:
                self.durum_ayarla(
                    onceki if onceki != MikrofonDurum.ISIK else MikrofonDurum.BEKLEMEDE
                )

        QTimer.singleShot(max(200, sure_ms), geri)

    def bus_bagla(self, bus: Any) -> None:
        """EventBus ses olaylarına abone olur."""
        self.bus_coz()
        if bus is None:
            return
        self._bus = bus

        def _wake(_event: Any = None) -> None:
            self.wake_flas()

        def _dinle_bas(_event: Any = None) -> None:
            self.durum_ayarla(MikrofonDurum.DINLIYOR)

        def _dinle_bit(_event: Any = None) -> None:
            self.durum_ayarla(MikrofonDurum.BEKLEMEDE)
            self.seviye_ayarla(0.0)

        from core.events import (
            OLAY_DINLEME_BASLADI,
            OLAY_DINLEME_BITTI,
            OLAY_WAKE_WORD,
        )

        for ad, fn in (
            (OLAY_WAKE_WORD, _wake),
            (OLAY_DINLEME_BASLADI, _dinle_bas),
            (OLAY_DINLEME_BITTI, _dinle_bit),
        ):
            hid = bus.subscribe(ad, fn)
            self._bus_aboneler.append((ad, hid))

    def bus_coz(self) -> None:
        bus = self._bus
        if bus is not None:
            for ad, hid in self._bus_aboneler:
                try:
                    bus.unsubscribe(ad, hid)
                except Exception:
                    pass
        self._bus_aboneler.clear()
        self._bus = None

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if self.tiklandi is not None:
            self.tiklandi.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = (self.height() - 28) / 2
        yari_cap = (self._boyut / 2) * self._olcek

        accent = QColor(self.model.accent)
        dim = QColor(self.model.accent_dim)

        # Dış glow
        if self.model.animasyon_acik and self.model.durum != MikrofonDurum.KAPALI:
            grad = QRadialGradient(QPointF(cx, cy), yari_cap * 1.35)
            g = QColor(accent)
            g.setAlpha(55)
            grad.setColorAt(0.0, g)
            g2 = QColor(accent)
            g2.setAlpha(0)
            grad.setColorAt(1.0, g2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawEllipse(QPointF(cx, cy), yari_cap * 1.35, yari_cap * 1.35)

        # Halkalar
        for i, carp in enumerate((1.0, 0.72, 0.45)):
            pen = QPen(accent if i == 0 else dim)
            pen.setWidth(2 if i == 0 else 1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = yari_cap * carp
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Merkez dolgu
        merkez = QColor(dim)
        merkez.setAlpha(180 if self.model.durum != MikrofonDurum.KAPALI else 80)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(merkez)
        painter.drawEllipse(QPointF(cx, cy), yari_cap * 0.22, yari_cap * 0.22)

        painter.end()

    def durdur(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()
        self.bus_coz()

    def baslat(self) -> None:
        if self.model.animasyon_acik and getattr(self, "_timer", None) is not None:
            self._timer.start()
            self._tik()

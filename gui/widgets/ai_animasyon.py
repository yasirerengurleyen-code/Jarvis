"""
gui/widgets/ai_animasyon.py
---------------------------
Merkez J.A.R.V.I.S. HUD animasyonu.

Renk kuralları:
- Yeşil: boşta / dinleme / kullanıcı konuşuyor
- Mavi: asistan (TTS) konuşuyor
- Kırmızı: hata
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
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


class AiDurum(str, Enum):
    """AI görsel durumu."""

    BOS = "bos"
    DINLIYOR = "dinliyor"
    DUSUNUYOR = "dusunuyor"
    YANIT = "yanit"
    KONUSUYOR = "konusuyor"  # TTS — mavi
    HATA = "hata"


# Durum → renk (hex)
_RENK_YESIL = "#00FF88"
_RENK_MAVI = "#3BA7FF"
_RENK_KIRMIZI = "#FF3B4A"
_RENK_ALTIN = "#FFC857"  # düşünürken (referans HUD)


def durum_rengi(durum: AiDurum) -> str:
    """HUD durum rengi (yeşil dinleme · mavi konuşma · altın düşünme · kırmızı hata)."""
    if durum == AiDurum.HATA:
        return _RENK_KIRMIZI
    if durum == AiDurum.KONUSUYOR:
        return _RENK_MAVI
    if durum == AiDurum.DUSUNUYOR:
        return _RENK_ALTIN
    # boş / dinleme / yanıt / kullanıcı → yeşil
    return _RENK_YESIL


def ai_halka_acisi(faz: float, durum: AiDurum, indeks: int) -> float:
    yon = 1.0 if indeks % 2 == 0 else -1.0
    hiz = {
        AiDurum.BOS: 0.35,
        AiDurum.DINLIYOR: 0.9,
        AiDurum.DUSUNUYOR: 1.6,
        AiDurum.YANIT: 1.1,
        AiDurum.KONUSUYOR: 1.3,
        AiDurum.HATA: 0.25,
    }.get(durum, 0.5)
    offset = indeks * (math.pi * 2 / 3)
    return (faz * hiz * yon) + offset


def ai_parlaklik(faz: float, durum: AiDurum) -> float:
    if durum == AiDurum.BOS:
        return 0.45 + 0.15 * math.sin(faz)
    if durum == AiDurum.HATA:
        return 0.45 + 0.45 * abs(math.sin(faz * 3))
    if durum == AiDurum.DUSUNUYOR:
        return 0.55 + 0.4 * abs(math.sin(faz * 2))
    if durum == AiDurum.DINLIYOR:
        return 0.6 + 0.35 * abs(math.sin(faz * 2.2))
    if durum == AiDurum.KONUSUYOR:
        return 0.7 + 0.25 * abs(math.sin(faz * 1.8))
    return 0.65 + 0.3 * abs(math.sin(faz * 1.4))


def durum_etiketi(durum: AiDurum) -> str:
    return {
        AiDurum.BOS: "● Dinleniyor",
        AiDurum.DINLIYOR: "● Dinleniyor",
        AiDurum.DUSUNUYOR: "● Düşünüyor",
        AiDurum.YANIT: "● Yanıt hazır",
        AiDurum.KONUSUYOR: "● Konuşuyor",
        AiDurum.HATA: "● Hata",
    }.get(durum, durum.value)


@dataclass
class AiAnimasyonModel:
    """AI animasyon durumu (Qt bağımsız)."""

    durum: AiDurum = AiDurum.BOS
    animasyon_acik: bool = True
    faz: float = 0.0
    mesaj: str = ""
    accent: str = _RENK_YESIL
    accent_dim: str = "#00C86A"
    speak: str = _RENK_MAVI
    danger: str = _RENK_KIRMIZI
    text: str = "#D8FFF6"
    parcaciklar: list[tuple[float, float, float]] = field(default_factory=list)

    @classmethod
    def from_config(cls, gui_bolumu: Optional[dict[str, Any]] = None) -> "AiAnimasyonModel":
        bolum = dict(gui_bolumu or {})
        efekt = bolum.get("effects") if isinstance(bolum.get("effects"), dict) else {}
        renk = bolum.get("colors") if isinstance(bolum.get("colors"), dict) else {}
        return cls(
            animasyon_acik=bool(efekt.get("ai_animation", True)),
            accent=str(renk.get("accent") or _RENK_YESIL),
            accent_dim=str(renk.get("accent_dim") or "#00A894"),
            danger=str(renk.get("danger") or _RENK_KIRMIZI),
            text=str(renk.get("text") or "#D8FFF6"),
        )

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "AiAnimasyonModel":
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

    def durum_ayarla(self, durum: AiDurum | str, mesaj: str = "") -> None:
        if isinstance(durum, str):
            self.durum = AiDurum(durum)
        else:
            self.durum = durum
        if mesaj:
            self.mesaj = mesaj

    def aktif_renk(self) -> str:
        return durum_rengi(self.durum)

    def adim(self, delta_faz: float = 0.16) -> float:
        if not self.animasyon_acik:
            return ai_parlaklik(self.faz, self.durum)
        carp = 0.45 if self.durum == AiDurum.BOS else 1.0
        self.faz = (self.faz + delta_faz * carp) % (math.pi * 2)
        if not self.parcaciklar:
            rnd = random.Random(42)
            self.parcaciklar = [
                (rnd.uniform(0, math.pi * 2), rnd.uniform(0.08, 0.92), rnd.uniform(0.6, 1.4))
                for _ in range(48)
            ]
        return ai_parlaklik(self.faz, self.durum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.durum.value,
            "animation": self.animasyon_acik,
            "brightness": ai_parlaklik(self.faz, self.durum),
            "color": self.aktif_renk(),
            "label": durum_etiketi(self.durum),
            "message": self.mesaj,
        }


class AiAnimasyonWidget(QFrame):  # type: ignore[misc, valid-type]
    """Merkez parçacık + halka Jarvis göstergesi."""

    if _PYSIDE_VAR:
        tiklandi = Signal()
    else:  # pragma: no cover
        tiklandi = None  # type: ignore[assignment]

    def __init__(
        self,
        model: Optional[AiAnimasyonModel] = None,
        parent: Any = None,
        *,
        boyut: int = 280,
        fps: int = 30,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.model = model or AiAnimasyonModel.ayarlardan()
        self._boyut = max(120, int(boyut))
        self._parlaklik = 0.5
        self._bus: Any = None
        self._bus_aboneler: list[tuple[str, str]] = []

        self.setObjectName("JarvisCekirdek")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self._boyut + 40, self._boyut + 72)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._baslik = QLabel("J.A.R.V.I.S.")
        self._baslik.setObjectName("Baslik")
        self._baslik.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._etiket = QLabel(durum_etiketi(self.model.durum))
        self._etiket.setObjectName("JarvisDurum")
        self._etiket.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(8, 8, 8, 8)
        yerlesim.addStretch(1)
        yerlesim.addWidget(self._baslik)
        yerlesim.addWidget(self._etiket)

        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(1000 / max(1, fps))))
        self._timer.timeout.connect(self._tik)
        if self.model.animasyon_acik:
            self._timer.start()
        self._tik()

    def _tik(self) -> None:
        self._parlaklik = self.model.adim()
        metin = durum_etiketi(self.model.durum)
        if self.model.mesaj and self.model.durum == AiDurum.HATA:
            metin = f"● {self.model.mesaj}"
        self._etiket.setText(metin)
        renk = self.model.aktif_renk()
        self._etiket.setStyleSheet(f"color: {renk}; background: transparent; font-weight: 600;")
        self._baslik.setStyleSheet(
            f"color: {renk}; background: transparent; font-size: 18px; font-weight: 700;"
        )
        self.update()

    def durum_ayarla(self, durum: AiDurum | str, mesaj: str = "") -> None:
        self.model.durum_ayarla(durum, mesaj=mesaj)
        self._tik()

    def dusunmeye_basla(self) -> None:
        self.durum_ayarla(AiDurum.DUSUNUYOR)

    def yanit_hazir(self, sure_ms: int = 1200) -> None:
        self.durum_ayarla(AiDurum.YANIT)

        def geri() -> None:
            if self.model.durum == AiDurum.YANIT:
                self.durum_ayarla(AiDurum.BOS)

        QTimer.singleShot(max(200, sure_ms), geri)

    def bus_bagla(self, bus: Any) -> None:
        self.bus_coz()
        if bus is None:
            return
        self._bus = bus

        def _dusun(_event: Any = None) -> None:
            self.dusunmeye_basla()

        def _yanit(_event: Any = None) -> None:
            self.yanit_hazir()

        def _tts_bas(_event: Any = None) -> None:
            self.durum_ayarla(AiDurum.KONUSUYOR)

        def _tts_bit(_event: Any = None) -> None:
            self.durum_ayarla(AiDurum.BOS)

        def _dinle_bas(_event: Any = None) -> None:
            self.durum_ayarla(AiDurum.DINLIYOR)

        def _dinle_bit(_event: Any = None) -> None:
            if self.model.durum == AiDurum.DINLIYOR:
                self.durum_ayarla(AiDurum.BOS)

        def _hata(event: Any = None) -> None:
            mesaj = ""
            if event is not None and getattr(event, "veri", None):
                mesaj = str(event.veri.get("mesaj") or event.veri.get("hata") or "")
            self.durum_ayarla(AiDurum.HATA, mesaj=mesaj or "Hata")

        from core.events import (
            OLAY_DINLEME_BASLADI,
            OLAY_DINLEME_BITTI,
            OLAY_DUSUNME_BASLADI,
            OLAY_HATA,
            OLAY_TTS_BASLADI,
            OLAY_TTS_BITTI,
            OLAY_YANIT_HAZIR,
        )

        for ad, fn in (
            (OLAY_DUSUNME_BASLADI, _dusun),
            (OLAY_YANIT_HAZIR, _yanit),
            (OLAY_TTS_BASLADI, _tts_bas),
            (OLAY_TTS_BITTI, _tts_bit),
            (OLAY_DINLEME_BASLADI, _dinle_bas),
            (OLAY_DINLEME_BITTI, _dinle_bit),
            (OLAY_HATA, _hata),
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
        cy = (self.height() - 56) / 2
        yari = self._boyut / 2 * 0.82
        hex_renk = self.model.aktif_renk()
        ana = QColor(hex_renk)
        dim = QColor(hex_renk)
        dim = dim.darker(140)

        # Dış hafif halo
        grad = QRadialGradient(QPointF(cx, cy), yari * 1.05)
        halo = QColor(ana)
        halo.setAlpha(int(30 + 50 * self._parlaklik))
        grad.setColorAt(0.0, halo)
        grad.setColorAt(0.55, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(QPointF(cx, cy), yari * 1.05, yari * 1.05)

        # Halkalar
        for i in range(4):
            pen = QPen(dim if i else ana)
            pen.setWidth(1 if i else 2)
            alpha = int(60 + 140 * self._parlaklik * (1 - i * 0.15))
            c = QColor(ana if i % 2 == 0 else dim)
            c.setAlpha(max(30, min(255, alpha)))
            pen.setColor(c)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = yari * (0.42 + i * 0.16)
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Parçacık bulutu
        for aci0, oran, hiz in self.model.parcaciklar:
            aci = aci0 + self.model.faz * hiz * (
                1.3 if self.model.durum in (AiDurum.DINLIYOR, AiDurum.KONUSUYOR) else 0.7
            )
            r = yari * oran * 0.55
            px = cx + math.cos(aci) * r
            py = cy + math.sin(aci) * r * 0.92
            nokta = QColor(ana)
            nokta.setAlpha(int(90 + 140 * self._parlaklik * (1.1 - oran)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(nokta)
            sz = 1.6 + 2.2 * (1.0 - oran) * self._parlaklik
            painter.drawEllipse(QPointF(px, py), sz, sz)

        # Merkez çekirdek
        cek = QColor(ana)
        cek.setAlpha(min(255, int(140 + 100 * self._parlaklik)))
        painter.setBrush(cek)
        painter.drawEllipse(QPointF(cx, cy), yari * 0.12, yari * 0.12)

        painter.end()

    def durdur(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()
        self.bus_coz()

    def baslat(self) -> None:
        if self.model.animasyon_acik and getattr(self, "_timer", None) is not None:
            self._timer.start()
            self._tik()


__all__ = [
    "AiDurum",
    "AiAnimasyonModel",
    "AiAnimasyonWidget",
    "ai_halka_acisi",
    "ai_parlaklik",
    "durum_etiketi",
    "durum_rengi",
]

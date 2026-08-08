"""
gui/widgets/medya_kontrolleri.py
--------------------------------
HUD kontrol çubuğu: LIVE / PAUSE / CAM / SHUTDOWN.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    Signal = None  # type: ignore[misc, assignment]


class MedyaKontrolleri(QFrame):  # type: ignore[misc, valid-type]
    """LIVE (mikrofon) / PAUSE (ses) / CAM / SHUTDOWN."""

    if _PYSIDE_VAR:
        ses_degisti = Signal(bool)
        kamera_degisti = Signal(bool)
        mikrofon_degisti = Signal(bool)
        kapat_istedi = Signal()
    else:  # pragma: no cover
        ses_degisti = None  # type: ignore[assignment]
        kamera_degisti = None  # type: ignore[assignment]
        mikrofon_degisti = None  # type: ignore[assignment]
        kapat_istedi = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        ses_acik: bool = True,
        kamera_acik: bool = True,
        mikrofon_acik: bool = True,
        parent: Any = None,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.setObjectName("HudKontrol")
        self.setProperty("cam", True)
        self._sessiz_guncelle = False

        kok = QHBoxLayout(self)
        kok.setContentsMargins(10, 10, 10, 10)
        kok.setSpacing(14)
        kok.addStretch(1)

        # LIVE = mikrofon, PAUSE = ses (TTS) kapalı, CAM = kamera
        self.btn_mikrofon = self._btn("🎙  LIVE", "Mikrofonu aç / kapa", "HudLive")
        self.btn_ses = self._btn("⏸  PAUSE", "Sesi (TTS) aç / kapa", "HudPause")
        self.btn_kamera = self._btn("📷  CAM", "Kamerayı aç / kapa", "HudCam")
        self.btn_kapat = QPushButton("⏻  SHUTDOWN")
        self.btn_kapat.setObjectName("HudShutdown")
        self.btn_kapat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_kapat.setToolTip("Pencereyi kapat")
        self.btn_kapat.setMinimumWidth(120)

        for b in (self.btn_mikrofon, self.btn_ses, self.btn_kamera, self.btn_kapat):
            kok.addWidget(b)
        kok.addStretch(1)

        self.btn_mikrofon.toggled.connect(self._mikrofon_toggle)
        self.btn_ses.toggled.connect(self._ses_toggle)
        self.btn_kamera.toggled.connect(self._kamera_toggle)
        self.btn_kapat.clicked.connect(self._kapat)

        self.durumlari_ayarla(
            ses=ses_acik,
            kamera=kamera_acik,
            mikrofon=mikrofon_acik,
        )

    def _btn(self, metin: str, ipucu: str, object_name: str) -> Any:
        btn = QPushButton(metin)
        btn.setObjectName(object_name)
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setToolTip(ipucu)
        btn.setMinimumWidth(110)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _mikrofon_toggle(self, acik: bool) -> None:
        self.btn_mikrofon.setText("🎙  LIVE" if acik else "🎙  MUTED")
        if self._sessiz_guncelle:
            return
        if self.mikrofon_degisti is not None:
            self.mikrofon_degisti.emit(bool(acik))

    def _ses_toggle(self, acik: bool) -> None:
        # checked=True → ses AÇIK; PAUSE görünümü ters: checked=False = paused
        # Buton checked iken ses açık; uncheck = pause (ses kapalı)
        self.btn_ses.setText("▶  RESUME" if not acik else "⏸  PAUSE")
        if self._sessiz_guncelle:
            return
        if self.ses_degisti is not None:
            self.ses_degisti.emit(bool(acik))

    def _kamera_toggle(self, acik: bool) -> None:
        self.btn_kamera.setText("📷  CAM" if acik else "📷  OFF")
        if self._sessiz_guncelle:
            return
        if self.kamera_degisti is not None:
            self.kamera_degisti.emit(bool(acik))

    def _kapat(self) -> None:
        if self.kapat_istedi is not None:
            self.kapat_istedi.emit()

    def durumlari_ayarla(
        self,
        *,
        ses: Optional[bool] = None,
        kamera: Optional[bool] = None,
        mikrofon: Optional[bool] = None,
    ) -> None:
        self._sessiz_guncelle = True
        try:
            if ses is not None:
                self.btn_ses.setChecked(bool(ses))
                self.btn_ses.setText("⏸  PAUSE" if ses else "▶  RESUME")
            if kamera is not None:
                self.btn_kamera.setChecked(bool(kamera))
                self.btn_kamera.setText("📷  CAM" if kamera else "📷  OFF")
            if mikrofon is not None:
                self.btn_mikrofon.setChecked(bool(mikrofon))
                self.btn_mikrofon.setText("🎙  LIVE" if mikrofon else "🎙  MUTED")
        finally:
            self._sessiz_guncelle = False

    @property
    def ses_acik(self) -> bool:
        return bool(self.btn_ses.isChecked())

    @property
    def kamera_acik(self) -> bool:
        return bool(self.btn_kamera.isChecked())

    @property
    def mikrofon_acik(self) -> bool:
        return bool(self.btn_mikrofon.isChecked())


__all__ = ["MedyaKontrolleri"]

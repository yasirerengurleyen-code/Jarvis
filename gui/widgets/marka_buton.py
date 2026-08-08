"""
gui/widgets/marka_buton.py
--------------------------
Sol üst J.A.R.V.I.S. dikdörtgen marka butonu.

Tıklanınca Ayarlar diyaloğunu açar. Yazılar tek satırda tam görünür.
"""

from __future__ import annotations

from typing import Any

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    Signal = None  # type: ignore[misc, assignment]


class MarkaButon(QFrame):  # type: ignore[misc, valid-type]
    """Dikdörtgen J.A.R.V.I.S. marka alanı — tıklanınca ayarlar."""

    if _PYSIDE_VAR:
        tiklandi = Signal()
    else:  # pragma: no cover
        tiklandi = None  # type: ignore[assignment]

    def __init__(
        self,
        parent: Any = None,
        *,
        genislik: int = 340,
        yukseklik: int = 78,
        boyut: int | None = None,  # geriye uyum (kare istenirse yok sayılır)
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError("PySide6 yüklü değil. Kurulum: pip install PySide6")
        super().__init__(parent)
        self.setObjectName("MarkaKare")
        self.setProperty("cam", True)
        w = max(260, int(genislik if boyut is None else max(genislik, boyut * 2)))
        h = max(64, int(yukseklik))
        self.setFixedSize(w, h)
        self.setMinimumSize(w, h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Ayarlar · API key · Voice Core")

        marka = QLabel("J.A.R.V.I.S.")
        marka.setObjectName("Baslik")
        marka.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        marka.setWordWrap(False)

        alt = QLabel("Just A Rather Very Intelligent System")
        alt.setObjectName("AltBaslik")
        alt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        alt.setWordWrap(False)

        yer = QVBoxLayout(self)
        yer.setContentsMargins(16, 10, 16, 10)
        yer.setSpacing(2)
        yer.addStretch(1)
        yer.addWidget(marka)
        yer.addWidget(alt)
        yer.addStretch(1)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.tiklandi is not None:
            self.tiklandi.emit()
        super().mousePressEvent(event)


__all__ = ["MarkaButon"]

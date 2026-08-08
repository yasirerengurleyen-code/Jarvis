"""
gui/widgets/karekod.py
----------------------
Eşleştirme QR (karekod) üretimi.

Görev:
- Metin yükünden PNG / QPixmap üretmek
- qrcode+Pillow yoksa metin yedek göstermek
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Optional


def qr_png_bytes(veri: str, *, kutu: int = 6, kenar: int = 2) -> Optional[bytes]:
    """QR PNG baytları; kütüphane yoksa None."""
    metin = (veri or "").strip()
    if not metin:
        return None
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except ImportError:
        return None

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=max(2, int(kutu)),
        border=max(1, int(kenar)),
    )
    qr.add_data(metin)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_pixmap(veri: str, *, piksel: int = 200) -> Any:
    """
    QPixmap döner; başarısızsa None.

    PySide6 + qrcode gerekir.
    """
    png = qr_png_bytes(veri)
    if not png:
        return None
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
    except ImportError:
        return None

    pm = QPixmap()
    if not pm.loadFromData(png, "PNG"):
        return None
    if piksel > 0 and (pm.width() != piksel or pm.height() != piksel):
        pm = pm.scaled(
            piksel,
            piksel,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pm


__all__ = ["qr_png_bytes", "qr_pixmap"]

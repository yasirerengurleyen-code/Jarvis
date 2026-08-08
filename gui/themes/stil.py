"""
gui/themes/stil.py
------------------
Tony Stark teması için QSS stil üretici.

Görev:
- TonyStarkTema renklerinden uygulama geneli stil sayfası üretmek
- Cam / neon vurgulu PySide6 QSS metni sağlamak
- PySide6 yokken de QSS metninin test edilebilmesi
"""

from __future__ import annotations

from typing import Any, Optional

from gui.themes.tony_stark import TonyStarkTema, tema_yukle


class StilUretici:
    """
    Tema → QSS dönüştürücü.

    PySide6 bağımlılığı yalnızca uygula() içinde istenir.
    """

    def __init__(self, tema: Optional[TonyStarkTema] = None) -> None:
        self.tema = tema or TonyStarkTema.varsayilan()

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "StilUretici":
        return cls(TonyStarkTema.ayarlardan(ayar_yonetici))

    def qss(self) -> str:
        """Uygulama geneli QSS metni."""
        r = self.tema.renkler_dict()
        efekt = self.tema.efektler
        neon = efekt.neon_glow
        cam = efekt.glassmorphism

        yuzey = r["surface"] if not cam else r["glass"]
        kenar = r["accent_dim"] if neon else r["surface"]
        glow = (
            f"border: 1px solid {kenar};"
            if neon
            else f"border: 1px solid {r['surface']};"
        )

        return f"""
/* WhiteCore AI — {self.tema.ad} */
QWidget {{
    background-color: {r["background"]};
    color: {r["text"]};
    font-family: "Segoe UI", "Consolas", sans-serif;
    font-size: 13px;
    selection-background-color: {r["accent_dim"]};
    selection-color: {r["background"]};
}}

QMainWindow, QDialog {{
    background-color: {r["background"]};
}}

QFrame#CamPanel, QFrame[cam="true"] {{
    background-color: {yuzey};
    {glow}
    border-radius: 10px;
}}

QLabel {{
    background: transparent;
    color: {r["text"]};
}}

QLabel#Baslik {{
    color: {r["accent"]};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 2px;
    background: transparent;
}}

QLabel#AltBaslik {{
    color: {r["accent_dim"]};
    font-size: 12px;
    background: transparent;
}}

QLabel#HudBaslik {{
    color: {r["accent"]};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    background: transparent;
}}

QLabel#HudBuyuk {{
    color: {r["text"]};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 42px;
    font-weight: 700;
    background: transparent;
}}

QLabel#NeonMetrik {{
    color: {r["accent"]};
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 14px;
    font-weight: 600;
    background: transparent;
}}

QLabel#OnlineRozet {{
    color: {r["accent"]};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 1px;
    padding: 6px 12px;
    border: 1px solid {r["accent_dim"]};
    border-radius: 4px;
    background: transparent;
}}

QFrame#HudPanel, QFrame#HudKontrol {{
    background-color: {yuzey};
    {glow}
    border-radius: 8px;
}}

QFrame#MarkaKare {{
    background-color: {yuzey};
    {glow}
    border-radius: 8px;
    min-width: 260px;
}}

QFrame#MarkaKare:hover {{
    border: 1px solid {r["accent"]};
}}

QPushButton#KarekodBtn {{
    font-weight: 700;
    letter-spacing: 1px;
    min-width: 120px;
    background-color: {r["surface"]};
    color: {r["accent"]};
    border: 1px solid {r["accent"]};
}}

QPushButton#KarekodBtn:hover {{
    background-color: {r["accent_dim"]};
    color: {r["background"]};
}}

QFrame#JarvisCekirdek {{
    background: transparent;
    border: none;
}}

QPushButton {{
    background-color: {r["surface"]};
    color: {r["text"]};
    border: 1px solid {r["accent_dim"]};
    border-radius: 6px;
    padding: 8px 14px;
    min-height: 28px;
}}

QPushButton:hover {{
    background-color: {r["accent_dim"]};
    color: {r["background"]};
    border: 1px solid {r["accent"]};
}}

QPushButton:pressed {{
    background-color: {r["accent"]};
    color: {r["background"]};
}}

QPushButton:disabled {{
    color: #667766;
    border-color: #334433;
    background-color: #0F0F0F;
}}

QPushButton#Tehlike {{
    border-color: {r["danger"]};
    color: {r["danger"]};
}}

QPushButton#Tehlike:hover {{
    background-color: {r["danger"]};
    color: {r["text"]};
}}

QPushButton#MedyaToggle, QPushButton#HudLive, QPushButton#HudPause, QPushButton#HudCam {{
    min-width: 110px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QPushButton#HudLive:checked {{
    background-color: #00FF88;
    color: #04120A;
    border: 1px solid #00FF88;
}}

QPushButton#HudLive:!checked {{
    background-color: {r["surface"]};
    color: {r["danger"]};
    border: 1px solid {r["danger"]};
}}

QPushButton#HudPause:checked {{
    background-color: #2B6BFF;
    color: #EAF0FF;
    border: 1px solid #3BA7FF;
}}

QPushButton#HudPause:!checked {{
    background-color: {r["surface"]};
    color: #3BA7FF;
    border: 1px solid #3BA7FF;
}}

QPushButton#HudCam:checked {{
    background-color: {r["accent_dim"]};
    color: {r["background"]};
    border: 1px solid {r["accent"]};
}}

QPushButton#HudCam:!checked {{
    background-color: {r["surface"]};
    color: #667777;
    border: 1px solid #334444;
}}

QPushButton#HudShutdown {{
    background-color: {r["surface"]};
    color: {r["danger"]};
    border: 1px solid {r["danger"]};
    font-weight: 700;
}}

QPushButton#HudShutdown:hover {{
    background-color: {r["danger"]};
    color: {r["text"]};
}}

QPushButton#SesNotuBtn {{
    min-width: 40px;
    font-size: 16px;
    font-weight: 700;
    background-color: {r["surface"]};
    border: 1px solid {r["accent_dim"]};
}}

QPushButton#SesNotuBtn:hover {{
    border: 1px solid {r["accent"]};
    background-color: {r["accent_dim"]};
    color: {r["background"]};
}}

QPushButton#MedyaToggle:checked {{
    background-color: {r["accent_dim"]};
    color: {r["background"]};
    border: 1px solid {r["accent"]};
}}

QPushButton#MedyaToggle:!checked {{
    background-color: {r["surface"]};
    color: {r["danger"]};
    border: 1px solid {r["danger"]};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {r["surface"]};
    color: {r["text"]};
    border: 1px solid {r["accent_dim"]};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {r["accent"]};
    selection-color: {r["background"]};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {r["accent"]};
}}

QScrollBar:vertical {{
    background: {r["background"]};
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {r["accent_dim"]};
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QStatusBar {{
    background-color: {r["surface"]};
    color: {r["accent_dim"]};
    border-top: 1px solid {r["accent_dim"]};
}}

QToolTip {{
    background-color: {r["surface"]};
    color: {r["text"]};
    border: 1px solid {r["accent"]};
    padding: 4px 8px;
}}

QProgressBar {{
    background-color: {r["surface"]};
    border: 1px solid {r["accent_dim"]};
    border-radius: 4px;
    text-align: center;
    color: {r["text"]};
}}

QProgressBar::chunk {{
    background-color: {r["accent"]};
    border-radius: 3px;
}}

QListWidget, QTreeWidget, QTableWidget {{
    background-color: {r["surface"]};
    color: {r["text"]};
    border: 1px solid {r["accent_dim"]};
    border-radius: 6px;
    outline: none;
}}

QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {r["accent_dim"]};
    color: {r["background"]};
}}

QTabWidget::pane {{
    border: 1px solid {r["accent_dim"]};
    background-color: {r["background"]};
    border-radius: 6px;
}}

QTabBar::tab {{
    background: {r["surface"]};
    color: {r["text"]};
    padding: 8px 16px;
    border: 1px solid {r["accent_dim"]};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background: {r["accent_dim"]};
    color: {r["background"]};
}}
""".strip()

    def degiskenler(self) -> dict[str, str]:
        """Tema CSS değişken benzeri sözlük (widget'lar için)."""
        r = self.tema.renkler_dict()
        return {
            "--wc-bg": r["background"],
            "--wc-surface": r["surface"],
            "--wc-glass": r["glass"],
            "--wc-accent": r["accent"],
            "--wc-accent-dim": r["accent_dim"],
            "--wc-text": r["text"],
            "--wc-danger": r["danger"],
            "--wc-warning": r["warning"],
        }

    def uygula(self, uygulama: Any = None) -> str:
        """
        QSS'i QApplication'a uygular.

        uygulama None ise qApp kullanılır.
        PySide6 yoksa RuntimeError.
        """
        stil = self.qss()
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as exc:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            ) from exc

        app = uygulama if uygulama is not None else QApplication.instance()
        if app is None:
            raise RuntimeError("Aktif QApplication yok; önce uygulama oluşturun")
        app.setStyleSheet(stil)
        return stil


def qss_uret(tema: Optional[TonyStarkTema] = None) -> str:
    """Kısa yardımcı: tema için QSS metni."""
    return StilUretici(tema or tema_yukle()).qss()


def stil_uygula(uygulama: Any = None, tema: Optional[TonyStarkTema] = None) -> str:
    """Kısa yardımcı: QSS üret + uygula."""
    return StilUretici(tema or tema_yukle()).uygula(uygulama)

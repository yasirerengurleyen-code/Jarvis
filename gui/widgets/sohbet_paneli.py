"""
gui/widgets/sohbet_paneli.py
----------------------------
Sohbet geçmişi ve mesaj giriş paneli.

Görev:
- Kullanıcı / asistan mesajlarını listelemek
- Metin girişi + gönder sinyali
- Engine / EventBus köprüsü için callback API
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
    )

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    Signal = None  # type: ignore[misc, assignment]


class MesajRol(str, Enum):
    KULLANICI = "kullanici"
    ASISTAN = "asistan"
    SISTEM = "sistem"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SohbetMesaji:
    """Tek sohbet satırı."""

    rol: MesajRol
    icerik: str
    zaman: str = field(default_factory=_utc)
    meta: dict[str, Any] = field(default_factory=dict)

    def etiket(self, asistan_adi: str = "J.A.R.V.I.S.") -> str:
        if self.rol == MesajRol.KULLANICI:
            return "Siz"
        if self.rol == MesajRol.ASISTAN:
            return asistan_adi
        return "Sistem"

    def formatli(self, asistan_adi: str = "J.A.R.V.I.S.") -> str:
        return f"[{self.etiket(asistan_adi)}] {self.icerik}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.rol.value,
            "content": self.icerik,
            "timestamp": self.zaman,
            "meta": self.meta,
        }


@dataclass
class SohbetModel:
    """Qt bağımsız sohbet geçmişi."""

    mesajlar: list[SohbetMesaji] = field(default_factory=list)
    asistan_adi: str = "J.A.R.V.I.S."
    max_mesaj: int = 200

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "SohbetModel":
        ad = "J.A.R.V.I.S."
        if ayar_yonetici is None:
            try:
                from config.ayarlar import ayarlar as global_ayarlar

                ayar_yonetici = global_ayarlar
            except Exception:
                return cls(asistan_adi=ad)
        try:
            if not getattr(ayar_yonetici, "yuklendi", False):
                ayar_yonetici.yukle()
            ad = str(ayar_yonetici.al("assistant.name", ad))
        except Exception:
            pass
        return cls(asistan_adi=ad)

    def ekle(self, rol: MesajRol | str, icerik: str, **meta: Any) -> SohbetMesaji:
        metin = (icerik or "").strip()
        if not metin:
            raise ValueError("Boş mesaj eklenemez")
        if isinstance(rol, str):
            rol = MesajRol(rol)
        msg = SohbetMesaji(rol=rol, icerik=metin, meta=dict(meta))
        self.mesajlar.append(msg)
        if len(self.mesajlar) > self.max_mesaj:
            self.mesajlar = self.mesajlar[-self.max_mesaj :]
        return msg

    def kullanici(self, icerik: str, **meta: Any) -> SohbetMesaji:
        return self.ekle(MesajRol.KULLANICI, icerik, **meta)

    def asistan(self, icerik: str, **meta: Any) -> SohbetMesaji:
        return self.ekle(MesajRol.ASISTAN, icerik, **meta)

    def sistem(self, icerik: str, **meta: Any) -> SohbetMesaji:
        return self.ekle(MesajRol.SISTEM, icerik, **meta)

    def temizle(self) -> None:
        self.mesajlar.clear()

    def metin(self) -> str:
        return "\n".join(m.formatli(self.asistan_adi) for m in self.mesajlar)

    def to_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.mesajlar]


# Engine'e mesaj iletmek için
GonderCallback = Callable[[str], Any]


class SohbetPaneli(QFrame):  # type: ignore[misc, valid-type]
    """
    Sohbet UI paneli.

    Sinyaller:
    - mesaj_gonderildi(str): kullanıcı Enter / Gönder ile mesaj yolladı
    """

    if _PYSIDE_VAR:
        mesaj_gonderildi = Signal(str)
        ses_notu_istedi = Signal()
    else:  # pragma: no cover
        mesaj_gonderildi = None  # type: ignore[assignment]
        ses_notu_istedi = None  # type: ignore[assignment]

    def __init__(
        self,
        model: Optional[SohbetModel] = None,
        parent: Any = None,
        *,
        gonder_callback: Optional[GonderCallback] = None,
        placeholder: str = "Jarvis'e yazın…",
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.model = model or SohbetModel.ayarlardan()
        self._gonder_callback = gonder_callback
        self._busy = False
        self._kayit_aktif = False

        self.setObjectName("CamPanel")
        self.setProperty("cam", True)

        baslik = QLabel("CONVERSATION")
        baslik.setObjectName("HudBaslik")

        self._gecmis = QTextEdit()
        self._gecmis.setReadOnly(True)
        self._gecmis.setObjectName("SohbetGecmisi")
        self._gecmis.setPlaceholderText("Henüz mesaj yok…")

        self._giris = QLineEdit()
        self._giris.setPlaceholderText(placeholder)
        self._giris.returnPressed.connect(self.gonder)

        self._btn_ses = QPushButton("🎙")
        self._btn_ses.setObjectName("SesNotuBtn")
        self._btn_ses.setToolTip("Ses notu kaydet (basılı tut / tıkla)")
        self._btn_ses.setFixedWidth(44)
        self._btn_ses.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_ses.clicked.connect(self._ses_notu_tik)

        self._btn = QPushButton("SEND")
        self._btn.clicked.connect(self.gonder)

        satir = QHBoxLayout()
        satir.setSpacing(8)
        satir.addWidget(self._giris, stretch=1)
        satir.addWidget(self._btn_ses)
        satir.addWidget(self._btn)

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(12, 10, 12, 10)
        yerlesim.setSpacing(8)
        yerlesim.addWidget(baslik)
        yerlesim.addWidget(self._gecmis, stretch=1)
        yerlesim.addLayout(satir)

        self._yenile_gorunum()

    def gonder_callback_ayarla(self, callback: Optional[GonderCallback]) -> None:
        self._gonder_callback = callback

    def gonder(self) -> None:
        """Girişteki metni gönderir."""
        if self._busy:
            return
        metin = self._giris.text().strip()
        if not metin:
            return
        self._giris.clear()
        self.kullanici_mesaji_ekle(metin)
        if self.mesaj_gonderildi is not None:
            self.mesaj_gonderildi.emit(metin)
        if self._gonder_callback is not None:
            self._gonder_callback(metin)

    def kullanici_mesaji_ekle(self, icerik: str, **meta: Any) -> SohbetMesaji:
        msg = self.model.kullanici(icerik, **meta)
        self._satir_yaz(msg)
        return msg

    def asistan_mesaji_ekle(self, icerik: str, **meta: Any) -> SohbetMesaji:
        msg = self.model.asistan(icerik, **meta)
        self._satir_yaz(msg)
        return msg

    def sistem_mesaji_ekle(self, icerik: str, **meta: Any) -> SohbetMesaji:
        msg = self.model.sistem(icerik, **meta)
        self._satir_yaz(msg)
        return msg

    def mesaj_ekle(self, rol: MesajRol | str, icerik: str, **meta: Any) -> SohbetMesaji:
        msg = self.model.ekle(rol, icerik, **meta)
        self._satir_yaz(msg)
        return msg

    def temizle(self) -> None:
        self.model.temizle()
        self._gecmis.clear()

    def beklemede(self, aktif: bool = True) -> None:
        """Yanıt beklerken girişi kilitle."""
        self._busy = bool(aktif)
        self._giris.setEnabled(not self._busy)
        self._btn.setEnabled(not self._busy)
        self._btn_ses.setEnabled(not self._busy)
        self._btn.setText("…" if self._busy else "SEND")

    def _ses_notu_tik(self) -> None:
        if self._busy or self._kayit_aktif:
            return
        if self.ses_notu_istedi is not None:
            self.ses_notu_istedi.emit()

    def ses_notu_durum(self, kayit: bool) -> None:
        """Kayıt sırasında buton görünümü."""
        self._kayit_aktif = bool(kayit)
        self._btn_ses.setText("⏹" if kayit else "🎙")
        self._btn_ses.setEnabled(not self._busy)
        self._giris.setEnabled(not kayit and not self._busy)

    def ses_notu_mesaji_ekle(
        self,
        *,
        sure: float,
        yol: str = "",
        demo: bool = False,
    ) -> SohbetMesaji:
        """Sohbete ses notu satırı ekler."""
        ek = " (demo)" if demo else ""
        metin = f"🎙 Ses notu · {sure:.1f}s{ek}"
        return self.kullanici_mesaji_ekle(metin, voice_note=True, path=yol, duration=sure)

    def _satir_yaz(self, msg: SohbetMesaji) -> None:
        renk = {
            MesajRol.KULLANICI: "#E8FFE8",
            MesajRol.ASISTAN: "#00FF88",
            MesajRol.SISTEM: "#00C86A",
        }.get(msg.rol, "#E8FFE8")
        guvenli = (
            msg.icerik.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        html = (
            f'<p style="margin:4px 0;">'
            f'<span style="color:{renk}; font-weight:600;">'
            f"{msg.etiket(self.model.asistan_adi)}</span>"
            f'<span style="color:#E8FFE8;"> — {guvenli}</span></p>'
        )
        self._gecmis.moveCursor(QTextCursor.MoveOperation.End)
        self._gecmis.insertHtml(html)
        self._gecmis.moveCursor(QTextCursor.MoveOperation.End)

    def _yenile_gorunum(self) -> None:
        self._gecmis.clear()
        for msg in self.model.mesajlar:
            self._satir_yaz(msg)

    def mesaj_sayisi(self) -> int:
        return len(self.model.mesajlar)

    def giris_metni(self) -> str:
        return self._giris.text()

    def giris_ayarla(self, metin: str) -> None:
        self._giris.setText(metin)

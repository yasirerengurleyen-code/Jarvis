"""
gui/windows/ayarlar_dialog.py
-----------------------------
Ayarlar penceresi: genel ayarlar + (masaüstünde) API key.

Telefonda / mobil modda API key alanı gösterilmez ve zorunlu değildir.
"""

from __future__ import annotations

import os
import platform
from typing import Any, Optional

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QVBoxLayout,
    )

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QDialog = object  # type: ignore[misc, assignment]


def mobil_mod_mu(*, zorla: Optional[bool] = None) -> bool:
    """
    Mobil istemci mi?

    - zorla verilirse onu kullanır
    - WHITECORE_MOBILE=1 / true
    - Android / iOS benzeri ortam
    """
    if zorla is not None:
        return bool(zorla)
    bayrak = os.environ.get("WHITECORE_MOBILE", "").strip().lower()
    if bayrak in {"1", "true", "yes", "mobil", "mobile"}:
        return True
    sistem = platform.system().lower()
    if sistem in {"android", "ios"}:
        return True
    return False


def api_key_gosterilsin_mi(*, mobil: Optional[bool] = None) -> bool:
    """Masaüstünde API key gerekir; telefonda gerekmez."""
    return not mobil_mod_mu(zorla=mobil)


class AyarlarDialog(QDialog):  # type: ignore[misc, valid-type]
    """Ayarlar + isteğe bağlı API key formu."""

    def __init__(
        self,
        parent: Any = None,
        *,
        ayar_yonetici: Any = None,
        mobil: Optional[bool] = None,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError("PySide6 yüklü değil")
        super().__init__(parent)
        self._ayar = ayar_yonetici
        self._mobil = mobil_mod_mu(zorla=mobil)
        self._api_goster = api_key_gosterilsin_mi(mobil=self._mobil)

        self.setWindowTitle("Ayarlar")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setObjectName("HudPanel")

        kok = QVBoxLayout(self)
        kok.setSpacing(12)

        baslik = QLabel("AYARLAR")
        baslik.setObjectName("HudBaslik")
        kok.addWidget(baslik)

        form = QFormLayout()
        form.setSpacing(10)

        self.chk_fullscreen = QCheckBox("Açılışta tam ekran")
        fs = True
        if ayar_yonetici is not None:
            try:
                fs = bool(ayar_yonetici.al("gui.window.start_fullscreen", True))
            except Exception:
                pass
        self.chk_fullscreen.setChecked(fs)
        form.addRow("Görünüm", self.chk_fullscreen)

        self.chk_ses = QCheckBox("Ses (TTS) açık")
        self.chk_ses.setChecked(True)
        form.addRow("Ses", self.chk_ses)

        self.chk_mikrofon = QCheckBox("Mikrofon açık")
        self.chk_mikrofon.setChecked(True)
        form.addRow("Mikrofon", self.chk_mikrofon)

        kok.addLayout(form)

        # VOICE CORE / Konuşurken
        vc = QLabel("VOICE CORE · KONUŞURKEN")
        vc.setObjectName("HudBaslik")
        kok.addWidget(vc)

        self.chk_tts_yanit = QCheckBox("Yanıtları sesli oku (TTS)")
        self.chk_barge = QCheckBox("Konuşurken kesilebilir (barge-in)")
        self.chk_ayar_konusurken = QCheckBox("Konuşurken ayarlara izin ver")
        self.chk_ses_notu_stt = QCheckBox("Ses notunu metne çevir (STT)")

        tts_on = barge = ayar_acik = stt_not = True
        not_sure = 5.0
        if ayar_yonetici is not None:
            try:
                tts_on = bool(ayar_yonetici.al("voice.speaking.tts_on_reply", True))
                barge = bool(ayar_yonetici.al("voice.speaking.barge_in", True))
                ayar_acik = bool(
                    ayar_yonetici.al("voice.speaking.settings_while_speaking", True)
                )
                stt_not = bool(ayar_yonetici.al("voice.speaking.voice_note_stt", True))
                not_sure = float(
                    ayar_yonetici.al("voice.speaking.voice_note_seconds", 5.0) or 5.0
                )
            except Exception:
                pass
        self.chk_tts_yanit.setChecked(tts_on)
        self.chk_barge.setChecked(barge)
        self.chk_ayar_konusurken.setChecked(ayar_acik)
        self.chk_ses_notu_stt.setChecked(stt_not)

        from PySide6.QtWidgets import QDoubleSpinBox

        self.spin_not_sure = QDoubleSpinBox()
        self.spin_not_sure.setRange(1.0, 20.0)
        self.spin_not_sure.setSingleStep(0.5)
        self.spin_not_sure.setSuffix(" sn")
        self.spin_not_sure.setValue(not_sure)

        vc_form = QFormLayout()
        vc_form.addRow(self.chk_tts_yanit)
        vc_form.addRow(self.chk_barge)
        vc_form.addRow(self.chk_ayar_konusurken)
        vc_form.addRow(self.chk_ses_notu_stt)
        vc_form.addRow("Ses notu süresi", self.spin_not_sure)
        kok.addLayout(vc_form)

        # API key — yalnızca masaüstü
        self._api_satir: Any = None
        self.api_giris: Any = None
        if self._api_goster:
            api_baslik = QLabel("API KEY")
            api_baslik.setObjectName("HudBaslik")
            kok.addWidget(api_baslik)

            ipucu = QLabel(
                "OpenAI anahtarı .env dosyasına yazılır (OPENAI_API_KEY).\n"
                "Telefonda bu alan gerekmez — PC tarafındaki anahtar kullanılır."
            )
            ipucu.setObjectName("AltBaslik")
            ipucu.setWordWrap(True)
            kok.addWidget(ipucu)

            self.api_giris = QLineEdit()
            self.api_giris.setEchoMode(QLineEdit.EchoMode.Password)
            self.api_giris.setPlaceholderText("sk-...")
            mevcut = os.environ.get("OPENAI_API_KEY", "").strip()
            if mevcut:
                # Maskele: son 4 karakter
                self.api_giris.setText(mevcut)
                self.api_giris.setPlaceholderText("Kayıtlı anahtar yüklü — değiştirmek için yazın")
            goster_btn = QPushButton("Göster")
            goster_btn.setCheckable(True)
            goster_btn.toggled.connect(self._api_goster_toggle)

            satir = QHBoxLayout()
            satir.addWidget(self.api_giris, stretch=1)
            satir.addWidget(goster_btn)
            kok.addLayout(satir)
            self._api_satir = satir
        else:
            bilgilendirme = QLabel(
                "Mobil / telefon modu: API key bu cihazda gerekmez.\n"
                "Beyin anahtarı masaüstü (PC) üzerinde tutulur."
            )
            bilgilendirme.setObjectName("AltBaslik")
            bilgilendirme.setWordWrap(True)
            kok.addWidget(bilgilendirme)

        dugmeler = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        dugmeler.accepted.connect(self._kaydet)
        dugmeler.rejected.connect(self.reject)
        kok.addWidget(dugmeler)

    def _api_goster_toggle(self, acik: bool) -> None:
        if self.api_giris is None:
            return
        self.api_giris.setEchoMode(
            QLineEdit.EchoMode.Normal if acik else QLineEdit.EchoMode.Password
        )

    def _kaydet(self) -> None:
        # Tam ekran tercihi → config.json (best-effort)
        if self._ayar is not None:
            try:
                from pathlib import Path
                import json

                yol = Path(getattr(self._ayar, "yol", None) or "")
                if yol.is_file():
                    veri = json.loads(yol.read_text(encoding="utf-8"))
                    gui = veri.setdefault("gui", {})
                    win = gui.setdefault("window", {})
                    win["start_fullscreen"] = bool(self.chk_fullscreen.isChecked())
                    voice = veri.setdefault("voice", {})
                    speaking = voice.setdefault("speaking", {})
                    speaking["tts_on_reply"] = bool(self.chk_tts_yanit.isChecked())
                    speaking["barge_in"] = bool(self.chk_barge.isChecked())
                    speaking["settings_while_speaking"] = bool(
                        self.chk_ayar_konusurken.isChecked()
                    )
                    speaking["voice_note_stt"] = bool(self.chk_ses_notu_stt.isChecked())
                    speaking["voice_note_seconds"] = float(self.spin_not_sure.value())
                    yol.write_text(
                        json.dumps(veri, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    if hasattr(self._ayar, "yukle"):
                        self._ayar.yukle()
            except Exception as exc:
                QMessageBox.warning(self, "Ayarlar", f"Config yazılamadı: {exc}")

        if self._api_goster and self.api_giris is not None:
            anahtar = self.api_giris.text().strip()
            if anahtar:
                try:
                    from config.env import env_anahtar_yaz

                    env_anahtar_yaz("OPENAI_API_KEY", anahtar)
                    os.environ["OPENAI_API_KEY"] = anahtar
                except Exception as exc:
                    QMessageBox.warning(self, "API key", f"Kaydedilemedi: {exc}")
                    return

        self.accept()

    @property
    def mobil(self) -> bool:
        return self._mobil

    @property
    def api_key_alani_var(self) -> bool:
        return self._api_goster


__all__ = ["AyarlarDialog", "mobil_mod_mu", "api_key_gosterilsin_mi"]

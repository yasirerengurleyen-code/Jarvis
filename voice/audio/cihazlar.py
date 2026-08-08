"""
voice/audio/cihazlar.py
-----------------------
Ses giriş/çıkış cihazı keşfi.

Görev:
- Sistemdeki mikrofon ve hoparlörleri listelemek
- config.json voice.microphone / voice.speaker ile eşleştirmek
- sounddevice yoksa güvenli boş liste / varsayılan dönmek

Ağır bağımlılık (sounddevice) isteğe bağlıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import VoiceError
from core.logger import logger_al

log = logger_al("voice.audio.cihazlar")


@dataclass
class SesCihazi:
    """Tek bir ses cihazı."""

    index: int
    ad: str
    max_girdi_kanal: int = 0
    max_cikti_kanal: int = 0
    ornek_hizi: float = 16000.0
    host_api: str = ""

    @property
    def mikrofon_mu(self) -> bool:
        return self.max_girdi_kanal > 0

    @property
    def hoparlor_mu(self) -> bool:
        return self.max_cikti_kanal > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.ad,
            "max_input_channels": self.max_girdi_kanal,
            "max_output_channels": self.max_cikti_kanal,
            "sample_rate": self.ornek_hizi,
            "host_api": self.host_api,
            "is_mic": self.mikrofon_mu,
            "is_speaker": self.hoparlor_mu,
        }


def _sounddevice_var_mi() -> bool:
    try:
        import sounddevice  # noqa: F401

        return True
    except ImportError:
        return False


class CihazYoneticisi:
    """Mikrofon ve hoparlör keşif / seçim yöneticisi."""

    def __init__(self, ayar_yonetici: Optional[Ayarlar] = None) -> None:
        self.ayarlar = ayar_yonetici or global_ayarlar
        self._onbellek: Optional[list[SesCihazi]] = None

    def _ai_yukle(self) -> None:
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:
                pass

    def cihazlari_tara(self, *, yenile: bool = False) -> list[SesCihazi]:
        """Tüm ses cihazlarını tarar."""
        if self._onbellek is not None and not yenile:
            return list(self._onbellek)

        if not _sounddevice_var_mi():
            log.warning(
                "sounddevice yüklü değil — sanal varsayılan cihazlar kullanılacak"
            )
            self._onbellek = self._sanal_cihazlar()
            return list(self._onbellek)

        try:
            import sounddevice as sd

            ham = sd.query_devices()
            hostapis = sd.query_hostapis()
            sonuc: list[SesCihazi] = []
            for i, d in enumerate(ham):
                host_adi = ""
                try:
                    hai = int(d.get("hostapi", 0))
                    host_adi = str(hostapis[hai].get("name", ""))
                except Exception:
                    host_adi = ""
                sonuc.append(
                    SesCihazi(
                        index=i,
                        ad=str(d.get("name", f"device-{i}")),
                        max_girdi_kanal=int(d.get("max_input_channels", 0)),
                        max_cikti_kanal=int(d.get("max_output_channels", 0)),
                        ornek_hizi=float(d.get("default_samplerate", 16000)),
                        host_api=host_adi,
                    )
                )
            self._onbellek = sonuc
            log.info("Ses cihazı tarandı: %s adet", len(sonuc))
            return list(sonuc)
        except Exception as exc:
            raise VoiceError(
                f"Ses cihazları taranamadı: {exc}",
                detay={"hata": str(exc)},
            ) from exc

    def mikrofonlar(self) -> list[SesCihazi]:
        return [c for c in self.cihazlari_tara() if c.mikrofon_mu]

    def hoparlorler(self) -> list[SesCihazi]:
        return [c for c in self.cihazlari_tara() if c.hoparlor_mu]

    def varsayilan_mikrofon(self) -> Optional[SesCihazi]:
        """config veya sistem varsayılan mikrofonu."""
        self._ai_yukle()
        idx = self.ayarlar.al("voice.microphone.device_index", None)
        mikler = self.mikrofonlar()
        if idx is not None:
            for c in mikler:
                if c.index == int(idx):
                    return c
            raise VoiceError(
                f"Yapılandırılmış mikrofon bulunamadı: index={idx}",
                detay={"device_index": idx},
            )
        if not mikler:
            return None
        # sounddevice default
        if _sounddevice_var_mi():
            try:
                import sounddevice as sd

                default = sd.default.device
                in_idx = default[0] if isinstance(default, (list, tuple)) else default
                if in_idx is not None:
                    for c in mikler:
                        if c.index == int(in_idx):
                            return c
            except Exception:
                pass
        return mikler[0]

    def varsayilan_hoparlor(self) -> Optional[SesCihazi]:
        """config veya sistem varsayılan hoparlörü."""
        self._ai_yukle()
        idx = self.ayarlar.al("voice.speaker.device_index", None)
        hop = self.hoparlorler()
        if idx is not None:
            for c in hop:
                if c.index == int(idx):
                    return c
            raise VoiceError(
                f"Yapılandırılmış hoparlör bulunamadı: index={idx}",
                detay={"device_index": idx},
            )
        if not hop:
            return None
        if _sounddevice_var_mi():
            try:
                import sounddevice as sd

                default = sd.default.device
                out_idx = default[1] if isinstance(default, (list, tuple)) else default
                if out_idx is not None:
                    for c in hop:
                        if c.index == int(out_idx):
                            return c
            except Exception:
                pass
        return hop[0]

    def ozet(self) -> dict[str, Any]:
        """GUI / log için özet."""
        mik = self.varsayilan_mikrofon()
        hop = self.varsayilan_hoparlor()
        return {
            "sounddevice": _sounddevice_var_mi(),
            "microphone_count": len(self.mikrofonlar()),
            "speaker_count": len(self.hoparlorler()),
            "default_microphone": mik.to_dict() if mik else None,
            "default_speaker": hop.to_dict() if hop else None,
        }

    @staticmethod
    def _sanal_cihazlar() -> list[SesCihazi]:
        """sounddevice yokken test / iskelet cihazları."""
        return [
            SesCihazi(
                index=0,
                ad="WhiteCore Sanal Mikrofon",
                max_girdi_kanal=1,
                max_cikti_kanal=0,
                ornek_hizi=16000.0,
                host_api="virtual",
            ),
            SesCihazi(
                index=1,
                ad="WhiteCore Sanal Hoparlör",
                max_girdi_kanal=0,
                max_cikti_kanal=2,
                ornek_hizi=22050.0,
                host_api="virtual",
            ),
        ]


# Paylaşılan örnek
cihaz_yoneticisi = CihazYoneticisi()

__all__ = [
    "SesCihazi",
    "CihazYoneticisi",
    "cihaz_yoneticisi",
]

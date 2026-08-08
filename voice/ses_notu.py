"""
voice/ses_notu.py
-----------------
Kısa ses notu kaydı (sohbet paneli için).

Görev:
- Mikrofon ile N saniye PCM kaydetmek
- WAV dosyasına yazmak
- sounddevice yoksa sessiz/demo WAV üretmek
"""

from __future__ import annotations

import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from core.logger import logger_al

log = logger_al("voice.ses_notu")

_PROJE = Path(__file__).resolve().parent.parent
_VARSAYILAN_DIR = _PROJE / "database" / "voice_notes"


def _utc_ad() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def wav_yaz(
    yol: Path,
    pcm: bytes,
    *,
    ornek_hizi: int = 16000,
    kanallar: int = 1,
    ornek_genislik: int = 2,
) -> Path:
    """PCM → WAV dosyası."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(yol), "wb") as wf:
        wf.setnchannels(kanallar)
        wf.setsampwidth(ornek_genislik)
        wf.setframerate(ornek_hizi)
        wf.writeframes(pcm)
    return yol


def sahte_pcm(*, sure_saniye: float = 1.0, ornek_hizi: int = 16000) -> bytes:
    """Sessiz PCM (demo / mikrofon yok)."""
    n = max(1, int(sure_saniye * ornek_hizi))
    return struct.pack(f"<{n}h", *([0] * n))


def ses_notu_kaydet(
    *,
    sure_saniye: float = 4.0,
    hedef_dir: Optional[Path] = None,
    mikrofon: Any = None,
    ornek_hizi: int = 16000,
) -> dict[str, Any]:
    """
    Ses notu kaydeder.

    Dönüş: {path, duration, sample_rate, bytes, demo}
    """
    sure = max(0.5, min(30.0, float(sure_saniye)))
    klasor = Path(hedef_dir) if hedef_dir is not None else _VARSAYILAN_DIR
    klasor.mkdir(parents=True, exist_ok=True)
    yol = klasor / f"not_{_utc_ad()}_{uuid4().hex[:6]}.wav"

    pcm = b""
    demo = False
    hz = ornek_hizi

    if mikrofon is not None and hasattr(mikrofon, "kaydet_saniye"):
        try:
            if not getattr(mikrofon, "calisiyor", True):
                mikrofon.baslat()
            pcm = mikrofon.kaydet_saniye(sure)
            hz = int(getattr(mikrofon, "ornek_hizi", ornek_hizi) or ornek_hizi)
        except Exception as exc:
            log.warning("Ses notu mikrofon hatası: %s — demo", exc)
            pcm = b""

    if not pcm:
        demo = True
        pcm = sahte_pcm(sure_saniye=sure, ornek_hizi=hz)

    wav_yaz(yol, pcm, ornek_hizi=hz)
    log.info("Ses notu kaydedildi: %s (%.1fs demo=%s)", yol.name, sure, demo)
    return {
        "path": str(yol),
        "duration": sure,
        "sample_rate": hz,
        "bytes": len(pcm),
        "demo": demo,
    }


__all__ = ["ses_notu_kaydet", "wav_yaz", "sahte_pcm"]

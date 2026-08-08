"""
config/ayarlar.py
-----------------
config.json yükleyici ve erişim katmanı.

Görev:
- config/config.json dosyasını okumak
- Noktalı anahtar ile değer almak (örn. ai.default_provider)
- Engine ve diğer modüllere tek kaynak sağlamak
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from core.exceptions import ConfigurationError

_PROJE_KOKU = Path(__file__).resolve().parent.parent
_VARSAYILAN_YOL = _PROJE_KOKU / "config" / "config.json"


class Ayarlar:
    """WhiteCore yapılandırma yöneticisi."""

    def __init__(self, yol: Optional[Path] = None) -> None:
        self.yol = Path(yol) if yol else _VARSAYILAN_YOL
        self._veri: dict[str, Any] = {}
        self._yuklendi = False

    @property
    def yuklendi(self) -> bool:
        return self._yuklendi

    @property
    def veri(self) -> dict[str, Any]:
        return self._veri

    def yukle(self) -> dict[str, Any]:
        """config.json dosyasını yükler."""
        if not self.yol.exists():
            raise ConfigurationError(
                f"Yapılandırma dosyası bulunamadı: {self.yol}",
                detay={"path": str(self.yol)},
            )
        try:
            self._veri = json.loads(self.yol.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                "config.json geçersiz JSON",
                detay={"path": str(self.yol), "hata": str(exc)},
            ) from exc
        except OSError as exc:
            raise ConfigurationError(
                "config.json okunamadı",
                detay={"path": str(self.yol), "hata": str(exc)},
            ) from exc

        self._yuklendi = True
        return self._veri

    def al(self, anahtar: str, varsayilan: Any = None) -> Any:
        """
        Noktalı yol ile değer döner.

        Örnek: al('assistant.name') -> 'J.A.R.V.I.S.'
        """
        if not self._yuklendi:
            self.yukle()

        dugum: Any = self._veri
        for parca in anahtar.split("."):
            if not isinstance(dugum, dict) or parca not in dugum:
                return varsayilan
            dugum = dugum[parca]
        return dugum

    def bolum(self, ad: str) -> dict[str, Any]:
        """Üst düzey bir bölümü dict olarak döner."""
        deger = self.al(ad, {})
        return dict(deger) if isinstance(deger, dict) else {}


# Paylaşılan örnek — Engine bunu kullanır
ayarlar = Ayarlar()

__all__ = ["Ayarlar", "ayarlar"]

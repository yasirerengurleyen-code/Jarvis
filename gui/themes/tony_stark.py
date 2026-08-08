"""
gui/themes/tony_stark.py
------------------------
Tony Stark tarzı GUI tema modeli.

Görev:
- Siyah / cam / yeşil neon renk paletini tanımlamak
- config.json → gui.colors / gui.effects ile birleştirmek
- PySide6 olmadan da test edilebilir saf veri katmanı sunmak
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


# Config yokken kullanılan varsayılanlar (config.json ile uyumlu)
VARSAYILAN_RENKLER: dict[str, str] = {
    "background": "#050A0C",
    "surface": "#0B1518",
    "glass": "rgba(8, 22, 28, 0.78)",
    "accent": "#00E8C8",
    "accent_dim": "#00A894",
    "text": "#D8FFF6",
    "danger": "#FF3B4A",
    "warning": "#FFB020",
}

VARSAYILAN_EFEKTLER: dict[str, bool] = {
    "glassmorphism": True,
    "neon_glow": True,
    "microphone_animation": True,
    "ai_animation": True,
}

TEMA_ADI = "tony_stark"


@dataclass(frozen=True)
class Rgba:
    """0–255 RGB + 0–1 alpha."""

    r: int
    g: int
    b: int
    a: float = 1.0

    def hex(self, alpha_dahil: bool = False) -> str:
        """#RRGGBB veya #RRGGBBAA döner."""
        if not alpha_dahil:
            return f"#{self.r:02X}{self.g:02X}{self.b:02X}"
        alfa_bayt = max(0, min(255, int(round(self.a * 255))))
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}{alfa_bayt:02X}"

    def css(self) -> str:
        """CSS rgba(...) veya #hex."""
        if self.a >= 0.999:
            return self.hex()
        return f"rgba({self.r}, {self.g}, {self.b}, {self.a:.3f})"

    def tuple_rgb(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)

    def tuple_rgba(self) -> tuple[int, int, int, float]:
        return (self.r, self.g, self.b, self.a)


def renk_ayikla(deger: str) -> Rgba:
    """
    '#RRGGBB', '#RGB', '#RRGGBBAA' veya 'rgba(r,g,b,a)' metnini Rgba'ya çevirir.
    """
    metin = (deger or "").strip()
    if not metin:
        raise ValueError("Boş renk değeri")

    if metin.lower().startswith("rgba(") and metin.endswith(")"):
        ic = metin[5:-1]
        parcalar = [p.strip() for p in ic.split(",")]
        if len(parcalar) != 4:
            raise ValueError(f"Geçersiz rgba: {deger}")
        r, g, b = (int(float(parcalar[i])) for i in range(3))
        a = float(parcalar[3])
        return _sinirla(r, g, b, a)

    if metin.startswith("#"):
        h = metin[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            r = int(h[0:2], 16)
            g = int(h[2:4], 16)
            b = int(h[4:6], 16)
            return _sinirla(r, g, b, 1.0)
        if len(h) == 8:
            r = int(h[0:2], 16)
            g = int(h[2:4], 16)
            b = int(h[4:6], 16)
            a = int(h[6:8], 16) / 255.0
            return _sinirla(r, g, b, a)

    raise ValueError(f"Desteklenmeyen renk formatı: {deger}")


def _sinirla(r: int, g: int, b: int, a: float) -> Rgba:
    return Rgba(
        r=max(0, min(255, int(r))),
        g=max(0, min(255, int(g))),
        b=max(0, min(255, int(b))),
        a=max(0.0, min(1.0, float(a))),
    )


@dataclass
class TemaEfektleri:
    """GUI efekt anahtarları."""

    glassmorphism: bool = True
    neon_glow: bool = True
    microphone_animation: bool = True
    ai_animation: bool = True

    @classmethod
    def from_dict(cls, veri: Optional[Mapping[str, Any]]) -> "TemaEfektleri":
        kaynak = dict(VARSAYILAN_EFEKTLER)
        if veri:
            for k in kaynak:
                if k in veri:
                    kaynak[k] = bool(veri[k])
        return cls(**kaynak)

    def to_dict(self) -> dict[str, bool]:
        return {
            "glassmorphism": self.glassmorphism,
            "neon_glow": self.neon_glow,
            "microphone_animation": self.microphone_animation,
            "ai_animation": self.ai_animation,
        }


@dataclass
class TonyStarkTema:
    """
    Tony Stark tema paleti.

    PySide6 QSS üretimi sonraki dosyada (stil.py) yapılır.
    """

    ad: str = TEMA_ADI
    background: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["background"]))
    surface: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["surface"]))
    glass: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["glass"]))
    accent: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["accent"]))
    accent_dim: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["accent_dim"]))
    text: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["text"]))
    danger: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["danger"]))
    warning: Rgba = field(default_factory=lambda: renk_ayikla(VARSAYILAN_RENKLER["warning"]))
    efektler: TemaEfektleri = field(default_factory=TemaEfektleri)

    @classmethod
    def varsayilan(cls) -> "TonyStarkTema":
        return cls.from_config({})

    @classmethod
    def from_config(cls, gui_bolumu: Optional[Mapping[str, Any]] = None) -> "TonyStarkTema":
        """
        config.json → gui bölümünden tema üretir.

        gui_bolumu None ise yalnızca varsayılanlar kullanılır.
        """
        bolum = dict(gui_bolumu or {})
        renkler = dict(VARSAYILAN_RENKLER)
        gelen = bolum.get("colors") or {}
        if isinstance(gelen, Mapping):
            for k, v in gelen.items():
                if k in renkler and isinstance(v, str) and v.strip():
                    renkler[k] = v.strip()

        efektler = TemaEfektleri.from_dict(
            bolum.get("effects") if isinstance(bolum.get("effects"), Mapping) else None
        )
        ad = str(bolum.get("theme") or TEMA_ADI)

        return cls(
            ad=ad,
            background=renk_ayikla(renkler["background"]),
            surface=renk_ayikla(renkler["surface"]),
            glass=renk_ayikla(renkler["glass"]),
            accent=renk_ayikla(renkler["accent"]),
            accent_dim=renk_ayikla(renkler["accent_dim"]),
            text=renk_ayikla(renkler["text"]),
            danger=renk_ayikla(renkler["danger"]),
            warning=renk_ayikla(renkler["warning"]),
            efektler=efektler,
        )

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "TonyStarkTema":
        """config.ayarlar.Ayarlar örneğinden yükler (yoksa varsayılan)."""
        if ayar_yonetici is None:
            try:
                from config.ayarlar import ayarlar as global_ayarlar

                ayar_yonetici = global_ayarlar
            except Exception:
                return cls.varsayilan()

        try:
            if not getattr(ayar_yonetici, "yuklendi", False):
                ayar_yonetici.yukle()
            bolum = ayar_yonetici.bolum("gui")
        except Exception:
            return cls.varsayilan()

        return cls.from_config(bolum if isinstance(bolum, dict) else {})

    def renkler_dict(self) -> dict[str, str]:
        """QSS / CSS için string renk sözlüğü."""
        return {
            "background": self.background.css(),
            "surface": self.surface.css(),
            "glass": self.glass.css(),
            "accent": self.accent.css(),
            "accent_dim": self.accent_dim.css(),
            "text": self.text.css(),
            "danger": self.danger.css(),
            "warning": self.warning.css(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.ad,
            "colors": self.renkler_dict(),
            "effects": self.efektler.to_dict(),
        }


def tema_yukle(gui_bolumu: Optional[Mapping[str, Any]] = None) -> TonyStarkTema:
    """Kısa yardımcı: gui bölümünden veya varsayılan temayı döner."""
    if gui_bolumu is None:
        return TonyStarkTema.ayarlardan()
    return TonyStarkTema.from_config(gui_bolumu)

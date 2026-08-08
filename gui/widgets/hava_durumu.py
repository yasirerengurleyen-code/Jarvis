"""
gui/widgets/hava_durumu.py
--------------------------
Hava durumu gösterge widget'ı.

Görev:
- Konum için sıcaklık / durum metni sağlamak
- Open-Meteo API (anahtar gerekmez); ağ yoksa sahte/demo veri
- config.gui.widgets.show_weather bayrağına uymak
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    QLabel = object  # type: ignore[misc, assignment]


# WMO weather interpretation codes (kısa TR)
_WMO_TR: dict[int, str] = {
    0: "Açık",
    1: "Çoğunlukla açık",
    2: "Parçalı bulutlu",
    3: "Kapalı",
    45: "Sis",
    48: "Kırağılı sis",
    51: "Hafif çisenti",
    53: "Çisenti",
    55: "Yoğun çisenti",
    61: "Hafif yağmur",
    63: "Yağmur",
    65: "Şiddetli yağmur",
    71: "Hafif kar",
    73: "Kar",
    75: "Yoğun kar",
    80: "Sağanak",
    81: "Sağanak",
    82: "Şiddetli sağanak",
    95: "Gök gürültülü",
    96: "Dolu / fırtına",
    99: "Şiddetli fırtına",
}

# Varsayılan: İstanbul
_VARSAYILAN_SEHIR = "İstanbul"
_VARSAYILAN_LAT = 41.0082
_VARSAYILAN_LON = 28.9784


def wmo_aciklama(kod: int) -> str:
    """WMO kodunu Türkçe kısa metne çevirir."""
    if kod in _WMO_TR:
        return _WMO_TR[kod]
    # Yakın grup
    for anahtar, metin in _WMO_TR.items():
        if abs(anahtar - kod) <= 2:
            return metin
    return f"Kod {kod}"


@dataclass
class HavaDurumu:
    """Hava durumu örneği."""

    sehir: str = _VARSAYILAN_SEHIR
    sicaklik_c: float = 0.0
    durum: str = ""
    kod: Optional[int] = None
    ruzgar_kmh: Optional[float] = None
    nem_yuzde: Optional[float] = None
    kaynak: str = "open-meteo"  # open-meteo | sahte | onbellek
    zaman: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    hata: Optional[str] = None

    @property
    def ozet(self) -> str:
        return f"{self.sehir}: {self.sicaklik_c:.0f}°C — {self.durum}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.sehir,
            "temp_c": self.sicaklik_c,
            "condition": self.durum,
            "code": self.kod,
            "wind_kmh": self.ruzgar_kmh,
            "humidity": self.nem_yuzde,
            "source": self.kaynak,
            "timestamp": self.zaman,
            "error": self.hata,
            "summary": self.ozet,
        }


@dataclass
class HavaAyarlari:
    """Hava widget yapılandırması."""

    goster: bool = True
    sehir: str = _VARSAYILAN_SEHIR
    latitude: float = _VARSAYILAN_LAT
    longitude: float = _VARSAYILAN_LON
    guncelleme_ms: int = 15 * 60 * 1000  # 15 dk
    timeout_saniye: float = 4.0

    @classmethod
    def from_config(cls, gui_bolumu: Optional[dict[str, Any]] = None) -> "HavaAyarlari":
        bolum = dict(gui_bolumu or {})
        widgets = bolum.get("widgets") if isinstance(bolum.get("widgets"), dict) else {}
        weather = bolum.get("weather") if isinstance(bolum.get("weather"), dict) else {}
        return cls(
            goster=bool(widgets.get("show_weather", True)),
            sehir=str(weather.get("city") or _VARSAYILAN_SEHIR),
            latitude=float(weather.get("latitude", _VARSAYILAN_LAT)),
            longitude=float(weather.get("longitude", _VARSAYILAN_LON)),
            guncelleme_ms=int(weather.get("refresh_ms", 15 * 60 * 1000)),
            timeout_saniye=float(weather.get("timeout_seconds", 4.0)),
        )

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "HavaAyarlari":
        if ayar_yonetici is None:
            try:
                from config.ayarlar import ayarlar as global_ayarlar

                ayar_yonetici = global_ayarlar
            except Exception:
                return cls()
        try:
            if not getattr(ayar_yonetici, "yuklendi", False):
                ayar_yonetici.yukle()
            gui = ayar_yonetici.bolum("gui")
            return cls.from_config(gui if isinstance(gui, dict) else {})
        except Exception:
            return cls()


def sahte_hava(sehir: str = _VARSAYILAN_SEHIR, *, neden: str = "demo") -> HavaDurumu:
    """Ağ/API yokken tutarlı demo verisi."""
    return HavaDurumu(
        sehir=sehir,
        sicaklik_c=22.0,
        durum="Parçalı bulutlu",
        kod=2,
        ruzgar_kmh=12.0,
        nem_yuzde=55.0,
        kaynak="sahte",
        hata=neden,
    )


def hava_getir(
    ayarlar: Optional[HavaAyarlari] = None,
    *,
    zorla_sahte: bool = False,
    urlac: Any = None,
) -> HavaDurumu:
    """
    Open-Meteo current weather çeker.

    urlac: test için urllib.request.urlopen yerine geçirilebilir callable.
    """
    ayar = ayarlar or HavaAyarlari()
    if zorla_sahte:
        return sahte_hava(ayar.sehir, neden="zorla_sahte")

    params = urllib.parse.urlencode(
        {
            "latitude": ayar.latitude,
            "longitude": ayar.longitude,
            "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
            "timezone": "auto",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    ac = urlac or urllib.request.urlopen

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WhiteCoreAI/0.1"})
        with ac(req, timeout=ayar.timeout_saniye) as yanit:
            ham = yanit.read()
        veri = json.loads(ham.decode("utf-8"))
        current = veri.get("current") or {}
        kod = current.get("weather_code")
        kod_int = int(kod) if kod is not None else None
        return HavaDurumu(
            sehir=ayar.sehir,
            sicaklik_c=float(current.get("temperature_2m") or 0.0),
            durum=wmo_aciklama(kod_int) if kod_int is not None else "Bilinmiyor",
            kod=kod_int,
            ruzgar_kmh=(
                float(current["wind_speed_10m"])
                if current.get("wind_speed_10m") is not None
                else None
            ),
            nem_yuzde=(
                float(current["relative_humidity_2m"])
                if current.get("relative_humidity_2m") is not None
                else None
            ),
            kaynak="open-meteo",
            hata=None,
        )
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        hava = sahte_hava(ayar.sehir, neden=str(exc))
        return hava
    except Exception as exc:  # beklenmeyen
        return sahte_hava(ayar.sehir, neden=str(exc))


class HavaDurumuWidget(QFrame):  # type: ignore[misc, valid-type]
    """Hava durumu cam paneli."""

    def __init__(
        self,
        ayarlar: Optional[HavaAyarlari] = None,
        parent: Any = None,
        *,
        zorla_sahte: bool = False,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.ayarlar = ayarlar or HavaAyarlari.ayarlardan()
        self._zorla_sahte = zorla_sahte
        self._son: Optional[HavaDurumu] = None

        self.setObjectName("HudPanel")
        self.setProperty("cam", True)

        self._baslik = QLabel("WEATHER")
        self._baslik.setObjectName("HudBaslik")

        self._sicaklik = QLabel("")
        self._sicaklik.setObjectName("HudBuyuk")
        self._sicaklik.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._sehir = QLabel("")
        self._sehir.setObjectName("NeonMetrik")

        self._durum = QLabel("")
        self._durum.setObjectName("AltBaslik")

        self._detay = QLabel("")
        self._detay.setObjectName("AltBaslik")
        self._detay.setWordWrap(True)

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(14, 12, 14, 12)
        yerlesim.setSpacing(4)
        yerlesim.addWidget(self._baslik)
        yerlesim.addWidget(self._sicaklik)
        yerlesim.addWidget(self._sehir)
        yerlesim.addWidget(self._durum)
        yerlesim.addWidget(self._detay)

        self.setVisible(self.ayarlar.goster)

        self._timer = QTimer(self)
        self._timer.setInterval(max(60_000, int(self.ayarlar.guncelleme_ms)))
        self._timer.timeout.connect(self.yenile)
        self.yenile()
        self._timer.start()

    def yenile(self) -> None:
        if not self.ayarlar.goster:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._son = hava_getir(self.ayarlar, zorla_sahte=self._zorla_sahte)
        self._baslik.setText(f"WEATHER {self._son.sehir.upper()}")
        self._sicaklik.setText(f"{self._son.sicaklik_c:.0f}°C")
        self._sehir.setText(self._son.sehir.upper())
        self._durum.setText(self._son.durum.lower())
        parcalar = []
        hissedilen = self._son.sicaklik_c + 2 if self._son.nem_yuzde else self._son.sicaklik_c
        parcalar.append(f"hissedilen {hissedilen:.0f} derece")
        if self._son.nem_yuzde is not None:
            parcalar.append(f"nem yüzde {self._son.nem_yuzde:.0f}")
        if self._son.ruzgar_kmh is not None:
            parcalar.append(f"rüzgar {self._son.ruzgar_kmh:.0f} km/h")
        if self._son.kaynak == "sahte":
            parcalar.append("(demo)")
        self._detay.setText("\n".join(parcalar))

    @property
    def son(self) -> Optional[HavaDurumu]:
        return self._son

    def ozet_metni(self) -> str:
        return self._son.ozet if self._son else ""

    def durdur(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()

    def baslat(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.start()
            self.yenile()

"""
gui/widgets/sistem_metrikleri.py
--------------------------------
SYSTEM STATUS: CPU / RAM / DISK / BATTERY + ağ + uptime.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QProgressBar,
        QVBoxLayout,
    )

    _PYSIDE_VAR = True
except ImportError:  # pragma: no cover
    _PYSIDE_VAR = False
    QFrame = object  # type: ignore[misc, assignment]
    QLabel = object  # type: ignore[misc, assignment]

try:
    import psutil

    _PSUTIL_VAR = True
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _PSUTIL_VAR = False


@dataclass
class MetrikOrnegi:
    """Tek bir örnekleme anı."""

    cpu_yuzde: float = 0.0
    ram_yuzde: float = 0.0
    ram_kullanilan_gb: float = 0.0
    ram_toplam_gb: float = 0.0
    disk_yuzde: float = 0.0
    batarya_yuzde: Optional[float] = None
    batarya_sarj: bool = False
    gpu_yuzde: Optional[float] = None
    gpu_adi: str = ""
    ag_gonderilen_mb: float = 0.0
    ag_alinan_mb: float = 0.0
    ag_yukleme_kbs: float = 0.0
    ag_indirme_kbs: float = 0.0
    ag_aktif: bool = False
    uptime_saniye: float = 0.0
    sistem: str = ""
    kaynak: str = "psutil"
    ekstra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": self.cpu_yuzde,
            "ram_percent": self.ram_yuzde,
            "ram_used_gb": self.ram_kullanilan_gb,
            "ram_total_gb": self.ram_toplam_gb,
            "disk_percent": self.disk_yuzde,
            "battery_percent": self.batarya_yuzde,
            "battery_charging": self.batarya_sarj,
            "gpu_percent": self.gpu_yuzde,
            "gpu_name": self.gpu_adi,
            "net_sent_mb": self.ag_gonderilen_mb,
            "net_recv_mb": self.ag_alinan_mb,
            "net_up_kbs": self.ag_yukleme_kbs,
            "net_down_kbs": self.ag_indirme_kbs,
            "net_active": self.ag_aktif,
            "uptime_seconds": self.uptime_saniye,
            "system": self.sistem,
            "source": self.kaynak,
        }


def _bayt_gb(bayt: int) -> float:
    return round(bayt / (1024**3), 2)


def _bayt_mb(bayt: int) -> float:
    return round(bayt / (1024**2), 2)


def uptime_metni(saniye: float) -> str:
    s = max(0, int(saniye))
    sa, kalan = divmod(s, 3600)
    dk, sn = divmod(kalan, 60)
    return f"{sa:02d}:{dk:02d}:{sn:02d}"


def metrik_renk(yuzde: float) -> str:
    """İlerleme çubuğu rengi."""
    if yuzde >= 85:
        return "#FF3B4A"
    if yuzde >= 65:
        return "#FFB020"
    return "#00FF88"


def _gpu_nvidia() -> tuple[Optional[float], str]:
    if not shutil.which("nvidia-smi"):
        return None, ""
    try:
        tamam = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        if tamam.returncode != 0 or not tamam.stdout.strip():
            return None, ""
        satir = tamam.stdout.strip().splitlines()[0]
        parcalar = [p.strip() for p in satir.split(",")]
        if len(parcalar) < 2:
            return None, ""
        return float(parcalar[0]), parcalar[1]
    except Exception:
        return None, ""


_ONCEKI_NET: dict[str, Any] = {"t": 0.0, "sent": 0, "recv": 0}


def metrik_ornekle(*, cpu_aralik: float = 0.15) -> MetrikOrnegi:
    sistem = f"{platform.system()} {platform.release()}"
    if not _PSUTIL_VAR:
        return MetrikOrnegi(
            cpu_yuzde=12.5,
            ram_yuzde=42.0,
            ram_kullanilan_gb=6.8,
            ram_toplam_gb=16.0,
            disk_yuzde=55.0,
            batarya_yuzde=78.0,
            batarya_sarj=True,
            ag_gonderilen_mb=10.0,
            ag_alinan_mb=25.0,
            ag_yukleme_kbs=12.0,
            ag_indirme_kbs=40.0,
            ag_aktif=True,
            uptime_saniye=3661.0,
            sistem=sistem,
            kaynak="sahte",
        )

    assert psutil is not None
    cpu = float(psutil.cpu_percent(interval=cpu_aralik))
    bellek = psutil.virtual_memory()

    disk_yuzde = 0.0
    try:
        kok = "C:\\" if platform.system() == "Windows" else "/"
        disk_yuzde = float(psutil.disk_usage(kok).percent)
    except Exception:
        disk_yuzde = 0.0

    batarya_yuzde: Optional[float] = None
    batarya_sarj = False
    try:
        bat = psutil.sensors_battery()
        if bat is not None:
            batarya_yuzde = float(bat.percent)
            batarya_sarj = bool(bat.power_plugged)
    except Exception:
        pass

    gonderilen = alinan = 0.0
    yukleme = indirme = 0.0
    try:
        net = psutil.net_io_counters()
        gonderilen = _bayt_mb(int(net.bytes_sent))
        alinan = _bayt_mb(int(net.bytes_recv))
        simdi = time.monotonic()
        once_t = float(_ONCEKI_NET["t"])
        if once_t > 0:
            dt = max(0.2, simdi - once_t)
            yukleme = max(
                0.0,
                (int(net.bytes_sent) - int(_ONCEKI_NET["sent"])) / 1024.0 / dt,
            )
            indirme = max(
                0.0,
                (int(net.bytes_recv) - int(_ONCEKI_NET["recv"])) / 1024.0 / dt,
            )
        _ONCEKI_NET["t"] = simdi
        _ONCEKI_NET["sent"] = int(net.bytes_sent)
        _ONCEKI_NET["recv"] = int(net.bytes_recv)
    except Exception:
        pass

    ag_aktif = False
    try:
        for _ad, adresler in psutil.net_if_addrs().items():
            if any(getattr(a, "address", None) for a in adresler):
                ag_aktif = True
                break
    except Exception:
        ag_aktif = gonderilen > 0 or alinan > 0

    uptime = 0.0
    try:
        uptime = max(0.0, time.time() - float(psutil.boot_time()))
    except Exception:
        uptime = 0.0

    gpu_yuzde, gpu_adi = _gpu_nvidia()
    kaynak = "psutil" if gpu_yuzde is None else "karisik"

    return MetrikOrnegi(
        cpu_yuzde=round(cpu, 1),
        ram_yuzde=round(float(bellek.percent), 1),
        ram_kullanilan_gb=_bayt_gb(int(bellek.used)),
        ram_toplam_gb=_bayt_gb(int(bellek.total)),
        disk_yuzde=round(disk_yuzde, 1),
        batarya_yuzde=None if batarya_yuzde is None else round(batarya_yuzde, 1),
        batarya_sarj=batarya_sarj,
        gpu_yuzde=gpu_yuzde,
        gpu_adi=gpu_adi,
        ag_gonderilen_mb=gonderilen,
        ag_alinan_mb=alinan,
        ag_yukleme_kbs=round(yukleme, 1),
        ag_indirme_kbs=round(indirme, 1),
        ag_aktif=ag_aktif,
        uptime_saniye=uptime,
        sistem=sistem,
        kaynak=kaynak,
    )


def metrik_satirlari(
    ornek: MetrikOrnegi,
    *,
    cpu: bool = True,
    ram: bool = True,
    gpu: bool = True,
    ag: bool = True,
    sistem_bilgi: bool = True,
    disk: bool = True,
    batarya: bool = True,
) -> list[tuple[str, str]]:
    satirlar: list[tuple[str, str]] = []
    if cpu:
        satirlar.append(("CPU", f"%{ornek.cpu_yuzde:.1f}"))
    if ram:
        satirlar.append(
            (
                "RAM",
                f"%{ornek.ram_yuzde:.1f}  ({ornek.ram_kullanilan_gb:.1f}/{ornek.ram_toplam_gb:.1f} GB)",
            )
        )
    if disk:
        satirlar.append(("DISK", f"%{ornek.disk_yuzde:.1f}"))
    if batarya:
        if ornek.batarya_yuzde is None:
            satirlar.append(("BATARYA", "N/A"))
        else:
            sarj = " ⚡" if ornek.batarya_sarj else ""
            satirlar.append(("BATARYA", f"%{ornek.batarya_yuzde:.0f}{sarj}"))
    if gpu:
        if ornek.gpu_yuzde is None:
            satirlar.append(("GPU", "N/A"))
        else:
            ad = f" · {ornek.gpu_adi}" if ornek.gpu_adi else ""
            satirlar.append(("GPU", f"%{ornek.gpu_yuzde:.0f}{ad}"))
    if ag:
        durum = "Aktif" if ornek.ag_aktif else "Kapalı"
        satirlar.append(
            (
                "AĞ",
                f"{durum}  ↑{ornek.ag_yukleme_kbs:.1f} ↓{ornek.ag_indirme_kbs:.1f} KB/s",
            )
        )
    if sistem_bilgi and ornek.sistem:
        satirlar.append(("SİSTEM", ornek.sistem))
    return satirlar


@dataclass
class SistemMetrikAyarlari:
    show_cpu: bool = True
    show_ram: bool = True
    show_gpu: bool = False
    show_network: bool = True
    show_system_info: bool = False
    show_disk: bool = True
    show_battery: bool = True
    guncelleme_ms: int = 1500

    @classmethod
    def from_config(cls, gui_bolumu: Optional[dict[str, Any]] = None) -> "SistemMetrikAyarlari":
        bolum = dict(gui_bolumu or {})
        w = bolum.get("widgets") if isinstance(bolum.get("widgets"), dict) else {}
        return cls(
            show_cpu=bool(w.get("show_cpu", True)),
            show_ram=bool(w.get("show_ram", True)),
            show_gpu=bool(w.get("show_gpu", False)),
            show_network=bool(w.get("show_network", True)),
            show_system_info=bool(w.get("show_system_info", False)),
            show_disk=bool(w.get("show_disk", True)),
            show_battery=bool(w.get("show_battery", True)),
        )

    @classmethod
    def ayarlardan(cls, ayar_yonetici: Any = None) -> "SistemMetrikAyarlari":
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


class SistemMetrikleriWidget(QFrame):  # type: ignore[misc, valid-type]
    """SYSTEM STATUS HUD paneli."""

    def __init__(
        self,
        ayarlar: Optional[SistemMetrikAyarlari] = None,
        parent: Any = None,
        *,
        cpu_aralik: float = 0.05,
    ) -> None:
        if not _PYSIDE_VAR:
            raise RuntimeError(
                "PySide6 yüklü değil. Kurulum: pip install PySide6"
            )
        super().__init__(parent)
        self.ayarlar = ayarlar or SistemMetrikAyarlari.ayarlardan()
        self._cpu_aralik = cpu_aralik
        self._baslama = time.monotonic()
        self.setObjectName("HudPanel")
        self.setProperty("cam", True)

        baslik = QLabel("SYSTEM STATUS")
        baslik.setObjectName("HudBaslik")

        self._uptime = QLabel("UPTIME  00:00:00")
        self._uptime.setObjectName("AltBaslik")

        self._cubuklar: dict[str, QProgressBar] = {}
        self._etiketler: dict[str, QLabel] = {}
        self._cubuk_alan = QVBoxLayout()
        self._cubuk_alan.setSpacing(6)

        self._ag = QLabel("")
        self._ag.setObjectName("NeonMetrik")

        ana = QVBoxLayout(self)
        ana.setContentsMargins(14, 12, 14, 12)
        ana.setSpacing(8)
        ana.addWidget(baslik)
        ana.addWidget(self._uptime)
        ana.addLayout(self._cubuk_alan)
        ana.addWidget(self._ag)

        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(self.ayarlar.guncelleme_ms)))
        self._timer.timeout.connect(self.yenile)
        self.yenile()
        self._timer.start()

    def _cubuk_ekle(self, ad: str) -> None:
        satir = QHBoxLayout()
        k = QLabel(ad)
        k.setObjectName("AltBaslik")
        k.setFixedWidth(72)
        bar = QProgressBar()
        bar.setObjectName("HudBar")
        bar.setRange(0, 100)
        bar.setTextVisible(True)
        bar.setFormat("%p%")
        bar.setFixedHeight(16)
        v = QLabel("0%")
        v.setObjectName("NeonMetrik")
        v.setFixedWidth(48)
        v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        satir.addWidget(k)
        satir.addWidget(bar, stretch=1)
        satir.addWidget(v)
        self._cubuk_alan.addLayout(satir)
        self._cubuklar[ad] = bar
        self._etiketler[ad] = v

    def _cubuklari_kur(self) -> None:
        while self._cubuk_alan.count():
            item = self._cubuk_alan.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w is not None:
                        w.deleteLater()
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cubuklar.clear()
        self._etiketler.clear()
        if self.ayarlar.show_cpu:
            self._cubuk_ekle("CPU")
        if self.ayarlar.show_ram:
            self._cubuk_ekle("RAM")
        if self.ayarlar.show_disk:
            self._cubuk_ekle("DISK")
        if self.ayarlar.show_battery:
            self._cubuk_ekle("BATARYA")

    def _bar_stil(self, bar: Any, yuzde: float) -> None:
        renk = metrik_renk(yuzde)
        bar.setStyleSheet(
            f"""
            QProgressBar#HudBar {{
                background: #0A181C;
                border: 1px solid #145A55;
                border-radius: 3px;
                text-align: center;
                color: #D8FFF6;
                font-size: 10px;
            }}
            QProgressBar#HudBar::chunk {{
                background-color: {renk};
                border-radius: 2px;
            }}
            """
        )

    def yenile(self) -> None:
        ornek = metrik_ornekle(cpu_aralik=self._cpu_aralik)
        # Session uptime (boot yerine uygulama süresi daha okunaklı)
        oturum = time.monotonic() - self._baslama
        self._uptime.setText(f"UPTIME  {uptime_metni(oturum)}")

        istenen = []
        if self.ayarlar.show_cpu:
            istenen.append("CPU")
        if self.ayarlar.show_ram:
            istenen.append("RAM")
        if self.ayarlar.show_disk:
            istenen.append("DISK")
        if self.ayarlar.show_battery:
            istenen.append("BATARYA")
        if set(self._cubuklar.keys()) != set(istenen):
            self._cubuklari_kur()

        degerler = {
            "CPU": ornek.cpu_yuzde,
            "RAM": ornek.ram_yuzde,
            "DISK": ornek.disk_yuzde,
            "BATARYA": (
                float(ornek.batarya_yuzde)
                if ornek.batarya_yuzde is not None
                else 0.0
            ),
        }
        for ad, yuzde in degerler.items():
            if ad not in self._cubuklar:
                continue
            bar = self._cubuklar[ad]
            if ad == "BATARYA" and ornek.batarya_yuzde is None:
                bar.setValue(0)
                self._etiketler[ad].setText("N/A")
                self._bar_stil(bar, 0)
            else:
                bar.setValue(int(max(0, min(100, yuzde))))
                ekstra = " ⚡" if ad == "BATARYA" and ornek.batarya_sarj else ""
                self._etiketler[ad].setText(f"%{yuzde:.0f}{ekstra}")
                self._bar_stil(bar, yuzde)

        if self.ayarlar.show_network:
            self._ag.setText(
                f"↑ {ornek.ag_yukleme_kbs:.1f} KB/s   ↓ {ornek.ag_indirme_kbs:.1f} KB/s"
            )
            self._ag.setVisible(True)
        else:
            self._ag.setVisible(False)

        self._son_ornek = ornek

    @property
    def son_ornek(self) -> Optional[MetrikOrnegi]:
        return getattr(self, "_son_ornek", None)

    def metinler(self) -> dict[str, str]:
        return {k: v.text() for k, v in self._etiketler.items()}

    def durdur(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()

    def baslat(self) -> None:
        if getattr(self, "_timer", None) is not None:
            self._timer.start()
            self.yenile()


__all__ = [
    "MetrikOrnegi",
    "SistemMetrikAyarlari",
    "SistemMetrikleriWidget",
    "metrik_ornekle",
    "metrik_satirlari",
    "metrik_renk",
    "uptime_metni",
]

"""
core/logger.py
--------------
WhiteCore AI merkezi log sistemi.

Görev:
- logs/ klasörünü otomatik oluşturmak
- Uygulama loglarını logs/app.log dosyasına yazmak (günlük rotation)
- Önemli işlemleri logs/audit.jsonl dosyasına JSON satırları olarak kaydetmek
- Konsola renkli çıktı vermek
- Tüm modüllerin aynı yapılandırmayı paylaşmasını sağlamak

Kullanım:
    from core.logger import logger_al, audit_yaz

    log = logger_al("core.ornek")
    log.info("Sistem hazır")
    audit_yaz("baslatma", modul="core", detay={"surum": "0.1.0"})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any, Optional

# Proje kökü: WhiteCoreAI/
_PROJE_KOKU = Path(__file__).resolve().parent.parent
_LOGS_DIZINI = _PROJE_KOKU / "logs"
_APP_LOG = _LOGS_DIZINI / "app.log"
_AUDIT_LOG = _LOGS_DIZINI / "audit.jsonl"

_KOK_LOGGER_ADI = "whitecore"
_YAPILANDIRILDI = False
_KILIT = Lock()

# ANSI renk kodları (Windows 10+ ve modern terminaller)
_RENKLER = {
    "DEBUG": "\033[36m",     # cyan
    "INFO": "\033[32m",      # yeşil
    "WARNING": "\033[33m",   # sarı
    "ERROR": "\033[31m",     # kırmızı
    "CRITICAL": "\033[35m",  # magenta
}
_RESET = "\033[0m"
_KALIN = "\033[1m"


class RenkliKonsolFormatter(logging.Formatter):
    """Konsol için seviye bazlı renkli formatlayıcı."""

    def __init__(self, fmt: str, datefmt: Optional[str] = None, renkli: bool = True) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.renkli = renkli

    def format(self, record: logging.LogRecord) -> str:
        orijinal_seviye = record.levelname
        if self.renkli:
            renk = _RENKLER.get(orijinal_seviye, "")
            record.levelname = f"{renk}{_KALIN}{orijinal_seviye}{_RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = orijinal_seviye


class Utf8TimedRotatingFileHandler(TimedRotatingFileHandler):
    """UTF-8 kodlamalı günlük dosya döndürücü."""

    def __init__(self, filename: str, **kwargs: Any) -> None:
        kwargs.setdefault("encoding", "utf-8")
        super().__init__(filename, **kwargs)


def _config_oku() -> dict[str, Any]:
    """config/config.json içinden logging bölümünü okur; yoksa boş dict döner."""
    config_yolu = _PROJE_KOKU / "config" / "config.json"
    try:
        veri = json.loads(config_yolu.read_text(encoding="utf-8"))
        return dict(veri.get("logging", {}))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _windows_ansi_etkinlestir() -> None:
    """Windows konsolunda ANSI renklerini mümkünse açar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        cekirdek = ctypes.windll.kernel32  # type: ignore[attr-defined]
        tutac = cekirdek.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mod = ctypes.c_uint32()
        if cekirdek.GetConsoleMode(tutac, ctypes.byref(mod)) == 0:
            return
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        cekirdek.SetConsoleMode(tutac, mod.value | 0x0004)
    except Exception:
        # Renk açılamazsa sessizce düz metne düşülür
        pass


def logger_yapilandir(
    seviye: str = "INFO",
    konsol: bool = True,
    dosya: bool = True,
    renkli_konsol: bool = True,
    yedek_sayisi: int = 14,
    format_metni: Optional[str] = None,
    zorla: bool = False,
) -> logging.Logger:
    """
    Kök logger'ı bir kez yapılandırır.

    Args:
        seviye: DEBUG/INFO/WARNING/ERROR/CRITICAL
        konsol: Konsola yazılsın mı
        dosya: app.log'a yazılsın mı
        renkli_konsol: ANSI renk kullanılsın mı
        yedek_sayisi: Saklanacak günlük dosya sayısı
        format_metni: Özel format şablonu
        zorla: True ise mevcut yapılandırmayı yeniden kurar
    """
    global _YAPILANDIRILDI

    with _KILIT:
        if _YAPILANDIRILDI and not zorla:
            return logging.getLogger(_KOK_LOGGER_ADI)

        cfg = _config_oku()
        seviye = str(cfg.get("level", seviye)).upper()
        konsol = bool(cfg.get("console", konsol))
        dosya = bool(cfg.get("file", dosya))
        renkli_konsol = bool(cfg.get("colored_console", renkli_konsol))
        yedek_sayisi = int(cfg.get("backup_count", yedek_sayisi))
        format_metni = cfg.get(
            "format",
            format_metni
            or "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        )

        app_log = Path(cfg.get("file_path", str(_APP_LOG)))
        if not app_log.is_absolute():
            app_log = _PROJE_KOKU / app_log

        audit_log = Path(cfg.get("json_audit_path", str(_AUDIT_LOG)))
        if not audit_log.is_absolute():
            audit_log = _PROJE_KOKU / audit_log

        # logs/ otomatik oluştur
        app_log.parent.mkdir(parents=True, exist_ok=True)
        audit_log.parent.mkdir(parents=True, exist_ok=True)

        kok = logging.getLogger(_KOK_LOGGER_ADI)
        kok.handlers.clear()
        kok.setLevel(getattr(logging, seviye, logging.INFO))
        kok.propagate = False

        tarih_fmt = "%Y-%m-%d %H:%M:%S"

        if konsol:
            _windows_ansi_etkinlestir()
            konsol_handler = logging.StreamHandler(sys.stdout)
            konsol_handler.setLevel(getattr(logging, seviye, logging.INFO))
            konsol_handler.setFormatter(
                RenkliKonsolFormatter(format_metni, datefmt=tarih_fmt, renkli=renkli_konsol)
            )
            kok.addHandler(konsol_handler)

        if dosya:
            dosya_handler = Utf8TimedRotatingFileHandler(
                filename=str(app_log),
                when="midnight",
                interval=1,
                backupCount=yedek_sayisi,
                encoding="utf-8",
                utc=False,
            )
            dosya_handler.suffix = "%Y-%m-%d"
            dosya_handler.setLevel(getattr(logging, seviye, logging.INFO))
            dosya_handler.setFormatter(
                logging.Formatter(format_metni, datefmt=tarih_fmt)
            )
            kok.addHandler(dosya_handler)

        # Audit yolu sonraki çağrılar için saklanır
        kok._whitecore_audit_path = audit_log  # type: ignore[attr-defined]

        _YAPILANDIRILDI = True
        return kok


def logger_al(ad: Optional[str] = None) -> logging.Logger:
    """
    Modül logger'ı döndürür. İlk çağrıda otomatik yapılandırır.

    Args:
        ad: Alt logger adı (örn. 'core.engine'). None ise kök logger.
    """
    if not _YAPILANDIRILDI:
        logger_yapilandir()

    if not ad or ad == _KOK_LOGGER_ADI:
        return logging.getLogger(_KOK_LOGGER_ADI)

    if not ad.startswith(f"{_KOK_LOGGER_ADI}."):
        ad = f"{_KOK_LOGGER_ADI}.{ad}"
    return logging.getLogger(ad)


def audit_yaz(
    olay: str,
    *,
    modul: str = "system",
    seviye: str = "INFO",
    kullanici: Optional[str] = None,
    detay: Optional[dict[str, Any]] = None,
) -> None:
    """
    Önemli işlemleri audit.jsonl dosyasına tek satır JSON olarak yazar.

    Args:
        olay: Olay adı (örn. 'komut_onay', 'dosya_silindi')
        modul: Kaynak modül
        seviye: Olay seviyesi
        kullanici: İsteğe bağlı kullanıcı kimliği
        detay: Ek alanlar
    """
    if not _YAPILANDIRILDI:
        logger_yapilandir()

    kok = logging.getLogger(_KOK_LOGGER_ADI)
    audit_path: Path = getattr(kok, "_whitecore_audit_path", _AUDIT_LOG)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    kayit = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": olay,
        "module": modul,
        "level": seviye.upper(),
        "user": kullanici,
        "detail": detay or {},
    }

    with _KILIT:
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")

    # Audit olayını normal loga da düşür
    log = logger_al(f"audit.{modul}")
    mesaj = f"[AUDIT] {olay} | {detay or {}}"
    seviye_no = getattr(logging, seviye.upper(), logging.INFO)
    log.log(seviye_no, mesaj)


# Kolay import için kök logger örneği
logger = logger_al()

__all__ = [
    "logger",
    "logger_al",
    "logger_yapilandir",
    "audit_yaz",
]

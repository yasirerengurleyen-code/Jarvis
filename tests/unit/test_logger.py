"""core/logger.py birim testi."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Proje kökünü path'e ekle
KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.logger import audit_yaz, logger_al, logger_yapilandir


def test_logger() -> None:
    logs = KOK / "logs"
    app_log = logs / "app.log"
    audit_log = logs / "audit.jsonl"

    # Temiz başlangıç için eski test satırlarını silme — append modunda çalışır
    logger_yapilandir(seviye="INFO", zorla=True)

    assert logs.exists(), "logs/ klasörü oluşmadı"

    log = logger_al("tests.logger")
    log.info("WhiteCore logger INFO testi")
    log.warning("WhiteCore logger WARNING testi")
    log.error("WhiteCore logger ERROR testi")

    critical_log = logger_al("tests.logger.critical")
    critical_log.critical("WhiteCore logger CRITICAL testi")

    audit_yaz(
        "test_olayi",
        modul="tests",
        seviye="INFO",
        kullanici="geliştirici",
        detay={"asistan": "J.A.R.V.I.S.", "ok": True},
    )

    # Handler'ları flush et
    kok = logger_al()
    for h in kok.handlers:
        h.flush()

    assert app_log.exists(), "app.log oluşmadı"
    icerik = app_log.read_text(encoding="utf-8")
    assert "INFO" in icerik
    assert "WARNING" in icerik
    assert "ERROR" in icerik
    assert "CRITICAL" in icerik
    assert "WhiteCore logger INFO testi" in icerik

    assert audit_log.exists(), "audit.jsonl oluşmadı"
    son_satir = audit_log.read_text(encoding="utf-8").strip().splitlines()[-1]
    kayit = json.loads(son_satir)
    assert kayit["event"] == "test_olayi"
    assert kayit["module"] == "tests"
    assert kayit["detail"]["asistan"] == "J.A.R.V.I.S."

    # Aynı logger örneği paylaşımı
    a = logger_al("paylasim")
    b = logger_al("paylasim")
    assert a is b

    print("TEST_OK")
    print("logs_dir:", logs)
    print("app_log_bytes:", app_log.stat().st_size)
    print("audit_last_event:", kayit["event"])
    print("shared_logger:", a.name)


if __name__ == "__main__":
    test_logger()

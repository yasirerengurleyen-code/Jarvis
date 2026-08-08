"""core/exceptions.py birim testi."""

from __future__ import annotations

import json
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core.exceptions import (
    AIProviderError,
    ConfigurationError,
    MemoryError,
    MobileBridgeError,
    NetworkError,
    PluginError,
    SecurityError,
    VisionError,
    VoiceError,
    WakeWordError,
    WhiteCoreError,
)
from core.logger import logger_yapilandir


SINIFLAR = [
    WhiteCoreError,
    ConfigurationError,
    AIProviderError,
    VoiceError,
    WakeWordError,
    PluginError,
    NetworkError,
    MobileBridgeError,
    SecurityError,
    VisionError,
    MemoryError,
]


def test_exceptions() -> None:
    logger_yapilandir(zorla=True)

    # Temel alanlar
    err = ConfigurationError(
        "Geçersiz tema ayarı",
        detay={"alan": "gui.theme", "deger": "bilinmeyen"},
        logla=True,
    )
    assert err.kod == "CFG_0001"
    assert err.modul == "config"
    assert err.mesaj == "Geçersiz tema ayarı"
    assert err.zaman_damgasi
    assert err.detay["alan"] == "gui.theme"
    assert "CFG_0001" in str(err)

    veri = err.to_dict()
    assert veri["type"] == "ConfigurationError"
    assert veri["code"] == "CFG_0001"
    assert "timestamp" in veri

    # Tüm sınıfların varsayılan kodları
    beklenen_kodlar = {
        WhiteCoreError: "WC_0001",
        ConfigurationError: "CFG_0001",
        AIProviderError: "AI_0001",
        VoiceError: "VOICE_0001",
        WakeWordError: "WAKE_0001",
        PluginError: "PLG_0001",
        NetworkError: "NET_0001",
        MobileBridgeError: "MOB_0001",
        SecurityError: "SEC_0001",
        VisionError: "VIS_0001",
        MemoryError: "MEM_0001",
    }
    for sinif, kod in beklenen_kodlar.items():
        ornek = sinif("test", logla=False, audit=False)
        assert ornek.kod == kod, f"{sinif.__name__} kodu hatalı: {ornek.kod}"

    # Kalıtım
    assert issubclass(ConfigurationError, WhiteCoreError)
    assert issubclass(MemoryError, WhiteCoreError)

    # raise / except
    try:
        raise AIProviderError("OpenAI zaman aşımı", detay={"timeout": 60}, logla=False)
    except WhiteCoreError as e:
        assert e.kod == "AI_0001"
        assert e.detay["timeout"] == 60

    # SecurityError audit entegrasyonu
    audit_path = KOK / "logs" / "audit.jsonl"
    SecurityError(
        "Tehlikeli komut reddedildi",
        detay={"aksiyon": "system_shutdown"},
        logla=True,
        audit=True,
    )
    son = audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    kayit = json.loads(son)
    assert kayit["event"] == "exception"
    assert kayit["detail"]["kod"] == "SEC_0001"

    # Özel kod override
    ozel = NetworkError("WS koptu", kod="NET_0099", modul="network.websocket", logla=False)
    assert ozel.kod == "NET_0099"
    assert ozel.modul == "network.websocket"

    print("TEST_OK")
    print("sinif_sayisi:", len(SINIFLAR))
    print("ornek:", err)
    print("to_dict_keys:", sorted(veri.keys()))
    print("security_audit_event:", kayit["event"])


if __name__ == "__main__":
    test_exceptions()

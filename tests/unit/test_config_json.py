"""config/config.json doğrulama testi."""
import json
from pathlib import Path

path = Path("config/config.json")
assert path.exists(), "Dosya yok"

data = json.loads(path.read_text(encoding="utf-8"))

required = [
    "project",
    "assistant",
    "ai",
    "voice",
    "wake_word",
    "gui",
    "memory",
    "security",
    "logging",
    "network",
    "mobile",
    "plugins",
    "automation",
]
missing = [k for k in required if k not in data]
assert not missing, f"Eksik bölümler: {missing}"

assert data["assistant"]["name"] == "J.A.R.V.I.S."
assert data["wake_word"]["phrase"] == "Jarvis"
assert data["ai"]["default_provider"] == "openai"
assert data["memory"]["backend"] == "sqlite"
assert data["gui"]["framework"] == "PySide6"
assert "openai" in data["ai"]["providers"]
assert data["mobile"]["enabled"] is True
assert data["mobile"]["bridge_enabled"] is True
assert data["mobile"]["dry_run"] is True
assert data["mobile"]["primary_mobile"] == "ios"
assert data["mobile"]["platforms"]["ios"]["enabled"] is True

print("TEST_OK")
print("Bolum sayisi:", len(data))
print("Anahtarlar:", ", ".join(data.keys()))
print("Asistan:", data["assistant"]["name"])
print("Wake word:", data["wake_word"]["phrase"])
print("LLM:", data["ai"]["default_provider"], "/", data["ai"]["model"])
print("Tema:", data["gui"]["theme"])
print("Dosya boyutu:", path.stat().st_size, "bayt")
print("JSON gecerli: Evet")

# WhiteCore AI – Aşama 2 Planı (Brain + Memory)

**Durum: ✅ %100 TAMAMLANDI**

Bu aşama tamamlandı. Aşama 3'e (Voice) yalnızca kullanıcı `ONAYLIYORUM` dedikten sonra geçilir.

## Klasörler

```
brain/
├── providers/     # OpenAI, Ollama, Gemini, Claude, DeepSeek, OpenRouter, Local
├── prompts/       # Prompt yöneticisi
└── yoneticisi.py  # AI Manager

memory/
├── stores/        # SQLite, sohbet, kullanıcı, uzun süreli
├── arama.py       # Birleşik arama
└── hafiza.py      # Hafıza yöneticisi
```

## Tamamlanan dosyalar

| # | Dosya | Durum |
|---|--------|--------|
| 1 | `brain/providers/taban.py` | ✅ |
| 2 | `brain/providers/openai_saglayici.py` | ✅ |
| 3 | `brain/providers/ollama_saglayici.py` | ✅ |
| 4 | `brain/providers/gemini_saglayici.py` | ✅ |
| 5 | `brain/providers/claude_saglayici.py` | ✅ |
| 6 | `brain/providers/deepseek_saglayici.py` | ✅ |
| 7 | `brain/providers/fabrika.py` | ✅ |
| 8 | `brain/prompts/yonetici.py` | ✅ |
| 9 | `brain/yoneticisi.py` | ✅ |
| 10 | `memory/stores/sqlite_depo.py` | ✅ |
| 11 | `memory/stores/sohbet.py` | ✅ |
| 12 | `memory/stores/kullanici.py` | ✅ |
| 13 | `memory/stores/uzun_sureli.py` | ✅ |
| 14 | `memory/arama.py` | ✅ |
| 15 | `memory/hafiza.py` | ✅ |
| 16 | Engine entegrasyonu | ✅ |
| 17 | Entegrasyon testleri + demo | ✅ |

## Sağlayıcı geçişi

```python
# config.json → "ai.default_provider": "openai"
# veya kodda:
saglayici_olustur("ollama")
```

Desteklenen: openai, ollama, gemini, claude, deepseek, openrouter, local

## Tamamlanma ölçütü

- [x] Tüm sağlayıcılar tek satır config ile seçilebilir
- [x] SQLite sohbet / profil / uzun süreli hafıza çalışır
- [x] Arama çalışır
- [x] `python main.py --demo` bozulmaz (Memory + Brain aktif)
- [x] Aşama 2 birim testleri geçer

## Yasaklar (hâlâ geçerli)

- Voice / GUI / Skills / iPhone / Agent / Vision kodu Aşama 2 içinde yazılmaz
- Aşama 3+ dosyası, kullanıcı onayı olmadan oluşturulmaz

# WhiteCore AI – Aşama 3 Planı (Voice)

**Durum: ✅ %100 TAMAMLANDI**

Aşama 4 (GUI) yalnızca kullanıcı `ONAYLIYORUM` dedikten sonra başlar.

## Hedef akış

```
"Jarvis" (wake word)
    ↓
Mikrofon dinleme + STT
    ↓
Brain + Memory
    ↓
TTS
    ↓
Yanıt (ses / olay)
```

## Tamamlanan dosyalar

| # | Dosya | Durum |
|---|--------|--------|
| 1 | `voice/audio/cihazlar.py` | ✅ |
| 2 | `voice/audio/mikrofon.py` | ✅ |
| 3 | `voice/audio/kuyruk.py` | ✅ |
| 4 | `voice/wakeword/dinleyici.py` | ✅ |
| 5 | `voice/stt/taban.py` | ✅ |
| 6 | `voice/stt/faster_whisper_stt.py` | ✅ |
| 7 | `voice/stt/openai_whisper_stt.py` | ✅ |
| 8 | `voice/tts/taban.py` | ✅ |
| 9 | `voice/tts/piper_tts.py` | ✅ |
| 10 | `voice/tts/coqui_tts.py` | ✅ |
| 11 | `voice/yoneticisi.py` | ✅ |
| 12 | Engine entegrasyonu | ✅ |
| 13 | Testler + demo | ✅ |

## Notlar

- `faster-whisper`, `openai-whisper`, `piper-tts`, `TTS`, `sounddevice` yoksa sistem **sahte** motorlarla ayağa kalkar.
- Gerçek ses için: `pip install sounddevice faster-whisper piper-tts` (veya ilgili paketler).
- Wake word: config `wake_word.phrase` = **Jarvis**

## Yasaklar (hâlâ geçerli)

- GUI / Skills / iPhone / Agent / Vision — Aşama 4+ onayı olmadan yazılmaz

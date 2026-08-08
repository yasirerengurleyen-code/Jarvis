# WhiteCore AI

**J.A.R.V.I.S.** — Marvel esinli, tamamen özgün, modüler masaüstü yapay zekâ asistanı.

## Özellikler (hedef)

- Wake word: **Jarvis**
- STT: Faster Whisper / OpenAI Whisper
- TTS: Piper / Coqui TTS
- Çoklu LLM: OpenAI (varsayılan), Ollama, Gemini, Claude, DeepSeek, OpenRouter, yerel modeller
- SQLite hafıza (konuşma, tercihler, uzun süreli bellek)
- Eklenti sistemi (`plugins/`)
- Akıllı ajan (görev planlama)
- PySide6 arayüz (siyah / cam / yeşil neon)
- Çoklu platform: Windows → iPhone → iPad → Web (Android sonradan)

## Çoklu platform (öncelik)

1. **Windows** — ana sistem
2. **iPhone (iOS)**
3. **iPad (iPadOS)**
4. **Web Paneli**
5. **Android** — ilk sürümde yok; aynı köprü arayüzleriyle eklenebilir

Windows ↔ iPhone için QR / 6 haneli kod, HTTPS+WebSocket, sohbet senkronu,
dosya paylaşımı, bildirim, Telefonumu Bul, pil ve bağlantı durumu iskeleti
hazırlanır. Detaylar: [`docs/PLAN.md`](docs/PLAN.md)

## Klasör yapısı

```
WhiteCoreAI/
├── app/           # Uygulama giriş ve yaşam döngüsü
├── core/          # Ana çekirdek (olaylar, taban sınıflar, orkestrasyon)
├── brain/         # LLM beyin ve sağlayıcılar
├── memory/        # SQLite hafıza
├── skills/        # Yetenekler (sistem, web, dosya, medya…)
├── plugins/       # Harici eklentiler
├── automation/    # Akıllı ajan ve otomasyon
├── voice/         # STT, TTS, wake word
├── gui/           # PySide6 arayüz
├── vision/        # Kamera, OCR, görüntü analizi
├── security/      # Onay, loglama, güvenlik
├── config/        # Ayarlar (config.json)
├── database/      # SQLite dosyaları
├── logs/          # Uygulama logları
├── docs/          # Mimari ve proje planı
├── tests/         # Birim ve entegrasyon testleri
├── mobile/        # iOS / iPadOS / Web köprü iskeleti (+ android yer tutucu)
├── sync/          # Sohbet, dosya, bildirim, bulut senkron iskeleti
├── network/       # Eşleştirme, keşif, WebSocket, cihaz
├── assets/        # İkon, ses, görsel, font
└── main.py        # Ana giriş noktası
```

## Kurulum

```bash
cd WhiteCoreAI
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

## Çalıştırma

```bash
python main.py --gui
```

## İndirme sitesi + telefon

```bash
python website/serve.py
```

- Site: `http://127.0.0.1:8787/`
- **Telefon linki:** `http://127.0.0.1:8787/telefon/`
- GitHub Pages telefon linki:  
  https://yasirerengurleyen-code.github.io/Jarvis/telefon/

Telefonda PC LAN IP + Jarvis’teki 6 haneli kod ile bağlanılır (API key telefona girilmez).

## Geliştirme aşaması

Ayrıntılı yol haritası: [`docs/PLAN.md`](docs/PLAN.md)

## Asistan

| Alan | Değer |
|------|--------|
| Proje | WhiteCore AI |
| Asistan | J.A.R.V.I.S. |
| Wake Word | Jarvis |

## Lisans

Özel proje — geliştirme aşamasında.

# WhiteCore AI – Aşama 4 Planı (PySide6 GUI)

**Durum: ✅ %100 TAMAMLANDI**

Aşama 5+ yalnızca kullanıcı `ONAYLIYORUM` dedikten sonra başlar.
Bu aşamada dosyalar **tek tek** üretilir; her dosya sonrası test + açıklama + `ONAYLIYORUM` beklenir.

## Hedef

Tony Stark tarzı masaüstü arayüz:

- Siyah zemin / cam efekti / yeşil neon
- Sohbet + durum paneli
- Mikrofon ve yapay zekâ animasyonları
- CPU / RAM / GPU / ağ / saat / tarih / hava / sistem bilgisi
- **Bağlı Cihazlar** UI iskeleti (QR / kod butonları — gerçek ağ Aşama 5)

## Klasörler

```
gui/
├── themes/       # Tema + QSS / renkler
├── widgets/      # Widget bileşenleri
├── windows/      # Ana pencere
├── resources/    # Kaynak yardımcıları
└── yoneticisi.py # GUI yöneticisi (sonraki adım)

tests/unit/gui/   # Birim testleri
```

## Dosya sırası (onaylı ilerleme)

| # | Dosya | Durum |
|---|--------|--------|
| 0 | Klasör iskeleti + `docs/ASAMA4.md` | ✅ |
| 1 | `gui/themes/tony_stark.py` | ✅ |
| 2 | `gui/themes/stil.py` | ✅ |
| 3 | `gui/widgets/saat_tarih.py` | ✅ |
| 4 | `gui/widgets/sistem_metrikleri.py` | ✅ |
| 5 | `gui/widgets/hava_durumu.py` | ✅ |
| 6 | `gui/widgets/mikrofon_animasyon.py` | ✅ |
| 7 | `gui/widgets/ai_animasyon.py` | ✅ |
| 8 | `gui/widgets/sohbet_paneli.py` | ✅ |
| 9 | `gui/widgets/cihaz_paneli.py` | ✅ |
| 10 | `gui/windows/ana_pencere.py` | ✅ |
| 11 | `gui/yoneticisi.py` | ✅ |
| 12 | Engine + `main.py` entegrasyonu (`--gui`) | ✅ |
| 13 | Testler + demo | ✅ |

## Bağımlılık

```bash
pip install PySide6
# veya
pip install -r requirements-full.txt
```

PySide6 yoksa GUI modülü kontrollü hata verir; çekirdek (`main.py --demo`) bozulmaz.

## Çalıştırma

```bash
python main.py --gui
python main.py --gui --demo --wait 0.5
```

## Yasaklar

- Skills / Vision / Agent / tam Network runtime — Aşama 5+ onayı olmadan yazılmaz
- Aşama 5 yalnızca kullanıcı `ONAYLIYORUM` dedikten sonra başlar

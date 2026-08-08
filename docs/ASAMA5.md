# WhiteCore AI – Aşama 5 Planı (Skills)

**Durum: ✅ %100 TAMAMLANDI**

Ağ / Sync / iPhone / Ajan yalnızca Skills %100 + `ONAYLIYORUM` sonrası.

## Hedef

Bilgisayar kontrolü yetenekleri (`YetenekTabani`):

- Program açma
- Dosya işlemleri
- Terminal
- PDF
- OCR / Kamera / QR (ince skill sarmalayıcılar)
- Hava durumu
- Web arama
- Takvim / Hatırlatıcı
- Skills yöneticisi + Engine bağlama

## Klasörler

```
skills/
├── system/        # program, terminal
├── files/         # dosya, pdf
├── web/           # arama, hava
├── media/         # kamera, ocr, qr
├── productivity/  # takvim, hatırlatıcı
├── code/          # (iskelet; ajan aşamasında genişler)
├── taban.py       # ortak yardımcılar
└── yoneticisi.py  # Skill Manager
```

## Dosya sırası (onaylı ilerleme)

| # | Dosya | Durum |
|---|--------|--------|
| 0 | Klasör iskeleti + bu plan | ✅ |
| 1 | `skills/taban.py` | ✅ |
| 2 | `skills/yoneticisi.py` | ✅ |
| 3 | `skills/system/program_ac.py` | ✅ |
| 4 | `skills/system/terminal.py` | ✅ |
| 5 | `skills/files/dosya_islemleri.py` | ✅ |
| 6 | `skills/files/pdf_okuyucu.py` | ✅ |
| 7 | `skills/web/arama.py` | ✅ |
| 8 | `skills/web/hava.py` | ✅ |
| 9 | `skills/media/kamera.py` | ✅ |
| 10 | `skills/media/ocr.py` | ✅ |
| 11 | `skills/media/qr_okuyucu.py` | ✅ |
| 12 | `skills/productivity/takvim.py` | ✅ |
| 13 | `skills/productivity/hatirlatici.py` | ✅ |
| 14 | Engine entegrasyonu | ✅ |
| 15 | Testler + demo | ✅ |

## Tamamlanma ölçütü

- [x] 11 varsayılan skill kayıtlı ve Engine’e bağlı
- [x] `tests/unit/skills/**` + `tests/unit/test_engine_asama5.py` geçer
- [x] `python main.py --demo` Skills satırını gösterir (`✓ Skills başlatıldı (11 yetenek)`)
- [x] Tehlikeli skill’ler onay ister (`security.require_confirmation`)
- [x] Ağ / Sync / iPhone / Ajan bu aşamada yazılmadı

## Çalıştırma

```bash
python main.py --demo
python main.py --demo --wait 0.5
# birim testleri
python -m pytest tests/unit/skills tests/unit/test_engine_asama5.py -q
```

## Yasaklar

- `network/pairing/*`, sync runtime, iPhone köprüsü, akıllı ajan — sonraki aşama `ONAYLIYORUM` olmadan yazılmaz
- Tehlikeli skill’ler `security.require_confirmation` ile işaretlenir

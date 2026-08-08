# WhiteCore AI – Aşama 9 Planı (Vision ONLY)

**Durum: ✅ %100 TAMAMLANDI**

PLAN.md sabit sırası: Akıllı Ajan ✅ → **Vision** ✅ → Web / ekosistem (**sonraki aşama, ayrı onay**)

Bu checklist **yalnızca Vision** sistemine odaklanır.  
`plugins/`, Web paneli ve genel ekosistem **bu aşamada yok**; PLAN’da geçseler bile buraya eklenmez — Vision tamamlandıktan sonra ayrı `ONAYLIYORUM` ister.

Dosyalar **tek tek** üretilir; her dosya sonrası test + açıklama + `ONAYLIYORUM`.

## Hedef

Kullanıcı checklist’ine göre görüntü runtime (`vision/`):

| Bölüm | Kapsam |
|-------|--------|
| 📷 Kamera Manager | start/stop, fotoğraf, video akışı, cihaz seçimi, FPS |
| 📝 OCR Manager | Tesseract TR+EN, ön işleme, PDF OCR, ekran görüntüsü OCR |
| 👁️ Görsel Analiz | nesne, sahne, renk, QR, barkod, görsel açıklama |
| 🙂 Yüz | gerçek zamanlı algılama/tanıma, çoklu kullanıcı, kayıt, güven skoru, bilinmeyen, izinler; **LOCAL ONLY**; ayarlar toggle; Türkçe karşılama |
| 🧠 Vision AI | caption, VQA, sayma, multimodal |
| 🔌 Çekirdek köprü | Engine + EventBus + Logger + Config + Exceptions |

Skills aşamasındaki ince sarmalayıcılar (`skills/media/kamera`, `ocr`, `qr_okuyucu`)
**yeniden yazılmaz**; vision runtime onları sarar / köprüler.

## Gizlilik (zorunlu)

- Yüz gömme / şablon verisi **yalnızca yerel diskte** (`database/faces/` vb.)
- Buluta, sync’e veya harici API’ye yüz verisi **gönderilmez**
- Yüz tanıma **ayarlar toggle** ile açılır/kapanır (varsayılan: kapalı veya config’e bağlı)
- Kamera / yüz işleminden önce izin kontrolleri (`vision/yuz/gizlilik.py`)
- Wire JSON’da yüz şablonları taşınmaz; yalnızca güven skoru + görünen ad
- Bilinmeyen yüz → güvenli “tanınmadı” yolu; şablon üretilmez / gönderilmez

## Klasörler

```
vision/
├── modeller.py          # Ortak veri modelleri
├── yoneticisi.py        # Vision Manager (Engine köprüsü)
├── camera/              # Kamera Manager (skills/media/kamera köprüsü)
├── ocr/                 # OCR Manager (skills/media/ocr köprüsü)
├── analiz/              # Nesne / sahne / renk / QR / barkod
├── yuz/                 # Algılama + yerel tanıma + gizlilik + karşılama
└── ai/                  # Vision AI (caption / VQA / sayma / multimodal)

tests/unit/vision/
├── test_modeller.py
├── camera/
├── ocr/
├── analiz/
├── yuz/
└── ai/
```

## Yeniden kullanılan (yeniden yazılmaz)

| Öğe | Durum | Not |
|-----|--------|-----|
| `vision/__init__.py`, `camera/`, `ocr/`, `analiz/` paket stub | ✅ erken | Genişletilir |
| `skills/media/kamera.py` | ✅ Aşama 5 | Listele / aç / foto — vision.camera sarar |
| `skills/media/ocr.py` | ✅ Aşama 5 | Görüntü OCR — vision.ocr sarar |
| `skills/media/qr_okuyucu.py` | ✅ Aşama 5 | QR — vision.analiz.qr sarar |
| `VisionError` (`core/exceptions`) | ✅ çekirdek | Vision hataları buradan |
| EventBus / Logger | ✅ çekirdek | Vision olay + audit yayınlar |
| Network / Sync / iPhone / Ajan | ✅ Aşama 6–8 | Dokunulmaz |
| Web paneli / `plugins/` | ⏸ sonraki aşama | Bu checklist dışı |

## Dosya sırası (onaylı ilerleme)

### 0 — İskelet

| # | Dosya | Bölüm | Durum |
|---|--------|--------|--------|
| 0 | Klasörler (`yuz/`, `ai/`) + `docs/ASAMA9.md` | — | ✅ |

### 1 — Temel modeller

| # | Dosya | Bölüm | Durum |
|---|--------|--------|--------|
| 1 | `vision/modeller.py` | Tüm bölümler (ortak tipler) | ✅ |

Test: `tests/unit/vision/test_modeller.py` ✅

### 📷 Kamera Manager

Kapsam: start/stop, fotoğraf çekme, video akışı, kamera seçimi, FPS ayarı.

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 2 | `vision/camera/kamera.py` | Kamera Manager: start/stop, seçim, fotoğraf, FPS (skill köprüsü) | ✅ |
| 3 | `vision/camera/akis.py` | Video akışı (kare üretimi, FPS, dry_run) | ✅ |

Test: `tests/unit/vision/camera/test_kamera.py` ✅  
Test: `tests/unit/vision/camera/test_akis.py` ✅

Test alanı: `tests/unit/vision/camera/`

### 📝 OCR Manager

Kapsam: Tesseract TR+EN, görüntü ön işleme, PDF OCR, ekran görüntüsü OCR.

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 4 | `vision/ocr/on_isleme.py` | Ön işleme (gri, eşik, gürültü azaltma vb.) | ✅ |
| 5 | `vision/ocr/motor.py` | OCR Manager: Tesseract `tur+eng`, belge/görüntü (skill köprüsü) | ✅ |
| 6 | `vision/ocr/ekran.py` | Ekran görüntüsünden metin | ✅ |
| 7 | `vision/ocr/pdf.py` | PDF OCR | ✅ |

Test: `tests/unit/vision/ocr/test_on_isleme.py` ✅  
Test: `tests/unit/vision/ocr/test_motor.py` ✅  
Test: `tests/unit/vision/ocr/test_ekran.py` ✅  
Test: `tests/unit/vision/ocr/test_pdf.py` ✅  
Test alanı: `tests/unit/vision/ocr/`

### 👁️ Görsel Analiz

Kapsam: nesne, sahne, renk, QR, barkod, kısa görsel açıklama.

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 8 | `vision/analiz/nesne.py` | Nesne algılama | ✅ |
| 9 | `vision/analiz/sahne.py` | Sahne analizi + kısa açıklama | ✅ |
| 10 | `vision/analiz/renk.py` | Renk analizi | ✅ |
| 11 | `vision/analiz/qr.py` | QR + barkod (skill köprüsü) | ✅ |

Test: `tests/unit/vision/analiz/test_nesne.py` ✅  
Test: `tests/unit/vision/analiz/test_sahne.py` ✅  
Test: `tests/unit/vision/analiz/test_renk.py` ✅  
Test: `tests/unit/vision/analiz/test_qr.py` ✅  
Test alanı: `tests/unit/vision/analiz/`

### 🙂 Yüz Algılama ve Tanıma (LOCAL ONLY)

Kapsam: gerçek zamanlı algılama, çoklu kullanıcı kayıt/tanıma, güven skoru,
bilinmeyen yüz, izinler, ayarlar toggle, Türkçe karşılama (“Hoş geldin, …”).
Bulut / sync / harici API yok.

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 12 | `vision/yuz/gizlilik.py` | İzin + gizlilik + local-only + ayarlar toggle | ✅ |
| 13 | `vision/yuz/algilama.py` | Gerçek zamanlı yüz algılama | ✅ |
| 14 | `vision/yuz/kayit.py` | Çoklu kullanıcı kaydı (yerel disk) | ✅ |
| 15 | `vision/yuz/tanima.py` | Tanıma + güven + bilinmeyen + Türkçe karşılama | ✅ |

Test: `tests/unit/vision/yuz/test_gizlilik.py` ✅  
Test: `tests/unit/vision/yuz/test_algilama.py` ✅  
Test: `tests/unit/vision/yuz/test_kayit.py` ✅  
Test: `tests/unit/vision/yuz/test_tanima.py` ✅  
Test alanı: `tests/unit/vision/yuz/` (local-only + toggle + bilinmeyen yolları zorunlu)

### 🧠 Vision AI

Kapsam: caption, görsel soru-cevap (VQA), nesne sayma, multimodal.

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 16 | `vision/ai/aciklama.py` | Caption / görsel açıklama | ✅ |
| 17 | `vision/ai/soru_cevap.py` | Görsel soru-cevap (VQA) | ✅ |
| 18 | `vision/ai/sayma.py` | Nesne sayma | ✅ |
| 19 | `vision/ai/multimodal.py` | Metin + görsel birlikte analiz | ✅ |

Test: `tests/unit/vision/ai/test_aciklama.py` ✅  
Test: `tests/unit/vision/ai/test_soru_cevap.py` ✅  
Test: `tests/unit/vision/ai/test_sayma.py` ✅  
Test: `tests/unit/vision/ai/test_multimodal.py` ✅  
Test alanı: `tests/unit/vision/ai/`

### Orkestrasyon + çekirdek entegrasyon

Kapsam: Vision Manager; Engine; EventBus olayları; Logger/audit; `config.vision`;
`VisionError` kullanımı.

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 20 | `vision/yoneticisi.py` | Vision Manager (alt motorları birleştirir) | ✅ |
| 21 | Engine + EventBus + Logger + Config köprüsü | `vision` bekleyen listeden çıkar; `config.vision`; audit | ✅ |
| 22 | Demo + alan testleri özeti | `main.py --demo` Vision satırı; tüm `tests/unit/vision/**` | ✅ |

Test: `tests/unit/vision/test_yoneticisi.py` ✅  
Test: `tests/unit/test_engine_asama9.py` ✅

## Tamamlanma ölçütü

### Kamera
- [x] start/stop, fotoğraf, akış, cihaz seçimi, FPS çalışır (veya dry_run)

### OCR
- [x] Tesseract TR+EN; ön işleme; PDF OCR; ekran OCR (yoksa dry_run / sahte)

### Görsel Analiz
- [x] Nesne, sahne, renk, QR, barkod, kısa açıklama

### Yüz (local-only)
- [x] Gerçek zamanlı algılama + çoklu kullanıcı kayıt/tanıma
- [x] Güven skoru + bilinmeyen yolu
- [x] İzinler + ayarlar toggle
- [x] Türkçe karşılama: bilinen → `"Hoş geldin, {ad}."` / bilinmeyen → `"Kayıtlı olmayan bir kullanıcı algılandı."`
- [x] Yüz verisi yerel; buluta/sync’e gitmez (gizlilik testleri)
- [x] Wire’da şablon yok

### Vision AI
- [x] Caption, VQA, sayma, multimodal (veya dry_run)

### Çekirdek
- [x] Vision runtime Engine’e bağlı (`vision` bekleyen listeden çıkar)
- [x] EventBus olayları + Logger/audit (`logs/audit.jsonl`)
- [x] `config.vision` (yüz toggle vb.)
- [x] Hatalar `VisionError` / çekirdek istisnaları ile

### Test / demo
- [x] Her alan için `tests/unit/vision/**` geçer
- [x] `python main.py --demo` Vision satırını gösterir
- [x] Skills media sarmalayıcıları çift yazılmadan vision motorunu kullanır (veya dry_run köprü)
- [x] OpenCV / OCR / yüz modeli yoksa `dry_run` / sahte fallback

### Alan testleri özeti (#22)

| Alan | Test yolu | Not |
|------|-----------|-----|
| 📷 Kamera | `tests/unit/vision/camera/` | start/stop, fotoğraf, akış, FPS — dry_run OK |
| 📝 OCR | `tests/unit/vision/ocr/` | ön işleme, motor, ekran, PDF — dry_run/sahte OK |
| 👁️ QR / barkod | `tests/unit/vision/analiz/test_qr.py` | skill köprüsü + dry_run |
| 👁️ Nesne | `tests/unit/vision/analiz/test_nesne.py` | dry_run/sahte OK |
| 🙂 Yüz algılama | `tests/unit/vision/yuz/test_algilama.py` | local-only + izin |
| 🙂 Yüz tanıma | `tests/unit/vision/yuz/test_tanima.py` | güven, bilinmeyen, TR karşılama |
| 🧠 Vision AI | `tests/unit/vision/ai/` | caption / VQA / sayma / multimodal |
| 🔌 Engine | `tests/unit/test_engine_asama9.py` | köprü + demo Vision satırı |

### Bu aşamada yok
- [x] Web paneli / SPA — **ertelendi** (sonraki aşama)
- [x] `plugins/` ekosistemi — **ertelendi** (sonraki aşama)

## Çalıştırma

```bash
set PYTHONIOENCODING=utf-8
C:\Users\yasir\WhiteCoreAI\.venv\Scripts\python.exe -m pytest tests/unit/vision -q
python main.py --demo
```

## Notlar

- OpenCV / Pillow / pytesseract / yüz modelleri isteğe bağlı; yoksa `dry_run` / sahte
- `config.vision` Engine köprüsünde eklenir (yüz tanıma toggle dahil)
- Audit: kamera / OCR / yüz tanıma `logs/audit.jsonl`
- Wire JSON anahtarları İngilizce (olay / sync stili)
- Yüz şablonları wire’a serilmez
- Karşılama metinleri Türkçe

## Yasaklar

- Skills media’yı silip yeniden yazmak — yasak; köprüle
- Yüz verisini buluta / sync’e / harici API’ye göndermek — yasak
- Web SPA / `plugins/` bu checklist’e eklemek — yasak (ayrı aşama + `ONAYLIYORUM`)
- PLAN dışı yeni aşama numarası icat etmek
- Onaysız birden fazla dosya üretmek

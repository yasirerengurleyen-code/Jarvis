# WhiteCore AI – Aşama 6 Planı (Ağ Eşleştirme + Sync)

**Durum: ✅ TAMAMLANDI (%100)**

PLAN.md sabit sırası: Skills ✅ → **Ağ + Sync** ✅ → iPhone → Akıllı Ajan.

Dosyalar **tek tek** üretildi; her dosya sonrası test + açıklama + `ONAYLIYORUM`.

## Hedef

Windows host üzerinde:

- QR + 6 haneli kod ile eşleştirme (token tabanlı)
- Bağlı cihaz kaydı / çevrimiçi-çevrimdışı
- Yerel keşif iskeletinin doldurulması
- WebSocket protokol iskeletinin çalışır hale gelmesi
- Sohbet / dosya / bildirim / bulut sync uygulamaları (yerel runtime)
- GUI `CihazPaneli` ile köprü
- Engine `network.runtime` + `sync.runtime` aktifleştirme

iOS / Web istemcileri sonraki aşamada; bu aşamada **sunucu / host tarafı**.

## Klasörler

```
network/
├── device/       # Cihaz modeli + yönetici
├── pairing/      # QR / kod / token eşleştirme
├── discovery/    # Yerel ağ keşfi
├── websocket/    # WS sunucu / istemci
└── yoneticisi.py # Network Manager

sync/
├── chat/         # Sohbet senkronu
├── files/        # Dosya paylaşımı
├── notifications/# Bildirim köprüsü
├── cloud/        # Bulut yedek
└── yoneticisi.py # Sync Manager

tests/unit/network/
tests/unit/sync/
```

## Dosya sırası (onaylı ilerleme)

| # | Dosya | Durum |
|---|--------|--------|
| 0 | Klasör iskeleti + `docs/ASAMA6.md` | ✅ |
| 1 | `network/device/yonetici.py` | ✅ (erken; yeniden kullanıldı) |
| 2 | `network/pairing/token.py` | ✅ (erken; yeniden kullanıldı) |
| 3 | `network/pairing/servis.py` | ✅ |
| 4 | `network/discovery/kesif.py` | ✅ |
| 5 | `network/websocket/protokol.py` | ✅ |
| 6 | `network/websocket/sunucu.py` | ✅ |
| 7 | `sync/chat/senkron.py` | ✅ |
| 8 | `sync/files/paylasim.py` | ✅ |
| 9 | `sync/notifications/bildirim.py` | ✅ |
| 10 | `sync/cloud/yedek.py` | ✅ |
| 11 | `network/yoneticisi.py` | ✅ |
| 12 | `sync/yoneticisi.py` | ✅ |
| 13 | Engine + GUI köprüsü | ✅ |
| 14 | Testler + demo | ✅ |

## Tamamlanma ölçütü

- [x] Network + Sync runtime Engine’e bağlı (`network.runtime`, `sync.runtime`)
- [x] `tests/unit/network/**` + `tests/unit/sync/**` + `tests/unit/test_engine_asama6.py` geçer
- [x] `python main.py --demo` Network/Sync satırlarını gösterir  
  (`✓ Network başlatıldı (... cihaz, ws=...)`, `✓ Sync başlatıldı (... modül)`)
- [x] GUI `CihazPaneli` köprüsü (Aşama 6 #13)
- [x] iPhone / Akıllı Ajan bu aşamada yazılmadı

## Çalıştırma

```bash
python main.py --demo
python main.py --demo --wait 0.5
# birim testleri
python -m pytest tests/unit/network tests/unit/sync tests/unit/test_engine_asama6.py -q
```

## Notlar

- Erken iskeletler (`network/device/modeller.py`, `network/pairing/arayuzler.py`, `sync/arayuzler.py`) korunur
- `websockets` / `qrcode` isteğe bağlı; yoksa bellek içi / sahte mod
- Audit: eşleştirme ve cihaz olayları `logs/audit.jsonl`
- Eski pause notu: `docs/ASAMA_AG_ERTELENDI.md` (artık ASAMA6’ya yönlendirir)

## Yasaklar

- iPhone / iPadOS / Web istemci uygulaması — sonraki aşama
- Android — ertelenmiş
- Akıllı Ajan — ayrı `ONAYLIYORUM` olmadan yazılmaz

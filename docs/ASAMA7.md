# WhiteCore AI – Aşama 7 Planı (iPhone Entegrasyonu)

**Durum: ✅ %100 TAMAMLANDI**

PLAN.md sabit sırası: Ağ + Sync ✅ → **iPhone Entegrasyonu** ✅ → Akıllı Ajan (ayrı onay).

Dosyalar **tek tek** üretilir; her dosya sonrası test + açıklama + `ONAYLIYORUM`.

## Hedef

Windows host üzerinde iPhone istemci köprüsünü çalışır hale getirmek:

- PC ↔ iPhone komut sözleşmesi (Telefonumu Bul, pil, bildirim, …)
- `MobilKopru` gerçek uygulaması (Aşama 6 ağ/sync üzerine)
- iOS istemci iskeleti (`PlatformIstemciTabani`)
- Shortcuts / companion köprü sözleşmesi
- Mobile Manager + Engine `mobile.iphone_bridge` aktifleştirme
- GUI cihaz paneli ile iPhone komut köprüsü

Bu aşamada **native Swift/UIKit uygulaması yazılmaz**; Python tarafı protokol + köprü + istemci iskeleti.

Akıllı Ajan bu aşamada yazılmaz.

## Klasörler

```
mobile/
├── bridge/          # Ortak köprü arayüzleri + komut sözleşmesi
├── ios/             # iPhone istemci iskeleti
├── ipados/          # iPad (iOS çekirdeği ile paylaşır; ince sarmalayıcı)
├── web/             # Web paneli iskeleti (aynı sözleşme)
├── android/         # Yer tutucu (v1'de kodlanmaz)
└── yoneticisi.py    # Mobile Manager

tests/unit/mobile/
```

## Dosya sırası (onaylı ilerleme)

| # | Dosya | Durum |
|---|--------|--------|
| 0 | Klasör iskeleti + `docs/ASAMA7.md` | ✅ |
| 1 | `mobile/bridge/arayuzler.py` | ✅ (erken; yeniden kullanıldı) |
| 2 | `mobile/bridge/komutlar.py` | ✅ |
| 3 | `mobile/ios/modeller.py` | ✅ |
| 4 | `mobile/ios/istemci.py` | ✅ |
| 5 | `mobile/ios/kopru.py` | ✅ |
| 6 | `mobile/ios/shortcuts.py` | ✅ |
| 7 | `mobile/yoneticisi.py` | ✅ |
| 8 | Engine + GUI köprüsü | ✅ |
| 9 | Testler + demo | ✅ |

## Tamamlanma ölçütü

- [x] Mobile runtime Engine’e bağlı (`mobile.iphone_bridge` bekleyen listeden çıkar)
- [x] `tests/unit/mobile/**` + `tests/unit/test_engine_asama7.py` geçer
- [x] `python main.py --demo` Mobile / iPhone satırını gösterir  
  (`✓ Mobile / iPhone başlatıldı (motor=dry_run, primary=ios, N istemci)`)
- [x] Telefonumu Bul / pil / bildirim komutları köprü üzerinden çalışır (bellek içi / sahte istemci kabul)
- [x] Akıllı Ajan bu aşamada yazılmadı

## Çalıştırma

```bash
python main.py --demo
python main.py --demo --wait 0.5
# birim testleri
python -m pytest tests/unit/mobile tests/unit/test_engine_asama7.py -q
```

## Notlar

- Erken iskeletler korunur: `mobile/bridge/arayuzler.py`, `PlatformIstemciTabani`, olaylar (`OLAY_IPHONE_*`)
- Aşama 6 `network.*` + `sync.*` yeniden kullanılır; çift yazılmaz
- `config.mobile.commands` komut listesinin kaynağıdır
- Demo için `mobile.enabled/bridge_enabled=true` + `mobile.dry_run=true` (gerçek iPhone gerekmez)
- Tehlikeli `phone_to_pc` komutlarında `security.require_confirmation` / Windows onayı
- Audit: mobil komutlar `logs/audit.jsonl`

## Yasaklar

- Akıllı Ajan — ayrı `ONAYLIYORUM` olmadan yazılmaz
- Android native uygulama — ertelenmiş
- Tam Swift/Xcode iOS uygulaması — sonraki sürüm; bu aşamada Python iskelet + sözleşme

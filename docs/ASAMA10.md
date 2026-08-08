# WhiteCore AI – Aşama 10 Planı (Web / ekosistem)

**Durum: 🔄 DEVAM EDİYOR**

PLAN.md sabit sırası: Vision ✅ → **Web / ekosistem** 🔄  
(`plugins/` eklenti sistemi + `mobile/web` Web paneli)

Dosyalar **tek tek** üretilir; her dosya sonrası test + açıklama + `ONAYLIYORUM`.

## Hedef

Windows host üzerinde ekosistemi genişletmek:

| Bölüm | Kapsam |
|-------|--------|
| 🔌 Plugins | Harici eklenti keşfi / yükleme / sandbox; ana sistem değişmeden yeni özellik |
| 🌐 Web Paneli | Tarayıcı istemci iskeleti (`mobile/web`): yönetim + sohbet; HTTP/WS sözleşmesi |
| 🔗 Çekirdek köprü | Engine `plugins` bekleyen listeden çıkar; ajan PLUGIN yürütme; EventBus / Config |

Orijinal brief: *yeni özellik için yalnızca yeni plugin dosyası yeterli olsun; ana sistem değişmeden çalışsın.*

Web paneli tam SPA/React **yazılmaz**; Python tarafı istemci + panel/HTTP iskeleti
(Aşama 6 network + Aşama 7 mobil köprü sözleşmeleri yeniden kullanılır).

## Klasörler

```
plugins/
├── modeller.py       # Manifest / durum / sonuç modelleri
├── taban.py          # PluginTabani sözleşmesi
├── guvenlik.py       # allow/deny + sandbox
├── yukleyici.py      # Dizin keşfi / autoload
├── yoneticisi.py     # Plugin Manager (Engine)
└── ornek/            # Örnek eklenti(ler)

mobile/web/
├── modeller.py       # Web oturum / panel modelleri
├── istemci.py        # PlatformIstemciTabani (web)
├── panel.py          # HTTP yönetim / sohbet paneli iskeleti
└── kopru.py          # Web ↔ çekirdek köprü

tests/unit/plugins/
tests/unit/mobile/web/
```

## Yeniden kullanılan (yeniden yazılmaz)

| Öğe | Durum | Not |
|-----|--------|-----|
| `plugins/__init__.py`, `tests/unit/plugins/` | ✅ erken stub | Genişletilir |
| `mobile/web/__init__.py` | ✅ erken stub | Genişletilir |
| `PluginError`, `OLAY_PLUGIN_*` | ✅ çekirdek | Kullanılır |
| `config.plugins` + `security.sandbox_plugins` | ✅ config | Kullanılır |
| `network.*` HTTP/WS + `mobile.bridge` | ✅ Aşama 6–7 | Web paneli bağlanır |
| `AracTuru.PLUGIN` (ajan) | ✅ Aşama 8 iskelet | Bu aşamada bağlanır |
| Vision / Skills media | ✅ | Dokunulmaz |

## Dosya sırası (onaylı ilerleme)

### 0 — İskelet

| # | Dosya | Bölüm | Durum |
|---|--------|--------|--------|
| 0 | Klasörler (`plugins/ornek/`, `tests/unit/mobile/web/`) + `docs/ASAMA10.md` | — | ✅ |

### 🔌 Plugins

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 1 | `plugins/modeller.py` | Manifest, durum, sonuç, wire JSON | ✅ |
| 2 | `plugins/taban.py` | `PluginTabani` yaşam döngüsü + `calistir` | ✅ |
| 3 | `plugins/guvenlik.py` | allow/deny listesi, sandbox bayrağı | ✅ |
| 4 | `plugins/yukleyici.py` | Dizin tarama, autoload, dry_run | ⬜ |
| 5 | `plugins/yoneticisi.py` | Plugin Manager (EventBus / audit) | ⬜ |
| 6 | `plugins/ornek/merhaba.py` | Örnek eklenti (drop-in kanıtı) | ⬜ |

Test: `tests/unit/plugins/test_modeller.py` ✅  
Test: `tests/unit/plugins/test_taban.py` ✅  
Test: `tests/unit/plugins/test_guvenlik.py` ✅  
Test alanı: `tests/unit/plugins/`

### 🌐 Web Paneli

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 7 | `mobile/web/modeller.py` | Web oturum / panel durum modelleri | ⬜ |
| 8 | `mobile/web/istemci.py` | `PlatformIstemciTabani` web istemci | ⬜ |
| 9 | `mobile/web/panel.py` | HTTP yönetim + sohbet paneli iskeleti | ⬜ |
| 10 | `mobile/web/kopru.py` | Web ↔ network/mobile köprü | ⬜ |

Test alanı: `tests/unit/mobile/web/`

### 🔗 Köprü + kapanış

| # | Dosya | Kapsam | Durum |
|---|--------|--------|--------|
| 11 | Engine + ajan PLUGIN köprüsü + `config.mobile.platforms.web` | Entegrasyon | ⬜ |
| 12 | Testler + demo | `test_engine_asama10` + demo satırları | ⬜ |

## Tamamlanma ölçütü

- [ ] Plugin runtime Engine’e bağlı (`plugins` bekleyen listeden çıkar)
- [ ] Yeni eklenti dosyası drop-in yüklenebilir (`config.plugins.autoload`)
- [ ] `security.sandbox_plugins` / allow-deny uygulanır
- [ ] Ajan `AracTuru.PLUGIN` yürütmesi bağlanır (dry_run kabul)
- [ ] Web paneli iskeleti HTTP/WS üzerinden sohbet/yönetim stub’ı sunar
- [ ] `tests/unit/plugins/**` + `tests/unit/mobile/web/**` + `test_engine_asama10` geçer
- [ ] `python main.py --demo` Plugins + Web satırlarını gösterir

## Çalıştırma

```bash
set PYTHONIOENCODING=utf-8
C:\Users\yasir\WhiteCoreAI\.venv\Scripts\python.exe -m pytest tests/unit/plugins -q
python main.py --demo
```

## Notlar

- Wire JSON anahtarları İngilizce (olay / sync stili)
- Tehlikeli eklenti eylemlerinde `security.require_confirmation`
- Audit: plugin yükle / kaldır / hata → `logs/audit.jsonl`
- Web paneli native SPA sonraki sürüm; bu aşamada Python iskelet
- `config.plugins`: `enabled`, `directory`, `autoload`, `allow_list`, `deny_list`
- Demo için dry_run / sahte kabul (gerçek tarayıcı zorunlu değil)

## Yasaklar

- Vision / Skills yeniden yazmak — yasak
- Android native — ertelenmiş
- Tam React/Vue SPA — sonraki sürüm; bu aşamada iskelet
- Onaysız birden fazla dosya üretmek
- PLAN dışı aşama numarası icat etmek

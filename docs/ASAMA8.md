# WhiteCore AI – Aşama 8 Planı (Akıllı Ajan)

**Durum: ✅ %100 TAMAMLANDI**

PLAN.md sabit sırası: iPhone ✅ → **Akıllı Ajan** ✅ → Vision / ekosistem (ayrı onay).

Dosyalar **tek tek** üretilir; her dosya sonrası test + açıklama + `ONAYLIYORUM`.

## Hedef

Brain + Skills üzerine görev orkestrasyonu:

- Görev planlama (çok adımlı plan)
- Araç / skill seçimi
- Çok adımlı yürütme
- Hata düzeltme + karar mekanizması
- Plugin çağırma köprüsü (iskelet)
- `automation` runtime’ı Engine’e bağlama

Örnek senaryo: *"Yeni Python projesi oluştur"* → klasör → git → venv → README → editör.

Bu aşamada Vision / Web ekosistemi yazılmaz.

## Klasörler

```
automation/
├── agents/          # Plan modelleri, planlayıcı, araç seçici, yürütücü, karar, ajan
└── yoneticisi.py    # Automation Manager

tests/unit/automation/
```

## Dosya sırası (onaylı ilerleme)

| # | Dosya | Durum |
|---|--------|--------|
| 0 | Klasör iskeleti + `docs/ASAMA8.md` | ✅ |
| 1 | `automation/agents/modeller.py` | ✅ |
| 2 | `automation/agents/planlayici.py` | ✅ |
| 3 | `automation/agents/arac_secici.py` | ✅ |
| 4 | `automation/agents/yurutucu.py` | ✅ |
| 5 | `automation/agents/karar.py` | ✅ |
| 6 | `automation/agents/ajan.py` | ✅ |
| 7 | `automation/yoneticisi.py` | ✅ |
| 8 | Engine + olay köprüsü | ✅ |
| 9 | Testler + demo | ✅ |

## Tamamlanma ölçütü

- [x] Automation runtime Engine’e bağlı (`automation` bekleyen listeden çıkar)
- [x] `tests/unit/automation/**` + `tests/unit/test_engine_asama8.py` geçer
- [x] `python main.py --demo` Akıllı Ajan / Automation satırını gösterir  
  (`✓ Automation / Akıllı Ajan başlatıldı (motor=…, max_steps=N)`)
- [x] Çok adımlı plan dry_run ile çalışır (`config.automation.max_plan_steps`)
- [x] Tehlikeli çok adımlı işlerde `confirm_multi_step` / güvenlik onayı
- [x] Vision bu aşamada yazılmadı

## Çalıştırma

```bash
python main.py --demo
python main.py --demo --wait 0.5
# birim testleri
python -m pytest tests/unit/automation tests/unit/test_engine_asama8.py -q
```

## Notlar

- Paket kökü: `automation/` (README ile uyumlu); ajan kodu `automation/agents/`
- `config.automation`: `enabled`, `smart_agent`, `max_plan_steps`, `confirm_multi_step`
- Olay: `OLAY_AJAN_PLAN` (`brain.ajan_plan`) — plan yayınları
- Skills (`YetenekTabani`) ajan tarafından seçilir / zincirlenir; skill’ler yeniden yazılmaz
- `skills/code/` iskeleti ajan senaryolarında (proje oluşturma) genişletilebilir — ayrı onaylı dosya
- Audit: çok adımlı / tehlikeli planlar `logs/audit.jsonl`

## Yasaklar

- Vision / kamera pipeline — sonraki aşama (`ONAYLIYORUM` olmadan yazılmaz)
- Tam otonom tehlikeli sistem komutları — `security.require_confirmation` zorunlu
- Ağ / iPhone yeniden yazımı — Aşama 6–7 üzerine inşa edilir

# WhiteCore AI – Proje Planı ve Mimari

## Asistan

| Alan | Değer |
|------|--------|
| Proje | WhiteCore AI |
| Asistan | J.A.R.V.I.S. |
| Wake Word | Jarvis |
| Ana platform | Windows |

---

## Çoklu platform desteği

### Öncelik sırası

1. **Windows** — Ana masaüstü sistemi (PySide6)
2. **iPhone (iOS)** — Birincil mobil istemci
3. **iPad (iPadOS)** — Tablet istemci (iOS çekirdeği ile paylaşır)
4. **Web Paneli** — Tarayıcı üzerinden yönetim / sohbet

### Bilinçli olarak ertelenenler

- **Android** — İlk sürümde geliştirilmez. Aynı `mobile/` köprü arayüzleri
  ve protokol sözleşmeleri üzerinden sonradan eklenebilir.

### Ortak çekirdek ilkesi

Tüm istemciler (Windows GUI, iOS, iPadOS, Web) aynı Python çekirdeğine
(`core/`, `brain/`, `memory/`, `skills/`) HTTP/WebSocket protokolü ile bağlanır.
Platforma özel kod yalnızca ince istemci katmanlarında yaşar.

```
┌─────────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐
│  Windows UI │  │  iPhone  │  │   iPad   │  │   Web   │
└──────┬──────┘  └────┬─────┘  └────┬─────┘  └────┬────┘
       │              │             │             │
       └──────────────┴──────┬──────┴─────────────┘
                             │  HTTPS + WebSocket
                             ▼
              ┌──────────────────────────────┐
              │     WhiteCore AI Çekirdek     │
              │  (Windows host / sunucu rolü) │
              └──────────────────────────────┘
```

---

## Windows ↔ iPhone bağlantı özellikleri

| Özellik | v0.1 (iskelet) | Sonraki sürümler |
|---------|----------------|------------------|
| QR kod ile eşleştirme | Arayüz + klasör | Tam uygulama |
| 6 haneli eşleştirme kodu | Arayüz + klasör | Tam uygulama |
| Güvenli HTTPS / WebSocket | Protokol iskeleti | TLS + token |
| Sohbet geçmişi senkronu | Sync arayüzü | Çift yönlü sync |
| Dosya paylaşımı | Sync arayüzü | Transfer + izinler |
| Bildirim gönderme | Komut sözleşmesi | Push / yerel |
| Telefonumu Bul | Komut sözleşmesi | Ses / titreşim |
| Pil durumu | Komut sözleşmesi | Canlı durum |
| Bağlantı durumu | Cihaz modeli | Heartbeat |
| Çoklu cihaz | Cihaz yöneticisi iskeleti | N cihaz |

Android aynı sözleşmeleri (`mobile.bridge`, `network.pairing`, `sync.*`)
uygulayarak eklenecektir; çekirdek değişmeden genişler.

---

## Klasörler (platform / senkron)

```
mobile/
├── bridge/       # Ortak köprü arayüzleri
├── ios/          # iPhone istemci iskeleti
├── ipados/       # iPad istemci iskeleti
├── web/          # Web paneli iskeleti
└── android/      # Yer tutucu (v1'de kodlanmaz)

sync/
├── cloud/        # Bulut yedekleme iskeleti
├── chat/         # Sohbet geçmişi senkronu
├── files/        # Dosya paylaşımı
└── notifications/# Bildirim köprüsü

network/
├── pairing/      # QR + 6 haneli kod eşleştirme
├── discovery/    # Yerel ağ keşfi
├── websocket/    # WS sunucu/istemci iskeleti
└── device/       # Bağlı cihaz modeli
```

---

## Geliştirme aşamaları (sabit sıra — atlanmaz)

0. **Kurulum** ✅  
1. **Çekirdek** ✅  
2. **Brain + Memory** ✅  
3. **Voice** ✅  
4. **GUI (PySide6)** ✅  
5. **Skills** ✅  
6. **Ağ Eşleştirme + Sync** ✅ (`docs/ASAMA6.md`)  
7. **iPhone Entegrasyonu** ✅ (`docs/ASAMA7.md`)  
8. **Akıllı Ajan** ✅ (`docs/ASAMA8.md`)  
9. **Vision** ✅ (`docs/ASAMA9.md`)  
10. **Web / ekosistem** 🔄 (`docs/ASAMA10.md`) — `plugins/` + Web paneli (`mobile/web`)

---

## Güvenlik notları

- Eşleştirme token tabanlı olacak
- Tehlikeli uzaktan komutlarda Windows tarafında onay istenecek
- Tüm kritik işlemler `logs/audit.jsonl` dosyasına yazılacak

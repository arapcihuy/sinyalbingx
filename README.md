---
title: jneaf-bot
emoji: 🤖
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# 🤖 BingX Auto-Trading Bot — TradingView Webhook Bridge

Sistem penghubung sinyal **Pine Script TradingView** ke **BingX Futures** secara otomatis. Dibangun dengan Python & Flask untuk eksekusi order instan, manajemen leverage dinamis, dan notifikasi Telegram real-time.

---

## ✨ Fitur Utama

- **⚡ Eksekusi Instan:** Menghubungkan webhook TradingView langsung ke API BingX V2.
- **🔄 Auto-Reversal:** Menutup posisi berlawanan secara otomatis sebelum membuka posisi baru.
- **📱 Telegram Control:** Pantau saldo, ubah leverage, dan terima laporan PnL langsung di Telegram.
- **🚀 Cloud Ready:** Teroptimasi untuk deployment di **Railway.app** (Bypass blokir ISP lokal).
- **🛡️ Aman & Privat:** Validasi `REDACTED_WEBHOOK_SECRET` dan enkripsi API Key via Environment Variables.

---

## 📁 Struktur Proyek

```text
sinyalbingx/
├── webhook_server.py    ← Server Flask & Handler Webhook
├── order_manager.py     ← Logika Eksekusi & Kalkulasi Order
├── bingx_client.py      ← Client API BingX (V2 Perpetual)
├── settings_manager.py  ← Manajemen konfigurasi runtime
├── deploy_railway.sh    ← Script deployment otomatis
├── requirements.txt     ← Daftar dependensi
└── README.md            ← Dokumentasi (Anda di sini)
```

---

## 🚀 Panduan Deployment (Rekomendasi: Railway)

Gunakan **Railway** untuk kestabilan 24/7 dan menghindari pemblokiran API oleh ISP lokal.

### 1) Persiapan Environment Variables

Atur variabel berikut di Dashboard Railway:

| Key | Contoh Nilai | Deskripsi |
| --- | --- | --- |
| `BINGX_API_KEY` | `...` | API Key dari BingX |
| `BINGX_API_SECRET` | `...` | API Secret dari BingX |
| `REDACTED_WEBHOOK_SECRET` | `Tr4d3Bot...` | Password untuk keamanan webhook |
| `TELEGRAM_BOT_TOKEN` | `...` | Token dari @BotFather |
| `TELEGRAM_CHAT_ID` | `...` | Chat ID Telegram Anda |
| `WEBHOOK_URL` | `https://app-name.up.railway.app` | URL Publik Railway Anda |
| `AUTO_ENTRY` | `true` | Set true untuk eksekusi otomatis |

### 2) Deployment Otomatis

Jalankan script berikut di terminal lokal Anda:

```bash
chmod +x deploy_railway.sh
./deploy_railway.sh
```

---

## 🔔 Integrasi TradingView

### 1) Tambahkan Addon Webhook ke Pine Script

Pastikan strategi Anda mengirim payload JSON ke URL Webhook Railway Anda:
`https://app-name.up.railway.app/webhook`

### 2) Format Payload JSON (Contoh BUY)

```json
{
  "secret": "YOUR_SECRET",
  "action": "BUY",
  "symbol": "BTC-USDT",
  "price": {{close}},
  "tp1": 96000,
  "sl": 94000
}
```

---

## 📱 Perintah Telegram

- `/status` — Cek saldo USDT dan posisi aktif saat ini.
- `/leverage <angka>` — Ubah leverage secara dinamis (1x - 150x).
- `/report` — Laporan performa trading 24 jam terakhir.
- `/panic` — **Emergency Button!** Tutup semua posisi dan batalkan semua order.
- `/log` — Intip 15 baris aktivitas bot terakhir.

---

## ⚠️ Disclaimer

Gunakan bot ini dengan bijak. Selalu uji coba di akun **Demo/Testnet** sebelum menggunakan dana riil. Penulis tidak bertanggung jawab atas kerugian finansial yang mungkin terjadi akibat kesalahan konfigurasi atau malfungsi sistem.

# 🤖 BingX Auto-Trading Bot — TradingView Webhook Bridge

Sistem ini menghubungkan sinyal Pine Script di TradingView ke BingX Futures secara otomatis.  
Setiap sinyal BUY/SELL → otomatis buka order + pasang TP & SL di BingX.

---

## 📁 Struktur File

```
sinyalbingx/
├── webhook_server.py          ← Server utama (jalankan ini)
├── bingx_client.py            ← BingX API client
├── order_manager.py           ← Kalkulasi lot & eksekusi order
├── pine_script_alert_template.pine  ← Template untuk Pine Script
├── .env                       ← Konfigurasi rahasia (ISI INI DULU)
├── .env.example               ← Contoh konfigurasi
├── requirements.txt           ← Python dependencies
└── bot.log                    ← Log otomatis saat bot berjalan
```

---

## 🚀 SETUP STEP BY STEP

### LANGKAH 1 — Isi file `.env`

Buka file `.env` dan isi:

```env
BINGX_API_KEY=isi_api_key_dari_bingx
BINGX_API_SECRET=isi_secret_key_dari_bingx
WEBHOOK_SECRET=buat_password_acak_misal_tr4d3b0t2025
SYMBOL=BTC-USDT
LEVERAGE=10
RISK_PERCENT=1.5
TP_SL_MODE=pinescript   # atau "percent"
ORDER_TYPE=MARKET
```

**Cara dapat API Key BingX:**
1. Login BingX → klik foto profil → **API Management**
2. Klik **Create API**
3. Beri nama, aktifkan: ✅ **Trade Futures**
4. **JANGAN** aktifkan Withdraw
5. Salin API Key & Secret

---

### LANGKAH 2 — Install dependensi Python

Buka Terminal, jalankan:

```bash
cd /Users/mac/sinyalbingx
python3 -m venv venv
source venv/bin/activate
pip install flask python-dotenv requests
```

---

### LANGKAH 3 — Jalankan bot

```bash
cd /Users/mac/sinyalbingx
source venv/bin/activate
python3 webhook_server.py
```

Jika berhasil, akan muncul:
```
🚀 BingX Webhook Bot berjalan di http://0.0.0.0:5000
   Endpoint webhook: http://0.0.0.0:5000/webhook
```

---

### LANGKAH 4 — Buat URL publik dengan ngrok

TradingView perlu URL yang bisa diakses dari internet.

**Install ngrok** (jika belum):
```bash
brew install ngrok
```

**Daftarkan akun gratis** di https://ngrok.com → salin authtoken:
```bash
ngrok config add-authtoken TOKEN_ANDA
```

**Jalankan ngrok** (di terminal terpisah):
```bash
ngrok http 5000
```

Akan muncul URL seperti:
```
Forwarding  https://abc123.ngrok-free.app → http://localhost:5000
```

**Salin URL ini** → akan dipakai di TradingView.

---

### LANGKAH 5 — Setup Alert di TradingView

1. Buka TradingView → chart dengan Pine Script Anda
2. Buka Pine Script editor → tambahkan `alertcondition` (lihat `pine_script_alert_template.pine`)
3. Klik ikon **🔔 Alerts** → **Create Alert**
4. **Condition**: pilih strategi Anda → pilih sinyal BUY/SELL
5. **Notifications** → centang **Webhook URL**
6. **Webhook URL**: `https://abc123.ngrok-free.app/webhook`
7. **Message**: isi JSON ini (ganti YOUR_SECRET):

**Untuk BUY:**
```json
{"secret":"YOUR_SECRET","action":"BUY","symbol":"BTC-USDT","price":{{close}},"tp":{{plot("TP")}},"sl":{{plot("SL")}}}
```

**Untuk SELL:**
```json
{"secret":"YOUR_SECRET","action":"SELL","symbol":"BTC-USDT","price":{{close}},"tp":{{plot("TP")}},"sl":{{plot("SL")}}}
```

> ⚠️ Jika Pine Script Anda tidak punya plot TP/SL, gunakan `TP_SL_MODE=percent` di `.env` — server akan hitung otomatis.

---

### LANGKAH 6 — Test koneksi

Test manual dari Terminal:

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"password_anda","action":"BUY","symbol":"BTC-USDT","price":95000,"tp":97850,"sl":93500}'
```

Cek log di `bot.log` untuk memantau aktivitas.

---

## ⚠️ PERINGATAN PENTING

- Selalu test di akun **demo/testnet** dulu sebelum live
- Pastikan balance cukup untuk posisi yang dikalkulasi
- API Key hanya izin **Trade** — jangan aktifkan Withdraw
- Simpan `WEBHOOK_SECRET` yang kuat dan unik
- Jika ngrok gratis, URL berubah setiap restart → update di TradingView

---

## 📊 Format Payload Webhook Lengkap

```json
{
  "secret": "password_rahasia",
  "action": "BUY",          // BUY | SELL | CLOSE
  "symbol": "BTC-USDT",
  "price": 95000,           // harga entry (opsional, default = harga pasar)
  "tp": 97850,              // take profit price (jika TP_SL_MODE=pinescript)
  "sl": 93500               // stop loss price (jika TP_SL_MODE=pinescript)
}
```

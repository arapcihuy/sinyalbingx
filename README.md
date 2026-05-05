# 🤖 BingX Auto-Trading Bot — TradingView Webhook Bridge

Sistem ini menghubungkan sinyal Pine Script di TradingView ke BingX Futures secara otomatis.
Setiap sinyal BUY/SELL bisa membuka order dan memasang TP/SL di BingX.

---

## 📁 Struktur File

```text
sinyalbingx/
├── webhook_server.py              ← Server utama (jalankan ini)
├── bingx_client.py                ← BingX API client
├── order_manager.py               ← Kalkulasi lot & eksekusi order
├── clear_menu_task.py             ← Utility hapus menu Telegram
├── requirements.txt               ← Python dependencies
├── runtime.txt                    ← Versi runtime
├── README.md                      ← Dokumentasi proyek
└── bot.log                        ← Log otomatis saat bot berjalan
```

---

## 🚀 Setup

### 1) Isi file `.env`

```env
BINGX_API_KEY=isi_api_key_dari_bingx
BINGX_API_SECRET=isi_secret_key_dari_bingx
WEBHOOK_SECRET=buat_password_acak_misal_tr4d3b0t2025
SYMBOL=BTC-USDT
LEVERAGE=10
AUTO_ENTRY=false
RISK_PERCENT=1.5
TP_SL_MODE=pinescript
ORDER_TYPE=MARKET
WEBHOOK_DEDUP_TTL_SECONDS=45
```

**Cara dapat API Key BingX:**

1. Login BingX → klik foto profil → **API Management**
2. Klik **Create API**
3. Beri nama, aktifkan ✅ **Trade Futures**
4. **JANGAN** aktifkan Withdraw
5. Salin API Key & Secret

### 2) Install dependensi

```bash
cd /Users/mac/sinyalbingx
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3) Jalankan bot

```bash
cd /Users/mac/sinyalbingx
source venv/bin/activate
python3 webhook_server.py
```

Jika berhasil, akan muncul:

```text
🚀 BingX Webhook Bot berjalan di http://0.0.0.0:5000
   Endpoint webhook: http://0.0.0.0:5000/webhook
   Healthcheck: http://0.0.0.0:5000/health
```

### 4) Buat URL publik dengan ngrok

TradingView perlu URL yang bisa diakses dari internet.

**Install ngrok** (jika belum):

```bash
brew install ngrok
```

**Daftarkan akun gratis** di [ngrok.com](https://ngrok.com) → salin authtoken:

```bash
ngrok config add-authtoken TOKEN_ANDA
```

**Jalankan ngrok** (di terminal terpisah):

```bash
ngrok http 5000
```

Akan muncul URL seperti:

```text
Forwarding  https://abc123.ngrok-free.app → http://localhost:5000
```

### 5) Setup alert di TradingView

1. Buka TradingView → chart dengan Pine Script Anda
2. Buka Pine Script editor → tambahkan `alertcondition`
3. Klik ikon **🔔 Alerts** → **Create Alert**
4. **Condition**: pilih strategi Anda → pilih sinyal BUY/SELL
5. **Notifications** → centang **Webhook URL**
6. **Webhook URL**: `https://abc123.ngrok-free.app/webhook`
7. **Message**: isi JSON sesuai format di bawah

**BUY:**

```json
{"secret":"YOUR_SECRET","action":"BUY","symbol":"BTC-USDT","price":95000,"tp1":96000,"tp2":97000,"tp3":98000,"tp4":99000,"sl":94000}
```

**SELL:**

```json
{"secret":"YOUR_SECRET","action":"SELL","symbol":"BTC-USDT","price":95000,"tp1":94000,"tp2":93000,"tp3":92000,"tp4":91000,"sl":96000}
```

> Jika Pine Script Anda tidak punya TP/SL plot, gunakan `TP_SL_MODE=percent` di `.env`.
> Jika `AUTO_ENTRY=true`, bot akan eksekusi order otomatis tanpa tombol konfirmasi.

### 6) Test koneksi

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"password_anda","action":"BUY","symbol":"BTC-USDT","price":95000,"tp1":96000,"tp2":97000,"tp3":98000,"tp4":99000,"sl":94000}'
```

---

## ⚠️ Peringatan penting

- Selalu test di akun **demo/testnet** dulu sebelum live
- Pastikan balance cukup untuk posisi yang dikalkulasi
- API Key hanya izin **Trade** — jangan aktifkan Withdraw
- Simpan `WEBHOOK_SECRET` yang kuat dan unik
- Jika ngrok gratis, URL berubah setiap restart → update di TradingView
- Gunakan `/panic` di Telegram jika perlu menutup semua posisi dengan cepat

---

## 🤖 Command Telegram

- `/status` — cek saldo dan posisi aktif
- `/leverage <angka>` — ubah leverage default
- `/panic` — tutup semua posisi aktif dan batalkan order pending

---

## 📊 Format payload webhook

```json
{
  "secret": "password_rahasia",
  "action": "BUY",
  "symbol": "BTC-USDT",
  "price": 95000,
  "tp1": 96000,
  "tp2": 97000,
  "tp3": 98000,
  "tp4": 99000,
  "sl": 94000
}
```

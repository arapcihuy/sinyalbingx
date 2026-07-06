# 🤖 SinyalBingX

[![CodeQL](https://github.com/arapcihuy/sinyalbingx/actions/workflows/codeql.yml/badge.svg)](https://github.com/arapcihuy/sinyalbingx/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

Automated trading signal bot for BingX — receives TradingView webhook alerts, executes orders with dynamic risk management, and manages multi-asset positions (BTC, ETH, SOL, XRP, BNB, ADA).

---

## ✨ Features

- **TradingView Integration** — Webhook server接收 TP/SL/Entry signals langsung dari TradingView Pine Script
- **6 Multi-Asset Support** — BTC, ETH, SOL, XRP, BNB, ADA dengan leverage & risk per-coin
- **Brain Engine** — Dynamic leverage & position sizing berdasarkan balance akun
- **Smart TP/SL** — TP/SL dari TV bersifat mutlak, bot hanya adjust jika TV tidak kirim (Min SL Guard)
- **Order Management** — 4 TP partial close + trailing SL via BingX API
- **SQLite Persistence** — Semua sinyal tersimpan di `signals.db` (survive Railway redeploy)
- **Demo Mode** — Paper trading sebelum live

## 🏗️ Architecture

```
TradingView Alert
       │
       ▼ (webhook POST)
┌──────────────────┐
│  Webhook Server  │  webhook_server.py / cloudflare-worker.js
│  (Flask/CF Worker)│
└────────┬─────────┘
         ▼
┌──────────────────┐
│   Brain Engine   │  brain_engine.py — leverage, qty, risk calc
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Order Manager   │  order_manager.py — TP/SL execution, trailing
└────────┬─────────┘
         ▼
┌──────────────────┐
│  BingX REST API  │  bingx_client.py — order placement
└──────────────────┘
```

## 🛠️ Tech Stack

| Component | Tech |
|-----------|------|
| Language | Python 3.12 |
| Server | Flask / Gunicorn |
| API | BingX REST API (Futures) |
| Database | SQLite (`signals.db`) |
| Hosting | Railway + Docker |
| Trading | TradingView Pine Script |
| Monitoring | PM2 / Logs |

## 📦 Project Structure

```
sinyalbingx/
├── webhook_server.py      # Flask webhook receiver
├── cloudflare-worker.js   # Cloudflare Worker alternative
├── brain_engine.py        # Leverage & position sizing logic
├── order_manager.py       # TP/SL execution & trailing
├── bingx_client.py        # BingX API wrapper
├── pair_scanner.py        # Market scanner
├── backtest_engine.py     # Backtesting
├── db_logger.py           # SQLite signal logger
├── state_manager.py       # Trade state tracking
├── settings_manager.py    # Runtime config
├── scripts/               # Utility scripts
├── tests/                 # Test suite
├── BINGX_ADDON_TRADENTIX.pine  # TradingView indicator
├── TRADENTIX_BOT_WEBHOOK.pine  # TradingView alert script
├── Dockerfile             # Railway deploy
└── requirements.txt       # Python dependencies
```

## ⚙️ Configuration

Copy `.env.example` to `.env` dan isi credentials:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BINGX_API_KEY` | ✅ | BingX API key (Trade only, JANGAN Withdraw!) |
| `BINGX_API_SECRET` | ✅ | BingX API secret |
| `REDACTED_WEBHOOK_SECRET` | ✅ | Password rahasia untuk validasi webhook |
| `SYMBOL` | ✅ | Trading pair (default: `BTC-USDT`) |
| `LEVERAGE` | ✅ | Leverage 1-100 |
| `MARGIN_MODE` | ✅ | `ISOLATED` atau `CROSSED` |
| `RISK_PERCENT` | ✅ | Risk per trade dalam % dari balance |
| `TP_SL_MODE` | ✅ | `pinescript` (dari TV) atau `percent` (auto-calc) |
| `ORDER_TYPE` | ✅ | `MARKET` atau `LIMIT` |
| `PORT` | ❌ | Server port (default: 5000) |

## 🚀 Deployment

### Railway (Recommended)

```bash
git clone https://github.com/arapcihuy/sinyalbingx.git
cd sinyalbingx
# Isi .env dengan credentials Anda
railway up
```

### Docker

```bash
docker build -t sinyalbingx .
docker run -d --env-file .env -p 5000:5000 sinyalbingx
```

### Local Development

```bash
pip install -r requirements.txt
python webhook_server.py
```

## 📊 TradingView Setup

1. Import `TRADENTIX_BOT_WEBHOOK.pine` ke TradingView
2. Add indicator ke chart
3. Buat Alert → Webhook URL: `https://your-domain/webhook`
4. Isi `REDACTED_WEBHOOK_SECRET` di alert message

## 🔐 Security

- **Webhook Secret** — Set `REDACTED_WEBHOOK_SECRET` di `.env` DAN di TradingView alert
- **API Key** — Hanya beri izin Trade, JANGAN Withdraw
- **Demo Mode** — Selalu test di demo account dulu

## 📄 License

MIT

## 👤 Author

**arapcihuy** — [github.com/arapcihuy](https://github.com/arapcihuy)

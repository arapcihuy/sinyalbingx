# Premium Telegram Dashboard Mockup Design Spec

## Goal
Improve the trading bot's Telegram interactive command responses (`/status`, `/balance`, `/pnl`, `/settings`) to follow a premium, informative box-drawing tree layout ("Option 1"). Register a clickable commands menu in Telegram, apply error masking for system security, and add timestamps to ensure information freshness.

## New Commands & Features

### 1. Clickable Commands Menu
During bot initialization in `webhook_server.py`, invoke `bot.set_my_commands` to register the following list of commands directly with Telegram:
- `status` - Cek status bot & detail posisi aktif (LIVE/PAPER)
- `balance` - Cek saldo equity & margin bebas
- `pnl` - Laporan floating & realized PnL berkala
- `settings` - Lihat konfigurasi bot trading saat ini

### 2. Cybersecurity Error Masking
Wrap all Telegram command handler logics in try-except blocks. If an exception occurs, log the detailed stack trace to the system logger, and reply to the user with a standardized safe message:
`❌ Gagal memproses /[command]. Terjadi gangguan pada koneksi API atau rate limit tercapai. Silakan coba beberapa saat lagi.`

### 3. Freshness Timestamp
Every response generated from interactive commands must append a formatted timestamp at the bottom:
`🕒 Diperbarui: DD-MM-YYYY HH:MM:SS`

---

## Target Commands Design

### 1. `/status`
Show active trading mode (LIVE/PAPER), connection status, open positions count, and a box-drawing tree listing details for each open position:
- Symbol and Side with emojis (🟢 LONG / 🔴 SHORT)
- Leverage and Margin mode (e.g. `15x | Isolated`)
- Entry Price vs Current Price (e.g. `Entry: $67,250.00 ➔ Current: $67,800.00`)
- Position size and Margin allocation in USDT (e.g. `Size: 0.004 BTC | Margin: $17.93 USDT`)
- Unrealized PnL in USDT and percentage with color emojis (e.g. `Unrealized PnL: +2.85 USDT (+15.89%) 🟢`)
- Targets: Stop Loss (SL) and Take Profit (TP) levels currently active on the exchange (e.g. `Targets: SL $66,500 | TP1 $68,000 | TP2 $69,000`)
- Append: `🕒 Diperbarui: DD-MM-YYYY HH:MM:SS`

### 2. `/balance`
Display account balance metrics:
- Total Equity
- Available Margin (free funds to open new trades)
- Locked Margin (funds currently held in active positions)
- Append: `🕒 Diperbarui: DD-MM-YYYY HH:MM:SS`

### 3. `/pnl`
Present realized PnL across multiple timeframes alongside current unrealized PnL:
- Floating PnL (sum of current unrealized profit/loss)
- Realized PnL over the last 24 hours (1 day)
- Realized PnL over the last 3 days
- Realized PnL over the last 7 days
- Estimated Total PnL (Realized PnL + Unrealized PnL)
- Append: `🕒 Diperbarui: DD-MM-YYYY HH:MM:SS`

### 4. `/settings`
Clear visualization of bot configurations:
- Masked API Key
- Default Leverage and Margin Mode
- Risk per Trade Percent
- Auto Entry Status (showing if currently active or disabled dynamically)
- Webhook URL
- Trading mode configuration
- Append: `🕒 Diperbarui: DD-MM-YYYY HH:MM:SS`

---

## Proposed Implementation Details

### `/status` Details
- Retrieve open positions: `bx.get_open_positions()` for Live, `order_manager.load_paper_trades()` for Paper.
- Retrieve active TP/SL trigger levels from open orders using `bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})`.
- Align and output with box-drawing characters: `├─`, `└─`.

### `/balance` Details
- Fetch from BingX API for Live. Locked margin = total balance - available margin.
- Fetch from local paper trades for Paper (Total virtual equity - allocated virtual margin of open paper positions).

### `/pnl` Details
- Sum `REALIZED_PNL` and `COMMISSION` from `bx.get_income_history` for timeframes.
- Estimate Floating PnL from unrealized profit of open positions.



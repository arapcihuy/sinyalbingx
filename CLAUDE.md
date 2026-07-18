# SinyalBingX Project Guidelines

## MODE: SCALPER 1-TP (aktif sejak 19 Jul 2026)
**Konsep**: TV cuma kirim entry direction (LONG/SHORT + symbol). Brain auto-hitung TP1/SL/leverage/qty.
- `tp_mode = "tp1_only"` di `bot_settings.json`
- Brain hitung TP1 dari ATR 5m candle: `TP1 = max(3×ATR_5m, 0.5% entry)`
- Brain hitung SL: `SL = max(2×ATR_5m, 0.4% entry)`, RR minimal 1.25:1
- 100% qty ke TP1 (ga split ke TP2-4)
- Leverage otomatis dari SL distance (LIQ wajib lebih jauh dari SL + 10% buffer)
- TP1 minimal 0.5% (lewati fee BingX 0.10% round trip)
- TV timeframe: **5 menit** — sinyal lebih sering, TP lebih cepat kena

## Otoritas Mutlak Sinyal TV (Entry Only — Scalper Mode)
1. **TV kirim entry direction** (LONG/SHORT) + symbol — ini mutlak
2. **TV TP/SL di-skip** — brain_engine hitung TP1/SL otomatis dari ATR 5m
3. **Brain override**: `get_scalper_tp_sl()` di `brain_engine.py` → TP1/SL/leverage/qty
4. **Database Persist**: Semua sinyal TV tetap dicatat di SQLite (`signals.db`)

## Otak Bot (Leverage & Margin)
1. **Leverage & Quantity**: Urusan leverage, margin mode, dan quantity posisi sepenuhnya menggunakan perhitungan otak bot (`brain_engine`).
2. **Scalper Brain**: `brain_engine.get_scalper_tp_sl()` → hitung TP1, SL, leverage, qty dari ATR 5m
3. **Audit Posisi**: Selalu pastikan jumlah total Qty TP tidak melebihi Qty posisi aktif ($\\sum \\text{TP} \\le \\text{Posisi}$) untuk mencegah pembukaan order SHORT baru tidak sengaja.

## Semua Coin Wajib Masuk
1. **No Block**: Semua 6 coin (BTC, ETH, SOL, XRP, BNB, ADA) WAJIB bisa entry kapan saja.
2. **Fair Share Margin**: `max_margin_per_pos = equity / jumlah_posisi`. Setiap coin dapat jatah adil dari total equity.
3. **Leverage Auto-Adjust**: Leverage naik otomatis sampai margin muat dalam jatah.
4. **Risk Pakai Equity**: Risk calculation selalu pakai `balance` (equity total), BUKAN `available`.
5. **Min Qty BingX**: BingX min order 0.001 (BTC) / 0.01 (lainnya). Brain auto-bump qty ke min notional trigger ($17.84).

## ⚠️ CRITICAL: SCALPER mode — Brain override TV TP/SL!
1. **Entry = dari TV signal** (LONG/SHORT direction + symbol)
2. **TP1/SL = dari brain_engine** — dihitung dari ATR 5m candle
3. **Leverage = dari brain_engine** — hitung dari SL distance, LIQ wajib lebih jauh
4. **Qty = dari brain_engine** — 100% ke TP1 (ga split)
5. **1 order TP aja** — TP1 pakai `closePosition=true`

## Scalper Profitability Rules
- **Fee BingX**: 0.05% entry + 0.05% exit = 0.10% round trip
- **TP1 MINIMUM**: 0.5% dari entry (harus lewati fee!)
- **Contoh**: Entry 64000, TP1 = 64320 (0.5%), fee = 64 → net profit = 128 per 0.001 BTC
- **Scalper brain otomatis adjust**: kalau ATR 5m kecil, TP1 tetap minimal 0.5%

## Margin Allocation (Scalper Mode)
- Equity $35 → 6 coin → total margin ~$10 (29% utilization)
- BTC margin ~$1.50 (leveraged 75-100x dari SL distance)
- ETH margin ~$1.50 | SOL/BNB/XRP/ADA ~$1.5-2 masing-masing
- Total net profit kalau semua 6 TP1 kena: ~$4.50 (13% per round)

## Cek Sinyal Terakhir
- `active_trades.json` — posisi aktif, TP1, SL, qty, leverage
- `latest_signals.json` — sinyal terakhir per coin (action, price)
- `signals.db` (tabel `tv_signals`) — historical sinyal

## Bug Fixes & History
1. **load_latest_signals**: DB overwrite JSON → balik urutan (DB dulu, JSON overlay)
2. **Entry price**: TV kirim price rounded → selalu fetch `bx.get_current_price()`
3. **TP/SL recalc**: Kalau TV price beda >0.5% dari real entry, recalc proporsional
4. **JANGAN cancel_all_orders saat entry**: SL/TP aktif ikut terbuang. Pakai selective cancel.
5. **19 Jul 2026 — Scalper Mode**: Switch dari multi-TP swing ke 1-TP scalper, brain override TV TP/SL
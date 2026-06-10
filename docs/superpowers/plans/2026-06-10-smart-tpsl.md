# Smart Multi-TP/SL & Trailing SL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menghubungkan sinyal TradingView dengan 4 level Take Profit ke Railway, mengeksekusi order BingX Futures secara cerdas dengan profit target absolut \$1 per level TP, leverage dinamis, limit margin aman 50% saldo, serta mengaktifkan trailing SL otomatis berbasis milestone TP melalui thread latar belakang.

**Architecture:** Memanfaatkan server HTTP Python lokal di Railway untuk memproses webhook, memanggil BingX API untuk eksekusi order instan dengan order take profit dan stop loss parsial reduceOnly, serta menjalankan background thread polling berkala (setiap 15 detik) untuk mendeteksi milestone harga guna memperbarui stop loss aktif (trailing) secara otonom.

**Tech Stack:** Python 3.12, Flask/BaseHTTPRequestHandler, Requests, Threading, JSON State, BingX Swap V2 API.

---

## Task 1: Update Brain Engine Logic (Leverage, Multi-TP Qty, Trailing Check)

**Files:**

- Modify: `brain_engine.py`

- [ ] **Step 1: Ganti atau tambahkan fungsi hitung kuantitas multi-TP dan safety guard margin 50%**
  Ubah atau tambahkan fungsi `calculate_smart_multi_tp_qty` ke `brain_engine.py` untuk menghitung kuantitas parsial per TP berdasarkan profit target \$1 USDT, lengkap dengan limit pengaman 50% margin dari saldo tersedia.

  ```python
  def calculate_smart_multi_tp_qty(balance: float, entry_price: float, tp_prices: list, leverage: int, symbol: str) -> dict:
      """
      Menghitung kuantitas parsial untuk setiap level TP agar memberikan profit absolut $1 per level.
      Juga menerapkan safety guard margin maksimal 50% dari saldo.
      """
      cfg = get_symbol_config(symbol)
      qtys = []
      
      # Target profit $1 per level TP yang valid (>0)
      step_profit = 1.0 
      
      for tp_price in tp_prices:
          if tp_price <= 0:
              qtys.append(0.0)
              continue
          diff = abs(tp_price - entry_price)
          if diff == 0:
              qtys.append(0.0)
              continue
          qty = step_profit / diff
          qtys.append(qty)
          
      total_qty = sum(qtys)
      
      # Safety Guard: Batasi margin awal maksimal 50% dari saldo tersedia
      required_margin = (total_qty * entry_price) / leverage
      max_allowed_margin = balance * 0.5
      
      if required_margin > max_allowed_margin and required_margin > 0:
          factor = max_allowed_margin / required_margin
          qtys = [q * factor for q in qtys]
          total_qty = total_qty * factor
          logger.info(f"⚠️ SAFETY GUARD: Margin ${required_margin:.2f} melebihi 50% saldo (${max_allowed_margin:.2f}). Downscale factor: {factor:.4f}")
      
      # Terapkan presisi kuantitas per simbol
      qty_prec = cfg.get("qty_precision", 3)
      final_qtys = [round(q, qty_prec) for q in qtys]
      
      # Pastikan min_qty terpenuhi untuk level yang aktif
      for i in range(len(final_qtys)):
          if tp_prices[i] > 0 and final_qtys[i] < cfg.get("min_qty", 0.001):
              final_qtys[i] = cfg.get("min_qty", 0.001)
              
      return {
          "qtys": final_qtys,
          "total_qty": round(sum(final_qtys), qty_prec),
          "margin": (sum(final_qtys) * entry_price) / leverage
      }
  ```

- [ ] **Step 2: Tambahkan logika trailing SL berbasis milestone TP**
  Tambahkan fungsi `calculate_milestone_trailing_sl` ke `brain_engine.py` untuk menggeser SL saat harga menyentuh/melewati TP1, TP2, atau TP3.

  ```python
  def calculate_milestone_trailing_sl(current_price: float, side: str, entry_price: float, current_sl: float, tp1: float, tp2: float, tp3: float, symbol: str) -> dict:
      """
      Menghitung SL baru berdasarkan level milestone TP yang berhasil disentuh.
      TP1 terlewati -> SL ke Entry
      TP2 terlewati -> SL ke TP1
      TP3 terlewati -> SL ke TP2
      """
      cfg = get_symbol_config(symbol)
      price_prec = cfg.get("price_precision", 2)
      
      if side == "LONG":
          # LONG: Harga naik
          if tp3 > 0 and current_price >= tp3:
              new_sl = tp2
              reason = "TP3 tercapai -> SL digeser ke TP2"
          elif tp2 > 0 and current_price >= tp2:
              new_sl = tp1
              reason = "TP2 tercapai -> SL digeser ke TP1"
          elif tp1 > 0 and current_price >= tp1:
              new_sl = entry_price
              reason = "TP1 tercapai -> SL digeser ke Entry"
          else:
              return {"should_update": False, "new_sl": current_sl, "reason": "belum menyentuh milestone"}
              
          if new_sl > current_sl:
              return {
                  "should_update": True,
                  "new_sl": round(new_sl, price_prec),
                  "reason": reason
              }
      else:
          # SHORT: Harga turun
          if tp3 > 0 and current_price <= tp3:
              new_sl = tp2
              reason = "TP3 tercapai -> SL digeser ke TP2"
          elif tp2 > 0 and current_price <= tp2:
              new_sl = tp1
              reason = "TP2 tercapai -> SL digeser ke TP1"
          elif tp1 > 0 and current_price <= tp1:
              new_sl = entry_price
              reason = "TP1 tercapai -> SL digeser ke Entry"
          else:
              return {"should_update": False, "new_sl": current_sl, "reason": "belum menyentuh milestone"}
              
          if current_sl == 0 or new_sl < current_sl:
              return {
                  "should_update": True,
                  "new_sl": round(new_sl, price_prec),
                  "reason": reason
              }
              
      return {"should_update": False, "new_sl": current_sl, "reason": "tidak ada perubahan SL"}
  ```

- [ ] **Step 3: Uji integrasi internal brain_engine.py**
  Jalankan modul `brain_engine.py` secara langsung menggunakan unittest atau CLI jika ada untuk memverifikasi tidak ada kesalahan sintaksis.
  Command: `python3 -m py_compile brain_engine.py`
  Expected: Command selesai dengan status 0 (tidak ada error).

---

## Task 2: Modifikasi Webhook Server (Parse Payload TP3 & TP4)

**Files:**

- Modify: `webhook_server.py:41-67`

- [ ] **Step 1: Tambahkan parser tp3 dan tp4 di webhook_server.py**
  Ubah bagian parser POST request untuk `/tradingview` agar mengekstrak variabel `tp3` dan `tp4` dari JSON payload.

  ```python
                  else:
                      signal = (data.get("signal") or data.get("action") or "").upper()
                      pair = data.get("symbol", "").upper().replace(".P", "")
                      if "-USDT" not in pair: pair += "-USDT"
                      price = float(data.get("price") or 0)
                      sl = float(data.get("sl") or 0)
                      tp1 = float(data.get("tp1") or 0)
                      tp2 = float(data.get("tp2") or 0)
                      tp3 = float(data.get("tp3") or 0)
                      tp4 = float(data.get("tp4") or 0)
  ```

  Kirim data ini ke `order_manager.execute_signal`:

  ```python
                  result = order_manager.execute_signal({
                      "symbol": pair, "action": signal, "price": price,
                      "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4
                  })
  ```

- [ ] **Step 2: Kirim detail notifikasi Telegram yang indah**
  Ubah isi variabel `msg` notifikasi Telegram agar memuat 4 TP level secara lengkap.

  ```python
                  try:
                      import requests as r
                      msg = (
                          f"⚡ *SINYAL DIEKSEKUSI*\n"
                          f"━━━━━━━━━━━━━━━━━━━━━\n"
                          f"🪙 *Pair:* `{pair}`\n"
                          f"📈 *Action:* `{signal}`\n"
                          f"💵 *Entry:* `{price}`\n"
                          f"🛑 *Stop Loss:* `{sl}`\n"
                          f"🎯 *TP1:* `{tp1}` | *TP2:* `{tp2}`\n"
                          f"🎯 *TP3:* `{tp3}` | *TP4:* `{tp4}`\n"
                          f"Result: `{result.get('status')}`\n"
                          f"━━━━━━━━━━━━━━━━━━━━━"
                      )
                      r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
                  except Exception as e:
                      log.error(f"Gagal kirim Telegram: {e}")
  ```

- [ ] **Step 3: Uji kompilasi webhook_server.py**
  Jalankan: `python3 -m py_compile webhook_server.py`
  Expected: Command selesai tanpa error.

---

## Task 3: Modifikasi Order Manager (Logika Multi-TP & Real-time Balance)

**Files:**

- Modify: `order_manager.py`

- [ ] **Step 1: Sesuaikan parameter input di `execute_signal` untuk multi-TP**
  Ubah bagian pemanggilan leverage, dynamic margin, dan multi-TP di `execute_signal` di `order_manager.py` agar menggunakan logika kuantitas baru:

  ```python
      # Ambil TP/SL dari TV
      sl_price = _round_price(float(data.get("sl", 0)), symbol)
      tp1_price = _round_price(float(data.get("tp1", 0)), symbol)
      tp2_price = _round_price(float(data.get("tp2", 0)), symbol)
      tp3_price = _round_price(float(data.get("tp3", 0)), symbol)
      tp4_price = _round_price(float(data.get("tp4", 0)), symbol)
      
      tp_prices = [tp1_price, tp2_price, tp3_price, tp4_price]
      
      # Saldo akun riil untuk live, atau 100 untuk paper
      try:
          balance = bx.get_balance() if not paper_mode else 100.0
      except Exception as e:
          logger.error(f"Gagal ambil balance, fallback ke $100: {e}")
          balance = 100.0
          
      # Ambil leverage dinamis dari brain
      import brain_engine
      leverage = brain_engine.get_dynamic_leverage(balance)
      
      # Hitung kuantitas cerdas multi-TP dengan pengaman 50%
      calc_result = brain_engine.calculate_smart_multi_tp_qty(balance, entry_price, tp_prices, leverage, symbol)
      qtys = calc_result["qtys"]
      qty = calc_result["total_qty"]
  ```

- [ ] **Step 2: Simpan detail posisi yang dibuka ke `active_trades.json`**
  Simpan detail pemicu milestone dan harga TP individual ke state untuk pelacakan trailing SL:

  ```python
      # Simpan trade data (untuk trailing)
      active_trade_data[symbol] = {
          "symbol": symbol,
          "side": pos_side,
          "entry_price": entry_price,
          "sl": sl_price,
          "tp1": tp1_price,
          "tp2": tp2_price,
          "tp3": tp3_price,
          "tp4": tp4_price,
          "qtys": qtys,
          "qty": qty,
          "leverage": leverage,
          "status": "OPEN",
          "open_time": time.strftime("%Y-%m-%d %H:%M:%S"),
      }
      save_active_trades()
  ```

- [ ] **Step 3: Kirim multi-order TP/SL ke BingX Futures API**
  Modifikasi bagian live execution untuk mengirim order Market, kemudian memasang 1 SL dan 4 TP secara individual dengan reduceOnly: "true".

  ```python
      if paper_mode:
          trade = {
              "time": time.strftime("%Y-%m-%d %H:%M:%S"),
              "symbol": symbol,
              "side": pos_side,
              "entry": entry_price,
              "sl": sl_price,
              "tp": tp1_price,
              "qty": qty,
              "status": "OPEN_PAPER"
          }
          save_paper_trade(trade)
          logger.info(f"📝 PAPER TRADE OPENED: {symbol} {pos_side} @ {entry_price}")
          return {"status": "success_paper", "symbol": symbol, "qty": qty}

      # Live Execution
      bx.set_leverage(symbol, leverage, pos_side)
      order_res = bx.place_order(symbol, order_side, pos_side, qty, "MARKET")

      if order_res.get("code") == 0:
          sl_side = "SELL" if pos_side == "LONG" else "BUY"
          
          # 1. Pasang STOP LOSS Tunggal
          bx._request("POST", "/openApi/swap/v2/trade/order", {
              "symbol": symbol, "side": sl_side, "positionSide": pos_side,
              "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty,
              "reduceOnly": "true"
          })
          
          # 2. Pasang Tiap Level TP yang Valid
          for i, tp_price in enumerate(tp_prices):
              tp_qty = qtys[i]
              if tp_price > 0 and tp_qty > 0:
                  bx._request("POST", "/openApi/swap/v2/trade/order", {
                      "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                      "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": tp_qty,
                      "reduceOnly": "true"
                  })
                  
          return {"status": "success", "symbol": symbol, "qty": qty}
      else:
          return {"status": f"failed: {order_res.get('msg')}", "symbol": symbol}
  ```

- [ ] **Step 4: Update Trailing SL monitor (`check_and_update_trailing_sl`)**
  Ubah fungsi `check_and_update_trailing_sl` agar menggunakan logika trailing berbasis milestone TP.

  ```python
  def check_and_update_trailing_sl():
      """
      Memantau harga real-time dan menggeser SL saat menyentuh milestone TP1/TP2/TP3.
      """
      try:
          positions = bx.get_open_positions()
          if not positions:
              # Jika tidak ada posisi terbuka, kosongkan active_trade_data
              if active_trade_data:
                  active_trade_data.clear()
                  save_active_trades()
              return
          
          # Hapus symbol yang sudah tidak ada di bursa dari active_trade_data
          open_symbols = [p["symbol"] for p in positions]
          for sym in list(active_trade_data.keys()):
              if sym not in open_symbols:
                  del active_trade_data[sym]
          save_active_trades()
          
          for pos in positions:
              symbol = pos["symbol"]
              pos_side = pos["positionSide"]
              qty = abs(float(pos["positionAmt"]))
              current_price = bx.get_current_price(symbol)
              
              if current_price == 0 or symbol not in active_trade_data:
                  continue
                  
              trade = active_trade_data[symbol]
              entry_price = trade["entry_price"]
              current_sl = trade["sl"]
              tp1 = trade.get("tp1", 0)
              tp2 = trade.get("tp2", 0)
              tp3 = trade.get("tp3", 0)
              
              import brain_engine
              result = brain_engine.calculate_milestone_trailing_sl(
                  current_price, pos_side, entry_price, current_sl, tp1, tp2, tp3, symbol
              )
              
              if result["should_update"]:
                  new_sl = result["new_sl"]
                  sl_side = "SELL" if pos_side == "LONG" else "BUY"
                  
                  # 1. Batalkan semua SL lama di bursa (STOP_MARKET)
                  # Cari order STOP_MARKET di openOrders
                  try:
                      orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                      open_orders = orders_res.get("data", [])
                      if isinstance(open_orders, dict):
                          open_orders = open_orders.get("orders", [])
                      
                      for order in open_orders:
                          if order.get("type") == "STOP_MARKET":
                              bx.cancel_order(symbol, order.get("orderId"))
                  except Exception as ce:
                      logger.error(f"Gagal cancel SL lama: {ce}")
                      
                  # 2. Pasang SL baru
                  bx._request("POST", "/openApi/swap/v2/trade/order", {
                      "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                      "type": "STOP_MARKET", "stopPrice": new_sl, "quantity": qty,
                      "reduceOnly": "true"
                  })
                  
                  # 3. Update state lokal
                  trade["sl"] = new_sl
                  active_trade_data[symbol] = trade
                  save_active_trades()
                  
                  # 4. Kirim notifikasi Telegram tentang trailing SL
                  try:
                      TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                      TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
                      msg = (
                          f"🔄 *TRAILING STOP LOSS AKTIF*\n"
                          f"━━━━━━━━━━━━━━━━━━━━━\n"
                          f"🪙 *Pair:* `{symbol}`\n"
                          f"🛡️ *SL Baru:* `{new_sl}`\n"
                          f"📝 *Alasan:* {result['reason']}\n"
                          f"━━━━━━━━━━━━━━━━━━━━━"
                      )
                      import requests as r
                      r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
                  except:
                      pass
                      
                  logger.info(f"🔄 TRAILING SL {symbol}: {current_sl} → {new_sl} | {result['reason']}")
      except Exception as e:
          logger.error(f"Error check_and_update_trailing_sl: {e}")
  ```

- [ ] **Step 5: Pastikan file `order_manager.py` terkompilasi bersih**
  Jalankan: `python3 -m py_compile order_manager.py`
  Expected: Command selesai tanpa error.

---

## Task 4: Tambahkan Background Monitor Thread ke Webhook Server

**Files:**

- Modify: `webhook_server.py`

- [ ] **Step 1: Jalankan monitoring thread saat server startup**
  Tambahkan pemanggilan thread monitoring di akhir `webhook_server.py` agar bot secara berkala melakukan sinkronisasi posisi dan trailing SL secara otonom.

  ```python
  def start_background_monitor():
      import time
      import threading
      import order_manager
      
      def monitor_loop():
          logger.info("📡 Background monitor thread untuk trailing SL aktif...")
          while True:
              try:
                  order_manager.monitor_and_sync_positions()
              except Exception as e:
                  logger.error(f"Error di background monitor loop: {e}")
              time.sleep(15) # Jalankan setiap 15 detik
              
      t = threading.Thread(target=monitor_loop, daemon=True)
      t.start()
  ```

  Panggil fungsi `start_background_monitor()` tepat di atas block `if __name__ == "__main__":` atau di dalamnya:

  ```python
  if __name__ == "__main__":
      # Aktifkan background monitor
      start_background_monitor()
      
      port = int(os.getenv("PORT", 5000))
      server = HTTPServer(("0.0.0.0", port), Handler)
      log.info(f"Listening on :{port}")
      server.serve_forever()
  ```

- [ ] **Step 2: Kompilasi final dan jalankan verifikasi sintaks**
  Jalankan: `python3 -m py_compile webhook_server.py`
  Expected: Command selesai dengan status sukses.

---

## Task 5: Validasi Menggunakan Simulasi Trading

**Files:**

- Modify: `simulasi_trading.py`
- Run: `python3 simulasi_trading.py`

- [ ] **Step 1: Sesuaikan `simulasi_trading.py` dengan multi-TP 4 tingkat**
  Ubah data sinyal fiktif di `simulasi_trading.py` untuk menguji TP1, TP2, TP3, TP4 dan trailing SL.

  ```python
  # Data Sinyal Fiktif dengan 4 TP
  signal_data = {
      "symbol": symbol,
      "action": "LONG",
      "price": entry_price,
      "sl": 59000.0,
      "tp1": 61000.0,
      "tp2": 62000.0,
      "tp3": 63000.0,
      "tp4": 64000.0
  }
  ```

- [ ] **Step 2: Jalankan simulasi dan verifikasi pergeseran SL**
  Jalankan file simulasi trading untuk memastikan bot menghitung kuantitas dengan benar dan menggeser SL ke milestone sebelumnya saat harga bergerak melintasi level TP.
  Run: `python3 simulasi_trading.py`
  Expected: Output simulasi menunjukkan:
  - Berhasil menghitung kuantitas parsial per TP level.
  - Saat harga disimulasikan tembus TP1 (misal 61200), bot melacak milestone dan menggeser SL dari 59000 ke harga Entry (60000).

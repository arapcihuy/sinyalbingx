import os
import math
import logging
import json
import time
import requests
from dotenv import load_dotenv
import bingx_client as bx

load_dotenv()
logger = logging.getLogger(__name__)

# Global State
latest_signals = {}
active_trade_data = {}
last_known_positions = {}
_SYMBOL_PRECISION_CACHE = {}
_LAST_KNOWN_BALANCE = None

PAPER_TRADES_FILE = "paper_trades.json"
ACTIVE_TRADES_FILE = "active_trades.json"
LATEST_SIGNALS_FILE = "latest_signals.json"

import settings_manager

# Lazy import — jangan import di level module (cepatkan cold start)
# import brain_engine  # di-import di dalam fungsi saja

def get_paper_mode():
    """Mengambil status mode trading secara dinamis dari state_manager."""
    try:
        import state_manager
        return state_manager.get_trading_mode()["paper_mode"]
    except Exception:
        # Fallback jika diimpor sebelum state_manager siap
        import settings_manager
        current_settings = settings_manager.load_settings()
        return current_settings.get("paper_mode", True)

def load_paper_trades():
    if os.path.exists(PAPER_TRADES_FILE):
        try:
            with open(PAPER_TRADES_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_paper_trade(trade):
    trades = load_paper_trades()
    trades.append(trade)
    with open(PAPER_TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def update_paper_trades(trades):
    with open(PAPER_TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def load_latest_signals():
    global latest_signals
    if os.path.exists(LATEST_SIGNALS_FILE):
        try:
            with open(LATEST_SIGNALS_FILE, "r") as f:
                latest_signals = json.load(f)
        except:
            latest_signals = {}
    return latest_signals

def save_latest_signals():
    try:
        with open(LATEST_SIGNALS_FILE, "w") as f:
            json.dump(latest_signals, f, indent=4)
    except Exception as e:
        logger.error(f"Gagal simpan latest_signals: {e}")

def save_active_trades():
    try:
        with open(ACTIVE_TRADES_FILE, "w") as f:
            json.dump(active_trade_data, f, indent=4)
    except Exception as e:
        logger.error(f"Gagal simpan active_trades: {e}")

def load_active_trades():
    global active_trade_data
    if os.path.exists(ACTIVE_TRADES_FILE):
        try:
            with open(ACTIVE_TRADES_FILE, "r") as f:
                active_trade_data = json.load(f)
                logger.info(f"💾 State active trades di-load: {list(active_trade_data.keys())}")
        except Exception as e:
            logger.error(f"Gagal load active_trades: {e}")
            active_trade_data = {}
    return active_trade_data

# Inisialisasi state saat modul di-load
load_latest_signals()
load_active_trades()

def get_symbol_precision(symbol):
    """Ambil presisi quantity & price langsung dari BingX atau cache."""
    global _SYMBOL_PRECISION_CACHE
    if symbol in _SYMBOL_PRECISION_CACHE:
        return _SYMBOL_PRECISION_CACHE[symbol]
    
    try:
        import brain_engine
        cfg = brain_engine.get_symbol_config(symbol)
        precision = {
            "qty": cfg["qty_precision"],
            "price": cfg["price_precision"]
        }
        _SYMBOL_PRECISION_CACHE[symbol] = precision
        return precision
    except Exception as e:
        logger.error(f"Gagal ambil precision untuk {symbol} via brain_engine: {e}")
    
    return {"qty": 2, "price": 2}

def _round_qty(qty, symbol):
    """Round quantity based on symbol precision from API."""
    prec = get_symbol_precision(symbol)
    return round(float(qty), prec["qty"])

def _round_price(price, symbol):
    """Round price based on symbol precision from API."""
    prec = get_symbol_precision(symbol)
    return round(float(price), prec["price"])

def get_dynamic_risk_settings(balance: float) -> dict:
    """Leverage & risk dinamis — delegasi ke brain_engine."""
    import brain_engine
    leverage = brain_engine.get_dynamic_leverage(balance)
    risk_percent = brain_engine.get_dynamic_risk_percent(balance)
    logger.info(f"🧠 BRAIN: Balance ${balance:.2f} → Leverage {leverage}x, Risk {risk_percent}%")
    return {"leverage": leverage, "risk_percent": risk_percent}

def calculate_quantity_risk_based(balance: float, entry_price: float, sl_price: float, symbol: str, risk_percent: float) -> float:
    """Hitung quantity via brain_engine."""
    import brain_engine
    return brain_engine.calculate_position_size(balance, entry_price, sl_price, risk_percent, symbol)

def is_pair_eligible(symbol):
    """Cek apakah symbol ada dalam daftar eligible dari scanner."""
    if os.getenv("FILTER_BY_SCANNER", "false").lower() != "true":
        return True
        
    try:
        if not os.path.exists("scanned_pairs.json"):
            return True
        with open("scanned_pairs.json", "r") as f:
            data = json.load(f)
            return symbol in data.get("eligible_pairs", [])
    except:
        return True

def check_paper_exit():
    """Monitor paper trades for TP/SL hits using current prices."""
    trades = load_paper_trades()
    updated = False
    for t in trades:
        if t["status"] == "OPEN_PAPER":
            curr_price = bx.get_current_price(t["symbol"])
            if curr_price == 0:
                continue
            exit_trigger = None
            if t["side"] == "LONG":
                if curr_price <= t["sl"]:
                    exit_trigger = "SL"
                elif curr_price >= t["tp"]:
                    exit_trigger = "TP"
            else:  # SHORT
                if curr_price >= t["sl"]:
                    exit_trigger = "SL"
                elif curr_price <= t["tp"]:
                    exit_trigger = "TP"
            if exit_trigger:
                t["status"] = f"CLOSED_{exit_trigger}"
                t["exit_price"] = t["sl"] if exit_trigger == "SL" else t["tp"]
                t["close_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if t["side"] == "LONG":
                    t["pnl_usdt"] = (t["exit_price"] - t["entry"]) * t["qty"]
                else:
                    t["pnl_usdt"] = (t["entry"] - t["exit_price"]) * t["qty"]
                
                logger.info(f"✅ PAPER {exit_trigger} HIT: {t['symbol']} | PnL: ${t['pnl_usdt']:.2f}")
                
                # Kirim Notif Telegram Close
                try:
                    TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
                    url_notif = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
                    chat_id = TG_CHAT_ID
                    emoji = "🎯" if exit_trigger == "TP" else "🛑"
                    pnl_color = "+" if t["pnl_usdt"] >= 0 else ""
                    msg_text = (
                        f"{emoji} *SINYAL SELESAI (CLOSE) - PAPER*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Pair:* `{t['symbol']}` ({t.get('side', 'LONG')})\n"
                        f"📈 *Exit:* `{exit_trigger}` @ `{t['exit_price']:.4f}`\n"
                        f"💰 *PnL Bersih:* `{pnl_color}{t['pnl_usdt']:.2f} USDT`\n"
                        f"⚙️ *Mode:* `PAPER`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                    requests.post(url_notif, json={"chat_id": chat_id, "text": msg_text, "parse_mode": "Markdown"}, timeout=5)
                except Exception as te:
                    logger.error(f"Gagal kirim notif telegram: {te}")
                
                updated = True
    if updated:
        update_paper_trades(trades)

def notify_live_close(symbol: str, trade_data: dict):
    """Kirim notifikasi ke Telegram bahwa posisi LIVE telah selesai/tutup."""
    try:
        # Beri jeda 2 detik agar bursa mencatat data income
        time.sleep(2)
        income_history = bx.get_income_history(symbol=symbol, days=1)
        
        now_ms = time.time() * 1000
        five_mins_ms = 5 * 60 * 1000
        
        recent_pnl_records = []
        for inc in income_history:
            try:
                inc_time = int(inc.get("time", 0))
                if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION"] and (now_ms - inc_time < five_mins_ms):
                    recent_pnl_records.append(inc)
            except:
                continue
        
        realized_pnl = sum(float(r.get("income", 0)) for r in recent_pnl_records)
        
        if not recent_pnl_records:
            # Fallback jika data income belum tercatat
            try:
                curr_price = bx.get_current_price(symbol)
            except:
                curr_price = trade_data.get("entry_price", 0.0)
            side = trade_data.get("side", "LONG")
            entry = trade_data.get("entry_price", curr_price)
            qty = trade_data.get("qty", 0.0)
            if side == "LONG":
                realized_pnl = (curr_price - entry) * qty
            else:
                realized_pnl = (entry - curr_price) * qty
            exit_price = curr_price
            exit_trigger = "MANUAL/TP/SL"
        else:
            try:
                curr_price = bx.get_current_price(symbol)
            except:
                curr_price = trade_data.get("entry_price", 0.0)
            exit_price = curr_price
            exit_trigger = "TP" if realized_pnl >= 0 else "SL"
            
        emoji = "🎯" if realized_pnl >= 0 else "🛑"
        pnl_sign = "+" if realized_pnl >= 0 else ""
        
        TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
        
        msg_text = (
            f"{emoji} *SINYAL SELESAI (CLOSE) - LIVE*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Pair:* `{symbol}` ({trade_data.get('side', 'LONG')})\n"
            f"📈 *Exit:* `{exit_trigger}` @ `{exit_price:.4f}`\n"
            f"💰 *PnL Bersih:* `{pnl_sign}{realized_pnl:.2f} USDT`\n"
            f"⚙️ *Mode:* `LIVE`\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        url_notif = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url_notif, json={"chat_id": TG_CHAT_ID, "text": msg_text, "parse_mode": "Markdown"}, timeout=5)
        logger.info(f"📨 LIVE CLOSE NOTIFICATION SENT for {symbol} | PnL: ${realized_pnl:.2f}")
    except Exception as e:
        logger.error(f"Gagal kirim notif live close untuk {symbol}: {e}")

def is_position_open(symbol):
    """Cek apakah ada posisi terbuka untuk symbol ini di bursa atau paper."""
    if get_paper_mode():
        trades = load_paper_trades()
        return any(t["symbol"] == symbol and t["status"] == "OPEN_PAPER" for t in trades)
    
    positions = bx.get_open_positions(symbol)
    return len(positions) > 0

def get_total_open_positions_count():
    """Hitung total posisi yang sedang aktif."""
    if get_paper_mode():
        trades = load_paper_trades()
        return len([t for t in trades if t["status"] == "OPEN_PAPER"])
    
    positions = bx.get_open_positions()
    return len(positions)

def execute_signal(data: dict) -> dict:
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "BTC-USDT")

    # Check paper exits
    check_paper_exit()

    if action == "CLOSE":
        return _close_position(symbol)

    # ── CHECK EXISTING POSITION & REVERSAL ──
    target_pos_side = "LONG" if action in ["BUY", "LONG"] else "SHORT"
    opposite_pos_side = "SHORT" if target_pos_side == "LONG" else "LONG"
    
    existing_positions = []
    if not get_paper_mode():
        try:
            existing_positions = bx.get_open_positions(symbol)
        except Exception as pe:
            logger.error(f"Gagal get_open_positions untuk check reversal: {pe}")
    else:
        trades = load_paper_trades()
        existing_positions = [t for t in trades if t["symbol"] == symbol and t["status"] == "OPEN_PAPER"]

    for pos in existing_positions:
        pos_side_str = pos["side"] if get_paper_mode() else pos["positionSide"]
        if pos_side_str == opposite_pos_side:
            logger.info(f"🔄 Terdeteksi Sinyal Berbalik Arah (Reversal) untuk {symbol}: {pos_side_str} -> {target_pos_side}. Menutup posisi lama...")
            _close_position(symbol)
            if not get_paper_mode():
                time.sleep(1.5)
        elif pos_side_str == target_pos_side:
            logger.warning(f"⚠️ Posisi {target_pos_side} untuk {symbol} sudah terbuka. Mengabaikan sinyal duplikat.")
            return {"status": "already_open", "symbol": symbol}

    # ── SLOT MANAGEMENT ──
    # MAX_SLOTS = 3 
    # current_slots = get_total_open_positions_count()
    # 
    # if current_slots >= MAX_SLOTS:
    #     logger.warning(f"🚫 Slot Penuh ({current_slots}/{MAX_SLOTS}). Mengabaikan {symbol}.")
    #     return {"status": "slots_full", "symbol": symbol}
    
    # ── MARGIN SAFETY GUARD ──
    # Jangan buka trade baru jika saldo yang tersisa terlalu mepet
    try:
        if not get_paper_mode():
            balance_data = bx._request('GET', '/openApi/swap/v2/user/balance')
            if balance_data.get("code") == 0:
                available = float(balance_data["data"]["balance"]["availableMargin"])
                equity = float(balance_data["data"]["balance"]["equity"])
                # Jika margin tersedia kurang dari 20% dari total equity, jangan entry
                if available < (equity * 0.2):
                    logger.warning(f"⚠️ Margin Mepeet! (Avail: {available}). Membatalkan entry {symbol}.")
                    return {"status": "low_margin", "symbol": symbol}
    except:
        pass # Lanjut jika gagal cek balance (pakai pengaman saldo tetap)

    if not is_pair_eligible(symbol):
        logger.warning(f"🚫 {symbol} diabaikan oleh scanner (Low Expectancy).")
        return {"status": "ignored_by_scanner", "symbol": symbol}

    pos_side = "LONG" if action in ["BUY", "LONG"] else "SHORT"
    order_side = "BUY" if pos_side == "LONG" else "SELL"
    sl_side = "SELL" if pos_side == "LONG" else "BUY"

    paper_mode = get_paper_mode()
    entry_price = float(data.get("price", 0)) or bx.get_current_price(symbol)
    
    global _LAST_KNOWN_BALANCE
    # Jika paper_mode, hindari panggil API saldo real jika error
    try:
        if not paper_mode:
            balance = bx.get_balance()
            _LAST_KNOWN_BALANCE = balance
        else:
            balance = 100.0
    except Exception as e:
        logger.error(f"⚠️ Gagal ambil balance via bx.get_balance(): {e}")
        if _LAST_KNOWN_BALANCE is not None:
            logger.info(f"🔄 Menggunakan saldo terakhir yang dicache: ${_LAST_KNOWN_BALANCE:.2f}")
            balance = _LAST_KNOWN_BALANCE
        else:
            logger.warning("⚠️ Saldo terakhir tidak dicache. Fallback aman ke $25.00 USDT.")
            balance = 25.0

    risk_cfg = get_dynamic_risk_settings(balance)
    leverage = risk_cfg["leverage"]
    risk_pct = risk_cfg["risk_percent"]

    # ── 🧠 BRAIN: Leverage & Margin dinamis (TP/SL ngikutin TV) ──
    try:
        if not paper_mode:
            balance_data = bx._request('GET', '/openApi/swap/v2/user/balance')
            if balance_data and balance_data.get("code") == 0:
                balance = float(balance_data["data"]["balance"]["availableMargin"])
                _LAST_KNOWN_BALANCE = float(balance_data["data"]["balance"]["equity"])
    except Exception as e:
        logger.error(f"Gagal update balance live: {e}")
    
    import brain_engine
    risk_pct = brain_engine.get_dynamic_risk_percent(balance)
    
    # TP/SL dari TV (ngikutin script TRADENTIX PRO)
    sl_price = _round_price(float(data.get("sl", 0)), symbol)
    tp1_price = _round_price(float(data.get("tp1", 0)), symbol)
    tp2_price = _round_price(float(data.get("tp2", 0)), symbol)
    tp3_price = _round_price(float(data.get("tp3", 0)), symbol)
    tp4_price = _round_price(float(data.get("tp4", 0)), symbol)
    
    tp_prices = [tp1_price, tp2_price, tp3_price, tp4_price]
    
    # Fallback: kalau TV nggak kirim TP/SL, pakai brain
    if sl_price == 0 and tp1_price == 0:
        logger.info("📺 TV tidak kirim TP/SL, pakai brain engine")
        trade_plan = brain_engine.get_full_trade_plan(balance, entry_price, pos_side, symbol)
        sl_price = trade_plan["sl"]
        tp1_price = trade_plan["tp1"]
        tp2_price = trade_plan["tp2"]
        tp_prices = [tp1_price, tp2_price, 0.0, 0.0]
    
    # Hitung safe leverage agar SL berada sebelum likuidasi
    leverage = brain_engine.get_safe_leverage(balance, entry_price, sl_price, pos_side, symbol)
    
    # Hitung kuantitas cerdas multi-TP dengan pengaman 50%
    calc_result = brain_engine.calculate_smart_multi_tp_qty(balance, entry_price, tp_prices, leverage, symbol)
    qtys = calc_result["qtys"]
    qty = calc_result["total_qty"]
    
    if qty <= 0:
        logger.warning(f"🚫 Saldo tersedia (${balance:.2f} USDT) terlalu kecil untuk membuka kuantitas minimum untuk {symbol}. Mengabaikan sinyal.")
        return {"status": "insufficient_balance", "symbol": symbol}
    
    # ATR untuk trailing
    atr = entry_price * 0.01  # fallback 1%
    try:
        atr = brain_engine.calculate_atr([], 14) or atr
    except:
        pass
    
    logger.info(f"🧠 BRAIN: {symbol} {pos_side} | Lev: {leverage}x | Qty: {qty} | Margin: {calc_result['margin']:.2f} USDT")
    logger.info(f"📺 TV TP/SL: SL={sl_price} TP1={tp1_price} TP2={tp2_price} TP3={tp3_price} TP4={tp4_price}")
    
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
        "risk_pct": risk_pct,
        "atr": atr,
        "trailing": {
            "activate_atr_mult": 1.0,
            "offset_atr_mult": 0.5,
            "active": False,
            "highest_price": entry_price if pos_side == "LONG" else 0,
            "lowest_price": entry_price if pos_side == "SHORT" else 0,
        },
        "status": "OPEN",
        "open_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_active_trades()
 
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
        # 1. Pasang STOP LOSS Tunggal
        bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty
        })
        
        # 2. Pasang Tiap Level TP yang Valid
        for i, tp_price in enumerate(tp_prices):
            tp_qty = qtys[i]
            if tp_price > 0 and tp_qty > 0:
                bx._request("POST", "/openApi/swap/v2/trade/order", {
                    "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                    "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": tp_qty
                })
        return {"status": "success", "symbol": symbol, "qty": qty}
    else:
        return {"status": f"failed: {order_res.get('msg')}", "symbol": symbol}

def _close_position(symbol: str) -> dict:
    global active_trade_data
    paper_mode = get_paper_mode()
    if paper_mode:
        trades = load_paper_trades()
        for t in trades:
            if t["symbol"] == symbol and t["status"] == "OPEN_PAPER":
                t["status"] = "CLOSED_PAPER"
                t["close_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(PAPER_TRADES_FILE, "w") as f:
            json.dump(trades, f, indent=4)
        return {"msg": f"Closed paper position {symbol}"}

    positions = bx.get_open_positions(symbol)
    for pos in positions:
        side = pos["positionSide"]
        qty = abs(float(pos["positionAmt"]))
        close_side = "SELL" if side == "LONG" else "BUY"
        bx.place_order(symbol, close_side, side, qty)
    bx.cancel_all_orders(symbol)
    
    if symbol in active_trade_data:
        del active_trade_data[symbol]
        save_active_trades()
        
    return {"msg": f"Closed {symbol}"}

# Counter global untuk meredam spam alert Telegram
_RECONCILIATION_MISMATCH_COUNT = {}

def audit_position_reconciliation():
    """
    Membandingkan posisi aktif di bursa BingX dengan database posisi lokal (active_trades.json).
    Jika terdeteksi perbedaan status selama 3 putaran berturut-turut, kirimkan peringatan ke Telegram.
    """
    global _RECONCILIATION_MISMATCH_COUNT
    import state_manager
    mode = state_manager.get_trading_mode()
    
    # Rekonsiliasi hanya berlaku di LIVE mode (uang asli), demo tidak wajib ketat
    if mode["paper_mode"]:
        return
        
    try:
        # Ambil posisi riil di bursa
        real_positions = bx.get_open_positions()
        real_symbols = [p["symbol"] for p in real_positions]
        
        # Ambil posisi di log lokal
        local_trades = load_active_trades()
        local_symbols = [sym for sym, data in local_trades.items() if data.get("status") == "OPEN"]
        
        # Cari ketidakcocokan (mismatch)
        all_symbols = set(real_symbols + local_symbols)
        for sym in all_symbols:
            has_mismatch = False
            mismatch_reason = ""
            
            if sym in real_symbols and sym not in local_symbols:
                has_mismatch = True
                mismatch_reason = "Posisi aktif di bursa, tetapi TIDAK terdaftar di log bot lokal."
            elif sym in local_symbols and sym not in real_symbols:
                has_mismatch = True
                mismatch_reason = "Terdaftar OPEN di log bot lokal, tetapi TIDAK ada posisi di bursa."
                
            if has_mismatch:
                _RECONCILIATION_MISMATCH_COUNT[sym] = _RECONCILIATION_MISMATCH_COUNT.get(sym, 0) + 1
                if _RECONCILIATION_MISMATCH_COUNT[sym] == 3: # 3x berturut-turut (~45 detik)
                    # Kirim notifikasi peringatan ke Telegram
                    TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
                    msg = (
                        f"🚨 *ALARM REKONSILIASI POSISI*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Pair:* `{sym}`\n"
                        f"⚠️ *Anomali:* {mismatch_reason}\n"
                        f"📝 *Solusi:* Periksa manual open positions di aplikasi BingX Anda!\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                    try:
                        import requests
                        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                      json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
                    except Exception as te:
                        logger.error(f"Gagal kirim notif rekonsiliasi ke Telegram: {te}")
            else:
                _RECONCILIATION_MISMATCH_COUNT[sym] = 0
    except Exception as e:
        logger.error(f"Gagal melakukan audit rekonsiliasi: {e}")

def monitor_and_sync_positions():
    """Background monitor: cek paper exits + trailing SL + sync TP/SL posisi live."""
    try:
        check_paper_exit()  # Cek apakah paper trade sudah kena TP/SL
    except Exception as e:
        logger.error(f"Error monitor check_paper_exit: {e}")
    
    try:
        check_and_update_trailing_sl()  # 🧠 Trailing SL otomatis
    except Exception as e:
        logger.error(f"Error monitor trailing: {e}")

    try:
        sync_missing_tpsl()  # 🔄 Sync missing TP/SL untuk posisi live secara otomatis
    except Exception as e:
        logger.error(f"Error monitor sync: {e}")

    try:
        audit_position_reconciliation()  # 🔄 Audit rekonsiliasi posisi bursa vs lokal
    except Exception as e:
        logger.error(f"Error monitor reconciliation: {e}")

def sync_missing_tpsl():
    """Cek semua posisi aktif, jika ada yang tidak punya TP atau SL, pasang otomatis secara granular."""
    try:
        positions = bx.get_open_positions()
        if not positions:
            return "📭 Tidak ada posisi aktif untuk di-sync."

        results = []
        for pos in positions:
            symbol = pos["symbol"]
            side = pos["positionSide"]
            amt = abs(float(pos["positionAmt"]))
            entry = float(pos["avgPrice"])
            
            if amt == 0: continue

            # Cek order yang ada
            orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
            if orders_res.get("code") != 0:
                logger.error(f"Gagal mengambil open orders untuk {symbol}: {orders_res}")
                continue  # Lewati koin ini agar tidak menaruh order duplikat
                
            open_orders_raw = orders_res.get("data", [])
            if isinstance(open_orders_raw, dict):
                open_orders = open_orders_raw.get("orders", [])
            else:
                open_orders = open_orders_raw if isinstance(open_orders_raw, list) else []

            has_sl = any("STOP" in o.get("type", "") for o in open_orders)
            has_tp = any("TAKE_PROFIT" in o.get("type", "") for o in open_orders)
            
            if not has_sl or not has_tp:
                # Ambil dari active_trade_data terlebih dahulu, jika tidak ada baru latest_signals
                trade_state = active_trade_data.get(symbol)
                if trade_state:
                    sl_price = float(trade_state.get("sl", 0))
                    tp_price = float(trade_state.get("tp1", 0))
                else:
                    latest = load_latest_signals()
                    signal = latest.get(symbol)
                    
                    # Cek apakah side sinyal cocok dengan side posisi
                    signal_action = signal.get("action", "").upper() if signal else ""
                    side_matches = (side == "LONG" and signal_action in ["BUY", "LONG"]) or \
                                   (side == "SHORT" and signal_action in ["SELL", "SHORT"])

                    if side_matches:
                        sl_price = float(signal.get("sl", 0))
                        tp_price = float(signal.get("tp1", 0))
                    else:
                        # Estimasi aman jika data sinyal tidak cocok atau tidak ada
                        if side == "LONG":
                            sl_price = round(entry * 0.985, 2)
                            tp_price = round(entry * 1.01, 2)
                        else:
                            sl_price = round(entry * 1.015, 2)
                            tp_price = round(entry * 0.99, 2)

                sl_side = "SELL" if side == "LONG" else "BUY"
                
                # Pasang Stop Loss jika belum ada
                if not has_sl and sl_price > 0:
                    logger.info(f"⚠️ {symbol} tidak punya SL. Memasang SL {sl_price}...")
                    bx._request("POST", "/openApi/swap/v2/trade/order", {
                        "symbol": symbol, "side": sl_side, "positionSide": side,
                        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": amt
                    })
                    results.append(f"✅ {symbol}: SL dipasang ({sl_price})")
                
                # Pasang Take Profit jika belum ada
                if not has_tp and tp_price > 0:
                    logger.info(f"⚠️ {symbol} tidak punya TP. Memasang TP {tp_price}...")
                    bx._request("POST", "/openApi/swap/v2/trade/order", {
                        "symbol": symbol, "side": sl_side, "positionSide": side,
                        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": amt
                    })
                    results.append(f"✅ {symbol}: TP dipasang ({tp_price})")
            else:
                results.append(f"✔️ {symbol}: Sudah memiliki SL dan TP.")

        return "\n".join(results)
    except Exception as e:
        logger.error(f"Sync Error: {e}")
        return f"❌ Sync Error: {str(e)}"

def apply_manual_tpsl(symbol, tp_price, sl_price):
    """Pasang TP/SL manual untuk posisi aktif di bursa."""
    try:
        positions = bx.get_open_positions(symbol)
        if not positions:
            return {"error": f"Tidak ada posisi untuk {symbol}"}
        pos = positions[0]
        pos_side = pos["positionSide"]
        qty = abs(float(pos["positionAmt"]))
        sl_side = "SELL" if pos_side == "LONG" else "BUY"
        bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty
        })
        bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": qty
        })
        return {"symbol": symbol, "tps": [tp_price], "sl": sl_price}
    except Exception as e:
        return {"error": str(e)}

def check_and_update_trailing_sl():
    """
    Memantau harga real-time dan menggeser SL saat menyentuh milestone TP1/TP2/TP3.
    Mendukung mode Paper dan Live. Melacak harga puncak (peak price) untuk
    mencegah hilangnya status milestone akibat retrace harga sementara.
    """
    try:
        paper_mode = get_paper_mode()
        
        if paper_mode:
            trades = load_paper_trades()
            open_trades = [t for t in trades if t["status"] == "OPEN_PAPER"]
            positions = []
            for t in open_trades:
                positions.append({
                    "symbol": t["symbol"],
                    "positionSide": t["side"],
                    "positionAmt": t["qty"],
                    "avgPrice": t["entry"]
                })
        else:
            positions = bx.get_open_positions()
            
        open_symbols = [p["symbol"] for p in positions] if positions else []
        
        # Hapus symbol yang sudah tidak ada di bursa dari active_trade_data dengan notifikasi
        updated_state = False
        for sym in list(active_trade_data.keys()):
            if sym not in open_symbols:
                try:
                    if not paper_mode:
                        notify_live_close(sym, active_trade_data[sym])
                except Exception as n_err:
                    logger.error(f"Error notifying live close for {sym}: {n_err}")
                del active_trade_data[sym]
                updated_state = True
                
        if updated_state:
            save_active_trades()
            
        if not positions:
            return
        
        for pos in positions:
            symbol = pos["symbol"]
            pos_side = pos["positionSide"]
            qty = abs(float(pos["positionAmt"]))
            avg_price = float(pos["avgPrice"])
            current_price = bx.get_current_price(symbol)
            
            if current_price == 0:
                continue
                
            # --- 1. AUTO-ADOPT: Adopsi posisi manual jika tidak ada di state lokal ---
            if symbol not in active_trade_data:
                try:
                    import brain_engine
                    # Hitung balance akun untuk sizing / risk
                    balance = 100.0
                    try:
                        if not paper_mode:
                            balance = bx.get_balance()
                    except:
                        pass
                    
                    # Buat rencana TP/SL otomatis berbasis ATR
                    plan = brain_engine.get_full_trade_plan(balance, avg_price, pos_side, symbol)
                    
                    active_trade_data[symbol] = {
                        "symbol": symbol,
                        "side": pos_side,
                        "entry_price": avg_price,
                        "sl": plan["sl"],
                        "tp1": plan["tp1"],
                        "tp2": plan["tp2"],
                        "tp3": 0.0,
                        "tp4": 0.0,
                        "qtys": [qty/2, qty/2, 0.0, 0.0],
                        "qty": qty,
                        "leverage": plan["leverage"],
                        "risk_pct": plan["risk_percent"],
                        "atr": plan["atr"],
                        "trailing": {
                            "activate_atr_mult": 1.0,
                            "offset_atr_mult": 0.5,
                            "active": False,
                            "highest_price": avg_price if pos_side == "LONG" else 0,
                            "lowest_price": avg_price if pos_side == "SHORT" else 0,
                        },
                        "status": "OPEN",
                        "open_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "adopted": True
                    }
                    save_active_trades()
                    
                    # Kirim Telegram Notif Auto-Adopt
                    TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
                    mode_label = "PAPER" if paper_mode else "LIVE"
                    msg_adopt = (
                        f"📥 *POSISI MANUAL DIADOPSI ({mode_label})*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Pair:* `{symbol}` ({pos_side})\n"
                        f"📈 *Entry:* `{avg_price}`\n"
                        f"🛡️ *SL Otomatis:* `{plan['sl']}`\n"
                        f"🎯 *TP1:* `{plan['tp1']}` | *TP2:* `{plan['tp2']}`\n"
                        f"📝 *Status:* Berhasil diadopsi & diproteksi.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                    import requests as r
                    r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT_ID, "text": msg_adopt, "parse_mode": "Markdown"}, timeout=5)
                    logger.info(f"📥 AUTO-ADOPT: Posisi manual {symbol} {pos_side} diadopsi pada entry {avg_price}")
                except Exception as adopt_err:
                    logger.error(f"Gagal auto-adopt posisi {symbol}: {adopt_err}")
                    continue
            
            trade = active_trade_data[symbol]
            entry_price = trade["entry_price"]
            
            # --- 2. AUTO-CALIBRATION: Kalibrasi ulang jika entry di bursa berbeda dengan state ---
            # Jika selisih entry bursa vs state > 0.1%, lakukan kalibrasi ulang level TP/SL
            if abs(avg_price - entry_price) / entry_price > 0.001:
                try:
                    logger.info(f"🔄 Kalibrasi TP/SL {symbol} karena slippage: {entry_price} -> {avg_price}")
                    prec = get_symbol_precision(symbol)
                    price_prec = prec["price"]
                    
                    # Hitung persentase TP/SL dari entry lama
                    sl_pct = (trade["sl"] - entry_price) / entry_price
                    tp1_pct = (trade["tp1"] - entry_price) / entry_price if trade.get("tp1", 0) > 0 else 0
                    tp2_pct = (trade["tp2"] - entry_price) / entry_price if trade.get("tp2", 0) > 0 else 0
                    tp3_pct = (trade["tp3"] - entry_price) / entry_price if trade.get("tp3", 0) > 0 else 0
                    tp4_pct = (trade["tp4"] - entry_price) / entry_price if trade.get("tp4", 0) > 0 else 0
                    
                    # Set entry baru ke avg_price bursa
                    trade["entry_price"] = avg_price
                    trade["qty"] = qty
                    
                    # Terapkan persentase ke entry baru
                    trade["sl"] = round(avg_price * (1 + sl_pct), price_prec)
                    if tp1_pct != 0: trade["tp1"] = round(avg_price * (1 + tp1_pct), price_prec)
                    if tp2_pct != 0: trade["tp2"] = round(avg_price * (1 + tp2_pct), price_prec)
                    if tp3_pct != 0: trade["tp3"] = round(avg_price * (1 + tp3_pct), price_prec)
                    if tp4_pct != 0: trade["tp4"] = round(avg_price * (1 + tp4_pct), price_prec)
                    
                    # Reset peak price di trailing
                    if "trailing" in trade:
                        trade["trailing"]["highest_price"] = avg_price if pos_side == "LONG" else 0
                        trade["trailing"]["lowest_price"] = avg_price if pos_side == "SHORT" else 0
                    
                    active_trade_data[symbol] = trade
                    save_active_trades()
                    
                    # Kirim Telegram Notif Auto-Calibration
                    TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
                    mode_label = "PAPER" if paper_mode else "LIVE"
                    msg_calib = (
                        f"🔄 *KALIBRASI LEVEL TP/SL SELESAI ({mode_label})*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Pair:* `{symbol}`\n"
                        f"📈 *Entry Baru:* `{avg_price}` (Slippage/Susul)\n"
                        f"🛡️ *SL Baru:* `{trade['sl']}`\n"
                        f"🎯 *TP1 Baru:* `{trade.get('tp1', 0)}` | *TP2 Baru:* `{trade.get('tp2', 0)}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                    import requests as r
                    r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT_ID, "text": msg_calib, "parse_mode": "Markdown"}, timeout=5)
                except Exception as calib_err:
                    logger.error(f"Gagal melakukan kalibrasi {symbol}: {calib_err}")
            
            # Ambil kembali data setelah kemungkinan kalibrasi
            trade = active_trade_data[symbol]
            entry_price = trade["entry_price"]
            current_sl = trade["sl"]
            tp1 = trade.get("tp1", 0)
            tp2 = trade.get("tp2", 0)
            tp3 = trade.get("tp3", 0)
            
            # Pastikan struktur trailing eksis
            if "trailing" not in trade:
                trade["trailing"] = {
                    "activate_atr_mult": 1.0,
                    "offset_atr_mult": 0.5,
                    "active": False,
                    "highest_price": entry_price if pos_side == "LONG" else 0,
                    "lowest_price": entry_price if pos_side == "SHORT" else 0,
                }
            
            # Update harga tertinggi/terendah (peak price) sejak posisi dibuka
            if pos_side == "LONG":
                highest_price = max(current_price, trade["trailing"].get("highest_price", entry_price))
                trade["trailing"]["highest_price"] = highest_price
                peak_price = highest_price
            else:
                lowest_price = trade["trailing"].get("lowest_price", entry_price)
                if lowest_price == 0:
                    lowest_price = entry_price
                lowest_price = min(current_price, lowest_price)
                trade["trailing"]["lowest_price"] = lowest_price
                peak_price = lowest_price
                
            # Simpan update peak price ke state lokal
            active_trade_data[symbol] = trade
            save_active_trades()
            
            import brain_engine
            # Gunakan peak_price sebagai basis perhitungan milestone, bukan current_price
            result = brain_engine.calculate_milestone_trailing_sl(
                peak_price, pos_side, entry_price, current_sl, tp1, tp2, tp3, symbol
            )
            
            if result["should_update"]:
                new_sl = result["new_sl"]
                sl_side = "SELL" if pos_side == "LONG" else "BUY"
                
                if paper_mode:
                    # Update Stop Loss di database paper trades
                    trades = load_paper_trades()
                    for pt in trades:
                        if pt["symbol"] == symbol and pt["status"] == "OPEN_PAPER":
                            pt["sl"] = new_sl
                    update_paper_trades(trades)
                else:
                    # 1. Batalkan semua SL lama di bursa (STOP_MARKET)
                    try:
                        orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                        if orders_res.get("code") != 0:
                            raise Exception(f"API Error get open orders: {orders_res}")
                            
                        open_orders = orders_res.get("data", [])
                        if isinstance(open_orders, dict):
                            open_orders = open_orders.get("orders", [])
                        
                        for order in open_orders:
                            if order.get("type") == "STOP_MARKET":
                                bx.cancel_order(symbol, order.get("orderId"))
                    except Exception as ce:
                        logger.error(f"Gagal cancel SL lama, batalkan update SL baru demi keamanan: {ce}")
                        continue  # SKIP placing new SL if we couldn't cancel old ones!
                        
                    # 2. Pasang SL baru di bursa
                    bx._request("POST", "/openApi/swap/v2/trade/order", {
                        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                        "type": "STOP_MARKET", "stopPrice": new_sl, "quantity": qty
                    })
                
                # 3. Update state lokal
                trade["sl"] = new_sl
                active_trade_data[symbol] = trade
                save_active_trades()
                
                # 4. Kirim notifikasi Telegram tentang trailing SL
                try:
                    TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")
                    mode_label = "PAPER" if paper_mode else "LIVE"
                    msg = (
                        f"🔄 *TRAILING STOP LOSS AKTIF ({mode_label})*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Pair:* `{symbol}`\n"
                        f"🛡️ *SL Baru:* `{new_sl}`\n"
                        f"📝 *Alasan:* {result['reason']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                    import requests as r
                    r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
                except Exception as tg_err:
                    logger.error(f"Gagal notif trailing SL ke Telegram: {tg_err}")
                    
                logger.info(f"🔄 TRAILING SL {symbol} ({mode_label}): {current_sl} → {new_sl} | {result['reason']}")
    except Exception as e:
        logger.error(f"Error check_and_update_trailing_sl: {e}")


def reentry_signal(symbol):
    """Re-entry posisi menggunakan sinyal terakhir yang tersimpan."""
    if symbol in latest_signals:
        return execute_signal(latest_signals[symbol])
    return {"status": "no_signal", "symbol": symbol}
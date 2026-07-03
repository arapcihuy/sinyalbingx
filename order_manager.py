import os
import math
import logging
import json
import time
import threading
import requests
import tempfile
import sqlite3
from dotenv import load_dotenv
import bingx_client as bx

load_dotenv()
logger = logging.getLogger(__name__)

# Global State & Locks
state_lock = threading.RLock()
latest_signals = {}
active_trade_data = {}
last_known_positions = {}
_SYMBOL_PRECISION_CACHE = {}
_LAST_KNOWN_BALANCE = None

def _get_min_sl_pct(symbol):
    """Minimum SL percent: 2% BTC, 3% ETH, 2.5% others (CLAUDE.md Min SL Guard)."""
    if "BTC" in symbol:
        return 0.02
    elif "ETH" in symbol:
        return 0.03
    return 0.025

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

def _round_price(price, symbol):
    """Round price based on symbol precision from API."""
    prec = get_symbol_precision(symbol)
    return round(float(price), prec["price"])

def _recalc_tp_sl_for_entry(tv_sl, tv_tps, signal_price, actual_entry, side, symbol):
    """Recalculate TP/SL from TV signal relative to actual entry.
    TV signals have absolute prices based on signal_price. When actual_entry
    differs (market slippage), percentages must be preserved and reapplied.
    Returns (sl, [tp1..tp4]) with direction validated for LONG/SHORT."""
    if signal_price <= 0 or actual_entry <= 0:
        return tv_sl, tv_tps
    # If entry is very close to signal, use as-is
    if abs(actual_entry - signal_price) / signal_price < 0.001:
        return tv_sl, tv_tps
    
    result_sl = tv_sl
    result_tps = list(tv_tps)
    
    # Recalc SL: convert to % from signal, apply to entry
    if tv_sl > 0:
        sl_pct = (tv_sl - signal_price) / signal_price
        result_sl = _round_price(actual_entry * (1 + sl_pct), symbol)
        # Validate direction
        if side == "LONG" and result_sl >= actual_entry:
            result_sl = _round_price(actual_entry * (1 - _get_min_sl_pct(symbol)), symbol)
            logger.warning(f"⚠️ {symbol} TV SL recalc invalid (>{actual_entry} for LONG). Using min SL guard: {result_sl}")
        elif side == "SHORT" and result_sl <= actual_entry:
            result_sl = _round_price(actual_entry * (1 + _get_min_sl_pct(symbol)), symbol)
            logger.warning(f"⚠️ {symbol} TV SL recalc invalid (<{actual_entry} for SHORT). Using min SL guard: {result_sl}")
        # Min SL guard: ensure SL distance >= minimum
        _min = _get_min_sl_pct(symbol)
        if side == "LONG" and result_sl > 0:
            sl_dist = (actual_entry - result_sl) / actual_entry
            if sl_dist < _min:
                result_sl = _round_price(actual_entry * (1 - _min), symbol)
                logger.warning(f"⚠️ {symbol} SL too close ({sl_dist*100:.2f}% < {_min*100}%). Widened to {result_sl}")
        elif side == "SHORT" and result_sl > 0:
            sl_dist = (result_sl - actual_entry) / actual_entry
            if sl_dist < _min:
                result_sl = _round_price(actual_entry * (1 + _min), symbol)
                logger.warning(f"⚠️ {symbol} SL too close ({sl_dist*100:.2f}% < {_min*100}%). Widened to {result_sl}")
    
    # Recalc TPs: same percentage approach
    for i, tp in enumerate(tv_tps):
        if tp > 0:
            tp_pct = (tp - signal_price) / signal_price
            new_tp = _round_price(actual_entry * (1 + tp_pct), symbol)
            # Validate direction: LONG TPs above entry, SHORT TPs below
            if side == "LONG" and new_tp <= actual_entry:
                logger.warning(f"⚠️ {symbol} TV TP{i+1} recalc invalid (<{actual_entry} for LONG). Skipping.")
                new_tp = 0
            elif side == "SHORT" and new_tp >= actual_entry:
                logger.warning(f"⚠️ {symbol} TV TP{i+1} recalc invalid (>{actual_entry} for SHORT). Skipping.")
                new_tp = 0
            result_tps[i] = new_tp
    
    if result_sl != tv_sl or any(r != t for r, t in zip(result_tps, tv_tps)):
        logger.info(f"🔄 {symbol} TP/SL recalculated for entry {actual_entry} (was signal {signal_price})")
    return result_sl, result_tps

PAPER_TRADES_FILE = "paper_trades.json"
ACTIVE_TRADES_FILE = "active_trades.json"
LATEST_SIGNALS_FILE = "latest_signals.json"

import settings_manager

def _atomic_write_json(file_path, data):
    """Securely write JSON using a temporary file to prevent corruption."""
    try:
        dir_name = os.path.dirname(os.path.abspath(file_path))
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False) as tf:
            json.dump(data, tf, indent=4)
            tempname = tf.name
        os.replace(tempname, file_path)
    except Exception as e:
        logger.error(f"CRITICAL: Atomic write failed for {file_path}: {e}")
        # Fallback to normal write if replace fails
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        except:
            pass

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
    with state_lock:
        trades = load_paper_trades()
        trades.append(trade)
        _atomic_write_json(PAPER_TRADES_FILE, trades)

def update_paper_trades(trades):
    with state_lock:
        _atomic_write_json(PAPER_TRADES_FILE, trades)

def load_latest_signals():
    global latest_signals
    if os.path.exists(LATEST_SIGNALS_FILE):
        try:
            with open(LATEST_SIGNALS_FILE, "r") as f:
                latest_signals = json.load(f)
        except:
            latest_signals = {}
            
    db_path = "signals.db"
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS tv_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                action TEXT,
                price REAL,
                sl REAL,
                tp1 REAL,
                tp2 REAL,
                tp3 REAL,
                tp4 REAL
            )
        ''')
        c.execute("SELECT symbol, action, price, sl, tp1, tp2, tp3, tp4 FROM tv_signals ORDER BY ts ASC")
        rows = c.fetchall()
        for r in rows:
            sym = r[0]
            latest_signals[sym] = {
                "symbol": sym,
                "action": r[1],
                "price": r[2],
                "sl": r[3],
                "tp1": r[4],
                "tp2": r[5],
                "tp3": r[6],
                "tp4": r[7]
            }
        conn.close()
    except Exception as e:
        logger.error(f"Gagal load latest_signals dari DB: {e}")
    return latest_signals

def save_latest_signals():
    with state_lock:
        _atomic_write_json(LATEST_SIGNALS_FILE, latest_signals)
        db_path = "signals.db"
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS tv_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL,
                    symbol TEXT,
                    action TEXT,
                    price REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    tp4 REAL
                )
            ''')
            for sym, data in latest_signals.items():
                c.execute("SELECT id FROM tv_signals WHERE symbol=? AND action=? AND price=? AND sl=? AND tp1=?", 
                          (sym, data.get("action"), data.get("price"), data.get("sl"), data.get("tp1")))
                if not c.fetchone():
                    c.execute('''
                        INSERT INTO tv_signals (ts, symbol, action, price, sl, tp1, tp2, tp3, tp4)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (time.time(), sym, data.get("action"), data.get("price"), data.get("sl"), 
                          data.get("tp1"), data.get("tp2"), data.get("tp3"), data.get("tp4")))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Gagal save latest_signals ke DB: {e}")

def save_active_trades():
    with state_lock:
        _atomic_write_json(ACTIVE_TRADES_FILE, active_trade_data)

def load_active_trades():
    global active_trade_data
    if os.path.exists(ACTIVE_TRADES_FILE):
        try:
            with open(ACTIVE_TRADES_FILE, "r") as f:
                with state_lock:
                    active_trade_data = json.load(f)
                    logger.info(f"💾 State active trades di-load: {list(active_trade_data.keys())}")
        except Exception as e:
            logger.error(f"Gagal load active_trades: {e}")
            with state_lock:
                active_trade_data = {}
    return active_trade_data

# Inisialisasi state saat modul di-load
load_latest_signals()
load_active_trades()

# ── Startup: sync active_trades dari Exchange ──
def sync_from_exchange_on_startup():
    """Saat startup LIVE mode, sync active_trades.json dengan posisi real BingX."""
    global active_trade_data, state_lock
    import state_manager
    import logging as _log
    _logger = _log.getLogger(__name__)
    
    mode = state_manager.get_trading_mode()
    if mode["paper_mode"] or mode["use_demo"]:
        _logger.info("⏭️ Paper/Demo mode — skip exchange sync.")
        return
    
    try:
        positions = bx.get_open_positions()
        with state_lock:
            synced = {}
            for p in positions:
                sym = p["symbol"]
                amt = float(p["positionAmt"])
                if amt == 0: continue
                side = "LONG" if amt > 0 else "SHORT"
                # Preserve TP/SL: prioritas dari sinyal TV terakhir, lalu state lama
                old_trade = active_trade_data.get(sym, {})
                last_signal = latest_signals.get(sym, {})
                
                # TP/SL: sinyal TV > state lama > exchange orders > 0
                tv_sl_raw = float(last_signal.get("sl", 0))
                tv_tp1_raw = float(last_signal.get("tp1", 0))
                tv_signal_price = float(last_signal.get("price", 0)) or float(last_signal.get("entry_price", 0))
                
                if tv_sl_raw > 0 or tv_tp1_raw > 0:
                    # TV signal ada → recalc relatif ke actual entry
                    actual_entry = float(p.get("avgPrice", 0))
                    tv_tps_raw = [
                        float(last_signal.get("tp1", 0)),
                        float(last_signal.get("tp2", 0)),
                        float(last_signal.get("tp3", 0)),
                        float(last_signal.get("tp4", 0)),
                    ]
                    sl_val, recalc_tps = _recalc_tp_sl_for_entry(
                        tv_sl_raw, tv_tps_raw, tv_signal_price, actual_entry, side, sym
                    )
                    tp1_val = recalc_tps[0]
                    tp2_val = recalc_tps[1]
                    tp3_val = recalc_tps[2]
                    tp4_val = recalc_tps[3]
                else:
                    sl_val = old_trade.get("sl", 0)
                    tp1_val = old_trade.get("tp1", 0)
                    tp2_val = old_trade.get("tp2", 0)
                    tp3_val = old_trade.get("tp3", 0)
                    tp4_val = old_trade.get("tp4", 0)
                
                # Jika TV & state kosong, baca ulang dari exchange orders
                if not sl_val and not tp1_val:
                    try:
                        ex_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": sym})
                        if ex_res.get("code") == 0:
                            ex_data = ex_res.get("data", [])
                            ex_ords = ex_data.get("orders", []) if isinstance(ex_data, dict) else (ex_data if isinstance(ex_data, list) else [])
                            tp_ex = []
                            for o in ex_ords:
                                if "TAKE_PROFIT" in o.get("type", ""):
                                    tp_ex.append(float(o.get("stopPrice", 0)))
                                elif "STOP" in o.get("type", ""):
                                    sl_val = float(o.get("stopPrice", 0))
                            tp_ex.sort()
                            if len(tp_ex) >= 1: tp1_val = tp_ex[0]
                            if len(tp_ex) >= 2: tp2_val = tp_ex[1]
                            if len(tp_ex) >= 3: tp3_val = tp_ex[2]
                            if len(tp_ex) >= 4: tp4_val = tp_ex[3]
                            _logger.info(f"📥 {sym}: TP/SL dibaca dari exchange orders (no TV/state)")
                    except Exception as ex_err:
                        _logger.warning(f"Gagal baca exchange orders untuk {sym}: {ex_err}")
                
                synced[sym] = {
                    "symbol": sym,
                    "side": side,
                    "entry_price": float(p.get("avgPrice", 0)),
                    "qty": abs(amt),
                    "leverage": int(p.get("leverage", 10)),
                    "status": "OPEN_SYNCED",
                    "sl": sl_val,
                    "tp1": tp1_val,
                    "tp2": tp2_val,
                    "tp3": tp3_val,
                    "tp4": tp4_val,
                    "tp_notified": old_trade.get("tp_notified", {}),
                    "trailing_enabled": old_trade.get("trailing_enabled", True),
                    "peak_price": old_trade.get("peak_price", 0),
                    "trailing_sl_price": old_trade.get("trailing_sl_price", 0),
                    "milestone_reached": old_trade.get("milestone_reached", ""),
                }
            
            # Compare: jika berbeda, update
            if synced != {k: v for k, v in active_trade_data.items() if v.get("status") != "CLOSED"}:
                active_trade_data = synced
                _atomic_write_json(ACTIVE_TRADES_FILE, active_trade_data)
                _logger.info(f"🔄 Startup sync: updated active_trades.json ({len(synced)} positions from exchange)")
            else:
                _logger.info("✅ Startup sync: active_trades.json already in-sync.")
    except Exception as e:
        _logger.warning(f"⚠️ Startup sync failed (non-fatal): {e}")

sync_from_exchange_on_startup()

def _round_qty(qty, symbol):
    """Round quantity based on symbol precision from API."""
    prec = get_symbol_precision(symbol)
    return round(float(qty), prec["qty"])

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
    # Selalu ijinkan jika diatur UNLIMITED (DEFAULT)
    if os.getenv("FILTER_BY_SCANNER", "false").lower() != "true":
        return True
        
    try:
        if not os.path.exists("scanned_pairs.json"):
            # Jika file tidak ada tapi filter ON, maka blokir demi keamanan (conservative)
            return False
        with open("scanned_pairs.json", "r") as f:
            data = json.load(f)
            return symbol in data.get("eligible_pairs", [])
    except Exception as e:
        logger.error(f"Error checking pair eligibility: {e}")
        return False

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
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
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

def notify_tp_hit(symbol: str, tp_level: int, tp_price: float, trade_data: dict):
    """Kirim notifikasi ke Telegram bahwa level TP sudah tercapai (order TP terisi di bursa)."""
    try:
        TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
        entry = trade_data.get("entry_price", 0)
        side = trade_data.get("side", "LONG")
        pct = ((tp_price - entry) / entry * 100) if entry > 0 else 0
        msg = (
            f"🎯 *TP{tp_level} KENA! ({side})*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Pair:* `{symbol}`\n"
            f"📈 *Entry:* `{entry}` → *TP{tp_level}:* `{tp_price}` (`+{pct:.2f}%`)\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        import requests as r
        r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
               json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        logger.info(f"📨 TP{tp_level} HIT NOTIFICATION for {symbol} @ {tp_price}")
    except Exception as e:
        logger.error(f"Gagal kirim notif TP hit untuk {symbol}: {e}")

def notify_live_close(symbol: str, trade_data: dict):
    """Kirim notifikasi ke Telegram bahwa posisi LIVE telah selesai/tutup."""
    try:
        # Beri jeda 2 detik agar bursa mencatat data income
        time.sleep(2)
        income_history = bx.get_income_history(symbol=symbol, days=1)
        if income_history is None:
            income_history = []
        
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
        TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
        
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

    # SIMPAN SINYAL TERAKHIR KE MEMORY/FILE (di-load oleh tombol "Susul" / re_entry)
    global latest_signals
    latest_signals[symbol] = data
    save_latest_signals()

    # Check paper exits
    check_paper_exit()

    if action == "CLOSE":
        return _close_position(symbol)

    # ── CHECK EXISTING POSITION & REVERSAL ──
    # FORCE SYNC: Selalu update dari posisi asli di BingX sebelum cek sinyal
    if not get_paper_mode():
        try:
            live_pos = bx.get_open_positions(symbol)
            # Update state file dari kenyataan di bursa
            if not live_pos:
                with state_lock:
                    if symbol in active_trade_data:
                        del active_trade_data[symbol]
                save_active_trades()
        except:
            pass
    
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
            reason = f"Posisi {target_pos_side} untuk {symbol} sudah terbuka. Sinyal duplikat diabaikan."
            logger.warning(f"⚠️ {reason}")
            return {"status": "already_open", "symbol": symbol, "reason": reason}

    # ── SLOT MANAGEMENT ──
    # Batasi posisi aktif sesuai setting
    try:
        settings = settings_manager.load_settings()
        max_slots = int(settings.get("max_slots", 0))
        current_slots = get_total_open_positions_count()
        
        if max_slots > 0 and current_slots >= max_slots:
            reason = f"Slot penuh ({current_slots}/{max_slots}). Ini hanya aktif jika max_slots > 0."
            logger.warning(f"🚫 {reason} Mengabaikan {symbol}.")
            return {"status": "slots_full", "symbol": symbol, "reason": reason}
    except Exception as slot_err:
        logger.error(f"Error checking slot management: {slot_err}")
    
    # ── MARGIN SAFETY GUARD (DISABLED) ──
    # ponytail: dulunya blokir jika available < 5% equity. User request: semua sinyal wajib masuk.
    # Re-enable: uncomment block below jika mau batasi margin kritis.
    # try:
    #     if not get_paper_mode():
    #         balance_data = bx._request('GET', '/openApi/swap/v2/user/balance')
    #         if balance_data.get("code") == 0:
    #             available = float(balance_data["data"]["balance"]["availableMargin"])
    #             equity = float(balance_data["data"]["balance"]["equity"])
    #             if available < (equity * 0.05):
    #                 reason = f"Margin kritis ({available:.2f}). Entry dibatalkan."
    #                 logger.warning(f"⚠️ {reason}")
    #                 return {"status": "low_margin", "symbol": symbol, "reason": reason}
    # except:
    #     pass

    if not is_pair_eligible(symbol):
        reason = f"{symbol} diabaikan oleh scanner karena expectancy rendah / pair tidak eligible."
        logger.warning(f"🚫 {reason}")
        return {"status": "ignored_by_scanner", "symbol": symbol, "reason": reason}

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

    settings = settings_manager.load_settings()
    brain_enabled = settings.get("brain_enabled", True)

    # Default input TV
    tv_sl_price = _round_price(float(data.get("sl", 0)), symbol)
    tv_tp1_price = _round_price(float(data.get("tp1", 0)), symbol)
    tv_tp2_price = _round_price(float(data.get("tp2", 0)), symbol)
    tv_tp3_price = _round_price(float(data.get("tp3", 0)), symbol)
    tv_tp4_price = _round_price(float(data.get("tp4", 0)), symbol)

    # TV selalu sumber TP/SL
    sl_price = tv_sl_price
    tp1_price = tv_tp1_price
    tp2_price = tv_tp2_price
    tp3_price = tv_tp3_price
    tp4_price = tv_tp4_price
    tp_prices = [tp1_price, tp2_price, tp3_price, tp4_price]

    # ── TV TP/SL MUTLAK: Tidak ada MIN SL GUARD, tidak ada auto-generate TP ──
    # TP/SL 100% dari TV. Brain engine HANYA untuk leverage + qty.
    if sl_price == 0 and tp1_price == 0:
        # TV tidak kirim TP/SL sama sekali → brain full fallback
        logger.info("📺 TV tidak kirim TP/SL, fallback ke brain engine (4 TP)")
        trade_plan = brain_engine.get_full_trade_plan(balance, entry_price, pos_side, symbol)
        sl_price = _round_price(float(trade_plan.get("sl", 0)), symbol)
        tp1_price = _round_price(float(trade_plan.get("tp1", 0)), symbol)
        tp2_price = _round_price(float(trade_plan.get("tp2", 0)), symbol)
        tp3_price = _round_price(float(trade_plan.get("tp3", 0)), symbol)
        tp4_price = _round_price(float(trade_plan.get("tp4", 0)), symbol)
        tp_prices = [tp1_price, tp2_price, tp3_price, tp4_price]
    elif tp1_price == 0:
        # TV kirim SL tapi tidak kirim TP → brain generate TP pakai SL TV
        logger.info(f"📺 TV kirim SL={sl_price} tapi tanpa TP → brain generate 4 TP")
        trade_plan = brain_engine.get_full_trade_plan(balance, entry_price, pos_side, symbol)
        tp1_price = _round_price(float(trade_plan.get("tp1", 0)), symbol)
        tp2_price = _round_price(float(trade_plan.get("tp2", 0)), symbol)
        tp3_price = _round_price(float(trade_plan.get("tp3", 0)), symbol)
        tp4_price = _round_price(float(trade_plan.get("tp4", 0)), symbol)
        tp_prices = [tp1_price, tp2_price, tp3_price, tp4_price]

    try:
        tp_mode = settings.get("tp_mode", "multiple")
    except Exception:
        tp_mode = "multiple"

    logger.info(f"🎯 TV MUTLAK → TP1={tp1_price} TP2={tp2_price} TP3={tp3_price} TP4={tp4_price} SL={sl_price}")

    if brain_enabled:
        logger.info(f"🧠 BRAIN ENABLED → {symbol} pakai TV TP/SL + brain lev/margin")
        # Brain penuh hitung leverage — TV leverage diabaikan
        leverage = brain_engine.get_safe_leverage(balance, entry_price, sl_price, pos_side, symbol)
        risk_pct = float(brain_engine.get_dynamic_risk_percent(balance))
        logger.info(f"🧠 BRAIN LEV: {leverage}x | Risk: {risk_pct}%")
    else:
        logger.info(f"📺 BRAIN DISABLED → {symbol} pakai TP/SL dari TV")

    # ── LIQUIDATION GUARD: Turunkan leverage kalau SL ngelewatin liquid ──
    cfg = brain_engine.get_symbol_config(symbol)
    mmr = float(cfg.get("mmr", 0.005))
    buffer_pct = settings.get("liquidation_buffer_pct", 0.10)
    max_lev_attempts = 10

    for attempt in range(max_lev_attempts):
        est_liq = brain_engine.estimate_liquidation_price(entry_price, leverage, pos_side, mmr)
        if est_liq <= 0:
            break

        if pos_side == "LONG":
            min_safe_sl = est_liq * (1.0 + buffer_pct)
            if sl_price > min_safe_sl:
                break  # AMAN
            # SL ngelewatin liquid → turunkan leverage
            old_lev = leverage
            leverage = max(1, leverage - 2)
            logger.warning(f"🛡️ LIQ GUARD: {symbol} SL {sl_price} ngelewatin liq {est_liq} → turun leverage {old_lev}x → {leverage}x")
        else:
            max_safe_sl = est_liq * (1.0 - buffer_pct)
            if sl_price < max_safe_sl:
                break  # AMAN
            old_lev = leverage
            leverage = max(1, leverage - 2)
            logger.warning(f"🛡️ LIQ GUARD: {symbol} SL {sl_price} ngelewatin liq {est_liq} → turun leverage {old_lev}x → {leverage}x")

    # Final log
    est_liq_final = brain_engine.estimate_liquidation_price(entry_price, leverage, pos_side, mmr)
    logger.info(f"🛡️ LIQ CHECK: {symbol} {pos_side} | Entry={entry_price:.4f} SL={sl_price:.4f} Liq={est_liq_final:.4f} Lev={leverage}x")

    # Hitung kuantitas cerdas multi-TP dengan pengaman 50%
    calc_result = brain_engine.calculate_smart_multi_tp_qty(balance, entry_price, sl_price, tp_prices, leverage, risk_pct, symbol)
    qtys = calc_result["qtys"]
    qty = calc_result["total_qty"]

    # ── POST-QTY DEDUP: brain_engine hard limiter bisa menyamakan harga TP → dedup lagi ──
    seen_prices = set()
    for i in range(len(tp_prices)):
        p = tp_prices[i]
        if p > 0:
            if p in seen_prices:
                logger.warning(f"🎯 POST-QTY DEDUP: TP{i+1}={p} duplikat → digabungkan ke sisa")
                # Cari TP sebelumnya yang harganya sama, gabung qty
                for j in range(i-1, -1, -1):
                    if tp_prices[j] == p:
                        qtys[j] += qtys[i]
                        qtys[i] = 0.0
                        tp_prices[i] = 0
                        break
            else:
                seen_prices.add(p)
    # Rebuild tp1..tp4 dari tp_prices setelah dedup
    while len(tp_prices) < 4:
        tp_prices.append(0.0)
    tp_prices = tp_prices[:4]
    tp1_price, tp2_price, tp3_price, tp4_price = tp_prices
    logger.info(f"🎯 FINAL TP SET: TP1={tp1_price} TP2={tp2_price} TP3={tp3_price} TP4={tp4_price}")
    
    if qty <= 0:
        reason = f"Saldo tersedia ${balance:.2f} terlalu kecil untuk qty minimum {symbol}."
        logger.warning(f"🚫 {reason} Mengabaikan sinyal.")
        return {"status": "insufficient_balance", "symbol": symbol, "reason": reason}
    
    # ATR untuk trailing
    atr = entry_price * 0.01  # fallback 1%
    try:
        # Ambil data candle real (1h atau 15m) untuk ATR yang presisi
        candles = bx.get_candles(symbol, "1h", limit=30)
        if candles:
            real_atr = brain_engine.calculate_atr(candles, 14)
            if real_atr > 0:
                atr = real_atr
                logger.info(f"📊 ATR Real ({symbol}): {atr:.4f}")
    except Exception as atr_err:
        logger.warning(f"⚠️ Gagal ambil ATR real untuk {symbol}: {atr_err}. Pakai fallback 1%.")
    
    logger.info(f"🧠 BRAIN: {symbol} {pos_side} | Lev: {leverage}x | Qty: {qty} | Margin: {calc_result['margin']:.2f} USDT")
    logger.info(f"📺 TV TP/SL: SL={sl_price} TP1={tp1_price} TP2={tp2_price} TP3={tp3_price} TP4={tp4_price}")
    
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
        
        # Simpan trade data ke active_trade_data hanya untuk paper
        with state_lock:
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
                    "highest_price": entry_price,
                    "lowest_price": entry_price
                },
                "status": "OPEN",
                "open_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        save_active_trades()
        
        logger.info(f"📝 PAPER TRADE OPENED: {symbol} {pos_side} @ {entry_price}")
        return {"status": "success_paper", "symbol": symbol, "qty": qty}
 
    # Live Execution
    bx.set_leverage(symbol, leverage, pos_side)

    # ── CANCEL ALL EXISTING ORDERS sebelum pasang SL/TP baru ──
    # Mencegah SL/TP lama menumpuk jadi dobel
    try:
        bx.cancel_all_orders(symbol)
        logger.info(f"🧹 Semua order lama di-{symbol} dibuang sebelum entry baru.")
    except Exception as cancel_err:
        logger.warning(f"⚠️ Gagal cancel orders {symbol}: {cancel_err}")

    order_res = bx.place_order(symbol, order_side, pos_side, qty, "MARKET")

    if order_res.get("code") == 0:
        # ── Pakai actual fill price dari exchange, bukan TV price ──
        actual_entry = float(order_res.get("data", {}).get("order", {}).get("avgPrice", 0)) or entry_price
        if abs(actual_entry - entry_price) / max(entry_price, 1e-8) > 0.01:
            logger.info(f"🔄 {symbol} fill price {actual_entry} berbeda dari TV price {entry_price} → pakai fill price")
        entry_price = actual_entry

        # ── DIRECTION VALIDATION: pastikan TP/SL arahnya benar vs actual fill ──
        if pos_side == "LONG":
            if sl_price >= entry_price:
                logger.warning(f"🛡️ FIX: LONG SL {sl_price} >= entry {entry_price} → auto-adjust ke entry - 1%")
                sl_price = round(entry_price * 0.99, 3)
            for i in range(len(tp_prices)):
                if tp_prices[i] > 0 and tp_prices[i] <= entry_price:
                    logger.warning(f"🎯 FIX: LONG TP{i+1}={tp_prices[i]} <= entry {entry_price} → skip")
                    tp_prices[i] = 0
                    qtys[i] = 0
        else:  # SHORT
            if sl_price <= entry_price:
                logger.warning(f"🛡️ FIX: SHORT SL {sl_price} <= entry {entry_price} → auto-adjust ke entry + 1%")
                sl_price = round(entry_price * 1.01, 3)
            for i in range(len(tp_prices)):
                if tp_prices[i] > 0 and tp_prices[i] >= entry_price:
                    logger.warning(f"🎯 FIX: SHORT TP{i+1}={tp_prices[i]} >= entry {entry_price} → skip")
                    tp_prices[i] = 0
                    qtys[i] = 0

        # ── 1. Pasang STOP LOSS DULU (sebelum simpan state) ──
        sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty,
            "priceProtect": "true"
        })

        if sl_res.get("code") != 0:
            logger.error(f"🛑 CRITICAL: Gagal pasang STOP LOSS untuk {symbol}: {sl_res.get('msg')}")
            try:
                r_msg = f"⚠️ *EMERGENCY: SL FAILED* ⚠️\nPair: `{symbol}`\nError: `{sl_res.get('msg')}`\n*POSISI TERBUKA TANPA PROTEKSI!*"
                requests.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
                              json={"chat_id": os.getenv('TELEGRAM_CHAT_ID'), "text": r_msg, "parse_mode": "Markdown"})
            except: pass

        # ── 2. Pasang Tiap Level TP ──
        time.sleep(2)  # BingX rate limit

        placed_tp = []
        for i, tp_price in enumerate(tp_prices):
            tp_qty = qtys[i]
            if tp_price > 0 and tp_qty > 0:
                tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                    "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                    "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": tp_qty,
                    "priceProtect": "true"
                })
                if tp_res.get("code") == 0:
                    placed_tp.append((tp_price, tp_qty))
                else:
                    logger.warning(f"🎯 Gagal pasang TP{i+1} untuk {symbol}: {tp_res.get('msg')}")
                time.sleep(2)  # Rate limit: 2s gap (CLAUDE.md)

        # ── 3. Simpan state SETELAH orders berhasil dipasang ──
        with state_lock:
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
                "tp_notified": {},
                "open_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        save_active_trades()
        
        # Kirim Telegram Notif Entry Sukses
        try:
            msg_entry = (
                f"🚀 *ENTRY {pos_side}* | `{symbol}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 *Entry:* `{entry_price}`\n"
                f"⚖️ *Leverage:* `{leverage}x`\n"
                f"💰 *Margin/Qty:* `{qty}`\n"
                f"🛡️ *SL:* `{sl_price}`\n"
            )
            for i, p in enumerate(tp_prices):
                if p > 0: msg_entry += f"🎯 *TP{i+1}:* `{p}`\n"
            msg_entry += f"━━━━━━━━━━━━━━━━━━━━━"
            import requests as req
            res = req.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
                     json={"chat_id": os.getenv("TELEGRAM_CHAT_ID"), "text": msg_entry, "parse_mode": "Markdown"}, timeout=5)
            if res.status_code != 200:
                logger.error(f"Telegram API Error (Status {res.status_code}): {res.text}")
            res.raise_for_status()
        except Exception as e:
            logger.error(f"Gagal kirim notif telegram entry: {e}")

        return {"status": "success", "symbol": symbol, "qty": qty}
    else:
        reason = order_res.get('msg') or str(order_res)
        return {"status": f"failed: {reason}", "symbol": symbol, "reason": reason}


def _close_position(symbol: str) -> dict:
    global active_trade_data
    paper_mode = get_paper_mode()
    if paper_mode:
        trades = load_paper_trades()
        for t in trades:
            if t["symbol"] == symbol and t["status"] == "OPEN_PAPER":
                t["status"] = "CLOSED_PAPER"
                t["close_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _atomic_write_json(PAPER_TRADES_FILE, trades)
        return {"msg": f"Closed paper position {symbol}"}

    positions = bx.get_open_positions(symbol)
    for pos in positions:
        side = pos["positionSide"]
        qty = abs(float(pos["positionAmt"]))
        close_side = "SELL" if side == "LONG" else "BUY"
        bx.place_order(symbol, close_side, side, qty)
    bx.cancel_all_orders(symbol)
    
    if symbol in active_trade_data:
        with state_lock:
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
        local_symbols = [sym for sym, data in local_trades.items() if data.get("status") in ("OPEN", "OPEN_SYNCED")]
        
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
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
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
    """Background monitor: cek paper exits + trailing SL + TP hit notif + sync TP/SL posisi live."""
    try:
        check_paper_exit()  # Cek apakah paper trade sudah kena TP/SL
    except Exception as e:
        logger.error(f"Error monitor check_paper_exit: {e}")
    
    try:
        check_tp_hits()  # 🎯 Cek & notif TP yang kena
    except Exception as e:
        logger.error(f"Error monitor check_tp_hits: {e}")
    
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
            
            # Selalu periksa dan sinkronkan TP1-4 terlepas dari apakah sudah ada sebagian TP
            # Prioritas: sinyal TV terakhir > active_trade_data > brain_engine fallback
            last_signal = latest_signals.get(symbol, {})
            trade_state = active_trade_data.get(symbol, {})
            
            tv_sl = float(last_signal.get("sl", 0))
            tv_tp1 = float(last_signal.get("tp1", 0))
            tv_tp2 = float(last_signal.get("tp2", 0))
            tv_tp3 = float(last_signal.get("tp3", 0))
            tv_tp4 = float(last_signal.get("tp4", 0))
            
            state_sl = float(trade_state.get("sl", 0))
            state_tp1 = float(trade_state.get("tp1", 0))
            state_tp2 = float(trade_state.get("tp2", 0))
            state_tp3 = float(trade_state.get("tp3", 0))
            state_tp4 = float(trade_state.get("tp4", 0))
            
            # TP/SL: sinyal TV (mutlak) > exchange orders (no TV) > state lama
            if tv_sl > 0 or tv_tp1 > 0:
                # TV signal ada → recalc relatif ke actual entry
                tv_signal_price = float(last_signal.get("price", 0)) or float(last_signal.get("entry_price", 0))
                tv_tps_raw = [tv_tp1, tv_tp2, tv_tp3, tv_tp4]
                sl_price, recalc_tps = _recalc_tp_sl_for_entry(
                    tv_sl, tv_tps_raw, tv_signal_price, entry, side, symbol
                )
                tp1_price = recalc_tps[0] or state_tp1
                tp2_price = recalc_tps[1] or state_tp2
                tp3_price = recalc_tps[2] or state_tp3
                tp4_price = recalc_tps[3] or state_tp4
            else:
                # Tidak ada TV signal → baca dari exchange orders (source of truth)
                ex_sl = 0
                ex_tps = []
                for o in open_orders:
                    if "STOP" in o.get("type", "") and "TAKE_PROFIT" not in o.get("type", ""):
                        ex_sl = float(o.get("stopPrice", 0))
                    elif "TAKE_PROFIT" in o.get("type", ""):
                        ex_tps.append(float(o.get("stopPrice", 0)))
                ex_tps.sort()
                sl_price = ex_sl or state_sl
                tp1_price = ex_tps[0] if len(ex_tps) >= 1 else state_tp1
                tp2_price = ex_tps[1] if len(ex_tps) >= 2 else state_tp2
                tp3_price = ex_tps[2] if len(ex_tps) >= 3 else state_tp3
                tp4_price = ex_tps[3] if len(ex_tps) >= 4 else state_tp4
                if ex_sl > 0 or ex_tps:
                    logger.info(f"📥 {symbol}: TP/SL dibaca dari exchange orders (no TV signal)")
                # Guard SL: hindari SL = entry atau nol, gunakan minimum SL percent
                if sl_price <= 0 or abs(sl_price - entry) < 1e-8:
                    _min_sl = _get_min_sl_pct(symbol)
                    sl_price = _round_price(entry * (1.0 - _min_sl), symbol)
                    logger.warning(f"🛡️ Adjusted SL for {symbol}: set to guard price {sl_price} (min pct {_min_sl*100:.2f}%)")
                # Guard TP: hindari TP = entry
                for idx, tp_val in enumerate([tp1_price, tp2_price, tp3_price, tp4_price], start=1):
                    if tp_val > 0 and abs(tp_val - entry) < 1e-8:
                        logger.warning(f"⚠️ TP{idx} for {symbol} equal to entry price; clearing.")
                        if idx == 1:
                            tp1_price = 0
                        elif idx == 2:
                            tp2_price = 0
                        elif idx == 3:
                            tp3_price = 0
                        else:
                            tp4_price = 0
            tp_prices = [tp1_price, tp2_price, tp3_price, tp4_price]
            
            # Jika semua TP/SL masih 0, fallback ke brain_engine
            if sl_price == 0 and tp1_price == 0:
                import brain_engine
                logger.warning(f"⚠️ {symbol} tidak punya TP/SL dari sinyal TV maupun state. Fallback ke brain_engine.")
                plan = brain_engine.get_full_trade_plan(10000.0, entry, side, symbol)
                sl_price = plan["sl"]
                tp_prices = [plan["tp1"], plan["tp2"], plan.get("tp3", 0), plan.get("tp4", 0)]
                # Validate SL: avoid SL == entry or zero; apply minimum SL guard
                if sl_price <= 0 or abs(sl_price - entry) < 1e-8:
                    # Calculate a safe SL using the configured minimum SL percentage
                    _min_sl = _get_min_sl_pct(symbol)
                    sl_price = _round_price(entry * (1.0 - _min_sl), symbol)
                    logger.warning(f"🛡️ Adjusted SL for {symbol}: original SL was {plan['sl']}, set to guard price {sl_price} (min pct {_min_sl*100:.2f}%)")

            sl_side = "SELL" if side == "LONG" else "BUY"
            
            # Validasi SL: LONG → SL harus di bawah harga; SHORT → SL harus di atas harga
            if sl_price > 0 and not has_sl:
                try:
                    curr_price = bx.get_current_price(symbol)
                except:
                    curr_price = entry
                sl_invalid = (side == "LONG" and sl_price >= curr_price) or \
                             (side == "SHORT" and sl_price <= curr_price)
                if sl_invalid:
                    logger.warning(f"⚠️ {symbol} SL {sl_price} invalid (harga skrg {curr_price}). Skip pasang SL.")
                    results.append(f"⚠️ {symbol}: SL {sl_price} di {('atas' if side=='LONG' else 'bawah')} harga {curr_price}, skip.")
                    sl_price = 0  # prevent placement below
            
            # Pasang Stop Loss jika belum ada
            if not has_sl and sl_price > 0:
                logger.info(f"⚠️ {symbol} tidak punya SL. Memasang SL {sl_price}...")
                sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                    "symbol": symbol, "side": sl_side, "positionSide": side,
                    "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": amt,
                        "priceProtect": "true"
                    })
                if sl_res.get("code") != 0:
                    logger.error(f"🛑 Gagal pasang SL {symbol}: code={sl_res.get('code')} msg={sl_res.get('msg')}")
                    results.append(f"❌ {symbol}: Gagal pasang SL ({sl_res.get('msg')})")
                else:
                    results.append(f"✅ {symbol}: SL dipasang ({sl_price})")
            elif sl_price <= 0:
                results.append(f"✔️ {symbol}: Tidak ada harga SL di state.")
            else:
                results.append(f"✔️ {symbol}: Sudah memiliki SL.")
            
            # UPDATE active_trade_data dengan harga TP/SL yg dipakai (TV > state > brain_engine)
            # agar check_tp_hits pakai harga sama dengan di exchange
            with state_lock:
                if symbol in active_trade_data:
                    active_trade_data[symbol]["sl"] = sl_price
                    for i, tpv in enumerate(tp_prices):
                        if tpv > 0:
                            active_trade_data[symbol][f"tp{i+1}"] = tpv
                    save_active_trades()

            # Pasang Take Profit yang belum ada
            tp_count = 0
            weights = [0.35, 0.30, 0.20, 0.15]  # Distribusi qty: TP1=35%, TP2=30%, TP3=20%, TP4=15%

            # CEK: Berapa total TP qty yang sudah ada?
            current_tp_qty = sum(float(o.get("origQty", 0)) for o in open_orders if "TAKE_PROFIT" in o.get("type", ""))
            if current_tp_qty >= amt * 0.99:
                results.append(f"✔️ {symbol}: TP sudah lengkap (qty tertutup).")
                continue

            # Ambil notified state untuk avoid re-placing TP yang sudah ter-fill
            trade_state_for_sync = active_trade_data.get(symbol, {})
            tp_notified = trade_state_for_sync.get("tp_notified", {})

            for i, tp_val in enumerate(tp_prices):
                if tp_val > 0:
                    # Skip TP yang sudah ter-fill (notified = True)
                    if tp_notified.get(f"tp{i+1}", False):
                        logger.info(f"⏭️ Sync skip TP{i+1} ({tp_val}) — sudah ter-fill & notified.")
                        continue

                    # Cek apakah harga TP ini sudah ada di open orders (toleransi 0.5%)
                    already_has_this_tp = any(abs(float(o.get("stopPrice", 0)) - tp_val) < (tp_val * 0.005) for o in open_orders if "TAKE_PROFIT" in o.get("type", ""))
                    if not already_has_this_tp:
                        # Gunakan try/except untuk mencegah kegagalan satu TP membatalkan yang lain
                        try:
                            # Split sisa qty yang belum ada TP nya
                            remaining_qty_to_cover = amt - current_tp_qty
                            if remaining_qty_to_cover <= 0:
                                break # Stop jika qty sudah fully covered
                                
                            from brain_engine import get_symbol_config
                            cfg = get_symbol_config(symbol)
                            min_qty = cfg.get("min_qty", 0.001)
                            
                            # Coba pakai standard weight, tapi clamp agar gak lewat amt, minimal min_qty
                            tp_qty = round(amt * weights[i], 3) if i < len(weights) else round(amt * 0.1, 3)
                            tp_qty = max(min_qty, tp_qty)
                            tp_qty = min(remaining_qty_to_cover, tp_qty)
                            
                            if tp_qty > 0:
                                logger.info(f"⚠️ {symbol} missing TP{i+1}. Memasang TP {tp_val} (qty: {tp_qty})...")
                                bx._request("POST", "/openApi/swap/v2/trade/order", {
                                    "symbol": symbol, "side": sl_side, "positionSide": side,
                                    "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_val, "quantity": tp_qty,
                                    "priceProtect": "true"
                                })
                                current_tp_qty += tp_qty
                                tp_count += 1
                        except Exception as e:
                            logger.error(f"Gagal pasang TP{i+1} untuk {symbol}: {e}")
            if tp_count > 0:
                results.append(f"✅ {symbol}: {tp_count} TP baru dipasang")
            else:
                results.append(f"✔️ {symbol}: TP sudah lengkap.")

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
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty,
        })
        bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": qty
        })
        return {"symbol": symbol, "tps": [tp_price], "sl": sl_price}
    except Exception as e:
        return {"error": str(e)}

def check_tp_hits():
    """Cek apakah order TP sudah ter-fill di bursa, kirim notif Telegram per level."""
    try:
        paper_mode = get_paper_mode()
        if paper_mode:
            return  # Paper mode: tidak ada order real
        
        for symbol, trade in list(active_trade_data.items()):
            if trade.get("status") not in ("OPEN", "OPEN_SYNCED"):
                continue
            
            tp_levels = {
                "tp1": (1, trade.get("tp1", 0)),
                "tp2": (2, trade.get("tp2", 0)),
                "tp3": (3, trade.get("tp3", 0)),
                "tp4": (4, trade.get("tp4", 0)),
            }
            notified_key = "tp_notified"
            if notified_key not in trade:
                trade[notified_key] = {}
            
            # Ambil open orders di bursa
            orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol, "pageSize": 50})
            if orders_res.get("code") != 0:
                continue
            open_orders = orders_res.get("data", {}).get("orders", [])
            open_tp_prices = set()
            for o in open_orders:
                if o.get("type") == "TAKE_PROFIT_MARKET":
                    try:
                        open_tp_prices.add(float(o["stopPrice"]))
                    except (ValueError, KeyError):
                        pass
            
            for tp_key, (level, tp_price) in tp_levels.items():
                if tp_price <= 0:
                    continue
                if trade[notified_key].get(tp_key):
                    continue  # Sudah dinotif
                
                # Jika TP price tidak ada di open orders → sudah ter-fill
                tp_rounded = round(tp_price, 2)
                found_open = any(abs(float(o.get("stopPrice", 0)) - tp_rounded) < 0.5 
                                  for o in open_orders if o.get("type") == "TAKE_PROFIT_MARKET")
                
                if not found_open:
                    # TP sudah terkena (order hilang dari open orders)
                    notify_tp_hit(symbol, level, tp_price, trade)
                    trade[notified_key][tp_key] = True
            
            with state_lock:
                active_trade_data[symbol] = trade
            save_active_trades()
    except Exception as e:
        logger.error(f"Error check_tp_hits: {e}")

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
        with state_lock:
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
                
            # 1. Ambil data bursa dulu (DI LUAR LOCK agar tidak freeze)
            try:
                pos_data_res = bx.get_open_positions(symbol)
                balance = bx.get_balance()
            except Exception as e:
                logger.error(f"⚠️ Gagal fetch data bursa untuk {symbol}: {e}")
                continue

            # 2. Proses state (DI DALAM LOCK)
            with state_lock:
                if symbol not in active_trade_data:
                    try:
                        # Prioritas: sinyal TV terakhir > brain_engine fallback
                        last_signal = latest_signals.get(symbol, {})
                        tv_sl = float(last_signal.get("sl", 0))
                        tv_tp1 = float(last_signal.get("tp1", 0))
                        tv_tp2 = float(last_signal.get("tp2", 0))
                        tv_tp3 = float(last_signal.get("tp3", 0))
                        tv_tp4 = float(last_signal.get("tp4", 0))
                        
                        if tv_sl > 0 and tv_tp1 > 0:
                            # Recalc TP/SL dari sinyal TV relatif ke actual entry
                            tv_signal_price = float(last_signal.get("price", 0)) or float(last_signal.get("entry_price", 0))
                            tv_tps_raw = [tv_tp1, tv_tp2, tv_tp3, tv_tp4]
                            sl_val, recalc_tps = _recalc_tp_sl_for_entry(
                                tv_sl, tv_tps_raw, tv_signal_price, avg_price, pos_side, symbol
                            )
                            tp_prices = recalc_tps
                            logger.info(f"📺 Auto-adopt {symbol}: pakai TP/SL dari sinyal TV (SL={sl_val}, TP1={tp_prices[0]})")
                        else:
                            # Fallback ke brain_engine jika tidak ada sinyal TV
                            import brain_engine
                            plan = brain_engine.get_full_trade_plan(balance, avg_price, pos_side, symbol)
                            sl_val = plan["sl"]
                            tp_prices = [plan["tp1"], plan["tp2"], plan["tp3"], plan["tp4"]]
                            logger.info(f"🧠 Auto-adopt {symbol}: tidak ada sinyal TV, fallback ke brain_engine")
                        
                        # 4 TP weights konsisten (35/30/20/15)
                        weights = [0.35, 0.30, 0.20, 0.15]
                        
                        # Pasang TP/SL hanya jika BELUM ada di bursa (hindari duplikasi)
                        if not paper_mode:
                            try:
                                existing_orders = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                                existing_data = existing_orders.get("data", [])
                                if isinstance(existing_data, dict):
                                    existing_data = existing_data.get("orders", [])
                                existing_orders_list = existing_data if isinstance(existing_data, list) else []
                                has_sl = any("STOP" in o.get("type", "") for o in existing_orders_list)
                                has_tp = any("TAKE_PROFIT" in o.get("type", "") for o in existing_orders_list)
                                
                                if not has_sl and sl_val > 0:
                                    bx._request("POST", "/openApi/swap/v2/trade/order", {
                                        "symbol": symbol, "side": "BUY" if pos_side == "SHORT" else "SELL",
                                        "positionSide": pos_side, "type": "STOP_MARKET",
                                        "stopPrice": sl_val, "quantity": qty,
                                        "priceProtect": "true"
                                    })
                                    logger.info(f"✅ Adopt SL dipasang {symbol} @ {sl_val}")
                                
                                if not has_tp:
                                    for i, tp_price in enumerate(tp_prices):
                                        tp_qty = round(qty * weights[i], 4)
                                        if tp_price > 0 and tp_qty > 0:
                                            bx._request("POST", "/openApi/swap/v2/trade/order", {
                                                "symbol": symbol, "side": "BUY" if pos_side == "SHORT" else "SELL",
                                                "positionSide": pos_side, "type": "TAKE_PROFIT_MARKET",
                                                "stopPrice": tp_price, "quantity": tp_qty,
                                                "priceProtect": "true"
                                            })
                                            logger.info(f"✅ Adopt TP{i+1} dipasang {symbol} @ {tp_price} (qty: {tp_qty})")
                                            time.sleep(2)  # Rate limit: 2s gap (CLAUDE.md)
                                    logger.info(f"✅ Adopt {len(tp_prices)} TP dipasang {symbol}")
                                else:
                                    logger.info(f"ℹ️ Adopt skip — TP/SL sudah ada di bursa {symbol}")
                            except Exception as order_err:
                                logger.error(f"⚠️ Gagal pasang TP/SL adopt {symbol}: {order_err}")
                        
                        active_trade_data[symbol] = {
                            "symbol": symbol,
                            "side": pos_side,
                            "entry_price": avg_price,
                            "sl": sl_val,
                            "tp1": tp_prices[0],
                            "tp2": tp_prices[1],
                            "tp3": tp_prices[2],
                            "tp4": tp_prices[3],
                            "qty": qty,
                            "trailing": {
                                "activate_atr_mult": 1.0,
                                "offset_atr_mult": 0.5,
                                "active": False,
                                "highest_price": avg_price if pos_side == "LONG" else 0,
                                "lowest_price": avg_price if pos_side == "SHORT" else 0,
                            },
                            "status": "OPEN",
                            "tp_notified": {},
                            "open_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "adopted": True
                        }
                        save_active_trades()
                        
                        # Kirim Telegram Notif Auto-Adopt
                        TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                        TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
                        mode_label = "PAPER" if paper_mode else "LIVE"
                        msg_adopt = (
                            f"📥 *POSISI MANUAL DIADOPSI ({mode_label})*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🪙 *Pair:* `{symbol}` ({pos_side})\n"
                            f"📈 *Entry:* `{avg_price}`\n"
                            f"🛡️ *SL:* `{sl_val}`\n"
                            f"🎯 *TP1:* `{tp_prices[0]}` | *TP2:* `{tp_prices[1]}`\n"
                            f"🎯 *TP3:* `{tp_prices[2]}` | *TP4:* `{tp_prices[3]}`\n"
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
                
                if symbol not in active_trade_data:
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
                    
                    # Terapkan persentase ke entry baru
                    with state_lock:
                        trade["entry_price"] = avg_price
                        trade["qty"] = qty
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
                    TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
                    mode_label = "PAPER" if paper_mode else "LIVE"
                    msg_calib = (
                        f"🔄 *KALIBRASI LEVEL TP/SL SELESAI ({mode_label})*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Pair:* `{symbol}`\n"
                        f"📈 *Entry Baru:* `{avg_price}` (Slippage/Susul)\n"
                        f"🛡️ *SL Baru:* `{trade['sl']}`\n"
                        f"🎯 *TP1:* `{trade.get('tp1', 0)}` | *TP2:* `{trade.get('tp2', 0)}`\n"
                        f"🎯 *TP3:* `{trade.get('tp3', 0)}` | *TP4:* `{trade.get('tp4', 0)}`\n"
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
            with state_lock:
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

            # ── DESYNC PROTECTION FOR TEST/HISTORICAL SIGNALS ──
            # Jika harga live menyimpang > 3% dari entry price sejak awal, 
            # jangan lakukan trailing SL karena milestone TP ter-trigger palsu.
            init_slippage = abs(current_price - entry_price) / entry_price
            if init_slippage > 0.03 and not trade["trailing"].get("active", False):
                logger.warning(f"⚠️ desync protection: harga live ({current_price}) selisih {init_slippage*100:.2f}% dari entry ({entry_price}). Trailing SL diabaikan.")
                continue
            
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
                    # 1. Cancel SL lama dulu (hati-hati: TP jangan di-cancel, nanti pasang ulang)
                    try:
                        orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                        raw = orders_res.get("data", {})
                        if isinstance(raw, dict):
                            open_orders = raw.get("orders", [])
                        else:
                            open_orders = raw if isinstance(raw, list) else []

                        # Pisahkan SL dan TP — hanya cancel SL lama
                        sl_orders = [o for o in open_orders if "STOP" in o.get("type", "") and "TAKE_PROFIT" not in o.get("type", "")]
                        tp_orders = [o for o in open_orders if "TAKE_PROFIT" in o.get("type", "")]

                        for o in sl_orders:
                            bx._request("DELETE", "/openApi/swap/v2/trade/order", {"symbol": symbol, "orderId": o["orderId"]})
                            logger.info(f"🗑️ Batal SL lama: {o['orderId']} ({o.get('type')}) stopPrice={o.get('stopPrice')}")

                    except Exception as ce:
                        logger.error(f"Gagal cancel SL lama {symbol}: {ce}. Tetap pasang SL baru.")
                        tp_orders = []

                    # 2. Pasang SL baru — guard: SL trailing BOLEH di atas entry (lock profit)
                    # Guard HANYA cegah SL == entry (instant fill due to spread)
                    import brain_engine as _be_trail
                    cfg = _be_trail.get_symbol_config(symbol)
                    prec = cfg.get("price_precision", 2)
                    _entry_guard = round(trade.get("entry_price", 0) * 0.0005, prec)
                    _entry_price = trade.get("entry_price", 0)
                    if pos_side == "LONG" and abs(new_sl - _entry_price) < _entry_guard:
                        # SL terlalu dekat entry (< 0.05%) — geser sedikit ke bawah agar tidak instant fill
                        new_sl = round(_entry_price - _entry_guard, prec)
                        logger.warning(f"🛡️ SL trail guard: adjusted to {new_sl} (was too close to entry)")
                    elif pos_side == "SHORT" and abs(new_sl - _entry_price) < _entry_guard:
                        new_sl = round(_entry_price + _entry_guard, prec)
                        logger.warning(f"🛡️ SL trail guard: adjusted to {new_sl} (was too close to entry)")

                    if abs(new_sl - current_sl) > (10 ** -prec):
                        sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                            "type": "STOP_MARKET", "stopPrice": new_sl, "quantity": qty,
                        })
                        if sl_res.get("code", -1) == 0:
                            logger.info(f"✅ SL Berhasil digeser: {current_sl} -> {new_sl}")
                            # Update state lokal
                            with state_lock:
                                trade["sl"] = new_sl
                                active_trade_data[symbol] = trade
                            save_active_trades()

                            # Kirim notifikasi Telegram HANYA saat SL benar2 berubah
                            try:
                                TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
                                TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)
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
                                logger.error(f"Gagal kirim notif trailing SL: {tg_err}")
                        else:
                            logger.error(f"❌ Gagal pasang SL baru {symbol}: {sl_res.get('msg')}")
                    else:
                        logger.info(f"ℹ️ SL tidak berubah signifikan, skip update: {new_sl}")

                    # 3. Pastikan TP masih terpasang (cek dari exchange, bukan dari state)
                    # Jika ada TP yang hilang, pasang ulang berdasarkan data exchange saat ini
                    try:
                        if len(tp_orders) == 0:
                            # TP hilang semua — hitung ulang qty dari posisi sekarang
                            tp_prices_re = [trade.get("tp1", 0), trade.get("tp2", 0), trade.get("tp3", 0), trade.get("tp4", 0)]
                            tp_qtys_from_state = trade.get("qtys", [])
                            weights = [0.35, 0.30, 0.20, 0.15]
                            _gsc = _be_trail.get_symbol_config
                            _min_qty_re = _gsc(symbol).get("min_qty", 0.001)
                            current_tp_qty_placed = 0
                            for _i, _tp_val in enumerate(tp_prices_re):
                                if _tp_val <= 0:
                                    continue
                                # Gunakan qtys dari state jika ada, fallback ke weight
                                if _i < len(tp_qtys_from_state) and tp_qtys_from_state[_i] > 0:
                                    _tp_qty = tp_qtys_from_state[_i]
                                else:
                                    _remaining = qty - current_tp_qty_placed
                                    _tp_qty = max(_min_qty_re, min(round(qty * weights[_i], 4), _remaining))
                                if _tp_qty > 0:
                                    _tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                                        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                                        "type": "TAKE_PROFIT_MARKET", "stopPrice": _tp_val, "quantity": _tp_qty
                                    })
                                    if _tp_res.get("code", -1) == 0:
                                        current_tp_qty_placed += _tp_qty
                                        logger.info(f"🎯 Re-TP{_i+1} terpasang di {_tp_val} (qty: {_tp_qty})")
                                    else:
                                        logger.warning(f"⚠️ Re-TP{_i+1} gagal: {_tp_res.get('msg')}")
                        else:
                            logger.info(f"✔️ TP masih ada di exchange untuk {symbol} ({len(tp_orders)} order), tidak perlu re-TP")
                    except Exception as _tp_err:
                        logger.error(f"❌ Re-TP error untuk {symbol}: {_tp_err}")

                logger.info(f"🔄 TRAILING SL {symbol} ({mode_label}): {current_sl} → {new_sl} | {result['reason']}")
    except Exception as e:
        logger.error(f"Error check_and_update_trailing_sl: {e}")


def reentry_signal(symbol):
    """Re-entry posisi menggunakan sinyal terakhir yang tersimpan."""
    if symbol in latest_signals:
        return execute_signal(latest_signals[symbol])
    return {"status": "no_signal", "symbol": symbol}
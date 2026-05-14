import os
import math
import logging
import json
from dotenv import load_dotenv
import bingx_client as bx
import time
import settings_manager
import requests

load_dotenv()
logger = logging.getLogger(__name__)

# Config
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE_PERCENT", "2"))
TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

def send_telegram_msg(msg: str):
    """Kirim pesan ke Telegram secara langsung."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Gagal kirim notif Tele: {e}")

def send_mini_report():
    """Kirim ringkasan profit singkat."""
    try:
        incomes = bx.get_income_history(days=1)
        pnl_24h = sum(float(inc.get("income", 0)) for inc in incomes if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION", "FUNDING_FEE"])
        balance = bx.get_balance()
        
        icon = "📈" if pnl_24h >= 0 else "📉"
        msg = (
            f"📊 *UPDATE PROFIT 24 JAM*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Net PnL:* `{pnl_24h:+.2f} USDT` {icon}\n"
            f"🏦 *Balance:* `{balance:.2f} USDT`"
        )
        send_telegram_msg(msg)
    except:
        pass

# ── Mode TP: Baca dari settings_manager ──
def get_tp_mode():
    settings = settings_manager.load_settings()
    return settings.get("tp_mode", "tp1_only") == "tp1_only"

# State posisi aktif (Sekarang Permanen)
ACTIVE_TRADES_FILE = "active_trades.json"
active_trade_data = {}

def save_active_trades():
    with open(ACTIVE_TRADES_FILE, "w") as f:
        json.dump(active_trade_data, f)

def load_active_trades():
    global active_trade_data
    if os.path.exists(ACTIVE_TRADES_FILE):
        with open(ACTIVE_TRADES_FILE, "r") as f:
            active_trade_data = json.load(f)

# Load saat startup
load_active_trades()

last_known_positions = {} # Untuk deteksi posisi tertutup

# ── Sinyal terakhir untuk /susul ──
LATEST_SIGNALS_FILE = "latest_signals.json"

def load_latest_signals():
    if os.path.exists(LATEST_SIGNALS_FILE):
        try:
            with open(LATEST_SIGNALS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Gagal load latest signals: {e}")
    return {}

latest_signals = load_latest_signals()

def save_latest_signals():
    try:
        with open(LATEST_SIGNALS_FILE, "w") as f:
            json.dump(latest_signals, f, indent=2)
    except Exception as e:
        logger.error(f"Gagal save latest signals: {e}")


def _round_qty(qty: float, symbol: str = "BTC-USDT") -> float:
    precisions = {"BTC-USDT": 4, "ETH-USDT": 3, "SOL-USDT": 2}
    p = precisions.get(symbol, 2)
    factor = 10 ** p
    return math.floor(qty * factor) / factor


def calculate_quantity_risk_based(balance: float, entry_price: float, sl_price: float, symbol: str) -> float:
    """Hitung quantity berdasarkan nominal kerugian yang diinginkan (Risk per Trade)."""
    if entry_price == sl_price:
        return 0
        
    # Nominal USDT yang siap dirugikan (misal 2% dari $100 = $2)
    risk_amount_usdt = balance * (RISK_PER_TRADE / 100)
    
    # Jarak SL dalam harga
    price_diff = abs(entry_price - sl_price)
    
    # Qty = Risk USDT / Jarak Harga
    qty = risk_amount_usdt / price_diff
    
    qty = _round_qty(qty, symbol)
    if qty <= 0:
        raise ValueError(f"Quantity terlalu kecil untuk risk {RISK_PER_TRADE}%")
    return qty


def execute_signal(data: dict) -> dict:
    """
    Eksekusi sinyal dari TradingView / Tradentix Pro.
    Semua parameter (leverage, tp1-4, qty_tp1-4, sl) dari payload sinyal.
    Margin mode dari env (ISOLATED).
    """
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "BTC-USDT")

    if action == "CLOSE":
        return _close_position(symbol)

    pos_side  = "LONG" if action in ["BUY", "LONG"] else "SHORT"
    order_side = "BUY" if pos_side == "LONG" else "SELL"
    sl_side    = "SELL" if pos_side == "LONG" else "BUY"

    # ── Ambil semua parameter dari sinyal ──
    entry_price = float(data.get("price", 0)) or bx.get_current_price(symbol)
    sl_price    = float(data.get("sl", 0))
    leverage    = int(data.get("leverage", int(os.getenv("LEVERAGE", 20))))

    # Kumpulkan TP levels dari sinyal
    # Support 2 format:
    # - Format baru: tp1+qty_tp1, tp2+qty_tp2, dst (dari Pine Script terbaru)
    # - Format lama: hanya tp1 tanpa qty (qty otomatis dibagi rata)
    tp_levels_raw = []
    for i in range(1, 5):
        tp_price = float(data.get(f"tp{i}", 0))
        if tp_price > 0:
            tp_qty_pct = float(data.get(f"qty_tp{i}", 0))
            tp_levels_raw.append({"price": tp_price, "qty_pct": tp_qty_pct})

    # Jika tidak ada qty_tp sama sekali → bagi rata ke semua TP yang ada
    has_qty = any(t["qty_pct"] > 0 for t in tp_levels_raw)
    if not has_qty and tp_levels_raw:
        equal_pct = 100.0 / len(tp_levels_raw)
        for t in tp_levels_raw:
            t["qty_pct"] = equal_pct

    # Filter hanya TP yang valid (price > 0 dan qty > 0)
    tp_levels = [t for t in tp_levels_raw if t["price"] > 0 and t["qty_pct"] > 0]

    # ── Terapkan mode TP dari setting global ──
    tp_mode_is_tp1_only = get_tp_mode()
    if tp_mode_is_tp1_only and tp_levels:
        tp_levels = [{"price": tp_levels[0]["price"], "qty_pct": 100.0}]
        logger.info(f"📌 Mode TP1 Only → Close semua di TP1: {tp_levels[0]['price']}")
    else:
        logger.info(f"📊 Mode Multi-TP → {len(tp_levels)} level aktif")

    # ── Validasi wajib ──
    if sl_price == 0:
        raise ValueError("❌ SL tidak ada di sinyal. Eksekusi dibatalkan.")
    if not tp_levels:
        raise ValueError("❌ Tidak ada TP valid di sinyal. Eksekusi dibatalkan.")
    if entry_price == 0:
        raise ValueError("❌ Harga entry tidak valid.")

    # Normalisasi total qty_pct agar selalu 100%
    total_pct = sum(t["qty_pct"] for t in tp_levels)
    for t in tp_levels:
        t["qty_pct"] = t["qty_pct"] / total_pct  # 0.0 - 1.0

    logger.info(f"📊 {symbol} {pos_side} | Leverage: {leverage}x | Entry: {entry_price} | SL: {sl_price}")
    for i, t in enumerate(tp_levels, 1):
        logger.info(f"   TP{i}: {t['price']} ({t['qty_pct']*100:.0f}%)")

    # ── Auto-Reversal: tutup posisi berlawanan jika ada ──
    existing_positions = bx.get_open_positions(symbol)
    for pos in existing_positions:
        if pos.get("positionSide") != pos_side:
            logger.info(f"🔄 Reversal: Tutup {pos.get('positionSide')} → buka {pos_side}")
            _close_position(symbol)
            time.sleep(1.5)
            break

    # ── Hitung total quantity berdasarkan RISK PER TRADE ──
    balance = bx.get_balance()
    try:
        total_quantity = calculate_quantity_risk_based(balance, entry_price, sl_price, symbol)
        logger.info(f"💰 Balance: {balance:.2f} USDT | Risk: {RISK_PER_TRADE}% (${balance * RISK_PER_TRADE / 100}) | Qty: {total_quantity}")
    except Exception as e:
        logger.warning(f"⚠️ Gagal hitung risk-based qty: {e}. Pakai fallback margin 5%.")
        # Fallback jika SL terlalu dekat/jauh
        margin_fallback = balance * 0.05
        total_quantity = _round_qty((margin_fallback * leverage) / entry_price, symbol)

    # ── Set leverage & margin ISOLATED ──
    margin_mode = os.getenv("MARGIN_MODE", "ISOLATED").upper()
    bx.set_leverage(symbol, leverage, pos_side)
    bx.set_margin_type(symbol, margin_mode)

    # ── Buka posisi MARKET ──
    order_res = bx.place_order(symbol, order_side, pos_side, total_quantity, "MARKET")
    if order_res.get("code") != 0:
        raise Exception(f"Gagal buka posisi: {order_res}")
    
    # ── AMBIL QUANTITY AKTUAL (Fix Bug SL Ditolak) ──
    time.sleep(1.5) # Jeda agar posisi settle di BingX
    actual_pos = next((p for p in bx.get_open_positions(symbol) if p.get("positionSide") == pos_side), None)
    
    if not actual_pos:
        raise Exception("Gagal verifikasi posisi yang baru dibuka.")
        
    actual_quantity = abs(float(actual_pos.get("positionAmt", total_quantity)))
    logger.info(f"✅ Posisi {pos_side} {symbol} terbuka | Qty Aktual: {actual_quantity}")

    # ── Pasang SL + semua TP dengan qty split ──
    status_msg = "success"
    
    try:
        # Pasang Stop Loss (pakai actual_quantity)
        sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": actual_quantity
        })
        if sl_res.get("code", 0) != 0:
            raise Exception(f"SL Ditolak: {sl_res.get('msg')}")
        logger.info(f"🛑 SL terpasang di {sl_price} (qty: {actual_quantity})")

        # Pasang setiap TP dengan quantity proporsional (pakai actual_quantity)
        remaining_qty = actual_quantity
        for i, tp in enumerate(tp_levels):
            is_last = (i == len(tp_levels) - 1)

            # ── PROTEKSI MINIMUM ORDER SIZE (Fix TP Gagal) ──
            # BingX butuh min order size (estimasi ~22 USDT untuk amannya)
            MIN_ORDER_VAL = 22.0
            tp_qty = _round_qty(actual_quantity * tp["qty_pct"], symbol)
            tp_qty = min(tp_qty, remaining_qty)
            
            # Cek nilai order (qty * price)
            if (tp_qty * tp["price"]) < MIN_ORDER_VAL and not is_last:
                logger.warning(f"⚠️ TP{i+1} terlalu kecil (${tp_qty * tp['price']:.2f}). Menggabungkan ke TP berikutnya...")
                # Tambahkan qty_pct ini ke TP berikutnya
                tp_levels[i+1]["qty_pct"] += tp["qty_pct"]
                continue

            if is_last:
                tp_qty = remaining_qty

            if tp_qty <= 0:
                continue

            tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                "type": "TAKE_PROFIT_MARKET", "stopPrice": tp["price"], "quantity": tp_qty
            })
            if tp_res.get("code", 0) != 0:
                # Jika masih gagal karena size, abaikan dan lanjut (sisa akan ter-close di TP berikutnya)
                logger.error(f"❌ TP{i+1} Gagal: {tp_res.get('msg')}")
                continue

            logger.info(f"🎯 TP{i+1} terpasang di {tp['price']} (qty: {tp_qty})")
            remaining_qty = _round_qty(remaining_qty - tp_qty, symbol)

    except Exception as e:
        logger.error(f"⚠️ Posisi terbuka TAPI TP/SL gagal: {e}")
        status_msg = f"warning: TP/SL Gagal ({str(e)})"

    # ── Simpan state ──
    active_trade_data[symbol] = {
        "entry": entry_price,
        "tp1": tp_levels[0]["price"] if tp_levels else None,
        "tps": [t["price"] for t in tp_levels],
        "sl": sl_price,
        "side": pos_side,
        "leverage": leverage,
        "total_qty": total_quantity,
        "be_triggered": False # Flag untuk breakeven
    }
    save_active_trades()

    return {
        "status": status_msg,
        "total_quantity": total_quantity,
        "symbol": symbol,
        "action": action,
        "leverage": leverage,
        "tp_levels": tp_levels,
        "sl": sl_price
    }


def apply_manual_tpsl(symbol: str, tp_price: float, sl_price: float) -> dict:
    """Pasang TP/SL manual untuk posisi yang sudah terbuka."""
    positions = bx.get_open_positions()
    target_pos = next(
        (p for p in positions if p.get("symbol") == symbol and abs(float(p.get("positionAmt", 0))) > 0),
        None
    )
    if not target_pos:
        raise ValueError(f"Tidak ada posisi aktif untuk {symbol}.")

    pos_side = target_pos.get("positionSide")
    entry_price = float(target_pos.get("avgPrice"))
    total_quantity = abs(float(target_pos.get("positionAmt")))

    if sl_price == 0 or tp_price == 0:
        raise ValueError("Harga TP atau SL tidak valid.")

    if pos_side == "LONG" and sl_price >= entry_price:
        raise ValueError(f"SL ({sl_price}) harus di bawah Entry ({entry_price}) untuk LONG.")
    if pos_side == "SHORT" and sl_price <= entry_price:
        raise ValueError(f"SL ({sl_price}) harus di atas Entry ({entry_price}) untuk SHORT.")
    if pos_side == "LONG" and tp_price <= entry_price:
        raise ValueError(f"TP ({tp_price}) harus di atas Entry ({entry_price}) untuk LONG.")
    if pos_side == "SHORT" and tp_price >= entry_price:
        raise ValueError(f"TP ({tp_price}) harus di bawah Entry ({entry_price}) untuk SHORT.")

    bx.cancel_all_orders(symbol)
    sl_side = "SELL" if pos_side == "LONG" else "BUY"

    sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": total_quantity
    })
    if sl_res.get("code", 0) != 0:
        raise ValueError(f"SL Ditolak: {sl_res.get('msg')}")

    tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": total_quantity
    })
    if tp_res.get("code", 0) != 0:
        raise ValueError(f"TP Ditolak: {tp_res.get('msg')}")

    active_trade_data[symbol] = {
        "entry": entry_price, "tps": [tp_price],
        "sl": sl_price, "side": pos_side
    }
    return {"status": "success", "tps": [tp_price], "sl": sl_price}


def _close_position(symbol: str) -> dict:
    positions = bx.get_open_positions(symbol)
    if not positions:
        return {"msg": "No active position"}
    for pos in positions:
        side = pos["positionSide"]
        qty = abs(float(pos["positionAmt"]))
        close_side = "SELL" if side == "LONG" else "BUY"
        bx.place_order(symbol, close_side, side, qty)
    bx.cancel_all_orders(symbol)
    active_trade_data.pop(symbol, None)
    logger.info(f"✅ Posisi {symbol} ditutup.")
    return {"msg": f"Closed {symbol}"}


def reentry_signal(symbol: str) -> dict:
    if symbol not in latest_signals:
        raise ValueError(f"Tidak ada histori sinyal untuk {symbol}.")

    data = latest_signals[symbol]
    action = data.get("action", "").upper()

    if action == "CLOSE":
        raise ValueError(f"Sinyal terakhir untuk {symbol} adalah CLOSE.")

    current_price = bx.get_current_price(symbol)
    tp1 = float(data.get("tp1", 0))
    sl  = float(data.get("sl", 0))

    if sl == 0 or tp1 == 0:
        raise ValueError("Sinyal terakhir tidak punya TP1 atau SL valid.")

    if action in ["BUY", "LONG"]:
        if current_price >= tp1:
            raise ValueError(f"Terlambat: Harga ({current_price}) sudah di atas TP1 ({tp1}).")
        if current_price <= sl:
            raise ValueError(f"Berbahaya: Harga ({current_price}) sudah di bawah SL ({sl}).")
    else:
        if current_price <= tp1:
            raise ValueError(f"Terlambat: Harga ({current_price}) sudah di bawah TP1 ({tp1}).")
        if current_price >= sl:
            raise ValueError(f"Berbahaya: Harga ({current_price}) sudah di atas SL ({sl}).")

    bx.cancel_all_orders(symbol)
    data["price"] = current_price
    logger.info(f"🔄 Re-Entry {symbol} di harga market {current_price}")
    return execute_signal(data)


def sync_missing_tpsl():
    """Cek semua posisi aktif, jika ada yang tidak punya TP/SL, pasang otomatis."""
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
            open_orders_raw = orders_res.get("data", [])
            if isinstance(open_orders_raw, dict):
                open_orders = open_orders_raw.get("orders", [])
            else:
                open_orders = open_orders_raw if isinstance(open_orders_raw, list) else []

            has_tpsl = any("STOP" in o.get("type", "") or "TAKE_PROFIT" in o.get("type", "") for o in open_orders)
            
            if not has_tpsl:
                logger.info(f"⚠️ {symbol} tidak punya TP/SL. Memasang via Sync...")
                
                # Ambil dari sinyal terakhir jika ada dan SIDE-nya cocok
                latest = load_latest_signals()
                signal = latest.get(symbol)
                
                # Cek apakah side sinyal cocok dengan side posisi
                # (Sinyal BUY cocok dengan posisi LONG, SELL cocok dengan SHORT)
                signal_action = signal.get("action", "").upper() if signal else ""
                side_matches = (side == "LONG" and signal_action in ["BUY", "LONG"]) or \
                               (side == "SHORT" and signal_action in ["SELL", "SHORT"])

                if side_matches:
                    sl_price = float(signal.get("sl", 0))
                    tp_price = float(signal.get("tp1", 0))
                    logger.info(f"🎯 Sync {symbol}: Menggunakan data sinyal yang cocok.")
                else:
                    # Estimasi aman jika data sinyal tidak cocok atau tidak ada
                    logger.info(f"⚠️ Sync {symbol}: Arah sinyal tidak cocok, gunakan estimasi aman.")
                    if side == "LONG":
                        sl_price = round(entry * 0.985, 2) # 1.5% SL
                        tp_price = round(entry * 1.01, 2)  # 1% TP
                    else:
                        sl_price = round(entry * 1.015, 2)
                        tp_price = round(entry * 0.99, 2)

                apply_manual_tpsl(symbol, tp_price, sl_price)
                results.append(f"✅ {symbol}: TP/SL dipasang ({tp_price}/{sl_price})")
            else:
                results.append(f"✔️ {symbol}: Sudah ada TP/SL.")

        return "\n".join(results)
    except Exception as e:
        logger.error(f"Sync Error: {e}")
        return f"❌ Sync Error: {str(e)}"


def monitor_and_sync_positions():
    """
    Fungsi utama yang dipanggil oleh background thread:
    1. Sinkronisasi TP/SL yang hilang.
    2. Logika Breakeven (Geser SL ke Entry saat kena TP1).
    """
    try:
        positions = bx.get_open_positions()
        if not positions:
            return

        # Ambil settings terbaru
        tp_mode_is_tp1_only = get_tp_mode()

        for pos in positions:
            symbol = pos["symbol"]
            side = pos["positionSide"]
            amt = abs(float(pos.get("positionAmt", 0)))
            pnl = float(pos.get("unrealizedProfit", "0"))
            entry = float(pos.get("avgPrice", 0))
            mark_price = float(pos.get("markPrice", 0))
            
            if amt == 0: continue

            # ── AUTO-RECOVERY TINGKAT DEWA: Baca langsung dari BingX ──
            if symbol not in active_trade_data:
                logger.info(f"🔍 Mencoba memulihkan ingatan {symbol} dari order aktif di bursa...")
                try:
                    orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                    raw_data = orders_res.get("data", [])
                    open_orders = raw_data if isinstance(raw_data, list) else raw_data.get("orders", [])
                    
                    tps_rec = []
                    sl_rec = 0.0
                    
                    for o in open_orders:
                        o_type = o.get("type", "")
                        o_price = float(o.get("stopPrice", 0))
                        
                        if "TAKE_PROFIT" in o_type and o_price > 0:
                            tps_rec.append(o_price)
                        elif "STOP" in o_type and o_price > 0:
                            sl_rec = o_price
                            
                    if tps_rec or sl_rec > 0:
                        # Urutkan TP dari yang terdekat dengan harga entry
                        tps_rec.sort(reverse=(side == "SHORT"))
                        
                        active_trade_data[symbol] = {
                            "entry": entry,
                            "tp1": tps_rec[0] if tps_rec else None,
                            "tps": tps_rec,
                            "sl": sl_rec,
                            "side": side,
                            "be_triggered": False
                        }
                        save_active_trades()
                        logger.info(f"✅ Auto-Recovery BERHASIL untuk {symbol}! Ditemukan {len(tps_rec)} TP dan SL di {sl_rec}")
                except Exception as e:
                    logger.error(f"❌ Gagal Auto-Recovery {symbol}: {e}")

            # ── 1. Logika Trailing SL (SL Ikut Naik) ──
            # Hanya bekerja jika bukan mode tp1_only
            if not tp_mode_is_tp1_only:
                state = active_trade_data.get(symbol)
                if state:
                    tps = state.get("tps", [])
                    entry_saved = state.get("entry")
                    current_sl = state.get("sl")
                    side_pos = state.get("side")
                    is_long = (side_pos == "LONG")
                    
                    # Tentukan target SL baru berdasarkan TP yang sudah terlewati
                    # Urutan: Entry -> TP1 -> TP2 -> TP3
                    new_sl_target = None
                    
                    # Cek TP mana saja yang sudah terlewati
                    for i, tp_price in enumerate(tps):
                        reached = (is_long and mark_price >= tp_price) or (not is_long and mark_price <= tp_price)
                        if reached:
                            # Jika kena TP1 -> SL ke Entry
                            if i == 0:
                                new_sl_target = entry_saved
                            # Jika kena TP2 -> SL ke TP1, dst
                            elif i > 0:
                                new_sl_target = tps[i-1]
                    
                    # Jika ada target SL baru dan lebih menguntungkan dari SL saat ini
                    if new_sl_target:
                        is_better = (is_long and new_sl_target > current_sl) or (not is_long and new_sl_target < current_sl)
                        
                        if is_better:
                            logger.info(f"🚀 TRAILING SL: {symbol} menyentuh target baru. Geser SL ke {new_sl_target}...")
                            try:
                                bx.cancel_all_orders(symbol)
                                sl_side = "SELL" if is_long else "BUY"
                                
                                # Pasang SL baru
                                bx._request("POST", "/openApi/swap/v2/trade/order", {
                                    "symbol": symbol, "side": sl_side, "positionSide": side,
                                    "type": "STOP_MARKET", "stopPrice": new_sl_target, "quantity": amt
                                })
                                
                                # Pasang ulang sisa TP
                                for tp_price in tps:
                                    # Pasang TP yang harganya masih di depan harga saat ini
                                    is_ahead = (is_long and tp_price > mark_price) or (not is_long and tp_price < mark_price)
                                    if is_ahead:
                                        bx._request("POST", "/openApi/swap/v2/trade/order", {
                                            "symbol": symbol, "side": sl_side, "positionSide": side,
                                            "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": amt / len([t for t in tps if (is_long and t > mark_price) or (not is_long and t < mark_price)])
                                        })
                                
                                state["sl"] = new_sl_target
                                save_active_trades() # Simpan perubahan SL
                                logger.info(f"✅ TRAILING SL BERHASIL untuk {symbol} ke {new_sl_target}")
                                
                                # Notifikasi ke Telegram Premium Style
                                tp_index = tps.index(new_sl_target) if new_sl_target in tps else -1
                                tp_name = f"TP{tp_index + 1}" if tp_index >= 0 else "Entry (Modal)"
                                
                                notif_msg = (
                                    f"💎 *TARGET TERCAPAI: {symbol}*\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"🎯 *Target:* `{tp_name}` Terlewati!\n"
                                    f"🛡️ *Trailing:* SL naik ke `{new_sl_target}`\n"
                                    f"📈 *Status:* `Running in Profit`\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━"
                                )
                                send_telegram_msg(notif_msg)
                                time.sleep(1)
                                send_mini_report()
                                
                            except Exception as e:
                                logger.error(f"❌ Gagal eksekusi Trailing SL {symbol}: {e}")

            # ── 2. Deteksi Perubahan Quantity (Partial TP Hit di Bursa) ──
            last_pos = last_known_positions.get(symbol)
            if last_pos:
                last_amt = abs(float(last_pos.get("positionAmt", 0)))
                if amt < last_amt:
                    # Quantity berkurang! Berarti ada TP yang kena di bursa
                    diff = last_amt - amt
                    notif_partial = (
                        f"💰 *PARTIAL TP HIT: {symbol}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"✅ Terjual: `{diff}` koin\n"
                        f"📦 Sisa Posisi: `{amt}` koin\n"
                        f"💵 PnL Saat Ini: `{pnl:+.2f} USDT`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                    send_telegram_msg(notif_partial)
                    send_mini_report()

            # ── 3. Sinkronisasi TP/SL (Layanan Kesehatan) ──
            _sync_single_position(pos)

        # ── 4. Deteksi Posisi yang Hilang (Berhasil Close/SL/Liq) ──
        current_symbols = {p["symbol"] for p in positions}
        for sym in list(last_known_positions.keys()):
            if sym not in current_symbols:
                # Posisi tertutup!
                old_pos = last_known_positions[sym]
                logger.info(f"🚩 Posisi {sym} terdeteksi tertutup.")
                
                # Cek apakah ini Liquidation atau SL Biasa
                # Kita bisa cek saldo atau income history terakhir
                time.sleep(2) # Jeda sebentar agar income history update di bursa
                incomes = bx.get_income_history(days=1)
                liq_income = next((inc for inc in incomes if inc.get("symbol") == sym and inc.get("incomeType") == "LIQUIDATION"), None)
                
                if liq_income:
                    loss = abs(float(liq_income.get("income", 0)))
                    notif_close = (
                        f"💀 *LIQUIDATION DETECTED*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 *Symbol:* `{sym}`\n"
                        f"📉 *Status:* `Liquidated`\n"
                        f"💸 *Loss:* `-{loss:.2f} USDT`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ *Peringatan: Cek kembali margin kamu!*"
                    )
                else:
                    notif_close = (
                        f"🏁 *TRADE CLOSED: {sym}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📉 *Status:* `Position Closed`\n"
                        f"ℹ️ *Reason:* Target Hit atau Stop Loss\n"
                        f"━━━━━━━━━━━━━━━━━━━━━"
                    )
                
                send_telegram_msg(notif_close)
                # Hapus dari memori & simpan
                active_trade_data.pop(sym, None)
                last_known_positions.pop(sym, None)
                save_active_trades()
        
        # Update last_known_positions untuk loop berikutnya
        for p in positions:
            last_known_positions[p["symbol"]] = p

    except Exception as e:
        logger.error(f"Monitor Error: {e}")

def _sync_single_position(pos):
    """Internal sync untuk satu posisi agar tidak berisik di log."""
    try:
        symbol = pos["symbol"]
        # Cek order yang ada
        orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
        raw_data = orders_res.get("data", [])
        open_orders = raw_data if isinstance(raw_data, list) else raw_data.get("orders", [])
        
        # Cari apakah ada order TP atau SL
        has_tpsl = any(o.get("type") in ["STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"] for o in open_orders)
        
        if not has_tpsl:
            # Jika benar-benar tidak ada, bersihkan sisa orderan sampah (jika ada) baru pasang baru
            logger.info(f"⚠️ {symbol} terdeteksi tanpa TP/SL. Sinkronisasi ulang...")
            
            latest = load_latest_signals()
            signal = latest.get(symbol)
            if signal:
                sl_price = float(signal.get("sl", 0))
                tp_price = float(signal.get("tp1", 0))
                if sl_price > 0 and tp_price > 0:
                    bx.cancel_all_orders(symbol) # Bersihkan dulu biar nggak dobel
                    time.sleep(0.5)
                    apply_manual_tpsl(symbol, tp_price, sl_price)
    except Exception as e:
        logger.error(f"Sync Error {pos.get('symbol')}: {e}")

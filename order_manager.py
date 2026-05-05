import os
import math
import logging
from dotenv import load_dotenv
import bingx_client as bx

# Load environment variables
load_dotenv()

# Konfigurasi Logging
logger = logging.getLogger(__name__)

# Config Risk
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1.5"))
TP_PERCENT = float(os.getenv("TP_PERCENT", "3.0"))  
SL_PERCENT = float(os.getenv("SL_PERCENT", "2.0"))  
ORDER_TYPE = os.getenv("ORDER_TYPE", "MARKET")

# State untuk menyimpan data TP/SL per symbol
active_trade_data = {}

def _round_qty(qty: float, symbol: str = "BTC-USDT") -> float:
    """Bulatkan quantity ke step size yang valid sesuai symbol."""
    precisions = {"BTC-USDT": 4, "ETH-USDT": 3, "SOL-USDT": 2}
    p = precisions.get(symbol, 2)
    factor = 10 ** p
    return math.floor(qty * factor) / factor

def calculate_quantity(balance: float, entry_price: float, sl_price: float, leverage: int, symbol: str = "BTC-USDT") -> float:
    margin_amount = balance * (RISK_PERCENT / 100)
    qty = (margin_amount * leverage) / entry_price
    qty = _round_qty(qty, symbol)
    if qty <= 0: raise ValueError(f"Quantity terlalu kecil: {qty}")
    return qty

def execute_signal(data: dict) -> dict:
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "BTC-USDT")
    current_leverage = data.get("leverage", int(os.getenv("LEVERAGE", 10)))
    
    if action == "CLOSE":
        return _close_position(symbol)

    pos_side = "LONG" if action in ["BUY", "LONG"] else "SHORT"
    order_side = "BUY" if pos_side == "LONG" else "SELL"
    entry_price = float(data.get("price", 0)) or bx.get_current_price(symbol)
    sl_price = float(data.get("sl", 0))
    tp_levels_prices = [float(data.get(f"tp{i}", 0)) for i in range(1, 5)]

    balance = bx.get_balance()
    total_quantity = calculate_quantity(balance, entry_price, sl_price, current_leverage, symbol)
    
    bx.set_leverage(symbol, current_leverage, pos_side)
    bx.set_margin_mode(symbol, "ISOLATED")

    order_res = bx.place_order(symbol, order_side, pos_side, total_quantity, "MARKET")
    if order_res.get("code") != 0: raise Exception(f"Gagal buka posisi: {order_res}")

    # 6. Pasang TP/SL (Logika OPSI 1: Tutup 100% di TP1)
    status_msg = "success"
    try:
        sl_side = "SELL" if pos_side == "LONG" else "BUY"
        bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": total_quantity, "reduceOnly": "true"
        })

        tp1_price = tp_levels_prices[0]
        if tp1_price > 0:
            bx._request("POST", "/openApi/swap/v2/trade/order", {
                "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                "type": "TAKE_PROFIT_MARKET", "stopPrice": tp1_price, "quantity": total_quantity, "reduceOnly": "true"
            })
    except Exception as e:
        logger.error(f"⚠️ Posisi terbuka tapi TP/SL gagal dipasang: {e}")
        status_msg = f"warning: TP/SL Gagal ({str(e)})"

    active_trade_data[symbol] = {
        "entry": entry_price, "tps": [tp1_price] if tp1_price > 0 else [],
        "sl": sl_price, "side": pos_side, "last_tp_hit": 0
    }
    return {"status": status_msg, "total_quantity": total_quantity, "symbol": symbol, "action": action}

def apply_manual_tpsl(symbol: str, sl_price: float) -> dict:
    """Otomatis hitung & pasang TP/SL untuk posisi manual yang sudah terbuka."""
    positions = bx.get_open_positions()
    target_pos = next((p for p in positions if p.get("symbol") == symbol and abs(float(p.get("positionAmt", 0))) > 0), None)
    
    if not target_pos:
        raise ValueError(f"Tidak ada posisi aktif untuk {symbol}.")
        
    pos_side = target_pos.get("positionSide")
    entry_price = float(target_pos.get("avgPrice"))
    total_quantity = abs(float(target_pos.get("positionAmt")))
    
    if sl_price == 0 or entry_price == 0:
        raise ValueError("Harga Entry atau SL tidak valid.")
        
    # Hitung Jarak SL (Risk)
    risk_dist = abs(entry_price - sl_price)
    if risk_dist == 0:
        raise ValueError("Harga SL tidak boleh sama dengan Entry.")
        
    # Validasi arah SL
    if pos_side == "LONG" and sl_price >= entry_price:
        raise ValueError(f"SL ({sl_price}) harus di bawah Entry ({entry_price}) untuk posisi LONG.")
    if pos_side == "SHORT" and sl_price <= entry_price:
        raise ValueError(f"SL ({sl_price}) harus di atas Entry ({entry_price}) untuk posisi SHORT.")
        
    # Hitung 1 TP utama (Risk Reward 1:1.5 agar profit lebih terasa)
    if pos_side == "LONG":
        tp1_price = entry_price + (risk_dist * 1.5)
    else:
        tp1_price = entry_price - (risk_dist * 1.5)
        
    # Hapus semua TP/SL lama
    bx.cancel_all_orders(symbol)
    
    sl_side = "SELL" if pos_side == "LONG" else "BUY"
    
    # Pasang SL Baru
    bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": total_quantity, "reduceOnly": "true"
    })
    
    # Pasang TP1 Baru (100% Quantity)
    bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp1_price, "quantity": total_quantity, "reduceOnly": "true"
    })
        
    # Update state bot
    active_trade_data[symbol] = {
        "entry": entry_price, "tps": [tp1_price],
        "sl": sl_price, "side": pos_side, "last_tp_hit": 0
    }
    
    return {"status": "success", "tps": [tp1_price], "sl": sl_price}

def _close_position(symbol: str) -> dict:
    positions = bx.get_open_positions(symbol)
    if not positions: return {"msg": "No active position"}
    for pos in positions:
        side, qty = pos["positionSide"], abs(float(pos["positionAmt"]))
        close_side = "SELL" if side == "LONG" else "BUY"
        bx.place_order(symbol, close_side, side, qty, reduce_only=True)
    bx.cancel_all_orders(symbol)
    active_trade_data.pop(symbol, None)
    return {"msg": f"Closed {symbol}"}

def monitor_and_sync_positions():
    """Radar: Memantau posisi, adopsi posisi lama, dan trailing SL."""
    try:
        positions = bx.get_open_positions()
        if not positions: return

        for pos in positions:
            symbol, side = pos["symbol"], pos["positionSide"]
            entry, qty = float(pos["avgPrice"]), abs(float(pos["positionAmt"]))
            if qty == 0: continue

            # 1. Cek Order TP/SL Aktif di BingX
            orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
            
            if not isinstance(orders_res, dict):
                logger.warning(f"Radar: Response orders_res bukan dict: {orders_res}")
                continue
                
            open_orders_raw = orders_res.get("data", [])
            if isinstance(open_orders_raw, dict) and "orders" in open_orders_raw:
                open_orders = open_orders_raw["orders"]
            else:
                open_orders = open_orders_raw
                
            if not isinstance(open_orders, list):
                logger.warning(f"Radar: open_orders bukan list: {open_orders}")
                continue

            tp_orders = [o for o in open_orders if isinstance(o, dict) and o.get("type") == "TAKE_PROFIT_MARKET"]
            sl_orders = [o for o in open_orders if isinstance(o, dict) and o.get("type") == "STOP_MARKET"]

            # 2. FITUR ADOPT: Jika posisi belum tercatat, ambil data dari BingX
            if symbol not in active_trade_data:
                if tp_orders:
                    # Urutkan TP: Naik untuk LONG, Turun untuk SHORT
                    prices = sorted([float(o["stopPrice"]) for o in tp_orders])
                    if side == "SHORT": prices.reverse()
                    
                    sl_p = float(sl_orders[0]["stopPrice"]) if sl_orders else 0
                    active_trade_data[symbol] = {
                        "entry": entry, "tps": prices, "sl": sl_p, "side": side, "last_tp_hit": 0
                    }
                    logger.info(f"🛡️ Radar: Posisi {symbol} ({side}) DIADOPSI! Melacak {len(prices)} TP level.")
                continue

            # 3. LOGIKA TRAILING SL (MOVE SL TO BE)
            data = active_trade_data[symbol]
            rem_tps, orig_tps = len(tp_orders), len(data["tps"])
            
            # Update SL jika TP kena
            if rem_tps < orig_tps and data["last_tp_hit"] < 1:
                logger.info(f"🎯 {symbol} TP1 Hit! SL -> Entry ({entry})")
                _update_sl(symbol, side, entry, qty, sl_orders)
                data["last_tp_hit"] = 1
            elif rem_tps < orig_tps - 1 and data["last_tp_hit"] < 2:
                new_sl = data["tps"][0]
                logger.info(f"🎯 {symbol} TP2 Hit! SL -> TP1 ({new_sl})")
                _update_sl(symbol, side, new_sl, qty, sl_orders)
                # Jika TP4 sudah kena (Running Profit Mode)
                if rem_tps == 0 and data["last_tp_hit"] < 4:
                    new_sl = data["tps"][2] # SL ke harga TP3 sebagai base
                    logger.info(f"🚀 {symbol} TP4 Hit! Memulai Trailing Take Profit (TTP). SL -> TP3 ({new_sl})")
                    _update_sl(symbol, side, new_sl, qty, sl_orders)
                    data["last_tp_hit"] = 4
                
                # Tambahan: Jika sudah di tahap TTP, geser SL lebih agresif mengikuti harga (Trailing Stop Manual)
                if data["last_tp_hit"] >= 4:
                    curr_price = bx.get_current_price(symbol)
                    # Jika LONG, SL ditaruh 1% di bawah harga sekarang (hanya jika lebih tinggi dari SL lama)
                    if side == "LONG":
                        tp_sl = curr_price * 0.99
                        if tp_sl > data["sl"]:
                            logger.info(f"🔥 {symbol} TTP Active: Menggeser SL ke {tp_sl:.2f} (Trailing 1%)")
                            _update_sl(symbol, side, tp_sl, qty, sl_orders)
                            data["sl"] = tp_sl
                    # Jika SHORT, SL ditaruh 1% di atas harga sekarang (hanya jika lebih rendah dari SL lama)
                    else:
                        tp_sl = curr_price * 1.01
                        if data["sl"] == 0 or tp_sl < data["sl"]:
                            logger.info(f"🔥 {symbol} TTP Active: Menggeser SL ke {tp_sl:.2f} (Trailing 1%)")
                            _update_sl(symbol, side, tp_sl, qty, sl_orders)
                            data["sl"] = tp_sl

    except Exception as e:
        logger.error(f"Radar Error: {e}")

def _update_sl(symbol, side, new_price, qty, current_sl_orders):
    for sl in current_sl_orders:
        try:
            bx.cancel_order(symbol, str(sl["orderId"]))
        except Exception as e:
            logger.error(f"Gagal membatalkan SL lama: {e}")
            
    sl_side = "SELL" if side == "LONG" else "BUY"
    bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": side,
        "type": "STOP_MARKET", "stopPrice": new_price, "quantity": qty, "reduceOnly": "true"
    })

import os
import math
import logging
import json
from dotenv import load_dotenv
import bingx_client as bx
import time

# Load environment variables
load_dotenv()

# Konfigurasi Logging
logger = logging.getLogger(__name__)

# Config
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "10"))
ORDER_TYPE = os.getenv("ORDER_TYPE", "MARKET")

# State untuk menyimpan data TP/SL per symbol
active_trade_data = {}

# ── Simpan sinyal terakhir per koin untuk /susul ──
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
    """Bulatkan quantity ke step size yang valid sesuai symbol."""
    precisions = {"BTC-USDT": 4, "ETH-USDT": 3, "SOL-USDT": 2}
    p = precisions.get(symbol, 2)
    factor = 10 ** p
    return math.floor(qty * factor) / factor

def calculate_quantity(balance: float, entry_price: float, leverage: int, symbol: str = "BTC-USDT") -> float:
    """Hitung quantity berdasarkan RISK_PERCENT dari balance."""
    margin_amount = balance * (RISK_PERCENT / 100)
    qty = (margin_amount * leverage) / entry_price
    qty = _round_qty(qty, symbol)
    if qty <= 0:
        raise ValueError(f"Quantity terlalu kecil: {qty}")
    return qty

def execute_signal(data: dict) -> dict:
    """
    Eksekusi sinyal dari TradingView.
    Semua parameter (leverage, tp1, sl) diambil LANGSUNG dari payload sinyal.
    Tidak ada override dari sisi bot.
    """
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "BTC-USDT")

    if action == "CLOSE":
        return _close_position(symbol)

    pos_side = "LONG" if action in ["BUY", "LONG"] else "SHORT"
    order_side = "BUY" if pos_side == "LONG" else "SELL"

    # ── Ambil semua parameter dari sinyal ──
    entry_price = float(data.get("price", 0)) or bx.get_current_price(symbol)
    sl_price    = float(data.get("sl", 0))
    tp1_price   = float(data.get("tp1", 0))
    leverage    = int(data.get("leverage", int(os.getenv("LEVERAGE", 10))))

    # ── Validasi wajib ──
    if sl_price == 0:
        raise ValueError("❌ SL tidak ada di sinyal. Eksekusi dibatalkan.")
    if tp1_price == 0:
        raise ValueError("❌ TP1 tidak ada di sinyal. Eksekusi dibatalkan.")
    if entry_price == 0:
        raise ValueError("❌ Harga entry tidak valid.")

    logger.info(f"📊 Signal: {symbol} {pos_side} | Leverage: {leverage}x | Entry: {entry_price} | TP1: {tp1_price} | SL: {sl_price}")

    # ── Auto-Reversal: tutup posisi berlawanan jika ada ──
    existing_positions = bx.get_open_positions(symbol)
    for pos in existing_positions:
        if pos.get("positionSide") != pos_side:
            logger.info(f"🔄 Reversal: Menutup posisi {pos.get('positionSide')} sebelum buka {pos_side}")
            _close_position(symbol)
            time.sleep(1.0)
            break

    # ── Hitung quantity dari RISK_PERCENT env ──
    balance = bx.get_balance()
    total_quantity = calculate_quantity(balance, entry_price, leverage, symbol)

    logger.info(f"💰 Balance: {balance:.2f} USDT | Risk: {RISK_PERCENT}% | Qty: {total_quantity}")

    # ── Set leverage & margin mode ISOLATED ──
    margin_mode = os.getenv("MARGIN_MODE", "ISOLATED").upper()
    bx.set_leverage(symbol, leverage, pos_side)
    bx.set_margin_type(symbol, margin_mode)

    # ── Buka posisi MARKET ──
    order_res = bx.place_order(symbol, order_side, pos_side, total_quantity, "MARKET")
    if order_res.get("code") != 0:
        raise Exception(f"Gagal buka posisi: {order_res}")

    logger.info(f"✅ Posisi {pos_side} {symbol} terbuka | Qty: {total_quantity}")

    # ── Pasang TP1 + SL dari sinyal ──
    status_msg = "success"
    time.sleep(1.5)  # Jeda agar order settle di BingX

    try:
        sl_side = "SELL" if pos_side == "LONG" else "BUY"

        # Pasang Stop Loss
        sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": total_quantity
        })
        if sl_res.get("code", 0) != 0:
            raise Exception(f"SL Ditolak: {sl_res.get('msg')}")
        logger.info(f"🛑 SL terpasang di {sl_price}")

        # Pasang Take Profit 1 (hanya TP1)
        tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "TAKE_PROFIT_MARKET", "stopPrice": tp1_price, "quantity": total_quantity
        })
        if tp_res.get("code", 0) != 0:
            raise Exception(f"TP1 Ditolak: {tp_res.get('msg')}")
        logger.info(f"🎯 TP1 terpasang di {tp1_price}")

    except Exception as e:
        logger.error(f"⚠️ Posisi terbuka TAPI TP/SL gagal: {e}")
        status_msg = f"warning: TP/SL Gagal ({str(e)})"

    # ── Simpan data posisi aktif ──
    active_trade_data[symbol] = {
        "entry": entry_price,
        "tps": [tp1_price],
        "sl": sl_price,
        "side": pos_side,
        "leverage": leverage
    }

    return {
        "status": status_msg,
        "total_quantity": total_quantity,
        "symbol": symbol,
        "action": action,
        "leverage": leverage,
        "tp1": tp1_price,
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

    if sl_price == 0 or entry_price == 0 or tp_price == 0:
        raise ValueError("Harga TP, SL, atau Entry tidak valid.")

    # Validasi arah
    if pos_side == "LONG" and sl_price >= entry_price:
        raise ValueError(f"SL ({sl_price}) harus di bawah Entry ({entry_price}) untuk LONG.")
    if pos_side == "SHORT" and sl_price <= entry_price:
        raise ValueError(f"SL ({sl_price}) harus di atas Entry ({entry_price}) untuk SHORT.")
    if pos_side == "LONG" and tp_price <= entry_price:
        raise ValueError(f"TP ({tp_price}) harus di atas Entry ({entry_price}) untuk LONG.")
    if pos_side == "SHORT" and tp_price >= entry_price:
        raise ValueError(f"TP ({tp_price}) harus di bawah Entry ({entry_price}) untuk SHORT.")

    # Hapus TP/SL lama & pasang baru
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
    """Tutup semua posisi untuk symbol tertentu."""
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
    """Re-entry berdasarkan sinyal terakhir jika masih valid."""
    if symbol not in latest_signals:
        raise ValueError(f"Tidak ada histori sinyal untuk {symbol}.")

    data = latest_signals[symbol]
    action = data.get("action", "").upper()

    if action == "CLOSE":
        raise ValueError(f"Sinyal terakhir untuk {symbol} adalah CLOSE. Tidak bisa re-entry.")

    current_price = bx.get_current_price(symbol)
    tp1 = float(data.get("tp1", 0))
    sl  = float(data.get("sl", 0))

    if sl == 0 or tp1 == 0:
        raise ValueError("Sinyal terakhir tidak punya TP1 atau SL valid.")

    # Validasi harga saat ini masih dalam range yang aman
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

    # Cancel order lama jika ada
    bx.cancel_all_orders(symbol)

    # Re-entry dengan harga market saat ini
    data["price"] = current_price
    logger.info(f"🔄 Re-Entry {symbol} di harga market {current_price}")
    return execute_signal(data)


def monitor_and_sync_positions():
    """
    Monitor sederhana: adopsi posisi yang tidak tercatat di memori bot.
    Tidak ada trailing SL otomatis — biarkan BingX TP/SL yang handle.
    """
    try:
        positions = bx.get_open_positions()
        if not positions:
            return

        for pos in positions:
            symbol = pos["symbol"]
            side   = pos["positionSide"]
            entry  = float(pos["avgPrice"])
            qty    = abs(float(pos["positionAmt"]))

            if qty == 0:
                continue

            # Jika posisi belum tercatat di bot, adopsi dari BingX
            if symbol not in active_trade_data:
                orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                open_orders_raw = orders_res.get("data", [])
                if isinstance(open_orders_raw, dict):
                    open_orders = open_orders_raw.get("orders", [])
                else:
                    open_orders = open_orders_raw if isinstance(open_orders_raw, list) else []

                tp_orders = [o for o in open_orders if isinstance(o, dict) and "TAKE_PROFIT" in o.get("type", "")]
                sl_orders = [o for o in open_orders if isinstance(o, dict) and "STOP" in o.get("type", "")]

                tp_price = float(tp_orders[0]["stopPrice"]) if tp_orders else 0
                sl_price = float(sl_orders[0]["stopPrice"]) if sl_orders else 0

                active_trade_data[symbol] = {
                    "entry": entry, "tps": [tp_price] if tp_price else [],
                    "sl": sl_price, "side": side
                }
                logger.info(f"🛡️ Radar: Posisi {symbol} ({side}) diadopsi | TP1: {tp_price} | SL: {sl_price}")

    except Exception as e:
        logger.error(f"Radar Error: {e}")

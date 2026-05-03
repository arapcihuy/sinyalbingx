import os
import math
import logging
from dotenv import load_dotenv
import bingx_client as bx

load_dotenv()

logger = logging.getLogger(__name__)

SYMBOL = os.getenv("SYMBOL", "BTC-USDT")
LEVERAGE = int(os.getenv("LEVERAGE", 10))
MARGIN_MODE = os.getenv("MARGIN_MODE", "ISOLATED")  # "ISOLATED" atau "CROSSED"
RISK_PERCENT = float(os.getenv("RISK_PERCENT", 1.5))
TP_SL_MODE = os.getenv("TP_SL_MODE", "pinescript")   # "pinescript" atau "percent"
TP_PERCENT = float(os.getenv("TP_PERCENT", 3.0))
SL_PERCENT = float(os.getenv("SL_PERCENT", 1.5))
ORDER_TYPE = os.getenv("ORDER_TYPE", "MARKET")


def _round_qty(qty: float, step: float = 0.00001) -> float:
    """Bulatkan quantity ke step size yang valid (untuk BTC biasanya 0.0001 atau lebih kecil)."""
    return math.floor(qty / step) * step


def calculate_quantity(balance: float, entry_price: float, sl_price: float, leverage: int) -> float:
    """
    Hitung jumlah kontrak berdasarkan:
    - Balance tersedia
    - Harga entry
    - Stop loss (untuk menentukan risk dalam USDT)
    - Leverage
    """
    risk_amount = balance * (RISK_PERCENT / 100)     # USDT yang siap di-risk
    price_diff = abs(entry_price - sl_price)          # jarak entry ke SL

    if price_diff == 0:
        raise ValueError("Entry dan SL tidak boleh sama!")

    # Qty = risk_amount / price_diff (dengan leverage sudah diperhitungkan)
    qty = (risk_amount * leverage) / entry_price
    qty = _round_qty(qty)

    if qty <= 0:
        raise ValueError(f"Quantity terlalu kecil: {qty}. Cek balance atau RISK_PERCENT.")

    return qty


def execute_signal(signal: dict) -> dict:
    """
    Proses sinyal dari TradingView TRADENTIX PRO dan eksekusi order di BingX.

    Payload dari Pine Script TRADENTIX PRO:
    {
        "action": "BUY" atau "SELL",
        "symbol": "BTC-USDT",
        "price": 95000,
        "tp1": 95500,   ← TP level 1
        "tp2": 96200,   ← TP level 2
        "tp3": 97100,   ← TP level 3
        "tp4": 98500,   ← TP level 4
        "sl":  93500    ← Stop Loss
    }
    """
    action = signal.get("action", "").upper()
    symbol = signal.get("symbol", SYMBOL)

    if action not in ["BUY", "SELL"]:
        raise ValueError(f"Action tidak valid: {action}. Gunakan BUY atau SELL.")

    # ── Tentukan posisi side ──
    position_side = "LONG" if action == "BUY" else "SHORT"
    order_side = "BUY" if action == "BUY" else "SELL"

    # ── Ambil Leverage & Margin Mode dari Signal (opsional) atau .env ──
    current_leverage = int(signal.get("leverage", LEVERAGE))
    current_margin_mode = signal.get("margin_mode", MARGIN_MODE).upper()

    # ── Set Margin Mode & Leverage ──
    try:
        # Set Margin Mode (Isolated/Crossed)
        bx.set_margin_type(symbol, current_margin_mode)
        logger.info(f"Margin mode set: {current_margin_mode} for {symbol}")

        # Set Leverage
        bx.set_leverage(symbol, current_leverage, position_side)
        logger.info(f"Leverage set: {current_leverage}x {position_side}")
    except Exception as e:
        logger.warning(f"Gagal set margin/leverage (mungkin sudah sesuai atau ada posisi aktif): {e}")

    # ── Ambil harga entry ──
    current_price = bx.get_current_price(symbol)
    entry_price = float(signal.get("price", current_price))

    # ── Hitung TP dan SL ──
    # TRADENTIX PRO mengirim: tp1, tp2, tp3, tp4, sl
    sl_price = float(signal.get("sl", 0))
    tp_levels_prices = [
        float(signal.get("tp1", 0)),
        float(signal.get("tp2", 0)),
        float(signal.get("tp3", 0)),
        float(signal.get("tp4", 0))
    ]
    
    if sl_price == 0 or tp_levels_prices[0] == 0:
        raise ValueError("TP1 atau SL tidak diterima dari TradingView!")

    # ── Ambil balance & Hitung total quantity ──
    balance = bx.get_balance()
    logger.info(f"Balance tersedia: {balance:.2f} USDT")

    total_quantity = calculate_quantity(balance, entry_price, sl_price, current_leverage)
    logger.info(f"Total Quantity: {total_quantity} kontrak")

    # ── Bagi Quantity ke 4 TP (Masing-masing 25%) ──
    # Pastikan pembagian tidak membuat quantity per TP jadi 0
    qty_per_tp = _round_qty(total_quantity / 4)
    if qty_per_tp <= 0:
        # Jika terlalu kecil untuk dibagi 4, gunakan 1 TP saja (TP4)
        tp_configs = [(tp_levels_prices[3], total_quantity)]
        logger.info("Quantity terlalu kecil untuk dibagi 4, menggunakan single TP (TP4)")
    else:
        # Bagi ke 4 level, sisanya masukkan ke TP terakhir
        tp_configs = []
        remaining_qty = total_quantity
        for i in range(3):
            tp_configs.append((tp_levels_prices[i], qty_per_tp))
            remaining_qty -= qty_per_tp
        tp_configs.append((tp_levels_prices[3], _round_qty(remaining_qty)))

    result = {
        "symbol": symbol,
        "action": action,
        "position_side": position_side,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "total_quantity": total_quantity,
        "tp_configs": tp_configs,
        "balance": balance,
        "orders": {}
    }

    # ── Batalkan order lama jika ada ──
    try:
        bx.cancel_all_orders(symbol)
        logger.info("Order lama dibatalkan.")
    except Exception as e:
        logger.warning(f"Cancel order: {e}")

    # ── Buka order entry ──
    logger.info(f"Membuka order {action} {symbol} qty={total_quantity}")
    order_result = bx.place_order(
        symbol=symbol,
        side=order_side,
        position_side=position_side,
        quantity=total_quantity,
        order_type=ORDER_TYPE,
        price=entry_price if ORDER_TYPE == "LIMIT" else None,
    )
    result["orders"]["entry"] = order_result
    logger.info(f"Order entry: {order_result}")

    # ── Pasang Multi TP & SL ──
    logger.info(f"Set Multi-TP: {tp_configs} SL={sl_price}")
    tpsl_result = bx.set_multi_tp_sl(
        symbol=symbol,
        position_side=position_side,
        stop_price=sl_price,
        tp_levels=tp_configs,
        total_qty=total_quantity
    )
    result["orders"]["tpsl"] = tpsl_result
    logger.info(f"Multi-TP/SL result: {tpsl_result}")

    return result


def apply_tpsl_to_existing(signal: dict) -> dict:
    """Hanya pasang TP/SL untuk posisi yang sudah terbuka."""
    symbol = signal.get("symbol", SYMBOL)
    
    # ── Cek posisi aktif ──
    positions = bx.get_open_positions(symbol)
    if not positions:
        raise ValueError(f"Tidak ada posisi aktif untuk {symbol}!")
    
    # Ambil posisi pertama
    pos = positions[0]
    position_side = pos.get("positionSide", "LONG")
    total_quantity = abs(float(pos.get("positionAmt", 0)))
    
    if total_quantity == 0:
        raise ValueError(f"Posisi {symbol} ditemukan tapi jumlahnya 0.")

    # ── Hitung TP dan SL dari sinyal ──
    sl_price = float(signal.get("sl", 0))
    tp_levels_prices = [
        float(signal.get("tp1", 0)),
        float(signal.get("tp2", 0)),
        float(signal.get("tp3", 0)),
        float(signal.get("tp4", 0))
    ]

    # ── Bagi Quantity ke 4 TP ──
    qty_per_tp = _round_qty(total_quantity / 4)
    if qty_per_tp <= 0:
        tp_configs = [(tp_levels_prices[3], total_quantity)]
    else:
        tp_configs = []
        remaining_qty = total_quantity
        for i in range(3):
            tp_configs.append((tp_levels_prices[i], qty_per_tp))
            remaining_qty -= qty_per_tp
        tp_configs.append((tp_levels_prices[3], _round_qty(remaining_qty)))

    # ── Pasang ke BingX ──
    bx.cancel_all_orders(symbol) # Bersihkan TP/SL lama
    bx.set_multi_tp_sl(
        symbol=symbol,
        position_side=position_side,
        stop_price=sl_price,
        tp_levels=tp_configs,
        total_qty=total_quantity
    )

    return {
        "symbol": symbol,
        "total_quantity": total_quantity,
        "tp_configs": tp_configs,
        "sl_price": sl_price
    }

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


def _round_qty(qty: float, step: float = 0.001) -> float:
    """Bulatkan quantity ke step size yang valid."""
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
    # Gunakan tp1 sebagai TP utama untuk BingX, sl sebagai SL
    if TP_SL_MODE == "pinescript":
        # Cek format TRADENTIX PRO (multi-TP)
        tp1_price = float(signal.get("tp1", signal.get("tp", 0)))
        tp4_price = float(signal.get("tp4", tp1_price))
        sl_price  = float(signal.get("sl", 0))

        if tp1_price == 0 or sl_price == 0:
            raise ValueError("TP atau SL tidak diterima dari TradingView! Cek format payload.")

        # Gunakan TP4 (target terbesar) untuk pemasangan TP di BingX
        # TP1,2,3 akan dicapai secara partial — BingX tidak support multi-TP via API dasar
        tp_price = tp4_price
    else:
        # Mode percent: hitung dari entry price
        if action == "BUY":
            tp_price = entry_price * (1 + TP_PERCENT / 100)
            sl_price = entry_price * (1 - SL_PERCENT / 100)
        else:
            tp_price = entry_price * (1 - TP_PERCENT / 100)
            sl_price = entry_price * (1 + SL_PERCENT / 100)

    # ── Ambil balance ──
    balance = bx.get_balance()
    logger.info(f"Balance tersedia: {balance:.2f} USDT")

    # ── Hitung quantity ──
    quantity = calculate_quantity(balance, entry_price, sl_price, current_leverage)
    logger.info(f"Quantity: {quantity} kontrak")

    result = {
        "symbol": symbol,
        "action": action,
        "position_side": position_side,
        "entry_price": entry_price,
        "tp_price": round(tp_price, 2),
        "sl_price": round(sl_price, 2),
        "quantity": quantity,
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
    logger.info(f"Membuka order {action} {symbol} qty={quantity} entry={entry_price}")
    order_result = bx.place_order(
        symbol=symbol,
        side=order_side,
        position_side=position_side,
        quantity=quantity,
        order_type=ORDER_TYPE,
        price=entry_price if ORDER_TYPE == "LIMIT" else None,
    )
    result["orders"]["entry"] = order_result
    logger.info(f"Order entry: {order_result}")

    # ── Pasang TP & SL ──
    logger.info(f"Set TP={tp_price} SL={sl_price}")
    tpsl_result = bx.set_tp_sl(
        symbol=symbol,
        position_side=position_side,
        stop_price=sl_price,
        tp_price=tp_price,
    )
    result["orders"]["tpsl"] = tpsl_result
    logger.info(f"TP/SL result: {tpsl_result}")

    return result

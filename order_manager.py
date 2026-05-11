import os
import math
import logging
import json
from dotenv import load_dotenv
import bingx_client as bx
import time
import settings_manager

load_dotenv()
logger = logging.getLogger(__name__)

# Config
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "10"))

# ── Mode TP: Baca dari settings_manager ──
def get_tp_mode():
    settings = settings_manager.load_settings()
    return settings.get("tp_mode", "tp1_only") == "tp1_only"

# State posisi aktif
active_trade_data = {}

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


def calculate_quantity(balance: float, entry_price: float, leverage: int, symbol: str) -> float:
    """Hitung total quantity dari RISK_PERCENT balance."""
    margin_amount = balance * (RISK_PERCENT / 100)
    qty = (margin_amount * leverage) / entry_price
    qty = _round_qty(qty, symbol)
    if qty <= 0:
        raise ValueError(f"Quantity terlalu kecil: {qty}")
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

    # ── Hitung total quantity ──
    balance = bx.get_balance()
    total_quantity = calculate_quantity(balance, entry_price, leverage, symbol)
    logger.info(f"💰 Balance: {balance:.2f} USDT | Risk: {RISK_PERCENT}% | Total Qty: {total_quantity}")

    # ── Set leverage & margin ISOLATED ──
    margin_mode = os.getenv("MARGIN_MODE", "ISOLATED").upper()
    bx.set_leverage(symbol, leverage, pos_side)
    bx.set_margin_type(symbol, margin_mode)

    # ── Buka posisi MARKET ──
    order_res = bx.place_order(symbol, order_side, pos_side, total_quantity, "MARKET")
    if order_res.get("code") != 0:
        raise Exception(f"Gagal buka posisi: {order_res}")
    logger.info(f"✅ Posisi {pos_side} {symbol} terbuka | Qty: {total_quantity}")

    # ── Pasang SL + semua TP dengan qty split ──
    status_msg = "success"
    time.sleep(1.5)  # Jeda agar posisi settle

    try:
        # Pasang Stop Loss (full quantity)
        sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": total_quantity
        })
        if sl_res.get("code", 0) != 0:
            raise Exception(f"SL Ditolak: {sl_res.get('msg')}")
        logger.info(f"🛑 SL terpasang di {sl_price} (qty: {total_quantity})")

        # Pasang setiap TP dengan quantity proporsional
        remaining_qty = total_quantity
        for i, tp in enumerate(tp_levels):
            is_last = (i == len(tp_levels) - 1)

            # TP terakhir pakai sisa qty agar tidak ada selisih pembulatan
            if is_last:
                tp_qty = remaining_qty
            else:
                tp_qty = _round_qty(total_quantity * tp["qty_pct"], symbol)
                tp_qty = min(tp_qty, remaining_qty)

            if tp_qty <= 0:
                logger.warning(f"   TP{i+1}: qty 0, dilewati")
                continue

            tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                "type": "TAKE_PROFIT_MARKET", "stopPrice": tp["price"], "quantity": tp_qty
            })
            if tp_res.get("code", 0) != 0:
                raise Exception(f"TP{i+1} Ditolak: {tp_res.get('msg')}")

            logger.info(f"🎯 TP{i+1} terpasang di {tp['price']} (qty: {tp_qty}, {tp['qty_pct']*100:.0f}%)")
            remaining_qty = _round_qty(remaining_qty - tp_qty, symbol)

    except Exception as e:
        logger.error(f"⚠️ Posisi terbuka TAPI TP/SL gagal: {e}")
        status_msg = f"warning: TP/SL Gagal ({str(e)})"

    # ── Simpan state ──
    active_trade_data[symbol] = {
        "entry": entry_price,
        "tps": [t["price"] for t in tp_levels],
        "sl": sl_price,
        "side": pos_side,
        "leverage": leverage,
        "total_qty": total_quantity
    }

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


def monitor_and_sync_positions():
    """
    Monitor ringan: adopsi posisi yang tidak tercatat di memori.
    TP/SL sudah dipasang native di BingX — tidak perlu trailing dari bot.
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

            if symbol not in active_trade_data:
                orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                open_orders_raw = orders_res.get("data", [])
                if isinstance(open_orders_raw, dict):
                    open_orders = open_orders_raw.get("orders", [])
                else:
                    open_orders = open_orders_raw if isinstance(open_orders_raw, list) else []

                tp_orders = sorted(
                    [o for o in open_orders if isinstance(o, dict) and "TAKE_PROFIT" in o.get("type", "")],
                    key=lambda o: float(o.get("stopPrice", 0)),
                    reverse=(side == "SHORT")
                )
                sl_orders = [o for o in open_orders if isinstance(o, dict) and "STOP" in o.get("type", "")]

                tp_prices = [float(o["stopPrice"]) for o in tp_orders]
                sl_price  = float(sl_orders[0]["stopPrice"]) if sl_orders else 0

                active_trade_data[symbol] = {
                    "entry": entry, "tps": tp_prices,
                    "sl": sl_price, "side": side
                }
                logger.info(f"🛡️ Radar: {symbol} ({side}) diadopsi | TPs: {tp_prices} | SL: {sl_price}")

    except Exception as e:
        logger.error(f"Radar Error: {e}")

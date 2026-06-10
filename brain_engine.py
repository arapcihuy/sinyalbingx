"""
BRAIN ENGINE — Otak Trading Bot
================================
1. TP/SL pintar — ATR-based, adaptif per symbol
2. Leverage dinamis — berdasarkan saldo futures
3. Margin dinamis — risk-based position sizing
4. Trailing SL — auto-adjust SL saat harga profit
5. Multi-symbol support — BTC + ETH
"""

import logging
import math
import time

logger = logging.getLogger(__name__)

# ─── KONFIGURASI BRAIN ───────────────────────────────────────────
SYMBOL_CONFIG = {
    "BTC-USDT": {
        "atr_period": 14,
        "tp_atr_multiplier": 2.0,   # TP = 2x ATR dari entry
        "sl_atr_multiplier": 1.0,   # SL = 1x ATR dari entry
        "trail_activate_atr": 1.0,  # Trail aktif setelah profit 1x ATR
        "trail_offset_atr": 0.5,    # Jarak trailing 0.5x ATR dari harga tertinggi/terendah
        "min_qty": 0.001,
        "qty_precision": 3,
        "price_precision": 2,
    },
    "ETH-USDT": {
        "atr_period": 14,
        "tp_atr_multiplier": 2.0,
        "sl_atr_multiplier": 1.0,
        "trail_activate_atr": 1.0,
        "trail_offset_atr": 0.5,
        "min_qty": 0.01,
        "qty_precision": 2,
        "price_precision": 2,
    },
}

# Fallback config untuk symbol lain
DEFAULT_CONFIG = {
    "atr_period": 14,
    "tp_atr_multiplier": 2.0,
    "sl_atr_multiplier": 1.0,
    "trail_activate_atr": 1.0,
    "trail_offset_atr": 0.5,
    "min_qty": 0.001,
    "qty_precision": 3,
    "price_precision": 2,
}

# Leverage tiers berdasarkan saldo
LEVERAGE_TIERS = [
    (0, 10, 5),     # <$10  → lev 5x
    (10, 25, 10),   # $10-25 → lev 10x
    (25, 50, 15),   # $25-50 → lev 15x
    (50, 100, 20),  # $50-100 → lev 20x
    (100, 999999, 25),  # >$100 → lev 25x (cap aman)
]

# Risk per trade berdasarkan saldo
RISK_TIERS = [
    (0, 20, 2.0),    # <$10 → risk 2%
    (20, 50, 1.5),   # $10-25 → risk 1.5%
    (50, 100, 1.0),  # $25-50 → risk 1%
    (100, 999999, 1.0),  # >$50 → risk 1%
]


def get_symbol_config(symbol: str) -> dict:
    """Ambil konfigurasi symbol (BTC/ETH) atau fallback."""
    cfg = SYMBOL_CONFIG.get(symbol, DEFAULT_CONFIG)
    return cfg


def calculate_atr(candles: list, period: int = 14) -> float:
    """
    Hitung ATR dari data candle (list of dict: {high, low, close}).
    Returns ATR value atau fallback 1% dari harga terakhir.
    """
    if not candles or len(candles) < 2:
        return 0

    true_ranges = []
    for i in range(1, len(candles)):
        high = float(candles[i].get("high", candles[i].get("h", 0)))
        low = float(candles[i].get("low", candles[i].get("l", 0)))
        prev_close = float(candles[i - 1].get("close", candles[i - 1].get("c", 0)))

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        # Simple average kal cukup data
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
    else:
        # Wilder's smoothing
        atr = sum(true_ranges[:period]) / period
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period

    return atr


def calculate_tp_sl(entry_price: float, side: str, atr: float, symbol: str) -> dict:
    """
    Hitung TP dan SL berdasarkan ATR.
    
    Args:
        entry_price: Harga masuk
        side: "LONG" atau "SHORT"
        atr: ATR value
        symbol: Symbol trading
    
    Returns:
        Dict dengan tp1, tp2, sl prices
    """
    cfg = get_symbol_config(symbol)
    
    tp_mult = cfg["tp_atr_multiplier"]
    sl_mult = cfg["sl_atr_multiplier"]
    
    # Minimal ATR = 0.5% dari entry (fallback kalau ATR terlalu kecil)
    min_atr = entry_price * 0.005
    effective_atr = max(atr, min_atr)
    
    if side == "LONG":
        sl_price = entry_price - (effective_atr * sl_mult)
        tp1_price = entry_price + (effective_atr * tp_mult * 0.6)  # TP1: 60% target
        tp2_price = entry_price + (effective_atr * tp_mult)        # TP2: 100% target
    else:
        sl_price = entry_price + (effective_atr * sl_mult)
        tp1_price = entry_price - (effective_atr * tp_mult * 0.6)
        tp2_price = entry_price - (effective_atr * tp_mult)
    
    # Round sesuai presisi symbol
    price_prec = cfg["price_precision"]
    
    return {
        "sl": round(sl_price, price_prec),
        "tp1": round(tp1_price, price_prec),
        "tp2": round(tp2_price, price_prec),
        "atr_used": effective_atr,
    }


def get_dynamic_leverage(balance: float) -> int:
    """
    Tentukan leverage optimal berdasarkan saldo futures.
    Semakin kecil saldo, semakin kecil leverage (aman).
    """
    for min_bal, max_bal, lev in LEVERAGE_TIERS:
        if min_bal <= balance < max_bal:
            return lev
    return 10  # Default fallback


def get_dynamic_risk_percent(balance: float) -> float:
    """
    Tentukan risk per trade berdasarkan saldo.
    """
    for min_bal, max_bal, risk in RISK_TIERS:
        if min_bal <= balance < max_bal:
            return risk
    return 1.5  # Default fallback


def calculate_position_size(balance: float, entry_price: float, sl_price: float, risk_percent: float, symbol: str) -> float:
    """
    Hitung ukuran posisi berdasarkan risk management.
    Formula: qty = (balance * risk%) / |entry - sl|
    """
    cfg = get_symbol_config(symbol)
    price_diff = abs(entry_price - sl_price)
    
    if price_diff == 0 or price_diff < entry_price * 0.001:
        # Minimal risk $1
        risk_amount = max(balance * (risk_percent / 100), 1.0)
        qty = risk_amount / entry_price
    else:
        risk_amount = balance * (risk_percent / 100)
        qty = risk_amount / price_diff
    
    # Apply precision
    qty_prec = cfg["qty_precision"]
    qty = round(qty, qty_prec)
    
    # Minimal qty
    qty = max(qty, cfg["min_qty"])
    
    return qty


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
    required_margin = (total_qty * entry_price) / leverage if leverage > 0 else 0
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
        "margin": (sum(final_qtys) * entry_price) / leverage if leverage > 0 else 0
    }


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


def calculate_trailing_sl(current_price: float, side: str, entry_price: float, atr: float, current_sl: float, symbol: str) -> dict:
    """
    Cek apakah trailing SL perlu di-update.
    
    Returns:
        {"should_update": bool, "new_sl": float, "reason": str}
    """
    cfg = get_symbol_config(symbol)
    trail_activate = cfg["trail_activate_atr"]
    trail_offset = cfg["trail_offset_atr"]
    
    # Minimal ATR fallback
    min_atr = entry_price * 0.005
    effective_atr = max(atr, min_atr)
    
    trail_dist = effective_atr * trail_offset
    activate_dist = effective_atr * trail_activate
    
    if side == "LONG":
        profit_dist = current_price - entry_price
        
        # Belum sampai activation point
        if profit_dist < activate_dist:
            return {"should_update": False, "new_sl": current_sl, "reason": "belum activation"}
        
        # Hitung new SL
        proposed_sl = current_price - trail_dist
        # SL hanya naik, tidak turun
        new_sl = max(proposed_sl, current_sl, entry_price)
        
        if new_sl > current_sl:
            return {
                "should_update": True, 
                "new_sl": round(new_sl, cfg["price_precision"]),
                "reason": f"Profit {profit_dist:.2f} > activate {activate_dist:.2f}. SL naik ke {new_sl:.2f}"
            }
    
    else:  # SHORT
        profit_dist = entry_price - current_price
        
        if profit_dist < activate_dist:
            return {"should_update": False, "new_sl": current_sl, "reason": "belum activation"}
        
        proposed_sl = current_price + trail_dist
        # SL hanya turun (untuk short), tidak naik
        new_sl = min(proposed_sl, current_sl, entry_price) if current_sl else proposed_sl
        
        if new_sl < current_sl or current_sl == 0:
            return {
                "should_update": True,
                "new_sl": round(new_sl, cfg["price_precision"]),
                "reason": f"Profit {profit_dist:.2f} > activate {activate_dist:.2f}. SL turun ke {new_sl:.2f}"
            }
    
    return {"should_update": False, "new_sl": current_sl, "reason": "trailing tidak berubah"}


def get_full_trade_plan(balance: float, entry_price: float, side: str, symbol: str, candles: list = None) -> dict:
    """
    Generate trade plan lengkap: leverage, TP/SL, qty, trailing config.
    Ini adalah "otak" utama yang dipanggil saat entry.
    
    Returns:
        {
            "symbol": str,
            "side": str,
            "entry_price": float,
            "leverage": int,
            "risk_percent": float,
            "qty": float,
            "sl": float,
            "tp1": float,
            "tp2": float,
            "atr": float,
            "trail_config": dict,
        }
    """
    cfg = get_symbol_config(symbol)
    
    # 1. Hitung ATR (atau fallback)
    atr = 0
    if candles:
        atr = calculate_atr(candles, cfg["atr_period"])
    
    # Fallback ATR = 1% dari entry
    if atr == 0:
        atr = entry_price * 0.01
    
    # 2. Leverage dinamis
    leverage = get_dynamic_leverage(balance)
    
    # 3. Risk dinamis
    risk_percent = get_dynamic_risk_percent(balance)
    
    # 4. TP/SL pintar
    tp_sl = calculate_tp_sl(entry_price, side, atr, symbol)
    
    # 5. Position size
    qty = calculate_position_size(balance, entry_price, tp_sl["sl"], risk_percent, symbol)
    
    # 6. Trailing config
    plan = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "leverage": leverage,
        "risk_percent": risk_percent,
        "qty": qty,
        "sl": tp_sl["sl"],
        "tp1": tp_sl["tp1"],
        "tp2": tp_sl["tp2"],
        "atr": round(atr, 6),
        "trailing_config": {
            "activate_atr_mult": cfg["trail_activate_atr"],
            "offset_atr_mult": cfg["trail_offset_atr"],
            "active": False,
            "highest_price": entry_price if side == "LONG" else 0,
            "lowest_price": entry_price if side == "SHORT" else 0,
        }
    }
    
    logger.info(f"🧠 BRAIN PLAN: {symbol} {side} | Lev: {leverage}x | Risk: {risk_percent}% | Qty: {qty}")
    logger.info(f"   TP1: {tp_sl['tp1']} | TP2: {tp_sl['tp2']} | SL: {tp_sl['sl']} | ATR: {atr:.4f}")
    
    return plan

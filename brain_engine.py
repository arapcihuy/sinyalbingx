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


_DYNAMIC_SYMBOL_CACHE = {}

def get_symbol_config(symbol: str) -> dict:
    """Ambil konfigurasi symbol atau fetch secara dinamis dari BingX."""
    if symbol in SYMBOL_CONFIG:
        return SYMBOL_CONFIG[symbol]
        
    global _DYNAMIC_SYMBOL_CACHE
    if symbol in _DYNAMIC_SYMBOL_CACHE:
        return _DYNAMIC_SYMBOL_CACHE[symbol]
        
    try:
        import bingx_client as bx
        res = bx._request('GET', '/openApi/swap/v2/quote/contracts', {"symbol": symbol})
        if res.get("code") == 0 and res.get("data"):
            data = res["data"][0] if isinstance(res["data"], list) else res["data"]
            cfg = {
                "atr_period": 14,
                "tp_atr_multiplier": 2.0,
                "sl_atr_multiplier": 1.0,
                "trail_activate_atr": 1.0,
                "trail_offset_atr": 0.5,
                "min_qty": float(data.get("tradeMinQuantity", 0.001)),
                "qty_precision": int(data.get("quantityPrecision", 2)),
                "price_precision": int(data.get("pricePrecision", 2)),
                "mmr": _extract_contract_mmr(data),
            }
            _DYNAMIC_SYMBOL_CACHE[symbol] = cfg
            logger.info(f"✨ DYNAMIC CONFIG LOADED FOR {symbol}: min_qty={cfg['min_qty']}, qty_prec={cfg['qty_precision']}, price_prec={cfg['price_precision']}, mmr={cfg['mmr']}")
            return cfg
    except Exception as e:
        logger.error(f"⚠️ Gagal load dynamic config untuk {symbol}, menggunakan DEFAULT_CONFIG: {e}")
        
    return {**DEFAULT_CONFIG, "mmr": 0.005}


def _extract_contract_mmr(data: dict) -> float:
    """Ambil maintenance margin rate dari metadata contract kalau tersedia."""
    for key in ("maintMarginRate", "maintenanceMarginRate", "maintainMarginRate", "mmr"):
        val = data.get(key)
        if val is not None:
            try:
                mmr = float(val)
                if 0 < mmr < 1:
                    return mmr
            except Exception:
                pass
    return 0.005


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


def calculate_tp_sl(entry_price: float, side: str, atr: float, symbol: str, leverage: int = 0) -> dict:
    """
    Hitung TP dan SL berdasarkan ATR.
    Clamp SL terhadap buffer likuidasi supaya otak bot tidak bikin SL ngawur.
    """
    cfg = get_symbol_config(symbol)
    
    tp_mult = cfg["tp_atr_multiplier"]
    sl_mult = cfg["sl_atr_multiplier"]
    mmr = float(cfg.get("mmr", 0.005))
    buffer_pct = 0.10
    
    # Minimal ATR = 0.5% dari entry (fallback kalau ATR terlalu kecil)
    min_atr = entry_price * 0.005
    effective_atr = max(atr, min_atr)
    
    if side == "LONG":
        sl_price = entry_price - (effective_atr * sl_mult)
        tp1_price = entry_price + (effective_atr * tp_mult * 0.6)
        tp2_price = entry_price + (effective_atr * tp_mult)
        tp3_price = entry_price + (effective_atr * tp_mult * 1.4)
        tp4_price = entry_price + (effective_atr * tp_mult * 1.8)
    else:
        sl_price = entry_price + (effective_atr * sl_mult)
        tp1_price = entry_price - (effective_atr * tp_mult * 0.6)
        tp2_price = entry_price - (effective_atr * tp_mult)
        tp3_price = entry_price - (effective_atr * tp_mult * 1.4)
        tp4_price = entry_price - (effective_atr * tp_mult * 1.8)

    if leverage and leverage > 0:
        est_liq = estimate_liquidation_price(entry_price, leverage, side, mmr)
        if est_liq > 0:
            if side == "LONG":
                min_safe_sl = est_liq * (1.0 + buffer_pct)
                sl_price = max(sl_price, min_safe_sl)
            else:
                max_safe_sl = est_liq * (1.0 - buffer_pct)
                sl_price = min(sl_price, max_safe_sl)

    # TP ikut jarak SL final → RR stabil
    risk_dist = abs(entry_price - sl_price)
    
    # Target RR default (misal SL 1% → TP1 1.5%, TP2 3%, TP3 4.5%, TP4 6%)
    if side == "LONG":
        tp1_price = entry_price + (risk_dist * 1.5)
        tp2_price = entry_price + (risk_dist * 3.0)
        tp3_price = entry_price + (risk_dist * 4.5)
        tp4_price = entry_price + (risk_dist * 6.0)
    else:
        tp1_price = entry_price - (risk_dist * 1.5)
        tp2_price = entry_price - (risk_dist * 3.0)
        tp3_price = entry_price - (risk_dist * 4.5)
        tp4_price = entry_price - (risk_dist * 6.0)
    
    # LIMIT TP: Jangan biarkan TP melampaui 5% profit per trade untuk altcoins
    # Biar nggak 'kejauhan' di BingX
    max_tp_pct = 0.05
    if side == "LONG":
        tp1_price = min(tp1_price, entry_price * (1 + max_tp_pct * 0.5))
        tp2_price = min(tp2_price, entry_price * (1 + max_tp_pct))
        tp3_price = min(tp3_price, entry_price * (1 + max_tp_pct * 1.5))
        tp4_price = min(tp4_price, entry_price * (1 + max_tp_pct * 2.0))
    else:
        tp1_price = max(tp1_price, entry_price * (1 - max_tp_pct * 0.5))
        tp2_price = max(tp2_price, entry_price * (1 - max_tp_pct))
        tp3_price = max(tp3_price, entry_price * (1 - max_tp_pct * 1.5))
        tp4_price = max(tp4_price, entry_price * (1 - max_tp_pct * 2.0))
    
    price_prec = cfg["price_precision"]
    
    return {
        "sl": round(sl_price, price_prec),
        "tp1": round(tp1_price, price_prec),
        "tp2": round(tp2_price, price_prec),
        "tp3": round(tp3_price, price_prec),
        "tp4": round(tp4_price, price_prec),
        "atr_used": effective_atr,
    }


def get_dynamic_leverage(balance: float) -> int:
    """Tentukan leverage optimal berdasarkan saldo futures (override by settings if available)."""
    try:
        import os
        import json
        settings_path = "bot_settings.json"
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                settings = json.load(f)
                if "leverage" in settings:
                    return int(settings["leverage"])
    except:
        pass

    for min_bal, max_bal, lev in LEVERAGE_TIERS:
        if min_bal <= balance < max_bal:
            return lev
    return 10


def estimate_liquidation_price(entry_price: float, leverage: int, side: str, mmr: float = 0.005) -> float:
    """Estimasi liquid price kasar untuk isolated futures."""
    if entry_price <= 0 or leverage <= 0:
        return 0.0

    if side == "LONG":
        liq = entry_price * (1.0 - 1.0 / leverage + mmr)
        return max(0.0, liq)
    else:
        liq = entry_price * (1.0 + 1.0 / leverage - mmr)
        return max(0.0, liq)


def get_safe_leverage(balance: float, entry_price: float, sl_price: float, side: str, symbol: str) -> int:
    """
    Menghitung leverage aman agar Stop Loss terpicu sebelum Liquidation Price.
    Menggunakan Safety Factor 0.90 (buffer 10% jarak aman dari likuidasi).
    """
    base_leverage = get_dynamic_leverage(balance)
    
    if sl_price <= 0 or entry_price <= 0 or entry_price == sl_price:
        return base_leverage

    cfg = get_symbol_config(symbol)
    mmr = float(cfg.get("mmr", 0.005))

    try:
        if side == "LONG":
            if sl_price >= entry_price:
                return base_leverage
            denominator = 1.0 + mmr - (sl_price / entry_price)
        else:  # SHORT
            if sl_price <= entry_price:
                return base_leverage
            denominator = (sl_price / entry_price) + mmr - 1.0

        if denominator <= 0:
            return base_leverage
        l_max = 1.0 / denominator

        # Hitung leverage aman dengan buffer 15% (dulu 10%)
        safe_leverage = int(math.floor(l_max * 0.85))
        final_leverage = max(1, min(base_leverage, safe_leverage))
        logger.info(f"🛡️ AUDIT LEVERAGE: {symbol} | Base {base_leverage}x | L_max {l_max:.1f}x | Safe {safe_leverage}x | Final {final_leverage}x")
        return final_leverage
    except Exception as e:
        logger.error(f"Gagal menghitung safe leverage: {e}")
        return base_leverage



def get_dynamic_risk_percent(balance: float) -> float:
    """Tentukan risk per trade berdasarkan saldo (override by settings if available)."""
    try:
        import os
        import json
        settings_path = "bot_settings.json"
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                settings = json.load(f)
                if "risk_per_trade_percent" in settings:
                    return float(settings["risk_per_trade_percent"])
    except:
        pass
        
    for min_bal, max_bal, risk in RISK_TIERS:
        if min_bal <= balance < max_bal:
            return risk
    return 1.5


def calculate_position_size(balance: float, entry_price: float, sl_price: float, risk_percent: float, symbol: str, leverage: int = 1) -> float:
    """
    Hitung ukuran posisi berdasarkan risk management.
    Formula: qty = (balance * risk%) / |entry - sl|
    Ditambah pengaman leverage: qty * entry / leverage <= balance (Isolated Margin Guard)
    """
    cfg = get_symbol_config(symbol)
    price_diff = abs(entry_price - sl_price)
    
    # 1. Hitung Qty berdasarkan Risk budget ($)
    risk_amount = balance * (risk_percent / 100)
    
    if price_diff == 0 or price_diff < entry_price * 0.0001:
        # Fallback jika SL terlalu dekat: batasi margin max 5%
        qty = (balance * 0.05 * leverage) / entry_price
    else:
        qty = risk_amount / price_diff
    
    # 2. Leverage Guard: Pastikan margin awal (qty * entry / lev) tidak melebihi saldo tersedia
    # Kita beri buffer: max 70% dari balance (dulu 80%) untuk satu trade tunggal agar akun aman
    max_qty_by_margin = (balance * 0.7 * leverage) / entry_price
    if qty > max_qty_by_margin:
        logger.warning(f"⚠️ RISK OVERSIZE: Qty {qty:.4f} butuh margin terlalu besar. Scaled down to {max_qty_by_margin:.4f}")
        qty = max_qty_by_margin

    # 3. Apply precision & min_qty
    qty_prec = cfg.get("qty_precision", 2)
    qty = round(float(qty), qty_prec)
    qty = max(qty, cfg.get("min_qty", 0.001))
    
    return qty


def calculate_smart_multi_tp_qty(balance: float, entry_price: float, sl_price: float, tp_prices: list, leverage: int, risk_percent: float, symbol: str) -> dict:
    """
    Menghitung kuantitas parsial untuk setiap level TP.
    Total kuantitas tetap mengikuti budget risk (Stop Loss based).
    """
    cfg = get_symbol_config(symbol)
    qty_prec = cfg.get("qty_precision", 2)
    
    # 1. Hitung total qty berdasarkan budget risk
    total_qty = calculate_position_size(balance, entry_price, sl_price, risk_percent, symbol, leverage)
    
    # 2. Bagi qty ke TP levels
    valid_tps = [p for p in tp_prices if p > 0]
    if not valid_tps:
        return {"qtys": [total_qty], "total_qty": total_qty, "margin": (total_qty * entry_price) / leverage}
    
    # Pembagian: TP1 (40%), TP2 (30%), TP3 (20%), TP4 (10%) jika semua ada
    # Jika cuma 2 TP: TP1 (60%), TP2 (40%)
    weights = [0.4, 0.3, 0.2, 0.1]
    if len(valid_tps) == 1: weights = [1.0]
    elif len(valid_tps) == 2: weights = [0.6, 0.4]
    elif len(valid_tps) == 3: weights = [0.5, 0.3, 0.2]
    
    final_qtys = [0.0] * 4
    tp_idx = 0
    assigned_qty = 0.0
    
    for i, price in enumerate(tp_prices):
        if price > 0 and tp_idx < len(weights):
            # TP terakhir ambil sisa agar presisi
            if tp_idx == len(valid_tps) - 1:
                q = total_qty - assigned_qty
            else:
                q = total_qty * weights[tp_idx]
            
            q = round(max(q, cfg.get("min_qty", 0.001)), qty_prec)
            final_qtys[i] = q
            assigned_qty += q
            tp_idx += 1
            
    # 3. Recalculate total qty after rounding
    actual_total = round(sum(final_qtys), qty_prec)
    
    # --- DYNAMIC TP LEVEL CONSOLIDATION FOR SMALL BALANCE ---
    # Jika margin yang dibutuhkan setelah menerapkan min_qty melebihi 85% dari saldo tersedia,
    # kurangi level TP satu per satu dari yang terjauh demi menghindari error "Insufficient margin".
    while True:
        current_total_qty = sum(final_qtys)
        if current_total_qty == 0:
            break
        current_required_margin = (current_total_qty * entry_price) / leverage if leverage > 0 else 0
        if current_required_margin > (balance * 0.85) and current_required_margin > 0:
            active_indices = [idx for idx, price in enumerate(tp_prices) if price > 0 and final_qtys[idx] > 0]
            if len(active_indices) > 1:
                idx_to_disable = active_indices[-1]
                logger.info(f"⚠️ DYNAMIC CONSOLIDATION: Margin ${current_required_margin:.2f} melebihi 85% saldo tersedia (${balance:.2f}). Menonaktifkan TP{idx_to_disable+1} ({tp_prices[idx_to_disable]}) untuk mengurangi beban margin.")
                final_qtys[idx_to_disable] = 0.0
                continue
            else:
                break
        else:
            break
            
    # [HARD LIMITER] TP/SL Clamping
    # Membatasi TP/SL agar tidak terlalu jauh jika script TV mengirim data ngaco
    # TP max 5%, SL max 3%
    for i in range(len(tp_prices)):
        if tp_prices[i] > 0:
            dist = abs(tp_prices[i] - entry_price)
            if dist > (entry_price * 0.05):
                tp_prices[i] = entry_price + (0.05 * entry_price) if tp_prices[i] > entry_price else entry_price - (0.05 * entry_price)
    
    # Apply limit if sl is provided
    # (assuming sl is passed somewhere or handle it in order_manager)
            
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
    
    # Fallback ATR via live data
    if atr == 0:
        try:
            import bingx_client as bx
            live_candles = bx.get_candles(symbol, "1h", limit=30)
            if live_candles:
                atr = calculate_atr(live_candles, cfg.get("atr_period", 14))
        except Exception:
            pass

    if atr == 0:
        atr = entry_price * 0.01
    
    # 2. Leverage dinamis
    leverage = get_dynamic_leverage(balance)
    
    # 3. Risk dinamis
    risk_percent = get_dynamic_risk_percent(balance)
    
    # 4. TP/SL pintar
    tp_sl = calculate_tp_sl(entry_price, side, atr, symbol, leverage)
    
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
        "tp3": tp_sl.get("tp3", 0),
        "tp4": tp_sl.get("tp4", 0),
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
    logger.info(f"   TP1: {tp_sl['tp1']} | TP2: {tp_sl['tp2']} | TP3: {tp_sl.get('tp3',0)} | TP4: {tp_sl.get('tp4',0)} | SL: {tp_sl['sl']} | ATR: {atr:.4f}")
    
    return plan

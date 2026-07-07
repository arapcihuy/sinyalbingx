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
        "min_margin": 5.0,          # BingX minimum margin per position
        "max_lev": 150,             # BingX max leverage BTC
        "mmr": 0.004,               # Maintenance margin rate BTC
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
        "min_margin": 2.0,
        "max_lev": 100,
        "mmr": 0.005,
    },
    "BNB-USDT": {
        "atr_period": 14,
        "tp_atr_multiplier": 2.0,
        "sl_atr_multiplier": 1.0,
        "trail_activate_atr": 1.0,
        "trail_offset_atr": 0.5,
        "min_qty": 0.01,
        "qty_precision": 2,
        "price_precision": 2,
        "min_margin": 1.0,
        "max_lev": 75,
        "mmr": 0.005,
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
    "min_margin": 1.0,  # default min margin untuk symbol yg ga dikenal
    "max_lev": 100,
    "mmr": 0.005,
}

# Leverage tiers berdasarkan saldo (leverage dinaikkan untuk saldo kecil agar margin cukup memasang 4 TP)
LEVERAGE_TIERS = [
    (0, 10, 20),     # <$10  → lev 20x
    (10, 25, 20),   # $10-25 → lev 20x
    (25, 50, 20),   # $25-50 → lev 20x
    (50, 100, 20),  # $50-100 → lev 20x
    (100, 999999, 25),  # >$100 → lev 25x
]

def _linear_risk_percent(balance: float) -> float:
    """Risk% linear: 2.0% di $0, turun gradual ke 1.0% di $100, cap 1.0% di atasnya."""
    if balance <= 20:
        return 2.0
    elif balance >= 100:
        return 1.0
    else:
        # Linear dari 2.0% ($20) ke 1.0% ($100)
        return 2.0 - (balance - 20) * 1.0 / 80


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
                # SL untuk LONG wajib di BAWAH entry (minimum 1% dari entry)
                sl_price = min(sl_price, entry_price * (1.0 - 0.01))
            else:
                max_safe_sl = est_liq * (1.0 - buffer_pct)
                sl_price = min(sl_price, max_safe_sl)
                # SL untuk SHORT wajib di ATAS entry (minimum 1% dari entry)
                sl_price = max(sl_price, entry_price * (1.0 + 0.01))

    # TP ikut jarak SL final → RR stabil
    risk_dist = abs(entry_price - sl_price)
    # Minimum risk_dist 1% entry → TPs tidak terlalu rapat saat SL di-clamp dekat entry
    min_risk = entry_price * 0.01
    risk_dist = max(risk_dist, min_risk)
    
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
        
    return _linear_risk_percent(balance)


def calculate_margin_for_position(balance: float, entry_price: float, sl_price: float, 
                                   risk_percent: float, leverage: int, symbol: str) -> float:
    """Hitung margin yang dibutuhkan untuk satu posisi."""
    qty = calculate_position_size(balance, entry_price, sl_price, risk_percent, symbol, leverage)
    return (qty * entry_price) / leverage if leverage > 0 else 0


def get_leverage_for_min_margin(balance: float, entry_price: float, sl_price: float,
                                 side: str, symbol: str, target_margin: float = None) -> int:
    """
    Hitung leverage MAXIMUM yang masih memenuhi min_margin untuk symbol ini.
    Margin = risk_amount × entry / (sl_delta × lev)
    Untuk margin ≥ min_margin: lev ≤ risk_amount × entry / (sl_delta × min_margin)
    Juga mempertimbangkan liquidation safety (SL harus terpicu sebelum liq).
    """
    cfg = get_symbol_config(symbol)
    min_margin = cfg.get("min_margin", 1.0)
    mmr = float(cfg.get("mmr", 0.005))
    
    # Dapatkan base leverage dari safe_leverage
    base_lev = get_safe_leverage(balance, entry_price, sl_price, side, symbol)
    
    # Hitung margin dengan base leverage
    risk_pct = get_dynamic_risk_percent(balance)
    margin = calculate_margin_for_position(balance, entry_price, sl_price, risk_pct, base_lev, symbol)
    
    # Jika margin sudah cukup, return base
    if margin >= min_margin:
        return base_lev
    
    # Margin kurang → perlu TURUNKAN leverage (lev lebih kecil = margin lebih besar)
    # lev_max = risk_amount × entry / (sl_delta × min_margin)
    
    risk_amount = balance * (risk_pct / 100)
    sl_delta = abs(entry_price - sl_price)
    
    if sl_delta <= 0 or risk_amount <= 0:
        return base_lev
    
    lev_max = (risk_amount * entry_price) / (sl_delta * min_margin)
    lev_max = int(math.floor(lev_max))
    
    # Gunakan lev_max (lebih kecil dari base_lev) jika memenuhi min_margin
    if lev_max >= base_lev:
        # Base leverage sudah cukup, tapi margin masih kurang → hitung ulang
        # Artinya risk_amount terlalu kecil, return base_lev saja
        return base_lev
    
    # Cek liquidation safety untuk lev yg lebih kecil
    est_liq = estimate_liquidation_price(entry_price, lev_max, side, mmr)
    if est_liq > 0:
        buffer = 0.10  # 10% buffer dari liquidation
        if side == "LONG":
            min_safe_sl = est_liq * (1.0 + buffer)
            if sl_price < min_safe_sl:
                # Lev_max masih bikin SL dekat liq → cari lev lebih kecil
                for test_lev in range(lev_max, 0, -1):
                    test_liq = estimate_liquidation_price(entry_price, test_lev, side, mmr)
                    if test_liq > 0:
                        test_min_sl = test_liq * (1.0 + buffer)
                        if sl_price >= test_min_sl:
                            logger.info(f"🛡️ MIN MARGIN: {symbol} lev {test_lev}x (margin ≥ ${min_margin}, SL aman dari liq)")
                            return test_lev
                logger.warning(f"⚠️ {symbol} ga bisa penuhi min_margin ${min_margin} tanpa melanggar liquidation safety")
                return base_lev
        else:  # SHORT
            max_safe_sl = est_liq * (1.0 - buffer)
            if sl_price > max_safe_sl:
                for test_lev in range(lev_max, 0, -1):
                    test_liq = estimate_liquidation_price(entry_price, test_lev, side, mmr)
                    if test_liq > 0:
                        test_max_sl = test_liq * (1.0 - buffer)
                        if sl_price <= test_max_sl:
                            logger.info(f"🛡️ MIN MARGIN: {symbol} lev {test_lev}x (margin ≥ ${min_margin}, SL aman dari liq)")
                            return test_lev
                logger.warning(f"⚠️ {symbol} ga bisa penuhi min_margin ${min_margin} tanpa melanggar liquidation safety")
                return base_lev
    
    logger.info(f"🔄 MIN MARGIN: {symbol} {base_lev}x → {lev_max}x (margin ${margin:.2f} → target ≥${min_margin})")
    return lev_max


def get_risk_for_positions(balance: float, open_positions: int, symbols: list = None) -> float:
    """
    Hitung risk% optimal:
    - Linear scaling seiring balance (profit naik)
    - Floor dari total min margin (semua coin wajib masuk)
    """
    if not symbols:
        return get_dynamic_risk_percent(balance)
    
    total_min_margin = sum(get_symbol_config(s).get("min_margin", 1.0) for s in symbols)
    
    # Linear scaling: naik seiring balance
    base_risk = 1.0 + (balance / 200)  # 1.5% di $100, 3.5% di $500
    base_risk = min(base_risk, 5.0)
    
    # Min risk utk fit semua coin (20% buffer)
    min_risk = (total_min_margin / balance) * 100 * 1.2
    
    # Gunakan yg LEBIH BESAR
    risk_pct = max(min_risk, base_risk)
    risk_pct = max(0.5, min(5.0, risk_pct))
    
    logger.info(f"🧠 ZERO-REJECT RISK: {len(symbols)} symbols, min_margin=${total_min_margin:.2f}, balance=${balance:.2f} → risk={risk_pct:.2f}%")
    return risk_pct


def calculate_auto_leverage(balance: float, qty: float, entry_price: float, default_leverage: int) -> int:
    """
    Auto-bump leverage jika margin tidak cukup untuk qty yang diinginkan.
    Return leverage baru (bisa lebih tinggi dari default).
    ponytail: cap 50x. Naikkan jika BingX max leverage pair > 50.
    """
    margin_needed = (qty * entry_price) / default_leverage
    if margin_needed > balance and balance > 0:
        needed = int((qty * entry_price) / balance) + 1
        needed = min(needed, 50)
        if needed > default_leverage:
            logger.info(f"🔄 Auto-bump leverage {default_leverage}x → {needed}x (margin ${margin_needed:.2f} > balance ${balance:.2f})")
            return needed
    return default_leverage


def calculate_position_size(balance: float, entry_price: float, sl_price: float, risk_percent: float, symbol: str, leverage: int = 1) -> float:
    """
    Hitung ukuran posisi berdasarkan risk management.
    Formula: qty = (balance * risk%) / |entry - sl|
    Caps qty agar margin tidak melebihi 40% balance.
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
    
    # 2. MARGIN CAP: pastikan margin tidak melebihi 40% balance
    if leverage > 0 and entry_price > 0:
        max_margin = balance * 0.40
        margin = (qty * entry_price) / leverage
        if margin > max_margin and margin > 0:
            qty = (max_margin * leverage) / entry_price
            logger.info(f"📐 QTY CAP: {symbol} margin ${margin:.2f} > 40% (${max_margin:.2f}) → qty capped ke {qty:.6f}")
    
    # 3. Naikkan qty ke minimum jika perlu (BingX min order ~$2 notional)
    desired_qty = qty  # qty hasil perhitungan risk
    min_qty_for_4tp = cfg.get("min_qty", 0.001)  # ponytail: BingX accepts split across TPs, no need 4x
    if desired_qty < min_qty_for_4tp:
        logger.warning(f"⚠️ Qty {desired_qty:.4f} < min ({min_qty_for_4tp}). Setting ke {min_qty_for_4tp}")
        desired_qty = min_qty_for_4tp

    qty = desired_qty

    # 4. Apply precision & min_qty
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
    
    # Pembagian: TP1 (35%), TP2 (30%), TP3 (20%), TP4 (15%) jika semua ada
    # Jika cuma 2 TP: TP1 (60%), TP2 (40%)
    weights = [0.35, 0.30, 0.20, 0.15]
    if len(valid_tps) == 1: weights = [1.0]
    elif len(valid_tps) == 2: weights = [0.6, 0.4]
    elif len(valid_tps) == 3: weights = [0.50, 0.30, 0.20]
    
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
            
            # ponytail: no min_qty floor for TP split — BingX accepts sub-min qty per TP order (CLAUDE.md §Min Qty)
            q = round(q, qty_prec)
            final_qtys[i] = q
            assigned_qty += q
            tp_idx += 1
            
    # 3. Recalculate total qty after rounding
    actual_total = round(sum(final_qtys), qty_prec)
    
    # [REMOVED] Dynamic TP Consolidation — TP/SL fully from TV, bot tidak modify
            
    # [REMOVED] Hard Limiter — TP/SL fully from TV, bot tidak clamp
            
    return {
        "qtys": final_qtys,
        "total_qty": round(sum(final_qtys), qty_prec),
        "margin": (sum(final_qtys) * entry_price) / leverage if leverage > 0 else 0
    }


def calculate_milestone_trailing_sl(current_price: float, side: str, entry_price: float, current_sl: float, tp1: float, tp2: float, tp3: float, symbol: str) -> dict:
    """
    Menghitung SL baru berdasarkan level milestone TP yang berhasil disentuh.
    TP1 terlewati -> SL TIDAK berubah (biarkan di SL awal)
    TP2 terlewati -> SL ke TP1
    TP3 terlewati -> SL ke TP2
    """
    cfg = get_symbol_config(symbol)
    price_prec = cfg.get("price_precision", 2)
    
    # Buffer kecil 0.05% dari entry agar SL tidak persis di entry price
    # (hindari instant-fill karena spread/slippage)
    sl_entry_buffer = round(entry_price * 0.0005, price_prec)

    if side == "LONG":
        # LONG: Harga naik
        if tp3 > 0 and current_price >= tp3:
            new_sl = round(tp2, price_prec)
            reason = "TP3 tercapai -> SL digeser ke TP2"
        elif tp2 > 0 and current_price >= tp2:
            new_sl = round(tp1, price_prec)
            reason = "TP2 tercapai -> SL digeser ke TP1"
        else:
            return {"should_update": False, "new_sl": current_sl, "reason": "belum menyentuh milestone"}

        if new_sl > current_sl:
            return {
                "should_update": True,
                "new_sl": new_sl,
                "reason": reason
            }
    else:
        # SHORT: Harga turun
        if tp3 > 0 and current_price <= tp3:
            new_sl = round(tp2, price_prec)
            reason = "TP3 tercapai -> SL digeser ke TP2"
        elif tp2 > 0 and current_price <= tp2:
            new_sl = round(tp1, price_prec)
            reason = "TP2 tercapai -> SL digeser ke TP1"
        else:
            return {"should_update": False, "new_sl": current_sl, "reason": "belum menyentuh milestone"}

        if current_sl == 0 or new_sl < current_sl:
            return {
                "should_update": True,
                "new_sl": new_sl,
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


# ─────────────────────────────────────────────────────────────────────
# Fix 2-5: Extended brain utilities
# ─────────────────────────────────────────────────────────────────────

def get_safe_leverage_with_max(balance: float, entry_price: float, sl_price: float, side: str, symbol: str) -> int:
    """Wrap get_safe_leverage and cap at BingX max_leverage."""
    try:
        import bingx_client as bx
        bx_max = bx.get_max_leverage(symbol)
    except Exception as e:
        logger.warning(f"⚠️ Gagal ambil max_leverage BingX: {e}, fallback 25x")
        bx_max = 25

    safe = get_safe_leverage(balance, entry_price, sl_price, side, symbol)
    final = min(safe, bx_max) if bx_max > 0 else safe
    logger.info(f"🛡️ SAFE_LEV_WITH_MAX: {symbol} | Safe {safe}x | BX_Max {bx_max}x | Final {final}x")
    return final


def calculate_slippage_adjusted_sl(entry_price: float, sl_price: float, side: str, slippage_pct: float) -> float:
    """Adjust SL price to account for expected slippage.
    LONG: positive slippage (higher entry) → SL moves lower (wider).
    SHORT: positive slippage (lower entry) → SL moves higher (wider).
    """
    if side == "LONG":
        # SL is below entry; widen by slippage_pct of entry
        slippage_offset = entry_price * (slippage_pct / 100.0)
        adjusted = sl_price - slippage_offset
    else:
        # SHORT: SL is above entry; widen by slippage_pct of entry
        slippage_offset = entry_price * (slippage_pct / 100.0)
        adjusted = sl_price + slippage_offset

    logger.info(f"📉 SLIPPAGE ADJ: {side} | SL {sl_price} → {adjusted:.6f} (slip {slippage_pct}%)")
    return adjusted


def estimate_funding_cost(margin: float, funding_rate: float, hours_held: float) -> float:
    """Estimate total funding cost in USDT.
    BingX charges funding every 8h. funding_rate is per-interval (e.g. 0.0001 = 0.01%).
    """
    if margin <= 0 or funding_rate <= 0 or hours_held <= 0:
        return 0.0

    intervals = hours_held / 8.0
    cost = margin * funding_rate * intervals
    logger.info(f"💰 FUNDING COST: margin {margin} | rate {funding_rate} | {hours_held}h ({intervals:.1f}x) → {cost:.6f} USDT")
    return cost


def get_max_position_value(symbol: str, available_balance: float, leverage: int) -> float:
    """Max notional value = min(balance * leverage, BingX max_notional).
    BingX max notional derived from exchange max_leverage * balance.
    """
    notional_by_lev = available_balance * leverage

    try:
        import bingx_client as bx
        bx_max_lev = bx.get_max_leverage(symbol)
        bx_max_notional = available_balance * bx_max_lev if bx_max_lev > 0 else notional_by_lev
    except Exception as e:
        logger.warning(f"⚠️ Gagal ambil max_leverage BingX: {e}")
        bx_max_notional = notional_by_lev

    max_val = min(notional_by_lev, bx_max_notional)
    logger.info(f"📊 MAX_POS_VALUE: {symbol} | Lev {leverage}x → {notional_by_lev:.2f} | BX cap → {bx_max_notional:.2f} | Final {max_val:.2f}")
    return max_val

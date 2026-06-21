    if est_liq > 0:
        buffer_pct = settings.get("liquidation_buffer_pct", 0.10)
        if pos_side == "LONG":
            min_safe_sl = est_liq * (1.0 + buffer_pct)
            if sl_price <= min_safe_sl:
                logger.warning(f"🛡️ AUTO-ADJUST SL: {symbol} SL {sl_price} terlalu dekat liq {est_liq}. Adjusted to {min_safe_sl:.4f}")
                sl_price = _round_price(min_safe_sl, symbol)
        else:
            max_safe_sl = est_liq * (1.0 - buffer_pct)
            if sl_price >= max_safe_sl:
                logger.warning(f"🛡️ AUTO-ADJUST SL: {symbol} SL {sl_price} terlalu dekat liq {est_liq}. Adjusted to {max_safe_sl:.4f}")
                sl_price = _round_price(max_safe_sl, symbol)
        logger.info(f"🛡️ LIQ CHECK: {symbol} {pos_side} | Entry={entry_price:.4f} SL={sl_price:.4f} EstLiq={est_liq:.4f} Lev={leverage}x")

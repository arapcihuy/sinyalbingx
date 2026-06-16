import logging

logger = logging.getLogger("volatility_helper")

def calculate_atr(klines: list, period: int = 14) -> float:
    """
    Calculate Average True Range (ATR) from BingX K-lines.
    K-line format: dict with keys 'open', 'high', 'low', 'close', 'time'.
    """
    if len(klines) < 2:
        return 0.0
    
    true_ranges = []
    for i in range(len(klines)):
        h = float(klines[i]['high'])
        l = float(klines[i]['low'])
        
        if i == 0:
            tr = h - l
        else:
            prev_c = float(klines[i-1]['close'])
            tr = max(
                h - l,
                abs(h - prev_c),
                abs(l - prev_c)
            )
        true_ranges.append(tr)
    
    # Simple Moving Average of True Ranges for the last 'period' candles
    # Or as many as we have if less than period
    relevant_tr = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    if not relevant_tr:
        return 0.0
        
    return sum(relevant_tr) / len(relevant_tr)

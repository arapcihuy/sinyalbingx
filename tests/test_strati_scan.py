import requests
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

def calc_rma(series, length):
    rma = series.copy()
    rma.iloc[length] = rma.iloc[:length].mean()
    for i in range(length + 1, len(rma)):
        rma.iloc[i] = (rma.iloc[i-1] * (length - 1) + series.iloc[i]) / length
    return rma

def calc_atr(df, length=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return calc_rma(tr, length)

def calc_rsi(series, length=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = calc_rma(up, length)
    ema_down = calc_rma(down, length)
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

def calc_supertrend(df, period=15, multiplier=5.0):
    hl2 = (df['high'] + df['low']) / 2
    atr = calc_atr(df, period)
    up = hl2 - (multiplier * atr)
    dn = hl2 + (multiplier * atr)
    st = pd.Series(0.0, index=df.index)
    trend = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df['close'].iloc[i-1] > up.iloc[i-1]:
            up.iloc[i] = max(up.iloc[i], up.iloc[i-1])
        if df['close'].iloc[i-1] < dn.iloc[i-1]:
            dn.iloc[i] = min(dn.iloc[i], dn.iloc[i-1])
        if trend.iloc[i-1] == -1 and df['close'].iloc[i] > dn.iloc[i-1]:
            trend.iloc[i] = 1
        elif trend.iloc[i-1] == 1 and df['close'].iloc[i] < up.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]
        st.iloc[i] = up.iloc[i] if trend.iloc[i] == 1 else dn.iloc[i]
    return st, trend

def run_backtest_fast(df):
    """Run strategy backtest on pre-built dataframe. Returns stats dict."""
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['rsi14'] = calc_rsi(df['close'], 14)
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['atr14'] = calc_atr(df, 14)
    df['st'], df['trend'] = calc_supertrend(df, 15, 5.0)
    
    df['trend_prev'] = df['trend'].shift(1)
    df['buy_cross'] = (df['trend'] == 1) & (df['trend_prev'] == -1)
    df['sell_cross'] = (df['trend'] == -1) & (df['trend_prev'] == 1)
    df['buy_signal'] = df['buy_cross'] & (df['rsi14'] > 50) & (df['close'] > df['ema200']) & (df['volume'] > 0.8 * df['vol_ma20'])
    df['sell_signal'] = df['sell_cross'] & (df['rsi14'] < 50) & (df['close'] < df['ema200']) & (df['volume'] > 0.8 * df['vol_ma20'])
    
    trades = []
    in_position = False
    sl, tp, pos_side = 0, 0, ""
    tp_mult = 2.0
    sl_mult = 1.5
    
    for i, row in df.iterrows():
        if pd.isna(row['ema200']) or pd.isna(row['atr14']):
            continue
        if in_position:
            if pos_side == "LONG":
                if row['low'] <= sl:
                    trades.append(-sl_mult)
                    in_position = False
                elif row['high'] >= tp:
                    trades.append(tp_mult)
                    in_position = False
            elif pos_side == "SHORT":
                if row['high'] >= sl:
                    trades.append(-sl_mult)
                    in_position = False
                elif row['low'] <= tp:
                    trades.append(tp_mult)
                    in_position = False
        if not in_position:
            if row['buy_signal']:
                in_position = True
                pos_side = "LONG"
                sl = row['close'] - (sl_mult * row['atr14'])
                tp = row['close'] + (tp_mult * row['atr14'])
            elif row['sell_signal']:
                in_position = True
                pos_side = "SHORT"
                sl = row['close'] + (sl_mult * row['atr14'])
                tp = row['close'] - (tp_mult * row['atr14'])
    
    if not trades:
        return {"trades": 0, "wr": 0, "net_r": 0, "expectancy": 0}
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    wr = len(wins) / len(trades)
    net_r = sum(trades)
    expectancy = wr * tp_mult - (1 - wr) * sl_mult
    return {"trades": len(trades), "wr": wr, "net_r": net_r, "expectancy": expectancy}

# ── SCAN ALL MAJOR BINANCE FUTURES PAIRS ──
ALL_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "LTCUSDT", "NEARUSDT", "UNIUSDT", "ATOMUSDT",
    "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT",
    "PEPEUSDT", "WIFUSDT", "FETUSDT", "RENDERUSDT", "INJUSDT",
    "TIAUSDT", "SEIUSDT", "ENAUSDT", "WLDUSDT", "TRXUSDT",
]

print("="*70)
print(f"  SCANNING {len(ALL_PAIRS)} PAIRS — SUPERSTRATEGY 1H BACKTEST")
print("="*70)

results = []

for sym in ALL_PAIRS:
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        res = requests.get(url, params={"symbol": sym, "interval": "1h", "limit": 1500}, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < 200:
            print(f"  ⚠️  {sym} — data kurang, skip")
            continue
            
        df = pd.DataFrame(data, columns=["time","open","high","low","close","volume","ct","qav","not","tbb","tbq","i"])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        
        r = run_backtest_fast(df)
        r["symbol"] = sym.replace("USDT", "")
        results.append(r)
        
        status = "🟢" if r["expectancy"] > 0.3 else "🟡" if r["expectancy"] > 0 else "🔴"
        print(f"  {status} {sym.replace('USDT',''):8s} | {r['trades']:3d} trades | WR {r['wr']*100:5.1f}% | Net {r['net_r']:+7.2f}R | Exp {r['expectancy']:+6.3f}R")
        
    except Exception as e:
        print(f"  ❌ {sym} — error: {e}")

# ── SORT & RANK ──
results.sort(key=lambda x: x["expectancy"], reverse=True)

print("\n" + "="*70)
print("  TOP 10 PAIR TERBAIK (DIURUTKAN BY EXPECTANCY)")
print("="*70)
print(f"  {'Rank':<5} {'Pair':<10} {'Trades':>7} {'WR%':>6} {'Net R':>8} {'Expectancy':>11} {'Grade':>6}")
print("  " + "-"*60)

for i, r in enumerate(results[:10]):
    if r["expectancy"] > 0.5:
        grade = "S"
    elif r["expectancy"] > 0.3:
        grade = "A"
    elif r["expectancy"] > 0.1:
        grade = "B"
    elif r["expectancy"] > 0:
        grade = "C"
    else:
        grade = "D"
    
    print(f"  {i+1:<5} {r['symbol']:<10} {r['trades']:>7} {r['wr']*100:>5.1f}% {r['net_r']:>+8.2f}R {r['expectancy']:>+11.3f}R   {grade}")

print("="*70)

# ── REKOMENDASI ──
print("\n  REKOMENDASI AUTO-TRADE:")
good_pairs = [r for r in results if r["expectancy"] > 0.1 and r["trades"] >= 10]
if good_pairs:
    pair_names = [r["symbol"] for r in good_pairs[:5]]
    print(f"  ✅ Pair layak trade: {', '.join(pair_names)}")
    print(f"  Total {len(good_pairs)} pair punya expectancy positif")
else:
    print(f"  ⚠️  Tidak ada pair dengan expectancy > 0.1 dan min 10 trades")

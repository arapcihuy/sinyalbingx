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

def run_backtest(symbol="BTCUSDT", interval="1h"):
    print(f"Fetching data {symbol} {interval}...")
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 1500}
    res = requests.get(url, params=params).json()
    df = pd.DataFrame(res, columns=["time", "open", "high", "low", "close", "volume", "ct", "qav", "not", "tbb", "tbq", "i"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
        
    print("Menghitung Indikator (Pine Script Logic)...")
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['rsi14'] = calc_rsi(df['close'], 14)
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['atr14'] = calc_atr(df, 14)
    df['st'], df['trend'] = calc_supertrend(df, 15, 5.0)
    
    df['trend_prev'] = df['trend'].shift(1)
    df['buy_cross'] = (df['trend'] == 1) & (df['trend_prev'] == -1)
    df['sell_cross'] = (df['trend'] == -1) & (df['trend_prev'] == 1)
    
    # Sinyal Entry sesuai Pine Script
    df['buy_signal'] = df['buy_cross'] & (df['rsi14'] > 50) & (df['close'] > df['ema200']) & (df['volume'] > 0.8 * df['vol_ma20'])
    df['sell_signal'] = df['sell_cross'] & (df['rsi14'] < 50) & (df['close'] < df['ema200']) & (df['volume'] > 0.8 * df['vol_ma20'])
    
    print("Simulasi Trading...")
    trades = []
    in_position = False
    sl, tp, pos_side = 0, 0, ""
    tp_mult = 2.0  # TP1 = 2x ATR
    sl_mult = 1.5  # SL = 1.5x ATR
    
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
                
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    wr = len(wins) / len(trades) if trades else 0
    net_r = sum(trades)
    expectancy = wr * tp_mult - (1 - wr) * sl_mult
    
    print("")
    print("="*40)
    print(f"HASIL BACKTEST {symbol} ({interval})")
    print(f"Total Sinyal : {len(trades)}")
    print(f"Win Rate     : {wr*100:.1f}%")
    print(f"Profit (R)   : {net_r:.2f} R")
    print(f"Expectancy   : {expectancy:.3f} R per trade")
    print(f"Menang       : {len(wins)}")
    print(f"Kalah        : {len(losses)}")
    print("="*40)
    print("")
    
    return {"trades": len(trades), "wr": wr, "net_r": net_r, "expectancy": expectancy}

results = []
results.append(run_backtest("BTCUSDT", "1h"))
results.append(run_backtest("SOLUSDT", "1h"))
results.append(run_backtest("ETHUSDT", "1h"))
results.append(run_backtest("BTCUSDT", "4h"))
results.append(run_backtest("SOLUSDT", "4h"))

print("\n" + "="*50)
print("RINGKASAN SEMUA PAIR")
print("="*50)
for r in results:
    status = "PROFIT" if r["expectancy"] > 0 else "RUGI"
    print(f"{r['trades']} trades | WR {r['wr']*100:.0f}% | Net {r['net_r']:.2f}R | Expectancy {r['expectancy']:.3f}R | {status}")
print("="*50)

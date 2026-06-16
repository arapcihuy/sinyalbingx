import os
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import logging

# ── LOGGING ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def calc_rma(series, length):
    return series.ewm(alpha=1/length, min_periods=length, adjust=False).mean()

def calc_atr(df, length=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
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
    hl2 = (df['High'] + df['Low']) / 2
    atr = calc_atr(df, period)
    up = hl2 - (multiplier * atr)
    dn = hl2 + (multiplier * atr)
    st = pd.Series(0.0, index=df.index)
    trend = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df['Close'].iloc[i-1] > up.iloc[i-1]:
            up.iloc[i] = max(up.iloc[i], up.iloc[i-1])
        if df['Close'].iloc[i-1] < dn.iloc[i-1]:
            dn.iloc[i] = min(dn.iloc[i], dn.iloc[i-1])
        if trend.iloc[i-1] == -1 and df['Close'].iloc[i] > dn.iloc[i-1]:
            trend.iloc[i] = 1
        elif trend.iloc[i-1] == 1 and df['Close'].iloc[i] < up.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]
        st.iloc[i] = up.iloc[i] if trend.iloc[i] == 1 else dn.iloc[i]
    return st, trend


def manual_realtime_check():
    print("🔍 **MEMULAI REAL-TIME SCAN SEKARANG...**\n")
    
    with open("scanned_pairs.json", "r") as f:
        scan_data = json.load(f)
        eligible_pairs = scan_data.get("eligible_pairs", [])

    results = []
    for symbol in eligible_pairs:
        print(f"Checking {symbol}...", end="\r")
        try:
            yf_sym = symbol.replace("-USDT", "-USD")
            df = yf.download(yf_sym, period="5d", interval="15m", progress=False)
            if df.empty or len(df) < 50:
                continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
            df['RSI'] = calc_rsi(df['Close'], 14)
            st, df['Trend'] = calc_supertrend(df, 15, 5.0)
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            # Diagnostic Info
            status = "NEUTRAL"
            reason = ""
            
            if last['Trend'] == 1:
                status = "BULLISH (Supertrend)"
                if not (last['Close'] > last['EMA200']): reason += "Below EMA200; "
                if not (last['RSI'] > 50): reason += f"RSI {last['RSI']:.1f} < 50; "
            else:
                status = "BEARISH (Supertrend)"
                if not (last['Close'] < last['EMA200']): reason += "Above EMA200; "
                if not (last['RSI'] < 50): reason += f"RSI {last['RSI']:.1f} > 50; "
            
            # Check for fresh signal (crossover)
            is_fresh = (last['Trend'] != prev['Trend'])
            
            results.append({
                "Symbol": symbol,
                "Price": round(float(last['Close']), 4),
                "Trend": status,
                "RSI": round(float(last['RSI']), 1),
                "EMA200": round(float(last['EMA200']), 4),
                "Fresh Signal": "YES" if is_fresh else "NO",
                "Verdict": "WAIT" if not is_fresh else ("BUY" if last['Trend'] == 1 else "SELL")
            })
        except Exception as e:
            print(f"Error {symbol}: {e}")

    # Display Table
    df_res = pd.DataFrame(results)
    print(df_res.to_string(index=False))
    
    # Send Summary to Telegram
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        msg = "🔍 **Laporan Scan Real-Time**\n\n"
        for r in results:
            emoji = "🟢" if "BULLISH" in r['Trend'] else "🔴"
            msg += f"{emoji} `{r['Symbol']}` | RSI: {r['RSI']} | Fresh: {r['Fresh Signal']}\n"
        msg += "\n*Kesimpulan*: Belum ada koin yang sedang 'Crossover' (perubahan trend) saat ini."
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        print("\n✅ Ringkasan juga sudah dikirim ke Telegram Anda.")

if __name__ == "__main__":
    manual_realtime_check()

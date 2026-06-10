import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import logging
import warnings
import requests
import time
from datetime import datetime

# Import bingx_client untuk ambil daftar koin real dari bursa
import bingx_client as bx

warnings.filterwarnings('ignore')

# ── LOGGING ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── SETTINGS ──
SCAN_FILE = "scanned_pairs.json"

def get_all_bingx_symbols():
    """Ambil semua pair USDT-M aktif dari BingX."""
    try:
        res = bx._request('GET', '/openApi/swap/v2/quote/contracts')
        if res.get("code") == 0 and res.get("data"):
            # Filter hanya USDT currency dan status aktif
            symbols = [c['symbol'] for c in res['data'] if c.get('currency') == 'USDT' and c.get('status') == 1]
            logger.info(f"Berhasil mengambil {len(symbols)} simbol dari BingX.")
            return symbols
    except Exception as e:
        logger.error(f"Gagal ambil simbol dari BingX: {e}")
    
    # Fallback jika API gagal
    return ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]

# ── STRATEGY CALCULATIONS ──
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

def analyze_symbol(symbol):
    try:
        # Download last 60 days of 1h data
        df = yf.download(symbol, period="60d", interval="1h", progress=False)
        if df.empty or len(df) < 200:
            return None
        
        # Flatten columns if multi-index (yf 0.2.x quirk)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        df['RSI14'] = calc_rsi(df['Close'], 14)
        df['VolMA20'] = df['Volume'].rolling(20).mean()
        df['ATR14'] = calc_atr(df, 14)
        df['ST'], df['Trend'] = calc_supertrend(df, 15, 5.0)
        
        df['TrendPrev'] = df['Trend'].shift(1)
        df['BuyCross'] = (df['Trend'] == 1) & (df['TrendPrev'] == -1)
        df['SellCross'] = (df['Trend'] == -1) & (df['TrendPrev'] == 1)
        
        # Signals
        df['BuySig'] = df['BuyCross'] & (df['RSI14'] > 50) & (df['Close'] > df['EMA200']) & (df['Volume'] > 0.8 * df['VolMA20'])
        df['SellSig'] = df['SellCross'] & (df['RSI14'] < 50) & (df['Close'] < df['EMA200']) & (df['Volume'] > 0.8 * df['VolMA20'])
        
        trades = []
        in_pos = False
        sl, tp, side = 0, 0, ""
        tp_mult, sl_mult = 2.0, 1.5
        
        for i, row in df.iterrows():
            if pd.isna(row['EMA200']) or pd.isna(row['ATR14']): continue
            if in_pos:
                if side == "LONG":
                    if row['Low'] <= sl: trades.append(-sl_mult); in_pos = False
                    elif row['High'] >= tp: trades.append(tp_mult); in_pos = False
                else:
                    if row['High'] >= sl: trades.append(-sl_mult); in_pos = False
                    elif row['Low'] <= tp: trades.append(tp_mult); in_pos = False
            
            if not in_pos:
                if row['BuySig']:
                    in_pos, side = True, "LONG"
                    sl = row['Close'] - (sl_mult * row['ATR14'])
                    tp = row['Close'] + (tp_mult * row['ATR14'])
                elif row['SellSig']:
                    in_pos, side = True, "SHORT"
                    sl = row['Close'] + (sl_mult * row['ATR14'])
                    tp = row['Close'] - (tp_mult * row['ATR14'])
        
        if not trades: return None
        wr = len([t for t in trades if t > 0]) / len(trades)
        exp = wr * tp_mult - (1 - wr) * sl_mult
        
        return {
            "symbol": symbol.replace("-USD", "-USDT"),
            "trades": len(trades),
            "wr": round(wr, 4),
            "expectancy": round(exp, 4)
        }
    except Exception as e:
        logger.error(f"Error {symbol}: {e}")
        return None

def scan_all():
    logger.info("Mulai pemindaian pasar otomatis...")
    bingx_symbols = get_all_bingx_symbols()
    results = []
    
    # Batasi scan ke top koin jika terlalu banyak untuk menghindari limit yfinance
    # Tapi kita akan coba scan semua dengan delay kecil
    for bx_sym in bingx_symbols:
        # Konversi BingX (BTC-USDT) ke Yahoo Finance (BTC-USD)
        yf_sym = bx_sym.replace("-USDT", "-USD")
        
        # Skip jika bukan format standar
        if "-USD" not in yf_sym:
            continue
            
        res = analyze_symbol(yf_sym)
        if res:
            # Kembalikan simbol ke format BingX
            res["symbol"] = bx_sym
            results.append(res)
            logger.info(f"✅ ANALISIS SELESAI: {bx_sym} | Winrate: {res['wr']*100}% | Expectancy: {res['expectancy']}")
        
        # Delay kecil agar tidak kena rate limit Yahoo Finance
        time.sleep(0.5)
    
    # Filter koin yang "layak" (Expectancy positif & jumlah trade cukup)
    eligible = [r for r in results if r["expectancy"] > 0.05 and r["trades"] >= 2]
    eligible.sort(key=lambda x: x["expectancy"], reverse=True)
    
    data = {
        "last_scan": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "eligible_pairs": [r["symbol"] for r in eligible],
        "total_scanned": len(results),
        "total_eligible": len(eligible),
        "top_picks": eligible[:10]
    }
    
    with open(SCAN_FILE, "w") as f:
        json.dump(data, f, indent=4)
    
    # Kirim Laporan ke Telegram
    report = f"🤖 *AUTOMATIC MARKET SCAN COMPLETED*\n"
    report += f"━━━━━━━━━━━━━━━━━━━━━\n"
    report += f"📅 *Waktu:* `{data['last_scan']}`\n"
    report += f"🔍 *Total Scanned:* `{data['total_scanned']}` Pairs\n"
    report += f"🎯 *Eligible Pairs:* `{data['total_eligible']}`\n\n"
    report += f"🔥 *TOP EXPECTANCY (Strategy Tradentix):*\n"
    
    for r in eligible[:5]: # Tampilkan Top 5
        report += f"• `{r['symbol']}` (Exp: {r['expectancy']} | WR: {r['wr']*100}%)\n"
    
    report += f"━━━━━━━━━━━━━━━━━━━━━\n"
    report += f"🚀 *Status:* Bot Standby untuk eksekusi koin di atas."

    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": report, "parse_mode": "Markdown"})
    except Exception as e:
        logger.error(f"Gagal kirim laporan Telegram: {e}")

    logger.info(f"Scan selesai. {len(eligible)} pair masuk daftar trading.")
    return data

if __name__ == "__main__":
    scan_all()

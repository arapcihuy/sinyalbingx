import time
import logging
import os
import json

# Monkey patch requests with curl_cffi to bypass SSL TLSv1.3 issues on Hugging Face
from curl_cffi import requests as crequests
import requests

# Add dummy mount method to curl_cffi Session to prevent crash in libraries using requests adapters
def dummy_mount(self, prefix, adapter):
    pass
crequests.Session.mount = dummy_mount

requests.Session = crequests.Session
requests.get = crequests.get
requests.post = crequests.post
requests.put = crequests.put
requests.delete = crequests.delete
requests.patch = crequests.patch
requests.head = crequests.head
requests.options = crequests.options
requests.request = crequests.request

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

import bingx_client as bx
import order_manager
import settings_manager

load_dotenv()

# ── LOGGING ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("hunter.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ── SETTINGS ──
SCAN_INTERVAL = 900  # Scan tiap 15 menit (900 detik)
ST_PERIOD = 15
ST_MULT = 5.0
RSI_PERIOD = 14
EMA_PERIOD = 200

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

def get_signal(symbol):
    """Cek indikator teknikal untuk symbol tertentu."""
    try:
        # Download data 1 jam (lebih stabil untuk scalping konsisten)
        yf_sym = symbol.replace("-USDT", "-USD")
        df = yf.download(yf_sym, period="5d", interval="15m", progress=False)
        if df.empty or len(df) < 50:
            return None
        
        # Flatten columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['EMA200'] = df['Close'].ewm(span=EMA_PERIOD, adjust=False).mean()
        df['RSI'] = calc_rsi(df['Close'], RSI_PERIOD)
        df['VolMA20'] = df['Volume'].rolling(20).mean()
        df['ATR'] = calc_atr(df, 14)
        _, df['Trend'] = calc_supertrend(df, ST_PERIOD, ST_MULT)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        symbol_bingx = symbol
        
        # BUY SIGNAL
        if last['Trend'] == 1 and prev['Trend'] == -1:
            if last['RSI'] > 50 and last['Close'] > last['EMA200'] and last['Volume'] > 0.8 * last['VolMA20']:
                return {"symbol": symbol_bingx, "action": "BUY", "price": float(last['Close'])}
        
        # SELL SIGNAL
        if last['Trend'] == -1 and prev['Trend'] == 1:
            if last['RSI'] < 50 and last['Close'] < last['EMA200'] and last['Volume'] > 0.8 * last['VolMA20']:
                return {"symbol": symbol_bingx, "action": "SELL", "price": float(last['Close'])}
                
        return None
    except Exception as e:
        logger.error(f"Error checking signal for {symbol}: {e}")
        return None

def send_tg(msg):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

import pair_scanner

# ... (rest of imports)

def hunt():
    """Loop utama pemburu profit."""
    logger.info("🎯 HUNTER MODE ACTIVE: Berburu profit otonom...")
    send_tg("🎯 *HUNTER MODE ACTIVE*\nBot mulai berburu profit secara otonom (Tanpa TradingView).")
    
    last_rescan_time = 0
    RESCAN_INTERVAL = 86400 # 24 Jam
    
    while True:
        try:
            # 1. Cek apakah perlu re-scan pasar (sekali sehari)
            current_time = time.time()
            if current_time - last_rescan_time > RESCAN_INTERVAL:
                logger.info("🔄 Menjalankan re-scan pasar harian...")
                pair_scanner.scan_all()
                last_rescan_time = current_time

            # 1. Load Eligible Pairs & Filter by Quality
            with open("scanned_pairs.json", "r") as f:
                scan_data = json.load(f)
                all_eligible = scan_data.get("top_picks", [])
            
            # Filter hanya yang Winrate > 60% dan Expectancy > 0.1 untuk OPEN OTOMATIS
            high_quality_pairs = [p['symbol'] for p in all_eligible if p.get('wr', 0) >= 0.60 and p.get('expectancy', 0) >= 0.1]
            
            if not high_quality_pairs:
                # Fallback: jika tidak ada yang >60%, ambil top 5 saja
                high_quality_pairs = [p['symbol'] for p in all_eligible[:5]]

            logger.info(f"Scanning {len(high_quality_pairs)} HIGH-QUALITY pairs...")
            
            for symbol in high_quality_pairs:
                # Cek apakah koin ini sudah ada posisi terbuka (biar gak double open)
                if order_manager.is_position_open(symbol):
                    continue

                signal = get_signal(symbol)
                if signal:
                    logger.info(f"🚀 HIGH-WINRATE SIGNAL FOUND: {signal}")
                    # Berikan info winrate koin tersebut ke order_manager jika perlu
                    res = order_manager.execute_signal(signal)
                    
                    status = res.get("status", "unknown")
                    if "success" in status:
                        send_tg(f"✅ *HUNTER EXECUTION*\nPair: `{symbol}`\nAction: `{signal['action']}`\nStatus: `SUCCESS`")
                    else:
                        logger.warning(f"Execution failed for {symbol}: {status}")

            # 2. Sync & Cleanup Positions
            order_manager.monitor_and_sync_positions()
            
            # 3. Heartbeat Notification
            send_tg(f"💓 *HEARTBEAT*: Market scan selesai ({len(eligible_pairs)} pairs). Bot standby memantau market.")
            
            logger.info(f"Scan complete. Sleeping for {SCAN_INTERVAL}s...")
            time.sleep(SCAN_INTERVAL)
            
        except Exception as e:
            logger.error(f"Hunter Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    hunt()

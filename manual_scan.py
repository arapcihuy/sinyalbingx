import os
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from hunter_engine import get_signal, logger, calc_rsi, calc_supertrend

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

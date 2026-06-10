import yfinance as yf
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def calculate_atr(df, length=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = ranges.rolling(window=length).mean()
    return df

def load_historical_data(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    logger.info(f"Loading REAL data {symbol} via yfinance")
    yf_symbol = symbol.replace("USDT", "USD")
    
    try:
        df = yf.download(yf_symbol, period="3mo", interval="1h")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']]
        
        # EMAs
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # ATR
        df = calculate_atr(df, length=14)
        
        df = df.dropna()
        return df.tail(limit)
    except Exception as e:
        logger.error(f"Gagal load data: {e}")
        return pd.DataFrame()

def trend_following_signal(prev_candle, current_candle):
    # Trend Filter: EMA 9 > EMA 21 (Uptrend) / EMA 9 < EMA 21 (Downtrend)
    uptrend = current_candle['EMA_9'] > current_candle['EMA_21']
    downtrend = current_candle['EMA_9'] < current_candle['EMA_21']
    
    # RSI for pullback
    # LONG: Uptrend + RSI pullback (RSI drops to 40-50 and bounces)
    if uptrend and current_candle['RSI'] < 50 and prev_candle['RSI'] >= 50:
        return "LONG"
        
    # SHORT: Downtrend + RSI pullback (RSI jumps to 50-60 and drops)
    if downtrend and current_candle['RSI'] > 50 and prev_candle['RSI'] <= 50:
        return "SHORT"
        
    return None

def run_trend_backtest(df, initial_balance=100.0, risk_per_trade_percent=2.0, leverage=10):
    balance = initial_balance
    trades = []
    open_position = None

    for i in range(1, len(df)):
        current_candle = df.iloc[i]
        prev_candle = df.iloc[i-1]
        
        if not open_position:
            signal = trend_following_signal(prev_candle, current_candle)
            if signal:
                entry_price = current_candle['close']
                atr = current_candle['ATR']
                
                # R:R = 2:1
                # SL = 1.5x ATR, TP = 3.0x ATR
                sl_dist = 1.5 * atr
                tp_dist = 3.0 * atr
                
                if signal == "LONG":
                    tp_price = entry_price + tp_dist
                    sl_price = entry_price - sl_dist
                else:
                    tp_price = entry_price - tp_dist
                    sl_price = entry_price + sl_dist
                    
                risk_amount = balance * (risk_per_trade_percent / 100)
                quantity = risk_amount / (sl_dist * leverage) if sl_dist > 0 else 0

                if quantity > 0:
                    open_position = {
                        "type": signal, "entry": entry_price, "qty": quantity,
                        "tp": tp_price, "sl": sl_price, "time": current_candle.name,
                        "sl_dist": sl_dist
                    }
                    trades.append(open_position.copy())
        else:
            p = open_position
            closed = False
            pnl = 0
            close_reason = ""
            
            # Simulasi PnL realistis dengan Leverage
            pnl_if_sl = - (balance * (risk_per_trade_percent / 100))
            pnl_if_tp = (balance * (risk_per_trade_percent / 100)) * 2 # 2:1 R:R
            
            if p['type'] == "LONG":
                if current_candle['low'] <= p['sl']:
                    pnl = pnl_if_sl
                    closed = True; close_reason = "SL"
                elif current_candle['high'] >= p['tp']:
                    pnl = pnl_if_tp
                    closed = True; close_reason = "TP"
            else:
                if current_candle['high'] >= p['sl']:
                    pnl = pnl_if_sl
                    closed = True; close_reason = "SL"
                elif current_candle['low'] <= p['tp']:
                    pnl = pnl_if_tp
                    closed = True; close_reason = "TP"
                    
            if closed:
                balance += pnl
                trades[-1]['pnl'] = pnl
                trades[-1]['reason'] = close_reason
                open_position = None

    wins = [t for t in trades if t.get('reason') == 'TP']
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    return balance, len(trades), win_rate, trades

if __name__ == "__main__":
    df = load_historical_data("BTC-USDT", limit=720) # Tes 1 bulan (720 jam)
    final_bal, total_trades, wr, trades = run_trend_backtest(df, initial_balance=100.0)
    
    print(f"--- HASIL BACKTEST TREND FOLLOWING (R:R 2:1) ---")
    print(f"Modal Awal:  $100.00")
    print(f"Modal Akhir: ${final_bal:.2f}")
    print(f"Net Profit:  ${final_bal - 100:.2f} ({(final_bal - 100)/100*100:.2f}%)")
    print(f"Total Trade: {total_trades}")
    print(f"Win Rate:    {wr:.1f}%")
    
    if total_trades > 0:
        # Calculate Expectancy
        win_prob = wr / 100
        loss_prob = 1 - win_prob
        # Since R:R is 2:1, risk is 2% and reward is 4%
        avg_win = 4.0 # 4% of $100 approx
        avg_loss = 2.0 # 2% of $100 approx
        expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)
        print(f"Expectancy:  {expectancy:.4f}")
    
    print("-" * 30)
    if trades:
        print("Sampel 3 Trade Terakhir:")
        for t in trades[-3:]:
            print(f"[{t['time'].strftime('%m-%d %H:%M')}] {t['type']} -> {t.get('reason')} ({t.get('pnl',0):+.2f})")

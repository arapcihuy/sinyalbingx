import json
import os

PAPER_TRADES_FILE = "/Users/mac/sinyalbingx/paper_trades.json"

def check_pnl():
    if not os.path.exists(PAPER_TRADES_FILE):
        print("Belum ada data paper trade.")
        return

    try:
        with open(PAPER_TRADES_FILE, "r") as f:
            trades = json.load(f)
    except Exception as e:
        print(f"Error membaca file: {e}")
        return
        
    print("=" * 45)
    print(" 📊 LAPORAN PAPER TRADING (SIMULATOR) 📊")
    print("=" * 45)
    
    total_pnl = 0
    open_count = 0
    closed_count = 0
    
    for t in trades:
        status = t.get("status", "UNKNOWN")
        symbol = t.get("symbol", "UNKNOWN")
        side = t.get("side", "UNKNOWN")
        entry = t.get("entry", 0)
        
        if status == "OPEN_PAPER":
            open_count += 1
            print(f"🟢 [OPEN]   {symbol} | {side} | Entry: {entry}")
        elif status.startswith("CLOSED"):
            closed_count += 1
            pnl = t.get("pnl_usdt", 0)
            total_pnl += pnl
            icon = "✅" if pnl > 0 else "❌"
            print(f"{icon} [{status}] {symbol} | {side} | Entry: {entry} | PnL: ${pnl:.2f}")

    print("-" * 45)
    print(f"Total Trade Tertutup: {closed_count}")
    print(f"Trade Masih Terbuka: {open_count}")
    
    if total_pnl >= 0:
        print(f"💵 Total PnL Bersih: +${total_pnl:.2f} (PROFIT)")
    else:
        print(f"🔻 Total PnL Bersih: -${abs(total_pnl):.2f} (LOSS)")
    print("=" * 45)

if __name__ == "__main__":
    check_pnl()
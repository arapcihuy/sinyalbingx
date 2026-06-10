import os
import sys

# Add directory to path
sys.path.append("/Users/mac/sinyalbingx")

import bingx_client as bx

try:
    print("Fetching balance...")
    balance = bx.get_balance()
    print(f"Equity Balance: {balance:.2f} USDT")
    
    print("\nFetching open positions...")
    positions = bx.get_open_positions()
    if not positions:
        print("No open positions found.")
    else:
        for idx, p in enumerate(positions, 1):
            print(f"{idx}. Symbol: {p.get('symbol')} | Side: {p.get('positionSide')} | Amt: {p.get('positionAmt')} | UnPnL: {p.get('unrealizedProfit')} USDT")
except Exception as e:
    print(f"Error: {e}")

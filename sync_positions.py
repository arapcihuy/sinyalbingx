
import os
import json
import logging
import bingx_client as bx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_active_trades():
    logger.info("Syncing active_trades.json with real BingX positions...")
    
    # Force LIVE mode, ignore env vars (this is an explicit manual sync)
    os.environ["USE_DEMO"] = "false"
    
    # 1. Kosongin / reset active_trades.json jika data lama
    with open("active_trades.json", "w") as f:
        json.dump({}, f, indent=4)
    logger.info("Cleared active_trades.json.")

    # 2. Ambil real-time positions dari BingX
    try:
        positions = bx.get_open_positions()
        if not positions:
            logger.info("No active positions on BingX.")
            return

        logger.info(f"Found {len(positions)} active positions on BingX.")
        
        active_trades = {}
        for p in positions:
            symbol = p.get("symbol")
            amt = float(p.get("positionAmt", 0))
            if amt == 0: continue
            
            side = "LONG" if amt > 0 else "SHORT"
            entry_price = float(p.get("avgPrice", 0))
            
            # Simple reconstruct
            active_trades[symbol] = {
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "qty": abs(amt),
                "status": "OPEN_SYNCED"
            }
            logger.info(f"Synced {symbol} {side} Qty: {abs(amt)}")
            
        with open("active_trades.json", "w") as f:
            json.dump(active_trades, f, indent=4)
        logger.info("active_trades.json updated successfully.")
        
    except Exception as e:
        logger.error(f"Failed to sync: {e}")

if __name__ == "__main__":
    sync_active_trades()

import bingx_client as bx
import order_manager
import time

try:
    symbol = "SOL-USDT"
    print("Opening 10x position...")
    bx.set_leverage(symbol, 10, "LONG")
    
    # Get price
    price = bx.get_current_price(symbol)
    
    # Open market
    res = bx.place_order(symbol, "BUY", "LONG", 0.5, "MARKET")
    print("Open pos:", res)
    
    time.sleep(1)
    
    sl_price = round(price * 0.95, 2)
    tp1_price = round(price * 1.05, 2)
    print(f"Placing TP {tp1_price} SL {sl_price}")
    
    # Try SL
    sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": "SELL", "positionSide": "LONG",
        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": 0.5, "reduceOnly": "true"
    })
    print("SL res:", sl_res)
    
    # Try TP
    tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": "SELL", "positionSide": "LONG",
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp1_price, "quantity": 0.5, "reduceOnly": "true"
    })
    print("TP res:", tp_res)
    
except Exception as e:
    print("Error:", e)
finally:
    # close all
    order_manager._close_all_positions()

import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx

symbol = "BTC-USDT"
pos_side = "LONG"
sl_side = "SELL"
qty = 0.002
sl_price = 59000

print(f"Setting new SL: {sl_price}")
sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": sl_side, "positionSide": pos_side,
    "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty
})
print("SL Response:", sl_res)

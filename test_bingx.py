import bingx_client as bx
import json
res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": "ETH-USDT"})
print(json.dumps(res, indent=2))

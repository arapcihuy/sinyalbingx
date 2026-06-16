import re

def clean_number(num_str):
    if not num_str:
        return 0.0
    if "," in num_str:
        # Format Indonesia: 1.635,25 -> 1635.25
        num_str = num_str.replace(".", "").replace(",", ".")
    try:
        return float(num_str)
    except ValueError:
        return 0.0

def parse_complex_alert(text):
    data = {}
    
    # 1. Parse Action
    # Prioritaskan pencarian pola eksplisit seperti "order buy/sell", "buy entry zone", "sell entry zone"
    action_match = re.search(r"(?:order|zone|side)?\s*(buy|sell|long|short)\s*(?:entry|zone|order|side)?", text, re.IGNORECASE)
    
    # Cek kecocokan ikon emoji atau teks
    if re.search(r"✅\s*Buy|Buy Entry Zone|\b(buy|long)\b", text, re.IGNORECASE):
        data["action"] = "BUY"
    elif re.search(r"❎\s*Sell|Sell Entry Zone|\b(sell|short)\b", text, re.IGNORECASE):
        data["action"] = "SELL"
    elif action_match:
        act = action_match.group(1).upper()
        if act in ["LONG", "BUY"]:
            data["action"] = "BUY"
        elif act in ["SHORT", "SELL"]:
            data["action"] = "SELL"

    # 2. Parse Symbol
    # Cek #ETHUSDT atau Coin: ETHUSDT atau terisi pada ETHUSDT
    symbol_match = re.search(r"#\s*([A-Z0-9]+)", text)
    if not symbol_match:
        symbol_match = re.search(r"Coin\s*:\s*([A-Z0-9]+)", text, re.IGNORECASE)
    if not symbol_match:
        symbol_match = re.search(r"(?:terisi pada|pada)\s+([A-Z0-9.-]+)", text, re.IGNORECASE)
        
    if symbol_match:
        symbol = symbol_match.group(1).upper()
        symbol = re.sub(r'[^A-Z0-9-]', '', symbol)
        symbol = symbol.replace("USDT.P", "USDT")
        if symbol.endswith("USDT") and "-" not in symbol:
            symbol = symbol[:-4] + "-USDT"
        data["symbol"] = symbol

    # 3. Parse Entry Price
    price_match = re.search(r"(?:entry zone|entry|harga|@)\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
    if not price_match:
        # Fallback jika hanya ada format desimal setelah '@'
        price_match = re.search(r"@\s*([0-9.,]+)", text)
        
    if price_match:
        data["price"] = clean_number(price_match.group(1))

    # 4. Parse Stop Loss
    sl_match = re.search(r"(?:stop-loss|stop target|sl)\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
    if sl_match:
        data["sl"] = clean_number(sl_match.group(1))

    # 5. Parse Take Profits
    for i in range(1, 5):
        tp_match = re.search(rf"(?:target {i}|take profit {i}|tp{i})\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
        if tp_match:
            data[f"tp{i}"] = clean_number(tp_match.group(1))

    # Validasi minimal ada action dan symbol
    if "action" in data and "symbol" in data:
        # Isi default 0.0 jika tidak ditemukan
        data["price"] = data.get("price", 0.0)
        data["sl"] = data.get("sl", 0.0)
        data["tp1"] = data.get("tp1", 0.0)
        return data
        
    return None

# Test case dari tangkapan layar user
test_text_buy = """
#ETHUSDT | 15 | leverage 10-20x
✅ Buy Entry Zone: 1677
🎯 Accuracy of this strategy: 77% -

- 📯 - Signal details:
Target 1 : 1692
Target 2 : 1707
Target 3 : 1727
Target 4 : 1768
🎒 Backtest signals Days:14
❌ Stop-Loss: 1616
💡 Happy Trade
By tradelocal*
"""

test_text_sell = """
#ETHUSDT | 15 | leverage 10-20x
❎ Sell Entry Zone: 1639.75
Stop Target: 1686.2329
Take Profit 1: 1628.1292
Take Profit 2: 1616.5085
Take Profit 3: 1601.0142
"""

print("BUY TEST RESULT:", parse_complex_alert(test_text_buy))
print("SELL TEST RESULT:", parse_complex_alert(test_text_sell))

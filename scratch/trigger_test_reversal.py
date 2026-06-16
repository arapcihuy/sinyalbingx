import requests

url = "https://sinyal-bingx-production.up.railway.app/tradingview?secret=REDACTED_WEBHOOK_SECRET"

text_body = """#ETHUSDT | 15 | leverage 10-20x
✅ Buy Entry Zone: 1677
Accuracy of this strategy : 77 % -

- 🤹 - Signal details:
Target 1 : 1692
Target 2 : 1707
Target 3 : 1727
Target 4 : 1768
🚨Backtest signals Days:14
❌Stop-Loss: 1616
💡Happy Trade
By trade local*"""

headers = {"Content-Type": "text/plain"}
response = requests.post(url, data=text_body, headers=headers)
print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.text}")

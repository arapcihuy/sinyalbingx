import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from webhook_server import parse_plain_text_alert

alert_text = """
Buy Entry Zone
BINANCE:ETHUSDT
Buy Entry: 3500
Stop-Loss: 3400.0
Targets: 3550.0, 3600.0, 3650.0, 3700.0
"""

data = parse_plain_text_alert(alert_text)
print("PARSED DATA:")
print(data)

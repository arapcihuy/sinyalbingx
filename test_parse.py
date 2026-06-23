import sys
import os
sys.path.append(os.getcwd())
from webhook_server import parse_plain_text_alert

text_body = """
Buy Entry
Targets
Stop-Loss
BINANCE:ETHUSDT
"""
print(parse_plain_text_alert(text_body))

import unittest
import os
import sys

# Tambahkan project root ke path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webhook_server import clean_number, parse_plain_text_alert
from ai_trading import gemini_filter

class AdditionalSecurityTests(unittest.TestCase):
    def test_clean_number_us_format(self):
        # US Format: 65,230.50 -> 65230.5
        self.assertEqual(clean_number("65,230.50"), 65230.50)
        self.assertEqual(clean_number("1,234.56"), 1234.56)

    def test_clean_number_eu_id_format(self):
        # EU/ID Format: 65.230,50 -> 65230.5
        self.assertEqual(clean_number("65.230,50"), 65230.50)
        self.assertEqual(clean_number("1.635,25"), 1635.25)
        self.assertEqual(clean_number("1.234,56"), 1234.56)

    def test_clean_number_single_separator(self):
        # Hanya koma desimal
        self.assertEqual(clean_number("1234,56"), 1234.56)
        self.assertEqual(clean_number("1,5"), 1.5)
        # Hanya koma ribuan
        self.assertEqual(clean_number("65,000"), 65000.0)
        # Hanya titik desimal
        self.assertEqual(clean_number("65230.50"), 65230.50)
        # Hanya titik ribuan
        self.assertEqual(clean_number("65.000"), 65000.0)

    def test_parse_plain_text_alert_with_secret_in_body(self):
        # Test secret di body teks
        alert_text = (
            "TRADENTIX PRO (UTC, No Filtering, 7): order sell @ 1.635,25 terisi pada ETHUSDT.\n"
            "secret: MySecretKey123\n"
            "Posisi strategi..."
        )
        parsed = parse_plain_text_alert(alert_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("secret"), "MySecretKey123")
        self.assertEqual(parsed.get("price"), 1635.25)
        self.assertEqual(parsed.get("symbol"), "ETH-USDT")
        self.assertEqual(parsed.get("action"), "SELL")

    def test_parse_plain_text_alert_with_password_in_body(self):
        # Test password di body teks
        alert_text = (
            "TRADENTIX PRO (UTC): order buy @ 2.500,00 terisi pada BTCUSDT.\n"
            "password: SecPas555\n"
        )
        parsed = parse_plain_text_alert(alert_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("secret"), "SecPas555")
        self.assertEqual(parsed.get("price"), 2500.00)
        self.assertEqual(parsed.get("symbol"), "BTC-USDT")

    def test_gemini_filter_fallback_offline_kline(self):
        # Simulasikan offline K-Line dengan memanggil validate_signal tanpa mock_klines
        # Kita mock bingx_client._request agar melempar Exception atau mengembalikan error
        import bingx_client
        original_request = bingx_client._request
        try:
            # Paksa request gagal
            bingx_client._request = lambda *args, **kwargs: {"code": 10001, "msg": "API Offline"}
            
            approved, reason, _ = gemini_filter.validate_signal(
                pair="BTC-USDT",
                action="BUY",
                price=60000.0,
                sl=59000.0,
                tp1=61000.0,
                tp2=62000.0,
                mock_klines=None
            )
            self.assertTrue(approved)
            self.assertIn("BingX K-Line API down", reason)
        finally:
            # Kembalikan request asli
            bingx_client._request = original_request

if __name__ == "__main__":
    unittest.main()

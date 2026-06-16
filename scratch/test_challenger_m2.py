import unittest
import os
import sys

# Tambahkan project root ke path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webhook_server import clean_number

class CleanNumberPrecisionTests(unittest.TestCase):
    def test_standard_us_format(self):
        # Format US standar dengan pemisah koma dan titik desimal
        self.assertEqual(clean_number("65,230.50"), 65230.50)
        self.assertEqual(clean_number("1,234.56"), 1234.56)
        self.assertEqual(clean_number("1,234,567.89"), 1234567.89)

    def test_standard_eu_id_format(self):
        # Format EU/ID standar dengan pemisah titik dan koma desimal
        self.assertEqual(clean_number("65.230,50"), 65230.50)
        self.assertEqual(clean_number("1.234,56"), 1234.56)
        self.assertEqual(clean_number("1.234.567,89"), 1234567.89)

    def test_single_separators_decimal(self):
        # Input dengan satu pemisah desimal saja
        self.assertEqual(clean_number("65230.50"), 65230.50)
        self.assertEqual(clean_number("1234,56"), 1234.56)
        self.assertEqual(clean_number("0.05"), 0.05)
        self.assertEqual(clean_number("0,05"), 0.05)

    def test_three_decimal_places_critical(self):
        # KASUS KRITIS: Desimal 3 angka di belakang titik/koma (misal harga koin kecil atau presisi tinggi)
        # Jika "0.012" atau "12.345" dikirimkan:
        # Kita harapkan:
        # - "0.012" -> 0.012
        # - "12.345" -> 12.345
        # Mari kita uji apa yang dihasilkan sistem saat ini.
        print("\n--- PENGUJIAN PRESISI 3 DESIMAL ---")
        for val in ["0.012", "12.345", "0,012", "12,345", "1.234", "1,234", "65.000", "65,000"]:
            res = clean_number(val)
            print(f"Input: {val:<8} | parsed to: {res:<10} | Type: {type(res)}")
            
    def test_extreme_and_invalid_inputs(self):
        # Input kosong, None, atau bukan angka
        self.assertEqual(clean_number(""), 0.0)
        self.assertEqual(clean_number(None), 0.0)
        self.assertEqual(clean_number("abc"), 0.0)
        self.assertEqual(clean_number("12abc.34"), 0.0) # ValueError fallback

if __name__ == "__main__":
    unittest.main()

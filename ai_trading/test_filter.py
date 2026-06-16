import os
import sys
import argparse
import time
from typing import List

# Setup path proyek agar bisa mengimpor gemini_filter secara relatif
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import gemini_filter

def generate_mock_klines(start_price: float, end_price: float, volume: float = 100.0) -> List[dict]:
    """
    Menghasilkan 10 data K-line tiruan (mock) dengan pergerakan harga linier
    untuk mensimulasikan tren naik atau turun.
    """
    now_ms = int(time.time() * 1000)
    klines = []
    price_step = (end_price - start_price) / 9
    for i in range(10):
        o = start_price + i * price_step
        c = start_price + (i + 1) * price_step if i < 9 else end_price
        h = max(o, c) * 1.002
        l = min(o, c) * 0.998
        klines.append({
            "open": f"{o:.2f}",
            "close": f"{c:.2f}",
            "high": f"{h:.2f}",
            "low": f"{l:.2f}",
            "volume": f"{volume:.2f}",
            "time": now_ms - (9 - i) * 15 * 60 * 1000
        })
    return klines

def run_test_case(
    name: str,
    pair: str,
    action: str,
    price: float,
    sl: float,
    tp1: float,
    tp2: float,
    mock_klines: List[dict] = None
):
    print("=" * 80)
    print(f"RUNNING TEST CASE: {name}")
    print(f"Parameters: {action} {pair} @ {price} | SL: {sl} | TP1: {tp1} | TP2: {tp2}")
    if mock_klines:
        start_close = float(mock_klines[0]['close'])
        end_close = float(mock_klines[-1]['close'])
        trend = "NAIK (Bullish)" if end_close > start_close else "TURUN (Bearish)"
        print(f"Trend Lilin Mock: {trend} (Start: {start_close:.2f} -> End: {end_close:.2f})")
    else:
        print("Menggunakan Data Live dari API BingX")
    print("-" * 80)
    
    start_time = time.time()
    approved, reason, suggested_params = gemini_filter.validate_signal(
        pair=pair,
        action=action,
        price=price,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        mock_klines=mock_klines
    )
    elapsed = time.time() - start_time
    
    status_str = "✅ DISETUJUI (APPROVED)" if approved else "❌ DITOLAK (REJECTED)"
    print(f"Status Keputusan : {status_str}")
    print(f"Alasan AI        : {reason}")
    print(f"Saran Parameter  : {suggested_params}")
    print(f"Waktu Eksekusi   : {elapsed:.2f} detik")
    print("=" * 80)
    print()
    return approved

def main():
    parser = argparse.ArgumentParser(description="Script pengujian mandiri filter sinyal trading pintar menggunakan AI (Gemini 1.5 Flash).")
    parser.add_argument("--live", action="store_true", help="Jalankan pengujian tambahan menggunakan K-Line real-time dari API BingX.")
    parser.add_argument("--pair", type=str, default="BTC-USDT", help="Pair untuk pengujian live (default: BTC-USDT).")
    args = parser.parse_args()

    # Periksa API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  Peringatan: GEMINI_API_KEY tidak ditemukan di environment.")
        print("    Pengujian akan berjalan menggunakan mode fallback otomatis (selalu menyetujui sinyal).")
        print("    Silakan set environment variable GEMINI_API_KEY sebelum menjalankan untuk memvalidasi performa AI.")
        print()

    # Kasus 1: BUY saat Tren Bullish (Kecenderungan harga naik)
    # Lilin naik dari 65,000 ke 67,000
    mock_bullish = generate_mock_klines(65000, 67000)
    run_test_case(
        name="Kasus 1: Sinyal BUY/LONG saat Tren Naik (Bullish) - Ekspektasi: APPROVED",
        pair="BTC-USDT",
        action="BUY",
        price=67000.0,
        sl=65500.0,
        tp1=69000.0,
        tp2=70000.0,
        mock_klines=mock_bullish
    )

    # Kasus 2: BUY saat Tren Bearish (Kecenderungan harga turun)
    # Lilin turun dari 67,000 ke 63,000
    mock_bearish = generate_mock_klines(67000, 63000)
    run_test_case(
        name="Kasus 2: Sinyal BUY/LONG saat Tren Turun (Bearish) - Ekspektasi: REJECTED",
        pair="BTC-USDT",
        action="BUY",
        price=63000.0,
        sl=61500.0,
        tp1=65000.0,
        tp2=66000.0,
        mock_klines=mock_bearish
    )

    # Kasus 3: SELL saat Tren Bearish (Kecenderungan harga turun)
    # Lilin turun dari 67,000 ke 63,000
    run_test_case(
        name="Kasus 3: Sinyal SELL/SHORT saat Tren Turun (Bearish) - Ekspektasi: APPROVED",
        pair="BTC-USDT",
        action="SELL",
        price=63000.0,
        sl=64500.0,
        tp1=61000.0,
        tp2=60000.0,
        mock_klines=mock_bearish
    )

    # Kasus 4: Pengujian Live (Dijalankan jika argumen --live disematkan)
    if args.live:
        run_test_case(
            name=f"Kasus 4: Sinyal Live (Mengambil data K-line real-time dari BingX untuk {args.pair})",
            pair=args.pair,
            action="BUY",
            price=67000.0,
            sl=65500.0,
            tp1=69000.0,
            tp2=70000.0,
            mock_klines=None # Memicu pengambilan data live dari BingX
        )

if __name__ == "__main__":
    main()

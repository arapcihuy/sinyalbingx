import sys
import os

# Menambahkan working directory ke path agar modul bisa di-import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import brain_engine

def run_tests():
    print("=" * 60)
    print("🧪 MEMULAI UNIT TEST: LIQUIDATION PROTECTION (LEVERAGE CAPPING)")
    print("=" * 60)

    # MMR untuk BTC & ETH di BingX
    mmr = 0.005

    # -------------------------------------------------------------
    # TEST CASE 1: LONG ETH dengan SL dalam (Risiko Likuidasi Tinggi jika 50x)
    # -------------------------------------------------------------
    balance = 8.0  # Saldo kecil, leverage dasar 5x
    balance_large = 150.0  # Saldo besar, leverage dasar 25x (atau custom ke 50x dalam skenario live)
    
    # Simulasikan kasus ETH-USDT LONG dari user
    # Entry: 1642.55, SL: 1607.23
    entry_price = 1642.55
    sl_price = 1607.23
    side = "LONG"
    symbol = "ETH-USDT"

    # Ganti LEVERAGE_TIERS sementara agar baseline leverage 50x untuk pengujian capping
    # Di settings akun user, leverage dasar bisa mencapai 50x
    brain_engine.LEVERAGE_TIERS = [(0, 999999, 50)]  # Paksa leverage dasar ke 50x
    
    safe_lev_long = brain_engine.get_safe_leverage(balance_large, entry_price, sl_price, side, symbol)
    
    # Hitung harga likuidasi untuk 50x vs Safe Leverage
    liq_50x = entry_price * (1 - 1/50) / (1 - mmr)
    liq_safe = entry_price * (1 - 1/safe_lev_long) / (1 - mmr)
    
    print("\n🟢 TEST CASE 1: LONG ETH-USDT")
    print(f"   Entry: {entry_price} | SL: {sl_price}")
    print(f"   Base Leverage: 50x")
    print(f"   Kalkulasi Safe Leverage: {safe_lev_long}x")
    print(f"   Liquid Price di 50x: {liq_50x:.2f} (SL {sl_price} DI BAWAH LIQUIDASI -> BAHAYA!)")
    print(f"   Liquid Price di {safe_lev_long}x: {liq_safe:.2f} (SL {sl_price} DI ATAS LIQUIDASI -> AMAN!)")
    
    assert safe_lev_long < 50, "Gagal capping leverage LONG!"
    assert sl_price > liq_safe, f"SL {sl_price} masih berada di bawah liquidation price {liq_safe}!"
    print("   ✅ STATUS: SUKSES (Leverage berhasil di-cap)")

    # -------------------------------------------------------------
    # TEST CASE 2: SHORT ETH dengan SL dalam
    # -------------------------------------------------------------
    entry_short = 1600.00
    sl_short = 1635.00
    side_short = "SHORT"
    
    safe_lev_short = brain_engine.get_safe_leverage(balance_large, entry_short, sl_short, side_short, symbol)
    
    liq_50x_short = entry_short * (1 + 1/50) / (1 + mmr)
    liq_safe_short = entry_short * (1 + 1/safe_lev_short) / (1 + mmr)
    
    print("\n🟢 TEST CASE 2: SHORT ETH-USDT")
    print(f"   Entry: {entry_short} | SL: {sl_short}")
    print(f"   Base Leverage: 50x")
    print(f"   Kalkulasi Safe Leverage: {safe_lev_short}x")
    print(f"   Liquid Price di 50x: {liq_50x_short:.2f} (SL {sl_short} DI ATAS LIQUIDASI -> BAHAYA!)")
    print(f"   Liquid Price di {safe_lev_short}x: {liq_safe_short:.2f} (SL {sl_short} DI BAWAH LIQUIDASI -> AMAN!)")
    
    assert safe_lev_short < 50, "Gagal capping leverage SHORT!"
    assert sl_short < liq_safe_short, f"SL {sl_short} masih berada di atas liquidation price {liq_safe_short}!"
    print("   ✅ STATUS: SUKSES (Leverage berhasil di-cap)")

    # -------------------------------------------------------------
    # TEST CASE 3: Kasus Tanpa SL (Kembali ke Base Leverage)
    # -------------------------------------------------------------
    safe_lev_no_sl = brain_engine.get_safe_leverage(balance_large, entry_price, 0.0, side, symbol)
    print("\n🟢 TEST CASE 3: TANPA SL")
    print(f"   Base Leverage: 50x")
    print(f"   Kalkulasi Safe Leverage: {safe_lev_no_sl}x")
    assert safe_lev_no_sl == 50, "Harusnya kembali ke base leverage jika tidak ada SL!"
    print("   ✅ STATUS: SUKSES (Kembali ke default)")

    print("\n" + "=" * 60)
    print("🎉 SEMUA TEST CASE LIQUIDATION PROTECTION BERHASIL LULUS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()

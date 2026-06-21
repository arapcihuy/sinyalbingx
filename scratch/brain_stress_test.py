import sys
import os
sys.path.append(os.getcwd())
import brain_engine as brain
import state_manager

# 1. Pastikan Mode Aman (Pure Simulation)
state_manager.demote_to_safe_mode("STRESS_TESTING")

def run_stress():
    print("═══ BRAIN ENGINE STRESS TEST (SIMULATION ONLY) ═══")
    scenarios = [
        {"symbol": "AVAX-USDT", "entry": 7.0, "side": "LONG", "atr": 1.5, "desc": "Extreme Volatility (High ATR)"},
        {"symbol": "AVAX-USDT", "entry": 7.0, "side": "LONG", "atr": 0.01, "desc": "Zero Volatility (Low ATR)"},
        {"symbol": "AVAX-USDT", "entry": 100.0, "side": "SHORT", "atr": 2.0, "desc": "Standard Short"},
        {"symbol": "SOL-USDT", "entry": 200.0, "side": "LONG", "atr": 5.0, "desc": "High Price Token"},
    ]

    for s in scenarios:
        print(f"\n🔥 SCENARIO: {s['desc']}")
        # Simulasi Saldo $100
        balance = 100.0
        
        # Hitung Leverage Aman
        plan_raw = brain.calculate_tp_sl(s['entry'], s['side'], s['atr'], s['symbol'], leverage=25)
        safe_lev = brain.get_safe_leverage(balance, s['entry'], plan_raw['sl'], s['side'], s['symbol'])
        
        # Hitung Plan Final
        plan = brain.calculate_tp_sl(s['entry'], s['side'], s['atr'], s['symbol'], leverage=safe_lev)
        
        # Validasi IQ
        liq = brain.estimate_liquidation_price(s['entry'], safe_lev, s['side'])
        dist_sl_liq = abs(plan['sl'] - liq) / s['entry'] * 100
        tp_profit = abs(plan['tp2'] - s['entry']) / s['entry'] * 100

        print(f"   - Result: SL {plan['sl']} | TP2 {plan['tp2']} | Lev {safe_lev}x")
        print(f"   - Liq Price: {liq:.3f}")
        print(f"   - SL-to-Liq Safety: {dist_sl_liq:.2f}% distance")
        print(f"   - Max Profit TP2: {tp_profit:.2f}% (Cap 5% check: {'PASS' if tp_profit <= 5.1 else 'FAIL'})")
        
        if s['side'] == "LONG":
            assert plan['sl'] > liq, "CRITICAL: SL below Liquidation!"
        else:
            assert plan['sl'] < liq, "CRITICAL: SL above Liquidation!"

if __name__ == "__main__":
    run_stress()
    print("\n✅ ALL BRAIN STRESS SCENARIOS PASSED. NO REAL ORDERS PLACED.")

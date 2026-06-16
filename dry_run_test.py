import sys
import os
import json
import threading

# Add current dir to path
sys.path.append(os.getcwd())

def test_atomic_persistence():
    print("🧪 Testing Atomic Persistence...")
    from order_manager import _atomic_write_json
    test_file = "test_atomic.json"
    data = {"status": "ok", "value": 123}
    _atomic_write_json(test_file, data)
    
    with open(test_file, "r") as f:
        read_back = json.load(f)
    
    assert read_back["status"] == "ok"
    os.remove(test_file)
    print("✅ Atomic Persistence: PASSED")

def test_sizing_logic():
    print("🧪 Testing Sizing Logic (BTC & DOGE)...")
    import brain_engine
    
    # BTC Test
    btc_qty = brain_engine.calculate_position_size(100.0, 60000.0, 58000.0, 1.0, "BTC-USDT", 20)
    print(f"   BTC Qty: {btc_qty} (Target budget $1, Price diff $2000)")
    assert btc_qty > 0
    
    # DOGE Test (High precision/small price)
    doge_qty = brain_engine.calculate_position_size(100.0, 0.15, 0.14, 1.0, "DOGE-USDT", 20)
    print(f"   DOGE Qty: {doge_qty} (Target budget $1, Price diff $0.01)")
    assert doge_qty > 0
    print("✅ Sizing Logic: PASSED")

def test_rlock_safety():
    print("🧪 Testing RLock Re-entrancy...")
    from order_manager import state_lock
    with state_lock:
        with state_lock: # Should not deadlock
            pass
    print("✅ RLock Safety: PASSED")

if __name__ == "__main__":
    try:
        test_atomic_persistence()
        test_sizing_logic()
        test_rlock_safety()
        print("\n🚀 ALL SIMULATIONS PASSED")
    except Exception as e:
        print(f"\n❌ SIMULATION FAILED: {e}")
        sys.exit(1)

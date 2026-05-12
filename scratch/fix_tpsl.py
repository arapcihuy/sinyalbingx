import order_manager
import bingx_client as bx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FixTP SL")

def fix_active_position(symbol="ETH-USDT"):
    try:
        # 1. Ambil posisi yang sedang open
        positions = bx.get_open_positions(symbol)
        if not positions:
            print(f"❌ Tidak ada posisi open untuk {symbol}")
            return

        pos = positions[0]
        side = pos["positionSide"]
        amt = abs(float(pos["positionAmt"]))
        
        print(f"🔍 Menemukan posisi {side} {symbol} sebanyak {amt} koin.")

        # 2. Ambil sinyal terakhir dari file
        latest = order_manager.load_latest_signals()
        if symbol not in latest:
            print(f"❌ Tidak ada data sinyal terakhir untuk {symbol} di file.")
            return
        
        signal = latest[symbol]
        sl_price = float(signal.get("sl", 0))
        tp_price = float(signal.get("tp1", 0))
        
        if sl_price == 0 or tp_price == 0:
            print(f"❌ Data SL/TP di sinyal terakhir tidak valid.")
            return

        print(f"🎯 Mencoba pasang SL: {sl_price} dan TP: {tp_price}")

        # 3. Pasang TP/SL
        res = order_manager.apply_manual_tpsl(symbol, tp_price, sl_price)
        print(f"✅ BERHASIL: {res}")

    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    fix_active_position("ETH-USDT")

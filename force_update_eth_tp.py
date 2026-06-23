import time
import json
import os
import sys

sys.path.append(os.getcwd())
import bingx_client as bx

def force_update_tp():
    symbol = "ETH-USDT"
    target_tps = [1786.0, 1804.0, 1829.0, 1878.0]
    weights = [0.35, 0.30, 0.20, 0.15]
    
    print("⏳ Menunggu API BingX unblocked...")
    while True:
        try:
            pos_res = bx.get_open_positions(symbol)
            # Jika berhasil (tidak lempar exception), keluar loop
            print("🟢 API unblocked! Memulai force update...")
            break
        except Exception as e:
            err_msg = str(e)
            if "100410" in err_msg:
                # Cari sisa waktu unblock
                import re
                unblock_ts = re.search(r"unblocked after (\d+)", err_msg)
                if unblock_ts:
                    sisa = (int(unblock_ts.group(1)) / 1000) - time.time()
                    print(f"⏳ Masih limit. Sisa waktu: {int(sisa)} detik...")
                else:
                    print("⏳ Masih limit...")
            else:
                print(f"⚠️ Error lain: {err_msg}")
        time.sleep(10)

    # 1. Ambil info posisi
    try:
        positions = bx.get_open_positions(symbol)
    except Exception as e:
        print(f"❌ Gagal ambil posisi setelah unblock: {e}")
        return
        
    if not positions:
        print("❌ Tidak ada posisi ETH aktif di bursa.")
        return
        
    pos = positions[0]
    qty = abs(float(pos["positionAmt"]))
    pos_side = pos["positionSide"]
    
    print(f"📦 Posisi aktif: {pos_side} | Qty: {qty}")

    # 2. Batalkan semua order TP lama
    try:
        orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
        open_orders = orders_res.get("data", {}).get("orders", []) if isinstance(orders_res.get("data"), dict) else []
    except Exception as e:
        print(f"❌ Gagal fetch open orders: {e}")
        open_orders = []
    
    cancel_count = 0
    for o in open_orders:
        if "TAKE_PROFIT" in o.get("type", ""):
            try:
                bx._request("DELETE", "/openApi/swap/v2/trade/order", {"symbol": symbol, "orderId": o["orderId"]})
                print(f"🗑️ Batal TP lama: {o['orderId']} @ {o.get('stopPrice')}")
                cancel_count += 1
            except Exception as e:
                print(f"❌ Gagal batal TP {o['orderId']}: {e}")
            
    if cancel_count == 0:
        print("ℹ️ Tidak ditemukan order TP lama di bursa.")

    # 3. Pasang order TP baru
    print("🎯 Memasang TP baru sesuai TV...")
    for i, tp_price in enumerate(target_tps):
        tp_qty = round(qty * weights[i], 4)
        if tp_qty > 0:
            try:
                res = bx._request("POST", "/openApi/swap/v2/trade/order", {
                    "symbol": symbol, 
                    "side": "BUY" if pos_side == "SHORT" else "SELL",
                    "positionSide": pos_side, 
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": tp_price, 
                    "quantity": tp_qty
                })
                print(f"✅ TP{i+1} dipasang @ {tp_price} (Qty: {tp_qty}) | Res: {res.get('code')}")
            except Exception as e:
                print(f"❌ Gagal pasang TP{i+1}: {e}")

    # 4. Sinkronisasi state lokal
    try:
        with open('active_trades.json', 'r+') as f:
            d = json.load(f)
            if symbol in d:
                d[symbol]["tp_notified"] = {}
                d[symbol]["tp1"] = target_tps[0]
                d[symbol]["tp2"] = target_tps[1]
                d[symbol]["tp3"] = target_tps[2]
                d[symbol]["tp4"] = target_tps[3]
                f.seek(0)
                json.dump(d, f, indent=4)
                f.truncate()
                print("💾 State active_trades.json diselaraskan.")
    except Exception as e:
        print(f"❌ Gagal update active_trades.json: {e}")

if __name__ == "__main__":
    force_update_tp()

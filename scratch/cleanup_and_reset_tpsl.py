import os
import sys
import json
import logging

# Tambahkan root path proyek agar bisa mengimpor modul lokal
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import bingx_client as bx
import order_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup_and_reset_tpsl")

def main():
    try:
        import state_manager
        env_paper = os.getenv("PAPER_MODE", "false").lower() == "true"
        env_demo = os.getenv("USE_DEMO", "false").lower() == "true"
        state_manager.set_mode(env_paper, env_demo, "RUNNING_CLEANUP")

        active_trades = order_manager.load_active_trades()
        if not active_trades:
            logger.info("📭 Tidak ada data transaksi aktif di active_trades.json.")
            return

        logger.info(f"💾 Ditemukan {len(active_trades)} koin aktif di state lokal: {list(active_trades.keys())}")

        for symbol, trade in active_trades.items():
            logger.info(f"🧹 Memulai pembersihan & reset untuk {symbol}...")
            
            # 1. Batalkan semua order terbuka di bursa untuk koin ini
            try:
                orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                if orders_res.get("code") == 0:
                    open_orders_raw = orders_res.get("data", [])
                    if isinstance(open_orders_raw, dict):
                        open_orders = open_orders_raw.get("orders", [])
                    else:
                        open_orders = open_orders_raw if isinstance(open_orders_raw, list) else []
                    
                    canceled_count = 0
                    for order in open_orders:
                        order_id = order.get("orderId")
                        if order_id:
                            bx.cancel_order(symbol, order_id)
                            canceled_count += 1
                    logger.info(f"✅ Berhasil membatalkan {canceled_count} order terbuka lama untuk {symbol}.")
                else:
                    logger.error(f"❌ Gagal mengambil order terbuka dari BingX untuk {symbol}: {orders_res}")
                    continue
            except Exception as e:
                logger.error(f"❌ Error saat membatalkan order lama untuk {symbol}: {e}")
                continue

            # 2. Ambil informasi posisi riil di bursa
            try:
                positions = bx.get_open_positions(symbol)
                if not positions:
                    logger.warning(f"⚠️ Tidak ada posisi aktif di bursa untuk {symbol}. Melewati pemasangan TP/SL.")
                    continue
                pos = positions[0]
                pos_side = pos["positionSide"]
                qty = abs(float(pos["positionAmt"]))
                logger.info(f"🪙 Posisi aktif di bursa: {symbol} {pos_side} | Ukuran: {qty}")
            except Exception as e:
                logger.error(f"❌ Gagal mengambil data posisi aktif untuk {symbol}: {e}")
                continue

            # 3. Tentukan level TP/SL dari state lokal
            sl_price = float(trade.get("sl", 0))
            tp1_price = float(trade.get("tp1", 0))
            tp2_price = float(trade.get("tp2", 0))
            qtys = trade.get("qtys", [qty/2, qty/2, 0.0, 0.0])
            
            sl_side = "SELL" if pos_side == "LONG" else "BUY"

            # 4. Pasang Stop Loss tunggal di bursa
            if sl_price > 0:
                try:
                    res_sl = bx._request("POST", "/openApi/swap/v2/trade/order", {
                        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": qty
                    })
                    if res_sl.get("code") == 0:
                        logger.info(f"🛡️ Berhasil memasang SL Tunggal di harga {sl_price} (Qty: {qty})")
                    else:
                        logger.error(f"❌ Gagal memasang SL di bursa: {res_sl}")
                except Exception as e:
                    logger.error(f"❌ Error saat memasang SL: {e}")

            # 5. Pasang Take Profit di bursa
            tps_to_place = []
            if tp1_price > 0:
                tps_to_place.append((tp1_price, qtys[0]))
            if tp2_price > 0:
                tps_to_place.append((tp2_price, qtys[1]))

            for tp_price, tp_qty in tps_to_place:
                if tp_price > 0 and tp_qty > 0:
                    try:
                        res_tp = bx._request("POST", "/openApi/swap/v2/trade/order", {
                            "symbol": symbol, "side": sl_side, "positionSide": pos_side,
                            "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": tp_qty
                        })
                        if res_tp.get("code") == 0:
                            logger.info(f"🎯 Berhasil memasang TP di harga {tp_price} (Qty: {tp_qty})")
                        else:
                            logger.error(f"❌ Gagal memasang TP di bursa: {res_tp}")
                    except Exception as e:
                        logger.error(f"❌ Error saat memasang TP: {e}")

        logger.info("✨ Proses pembersihan & penyetelan ulang TP/SL selesai.")
    except Exception as e:
        logger.error(f"❌ Gagal menjalankan script: {e}")

if __name__ == "__main__":
    main()

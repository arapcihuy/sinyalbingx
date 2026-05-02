import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import order_manager

load_dotenv()

# ── Setup logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", 5000))
HOST = os.getenv("HOST", "0.0.0.0")


# ─────────────────────────────────────────────
#  HEALTH CHECK
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "time": datetime.now().isoformat(),
        "message": "BingX Webhook Bot aktif ✅"
    })


# ─────────────────────────────────────────────
#  WEBHOOK ENDPOINT
# ─────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    logger.info("=" * 50)
    logger.info("📡 Sinyal masuk dari TradingView")

    # ── Parse payload ──
    try:
        if request.is_json:
            data = request.get_json()
        else:
            # TradingView kadang kirim sebagai text biasa
            raw = request.data.decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        logger.error(f"Gagal parse payload: {e}")
        return jsonify({"error": "Payload tidak valid"}), 400

    logger.info(f"Payload diterima: {json.dumps(data, indent=2)}")

    # ── Verifikasi secret ──
    if WEBHOOK_SECRET:
        received_secret = data.get("secret", "")
        if received_secret != WEBHOOK_SECRET:
            logger.warning("❌ Secret tidak cocok! Request ditolak.")
            return jsonify({"error": "Unauthorized"}), 401

    # ── Validasi field wajib ──
    action = data.get("action", "").upper()
    if action not in ["BUY", "SELL", "CLOSE"]:
        logger.warning(f"Action tidak dikenal: {action}")
        return jsonify({"error": f"Action tidak valid: {action}"}), 400

    # ── Proses CLOSE ──
    if action == "CLOSE":
        try:
            symbol = data.get("symbol", os.getenv("SYMBOL", "BTC-USDT"))
            result = _close_position(symbol, data)
            return jsonify({"status": "success", "action": "CLOSE", "result": result}), 200
        except Exception as e:
            logger.error(f"Gagal close: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Proses BUY / SELL ──
    try:
        result = order_manager.execute_signal(data)
        logger.info(f"✅ Order berhasil: {result}")
        return jsonify({
            "status": "success",
            "action": action,
            "result": {
                "symbol": result["symbol"],
                "quantity": result["quantity"],
                "entry": result["entry_price"],
                "tp": result["tp_price"],
                "sl": result["sl_price"],
            }
        }), 200

    except Exception as e:
        logger.error(f"❌ Error saat eksekusi order: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _close_position(symbol: str, data: dict) -> dict:
    """Tutup semua posisi aktif untuk symbol."""
    import bingx_client as bx

    positions = bx.get_open_positions(symbol)
    if not positions:
        return {"message": "Tidak ada posisi aktif"}

    closed = []
    for pos in positions:
        pos_side = pos.get("positionSide", "LONG")
        qty = abs(float(pos.get("positionAmt", 0)))

        if qty == 0:
            continue

        close_side = "SELL" if pos_side == "LONG" else "BUY"
        result = bx.place_order(
            symbol=symbol,
            side=close_side,
            position_side=pos_side,
            quantity=qty,
            order_type="MARKET",
        )
        bx.cancel_all_orders(symbol)  # batalkan TP/SL sisa
        closed.append(result)
        logger.info(f"Posisi {pos_side} ditutup: {result}")

    return {"closed_positions": closed}


# ─────────────────────────────────────────────
#  JALANKAN SERVER
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"🚀 BingX Webhook Bot berjalan di http://{HOST}:{PORT}")
    logger.info(f"   Endpoint webhook: http://{HOST}:{PORT}/webhook")
    app.run(host=HOST, port=PORT, debug=False)

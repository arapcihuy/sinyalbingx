import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

# Tambahkan project root ke path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bingx_client

def run_accuracy_check():
    print("================================================================================")
    print("🔍 MEMULAI EVALUASI AKURASI AI FILTER SECARA HISTORIS (BACKTEST 24 JAM TERAKHIR)")
    print("================================================================================")
    
    # 1. Ambil 100 K-Line 15m terakhir untuk BTC-USDT dari bursa BingX
    pair = "BTC-USDT"
    print(f"📡 Mengambil data 100 K-Line 15m terakhir untuk {pair}...")
    try:
        res = bingx_client._request(
            'GET',
            '/openApi/swap/v3/quote/klines',
            {'symbol': pair, 'interval': '15m', 'limit': 100}
        )
        if not (isinstance(res, dict) and res.get("code") == 0):
            print(f"❌ Gagal mengambil K-Line dari BingX: {res}")
            return
        klines = res.get("data", [])
        print(f"✅ Berhasil mengambil {len(klines)} K-Line dari bursa.")
    except Exception as e:
        print(f"❌ Exception saat memanggil BingX API: {e}")
        return

    if len(klines) < 80:
        print("⚠️ Data lilin tidak mencukupi untuk simulasi backtest.")
        return

    # Urutkan secara kronologis (terlama ke terbaru)
    klines = sorted(klines, key=lambda x: int(x.get("time", 0)))

    # 2. Definisikan 5 titik simulasi indeks (misal: 25, 38, 51, 64, 77)
    test_indices = [25, 38, 51, 64, 77]
    results = []

    # Local 9Router configuration
    ninerouter_url = "http://127.0.0.1:20128/v1/chat/completions"
    
    print("\n⏳ Mengevaluasi 5 skenario dengan AI Filter (local 9Router)...")
    
    for run_idx, idx in enumerate(test_indices):
        # Lilin input untuk AI (10 lilin sebelum indeks target)
        input_klines = klines[idx-10:idx]
        
        # Sinyal info
        entry_price = float(input_klines[-1]["close"])
        timestamp_ms = int(input_klines[-1]["time"])
        signal_time_str = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime('%H:%M:%S UTC')
        
        # Simulasikan parameter BUY
        action = "BUY"
        sl = entry_price * 0.985    # SL 1.5%
        tp1 = entry_price * 1.015   # TP1 1.5%
        tp2 = entry_price * 1.03    # TP2 3.0%
        
        # Format lilin input ke string prompt
        formatted_klines_list = []
        for c_idx, k in enumerate(input_klines):
            k_time = int(k.get("time", 0))
            utc_time = datetime.fromtimestamp(k_time / 1000, tz=timezone.utc).strftime('%H:%M:%S UTC')
            formatted_klines_list.append(
                f"- {utc_time} | Open: {k.get('open')} | High: {k.get('high')} | Low: {k.get('low')} | Close: {k.get('close')} | Vol: {k.get('volume')}"
            )
        klines_formatted = "\n".join(formatted_klines_list)

        # Prompt AI
        prompt = f"""
Anda adalah sistem filter AI perdagangan kuantitatif. Evaluasi kelayakan sinyal perdagangan BUY berdasarkan tren lilin berikut.

Detail Sinyal:
- Pair: {pair}
- Aksi: {action}
- Harga Entry: {entry_price}
- Stop Loss: {sl:.2f}
- Take Profit 1: {tp1:.2f}
- Take Profit 2: {tp2:.2f}

Data K-Line 15-Menit Terakhir:
{klines_formatted}

Kembalikan respon JSON mentah dengan kunci:
- 'approved': boolean (true jika mendukung BUY, false jika trend bearish/tidak mendukung)
- 'reason': string (alasan ringkas dalam bahasa Indonesia)
"""

        # Kirim ke local 9Router menggunakan model combo 'gemini'
        ai_approved = True
        ai_reason = "Default/Error fallback"
        
        try:
            payload = {
                "model": "gemini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "stream": False
            }
            resp = requests.post(ninerouter_url, json=payload, timeout=10)
            if resp.status_code == 200:
                res_data = resp.json()
                content = res_data["choices"][0]["message"]["content"].strip()
                # Clean markdown wrapper
                if content.startswith("```"):
                    content = content.strip("`").strip()
                    if content.startswith("json"):
                        content = content[4:].strip()
                decision = json.loads(content)
                ai_approved = bool(decision.get("approved", True))
                ai_reason = str(decision.get("reason", ""))
        except Exception as err:
            ai_reason = f"Error calling 9Router: {err}"

        # 3. Lacak K-Line SETELAH indeks target untuk menentukan Ground Truth (hasil riil perdagangan)
        # Evaluasi hingga 20 lilin ke depan (5 jam)
        future_klines = klines[idx:idx+20]
        ground_truth = "NEUTRAL"
        actual_profit_pct = 0.0
        
        for f_k in future_klines:
            f_low = float(f_k["low"])
            f_high = float(f_k["high"])
            f_close = float(f_k["close"])
            
            # Periksa apakah menyentuh SL dulu atau TP1 dulu
            if f_low <= sl:
                ground_truth = "LOSS"
                actual_profit_pct = -1.5
                break
            elif f_high >= tp1:
                ground_truth = "PROFIT"
                actual_profit_pct = 1.5
                # Cek jika sempat sentuh TP2
                if f_high >= tp2:
                    actual_profit_pct = 3.0
                break
        
        # Jika tidak menyentuh keduanya, tentukan berdasarkan close lilin terakhir
        if ground_truth == "NEUTRAL" and future_klines:
            last_close = float(future_klines[-1]["close"])
            actual_profit_pct = ((last_close - entry_price) / entry_price) * 100
            ground_truth = "PROFIT" if last_close > entry_price else "LOSS"

        # Tentukan hasil keputusan AI vs Ground Truth
        # True Positive (TP): AI Approved, Real Profit
        # True Negative (TN): AI Rejected, Real Loss (AI menyelamatkan kita!)
        # False Positive (FP): AI Approved, Real Loss (AI salah menyetujui)
        # False Negative (FN): AI Rejected, Real Profit (AI salah menolak)
        classification = ""
        if ai_approved and ground_truth == "PROFIT":
            classification = "True Positive (TP)"
        elif not ai_approved and ground_truth == "LOSS":
            classification = "True Negative (TN) [PROTECTED]"
        elif ai_approved and ground_truth == "LOSS":
            classification = "False Positive (FP)"
        elif not ai_approved and ground_truth == "PROFIT":
            classification = "False Negative (FN)"

        results.append({
            "run": run_idx + 1,
            "time": signal_time_str,
            "entry": entry_price,
            "ai_approved": ai_approved,
            "ai_reason": ai_reason,
            "ground_truth": ground_truth,
            "profit_pct": actual_profit_pct,
            "classification": classification
        })
        print(f" Skenario {run_idx+1} | Waktu: {signal_time_str} | Entry: {entry_price:.2f} | AI: {'🟢 SETUJU' if ai_approved else '🔴 TOLAK'} | Hasil Ril: {ground_truth} ({actual_profit_pct:+.2f}%) | Klasifikasi: {classification}")
        time.sleep(1) # Jeda sopan

    # 4. Ringkasan Statistik
    tp = sum(1 for r in results if r["classification"].startswith("True Positive"))
    tn = sum(1 for r in results if r["classification"].startswith("True Negative"))
    fp = sum(1 for r in results if r["classification"].startswith("False Positive"))
    fn = sum(1 for r in results if r["classification"].startswith("False Negative"))

    total = len(results)
    accuracy = ((tp + tn) / total) * 100 if total > 0 else 0.0
    
    # Perhitungan Win Rate
    # Tanpa AI: (Semua sinyal riil yang profit) / Total
    real_profits = sum(1 for r in results if r["ground_truth"] == "PROFIT")
    winrate_without_ai = (real_profits / total) * 100 if total > 0 else 0.0
    
    # Dengan AI: (Sinyal disetujui AI yang profit) / Total disetujui AI
    ai_approved_total = sum(1 for r in results if r["ai_approved"])
    ai_approved_profits = sum(1 for r in results if r["ai_approved"] and r["ground_truth"] == "PROFIT")
    winrate_with_ai = (ai_approved_profits / ai_approved_total) * 100 if ai_approved_total > 0 else 100.0

    print("\n" + "=" * 80)
    print("📊 LAPORAN RINGKAS EVALUASI AKURASI AI FILTER")
    print("=" * 80)
    print(f"📈 Akurasi AI (Mengambil Keputusan Benar): {accuracy:.1f}% ({tp+tn}/{total} Skenario)")
    print(f"🛡️ Total Kerugian yang Dihindari (True Negative): {tn} Transaksi")
    print(f"🟢 Win Rate Sinyal TANPA AI Filter           : {winrate_without_ai:.1f}%")
    print(f"🧠 Win Rate Sinyal DENGAN AI Filter          : {winrate_with_ai:.1f}%")
    print("-" * 80)
    print("Rincian Klasifikasi:")
    print(f" - [TP] Setuju & Profit: {tp}")
    print(f" - [TN] Tolak & Loss (Aman): {tn}")
    print(f" - [FP] Setuju & Loss: {fp}")
    print(f" - [FN] Tolak & Profit: {fn}")
    print("================================================================================")

if __name__ == "__main__":
    run_accuracy_check()

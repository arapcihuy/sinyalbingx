import subprocess
import time
import requests
import concurrent.futures
import os
import sys

def run_stress_test():
    print("=== MEMULAI VERIFIKASI STABILITAS SERVER & CONCURRENCY ===")
    
    # Port untuk server uji
    port = 9180
    
    # Siapkan environment variables untuk server
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["REDACTED_WEBHOOK_SECRET"] = "TestSecretKey123"
    env["PAPER_MODE"] = "true"
    env["ENABLE_MONITOR"] = "false"
    env["TELEGRAM_BOT_TOKEN"] = "" # Nonaktifkan telegram polling
    
    # Mulai webhook_server.py sebagai subprocess
    print("Memulai webhook_server.py di localhost:8099...")
    server_process = subprocess.Popen(
        [sys.executable, "webhook_server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Tunggu beberapa detik agar server binding ke port
    time.sleep(3)
    
    # Pastikan server berjalan
    if server_process.poll() is not None:
        print("Gagal memulai server. Output error:")
        stdout, stderr = server_process.communicate()
        print(stderr)
        return
        
    print("Server berhasil berjalan. Mulai mengirim request uji...")
    
    try:
        # 1. Tes Endpoint Health
        res = requests.get(f"http://127.0.0.1:{port}/health", timeout=3)
        print(f"Health check status: {res.status_code}, content: {res.text}")
        assert res.status_code == 200 and res.text == "OK", "Health check gagal!"
        
        # 2. Kirim request valid untuk BTC-USDT (Cached symbol)
        # Sinyal ini tidak akan memicu API call kontrak karena BTC-USDT ada di cache
        payload_btc = {
            "secret": "TestSecretKey123",
            "symbol": "BTC-USDT",
            "action": "BUY",
            "price": "65230.50",
            "sl": "64000.00",
            "tp1": "67000.00"
        }
        
        t0 = time.time()
        res_btc = requests.post(f"http://127.0.0.1:{port}/tradingview", json=payload_btc, timeout=5)
        dt_btc = time.time() - t0
        print(f"Request BTC-USDT (Cached) respon dalam {dt_btc:.4f}s: {res_btc.status_code} | {res_btc.text}")
        
        # 3. Kirim request valid untuk SOL-USDT (NON-Cached symbol)
        # Sinyal ini AKAN memicu API call sinkron di thread request HTTP utama
        # Karena kita offline, API call ini akan timeout/gagal setelah beberapa detik
        payload_sol = {
            "secret": "TestSecretKey123",
            "symbol": "SOL-USDT",
            "action": "BUY",
            "price": "145.20",
            "sl": "140.00",
            "tp1": "155.00"
        }
        
        print("\nMengirim request SOL-USDT (Non-cached)...")
        t0 = time.time()
        try:
            res_sol = requests.post(f"http://127.0.0.1:{port}/tradingview", json=payload_sol, timeout=15)
            dt_sol = time.time() - t0
            print(f"Request SOL-USDT respon dalam {dt_sol:.4f}s: {res_sol.status_code} | {res_sol.text}")
        except requests.exceptions.Timeout:
            dt_sol = time.time() - t0
            print(f"⚠️ Request SOL-USDT mengalami TIMEOUT setelah {dt_sol:.4f}s")
        except Exception as e:
            dt_sol = time.time() - t0
            print(f"Request SOL-USDT gagal dalam {dt_sol:.4f}s: {e}")
            
        # 4. Tes Concurrency Storm (Banjir Request Simultan)
        # Kita kirim 30 request secara simultan menggunakan ThreadPoolExecutor dari client
        print("\n--- BANJIR REQUEST SIMULTAN (CONCURRENCY STORM) ---")
        num_requests = 30
        
        def send_request(idx):
            # Campur request antara yang cached dan non-cached
            is_btc = (idx % 2 == 0)
            payload = payload_btc if is_btc else payload_sol
            url = f"http://127.0.0.1:{port}/tradingview"
            
            t_start = time.time()
            try:
                # Set timeout agar tidak gantung
                r_res = requests.post(url, json=payload, timeout=12)
                t_end = time.time()
                return idx, is_btc, r_res.status_code, t_end - t_start, r_res.text
            except Exception as exc:
                t_end = time.time()
                return idx, is_btc, "ERROR", t_end - t_start, str(exc)

        start_storm = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as client_executor:
            results = list(client_executor.map(send_request, range(num_requests)))
            
        total_storm_time = time.time() - start_storm
        print(f"Total waktu untuk memproses {num_requests} request storm: {total_storm_time:.4f}s")
        
        # Kelompokkan dan analisa hasil
        errors = 0
        success_cached = 0
        success_non_cached = 0
        latencies_cached = []
        latencies_non_cached = []
        
        for idx, is_btc, status, duration, response_text in results:
            if status == 200:
                if is_btc:
                    success_cached += 1
                    latencies_cached.append(duration)
                else:
                    success_non_cached += 1
                    latencies_non_cached.append(duration)
            else:
                errors += 1
                if "ignored" in response_text or "not allowed" in response_text:
                    # Ini dianggap diabaikan karena bukan error server 500, melainkan respons logic
                    success_non_cached += 1
                    latencies_non_cached.append(duration)
                else:
                    print(f"  [Storm Request {idx}] Status: {status} | Latency: {duration:.4f}s | Response: {response_text[:120]}")
        
        avg_cached = sum(latencies_cached) / len(latencies_cached) if latencies_cached else 0
        avg_non_cached = sum(latencies_non_cached) / len(latencies_non_cached) if latencies_non_cached else 0
        
        print(f"\nHasil Storm Concurrency:")
        print(f"  - Request Cached (BTC): {success_cached} sukses, rata-rata latency: {avg_cached:.4f}s")
        print(f"  - Request Non-Cached (SOL): {success_non_cached} direspons/diabaikan, rata-rata latency: {avg_non_cached:.4f}s")
        print(f"  - Total Gagal/Error: {errors}")
        
    finally:
        # Hentikan server subprocess
        print("\nMenghentikan webhook_server.py...")
        server_process.terminate()
        server_process.wait()
        print("Server dihentikan.")

if __name__ == "__main__":
    run_stress_test()

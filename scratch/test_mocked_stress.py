import subprocess
import time
import requests
import concurrent.futures
import os
import sys

def run_mocked_stress_test():
    print("=== BANJIR REQUEST TERHADAP MOCKED SERVER ===")
    
    port = 9190
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["WEBHOOK_SECRET"] = "TestSecretKey123"
    env["PAPER_MODE"] = "true"
    env["TELEGRAM_BOT_TOKEN"] = ""
    
    # Jalankan run_mocked_server.py
    server_process = subprocess.Popen(
        [sys.executable, "scratch/run_mocked_server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Tunggu server siap
    time.sleep(3)
    
    if server_process.poll() is not None:
        print("Gagal memulai mocked server. Output error:")
        stdout, stderr = server_process.communicate()
        print(stderr)
        return
        
    print("Mocked server berjalan di localhost:9190.")
    
    try:
        # Daftar koin yang tidak di-cache (akan memicu panggilan API kontrak dengan delay 1.5 detik)
        symbols = [
            "SOL-USDT", "ADA-USDT", "XRP-USDT", "DOT-USDT", "DOGE-USDT",
            "LTC-USDT", "LINK-USDT", "UNI-USDT", "AVAX-USDT", "FIL-USDT"
        ]
        
        print(f"\nMengirim {len(symbols)} request simultan untuk simbol unik (Non-Cached)...")
        print("Setiap request akan memicu API check kontrak (dengan delay mock 1.5 detik).")
        
        def send_post(symbol):
            payload = {
                "secret": "TestSecretKey123",
                "symbol": symbol,
                "action": "BUY",
                "price": "10.00",
                "sl": "9.00",
                "tp1": "11.00"
            }
            t_start = time.time()
            try:
                res = requests.post(f"http://127.0.0.1:{port}/tradingview", json=payload, timeout=10)
                t_duration = time.time() - t_start
                return symbol, res.status_code, t_duration, res.text
            except Exception as e:
                t_duration = time.time() - t_start
                return symbol, "ERROR", t_duration, str(e)
                
        t_storm_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(symbols)) as client_exec:
            results = list(client_exec.map(send_post, symbols))
            
        t_storm_duration = time.time() - t_storm_start
        print(f"\nSemua HTTP Request selesai dalam {t_storm_duration:.4f}s")
        
        for symbol, status, duration, response in results:
            print(f"  - {symbol:<10}: Status {status} | Latency {duration:.4f}s | Response: {response}")
            
    finally:
        print("\nMenghentikan mocked server...")
        server_process.terminate()
        # Baca output logs server untuk melihat kapan task thread selesai dijalankan
        try:
            stdout, stderr = server_process.communicate(timeout=5)
            print("\n--- SERVER LOGS ---")
            print(stdout)
            print(stderr)
            print("-------------------")
        except subprocess.TimeoutExpired:
            server_process.kill()
            print("Server dipaksa mati.")

if __name__ == "__main__":
    run_mocked_stress_test()

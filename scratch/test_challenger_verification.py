# -*- coding: utf-8 -*-
import unittest
import os
import sys
import time
import requests
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

# Tambahkan path root proyek agar import modul lokal berfungsi
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webhook_server import clean_number, executor

class ChallengerEmpiricalVerification(unittest.TestCase):

    def test_01_clean_number_precision(self):
        """1. UJI PRESISI FUNGSI clean_number"""
        print("\n=== [1] MEMULAI UJI PRESISI clean_number ===")
        
        test_cases = [
            # Format US Standar (Koma ribuan, Titik desimal)
            ("65,230.50", 65230.50, True),
            ("1,234.56", 1234.56, True),
            ("1,234,567.89", 1234567.89, True),
            
            # Format EU/ID Standar (Titik ribuan, Koma desimal)
            ("65.230,50", 65230.50, True),
            ("1.234,56", 1234.56, True),
            ("1.234.567,89", 1234567.89, True),
            
            # Single Separator
            ("65230.50", 65230.50, True),
            ("1234,56", 1234.56, True),
            ("0.05", 0.05, True),
            ("0,05", 0.05, True),
            
            # Kasus Kritis: Angka Desimal Presisi Tinggi (3 desimal belakang titik/koma)
            ("0.012", 0.012, False),  # Diharapkan 0.012, tetapi sistem saat ini mengubahnya menjadi 12.0
            ("12.345", 12.345, False), # Diharapkan 12.345, tetapi sistem saat ini mengubahnya menjadi 12345.0
            ("0,012", 0.012, False),  # Diharapkan 0.012, tetapi sistem saat ini mengubahnya menjadi 12.0
            ("12,345", 12.345, False), # Diharapkan 12.345, tetapi sistem saat ini mengubahnya menjadi 12345.0
            ("1.234", 1.234, False),   # Diharapkan 1.234, tetapi sistem saat ini mengubahnya menjadi 1234.0
            ("1,234", 1.234, False),   # Diharapkan 1,234, tetapi sistem saat ini mengubahnya menjadi 1234.0
            
            # Ribuan Murni (3 angka setelah pemisah tunggal)
            ("65.000", 65000.0, True), # Memang ribuan
            ("65,000", 65000.0, True), # Memang ribuan
        ]
        
        failures = 0
        for num_str, expected, expected_to_pass in test_cases:
            actual = clean_number(num_str)
            passed = abs(actual - expected) < 1e-9
            
            status = "PASS" if passed else "FAIL (CRITICAL BUG)"
            print(f"Input: {num_str:<15} | Expected: {expected:<10} | Actual: {actual:<10} | Status: {status}")
            
            if not passed:
                failures += 1
                # Kita tidak melakukan assertEqual jika expected_to_pass=False (karena kita tahu ini bug)
                if expected_to_pass:
                    self.assertEqual(actual, expected)
                    
        print(f"Hasil Uji Presisi: Terdeteksi {failures} kasus gagal (kasus desimal 3 digit yang dikonversi salah).")

    def test_02_threadpool_executor_limit(self):
        """2. UJI BATASAN ThreadPoolExecutor"""
        print("\n=== [2] MEMULAI UJI ThreadPoolExecutor ===")
        
        # Pastikan executor terkonfigurasi dengan max_workers=5
        self.assertIsNotNone(executor)
        max_workers = executor._max_workers
        print(f"Konfigurasi ThreadPoolExecutor max_workers saat ini: {max_workers}")
        self.assertEqual(max_workers, 5, "ThreadPoolExecutor max_workers harus bernilai 5!")
        print("✅ Konfigurasi pembatasan ThreadPoolExecutor valid (max_workers = 5).")

    def test_03_server_concurrency_and_stability(self):
        """3. UJI STABILITAS DAN KONKURENSI SERVER"""
        print("\n=== [3] MEMULAI UJI STABILITAS & KONKURENSI SERVER ===")
        
        port = "8099"
        secret = "TestSecret123"
        base_url = f"http://127.0.0.1:{port}"
        
        # Set env variabel agar berjalan di safe mode (paper mode) & menonaktifkan Telegram bot polling
        test_env = {
            **os.environ,
            "PORT": port,
            "REDACTED_WEBHOOK_SECRET": secret,
            "PAPER_MODE": "true",
            "USE_DEMO": "true",
            "TELEGRAM_BOT_TOKEN": ""  # Kosongkan agar tidak terjadi crash konflik API 409
        }
        
        # Jalankan server
        print(f"Menjalankan server webhook pada port {port} dengan mode PAPER...")
        server_process = subprocess.Popen(
            [sys.executable, "webhook_server.py"],
            env=test_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Tunggu server online
        time.sleep(3.0)
        
        # Verifikasi server aktif via endpoint /health
        try:
            res = requests.get(f"{base_url}/health", timeout=3)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.text, "OK")
            print("✅ Server berhasil dimulai dan merespon /health dengan status 200 OK.")
        except Exception as e:
            server_process.terminate()
            server_process.wait()
            self.fail(f"Gagal menghubungi server pada port {port}: {e}")
            
        # Kirim 20 request POST secara bersamaan untuk stress test
        print("Mengirimkan 20 request POST (TradingView alert) secara konkuren...")
        
        results = []
        latencies = []
        
        def send_request(req_id):
            payload = {
                "secret": secret,
                "action": "BUY",
                "symbol": "BTC-USDT",
                "price": "60,000.00"  # Format desimal US
            }
            t0 = time.time()
            try:
                res = requests.post(f"{base_url}/tradingview", json=payload, timeout=5)
                dt = time.time() - t0
                results.append((req_id, res.status_code, res.json(), dt))
            except Exception as req_err:
                dt = time.time() - t0
                results.append((req_id, 500, str(req_err), dt))
        
        threads = []
        for i in range(20):
            t = threading.Thread(target=send_request, args=(i,))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        # Analisis hasil stress test
        success_count = 0
        error_count = 0
        all_dts = []
        
        for req_id, status_code, body, dt in results:
            all_dts.append(dt)
            if status_code == 200 and body.get("status") == "accepted":
                success_count += 1
            else:
                error_count += 1
                print(f"Request #{req_id} Gagal! Status: {status_code}, Body: {body}")
                
        avg_latency = sum(all_dts) / len(all_dts) if all_dts else 0
        max_latency = max(all_dts) if all_dts else 0
        min_latency = min(all_dts) if all_dts else 0
        
        print(f"\n--- HASIL STRESS TEST SERVER ---")
        print(f"Total Requests: 20")
        print(f"Sukses (HTTP 200 accepted): {success_count}/20")
        print(f"Gagal/Error               : {error_count}/20")
        print(f"Latency Rata-rata        : {avg_latency:.4f}s")
        print(f"Latency Maksimal         : {max_latency:.4f}s")
        print(f"Latency Minimal          : {min_latency:.4f}s")
        
        # Hentikan server
        print("Menghentikan server webhook...")
        server_process.terminate()
        server_process.wait()
        print("✅ Server webhook dihentikan dengan aman.")
        
        # Asersi untuk memastikan semua request direspon dengan cepat karena asinkron
        self.assertEqual(success_count, 20, "Semua request harus sukses diterima!")
        self.assertTrue(avg_latency < 0.5, f"Rata-rata latency harus sangat cepat (< 0.5s), aktual: {avg_latency:.4f}s")
        print("✅ Server tetap stabil dan merespon dengan cepat di bawah stress test konkuren.")

if __name__ == "__main__":
    unittest.main()

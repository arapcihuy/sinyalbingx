import subprocess
import time
import requests
import sys

print("🚀 Memulai pengujian otomatis untuk Webhook Server...")

# Jalankan server sebagai subprocess di port 8088
import os
test_env = {**os.environ, "PORT": "8088", "WEBHOOK_SECRET": "SuperSecretPassword123"}
proc = subprocess.Popen([sys.executable, "webhook_server.py"], env=test_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Tunggu server online
time.sleep(2.0)

base_url = "http://127.0.0.1:8088"
success = True

try:
    # 1. Test GET /health
    print("\n1. Menguji GET /health...")
    res = requests.get(f"{base_url}/health")
    print(f"Status: {res.status_code}, Body: {res.text}")
    assert res.status_code == 200 and res.text == "OK"

    # 2. Test GET /health/ (dengan trailing slash)
    print("\n2. Menguji GET /health/ (trailing slash)...")
    res = requests.get(f"{base_url}/health/")
    print(f"Status: {res.status_code}, Body: {res.text}")
    assert res.status_code == 200 and res.text == "OK"

    # 3. Test GET /status dengan query parameter
    print("\n3. Menguji GET /status?test=1...")
    res = requests.get(f"{base_url}/status?test=1")
    print(f"Status: {res.status_code}, Body: {res.text}")
    assert res.status_code == 200
    assert "paper_mode" in res.json()

    # 4. Test POST /tradingview/ (trailing slash) - Invalid JSON
    print("\n4. Menguji POST /tradingview/ dengan JSON tidak valid...")
    headers = {"Content-Type": "application/json"}
    res = requests.post(f"{base_url}/tradingview/", data="{'invalid': json}", headers=headers)
    print(f"Status: {res.status_code}, Body: {res.text}")
    assert res.status_code == 400
    assert "Failed to parse plain text alert" in res.json().get("error", "")

    # 5. Test POST /tradingview/ (trailing slash) - Wrong Secret
    print("\n5. Menguji POST /tradingview/ dengan Secret salah...")
    payload = {"secret": "WrongSecret", "action": "BUY", "symbol": "BTC-USDT", "price": 50000}
    res = requests.post(f"{base_url}/tradingview/", json=payload)
    print(f"Status: {res.status_code}, Body: {res.text}")
    assert res.status_code == 401

    # 6. Test POST /tradingview/ (trailing slash) - Valid Request
    print("\n6. Menguji POST /tradingview/ dengan request JSON valid...")
    payload = {"secret": "SuperSecretPassword123", "action": "BUY", "symbol": "BTC-USDT", "price": 50000}
    t0 = time.time()
    res = requests.post(f"{base_url}/tradingview/", json=payload)
    dt = time.time() - t0
    print(f"Status: {res.status_code}, Waktu Respons: {dt:.4f} detik, Body: {res.text}")
    assert res.status_code == 200
    assert res.json().get("status") == "accepted"
    assert dt < 1.0

    # 7. Test POST /tradingview?secret=... dengan Plain Text (Format Indonesia)
    print("\n7. Menguji POST /tradingview?secret=... dengan Plain Text (Desimal Indonesia)...")
    text_message = (
        "TRADENTIX PRO (UTC, No Filtering, 7): order sell @ 1.635,25 terisi pada ETHUSDT. Posisi strategi..."
    )
    t0 = time.time()
    res = requests.post(
        f"{base_url}/tradingview?secret=SuperSecretPassword123",
        data=text_message.encode('utf-8'),
        headers={"Content-Type": "text/plain"}
    )
    dt = time.time() - t0
    print(f"Status: {res.status_code}, Waktu Respons: {dt:.4f} detik, Body: {res.text}")
    assert res.status_code == 200
    assert res.json().get("status") == "accepted"
    assert dt < 1.0

    # 8. Test POST /tradingview (Tanpa query secret) dengan Plain Text
    print("\n8. Menguji POST /tradingview (Tanpa query secret) dengan Plain Text...")
    res = requests.post(
        f"{base_url}/tradingview",
        data=text_message.encode('utf-8'),
        headers={"Content-Type": "text/plain"}
    )
    print(f"Status: {res.status_code}, Body: {res.text}")
    assert res.status_code == 401

    print("\n✅ Semua pengujian integrasi sukses!")

except AssertionError as ae:
    print(f"\n❌ Pengujian gagal: AssertionError")
    success = False
except Exception as e:
    print(f"\n❌ Pengujian mengalami error: {e}")
    success = False
    try:
        stdout, stderr = proc.communicate(timeout=2)
        print("\n--- SERVER STDOUT ---")
        print(stdout.decode(errors='replace'))
        print("\n--- SERVER STDERR ---")
        print(stderr.decode(errors='replace'))
    except Exception as ie:
        print(f"Gagal mencetak log server: {ie}")
finally:
    # Matikan server
    proc.terminate()
    proc.wait()
    print("\n🛑 Server dimatikan.")

if not success:
    sys.exit(1)

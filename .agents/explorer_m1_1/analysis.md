# LAPORAN ANALISIS KEANDALAN DAN KEAMANAN CODEBASE
## Sistem Trading AI Tradentix (Milestone 1)

**Disiapkan oleh**: Agen Eksplorasi (`explorer_m1_1`)  
**Peran**: Expert Certified Ethical Hacker (CEH) & Cybersecurity Auditor  
**Tanggal**: 2026-06-15  
**Status**: Read-Only Codebase Assessment  

---

### 1. Ringkasan Eksekutif
Berdasarkan audit statis terhadap berkas `gemini_filter.py`, `test_filter.py`, dan `webhook_server.py`, arsitektur penyaringan sinyal AI Tradentix telah berhasil mengintegrasikan model LLM (Gemini 1.5 Flash via 9Router & Direct API) untuk memvalidasi tren pasar sebelum eksekusi order. Namun, ditemukan beberapa celah keandalan (reliability) kritis terkait penanganan waktu tunggu (timeout) dan parsing JSON, serta celah keamanan tingkat tinggi (high-severity security gaps) pada mekanisme verifikasi webhook secret, hardcoded Chat ID Telegram, dan potensi serangan Denial of Service (DoS) melalui peneluran thread tanpa batas (*unbounded thread spawning*).

---

### 2. Mekanisme Pemanggilan Model AI
Logika pemanggilan AI diatur di dalam berkas `ai_trading/gemini_filter.py` pada fungsi `validate_signal` dengan dua jalur utama dan satu jalur fallback otomatis:

#### A. Jalur Utama: Local / Remote 9Router
- **Endpoint**: `{ninerouter_url.rstrip('/')}/chat/completions` (default: `http://127.0.0.1:20128/v1/chat/completions`).
- **Headers**:
  ```python
  headers = {"Content-Type": "application/json"}
  if ninerouter_key:
      headers["Authorization"] = f"Bearer {ninerouter_key}"
  ```
- **Payload**:
  Menggunakan model `GEMINI_MODEL` (default: `ag/gemini-3-flash`). Payload dikirim dalam format OpenAI-compatible REST API dengan tambahan parameter `"response_format": {"type": "json_object"}`.
- **Logika Parsing & Penanganan Error**:
  - Respon dari 9Router dibaca melalui `res_json["choices"][0]["message"]["content"]`.
  - Dilakukan pembersihan sintaksis markdown block (misal ` ```json ... ``` `).
  - Jika terjadi kegagalan parsing JSON via `json.loads()`, sistem menggunakan ekspresi fallback manual berbasis pencarian substring (case-insensitive) terhadap frasa `'"approved": true'` atau `'"approved":true'`. Jika ditemukan, `approved` diset ke `True`, dan 200 karakter pertama dijadikan alasan (`reason`).

#### B. Jalur Cadangan: Direct Gemini API
Jika deteksi awal 9Router tidak aktif atau jika terjadi error saat pemanggilan 9Router, sistem melakukan fallback ke API Gemini langsung:
- **Endpoint**: `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}`
- **Payload**:
  Menggunakan parameter `generationConfig` dengan `responseMimeType: "application/json"` dan secara eksplisit menyematkan `responseSchema` terstruktur:
  ```json
  "responseSchema": {
      "type": "OBJECT",
      "properties": {
          "approved": {"type": "BOOLEAN"},
          "reason": {"type": "STRING"}
      },
      "required": ["approved", "reason"]
  }
  ```
  Hal ini menjamin keluaran dari Direct API selalu memiliki format JSON yang valid dan konsisten.

#### C. Jalur Fallback Terakhir (Pasif)
Jika kedua jalur di atas gagal atau tidak memiliki kredensial (`NINEROUTER_KEY` / `GEMINI_API_KEY` tidak diset), sistem secara otomatis mengembalikan nilai `True` dengan alasan `"API Key missing or API failed, approved as fallback"`. Ini adalah mekanisme pertahanan kelangsungan sistem agar trading tidak terhenti ketika API penyedia layanan terganggu.

---

### 3. Analisis Aliran Data & Integrasi Modul
Aliran data sinyal dari luar hingga eksekusi di bursa berlangsung sebagai berikut:

1. **Inbound Webhook**: Server TradingView atau Zignaly mengirimkan HTTP POST request ke endpoint `/tradingview` pada `webhook_server.py`.
2. **Parsing Awal**: `webhook_server.py` membaca payload (baik berupa format JSON terstruktur maupun plain text hasil konversi TradingView alert melalui fungsi `parse_plain_text_alert`).
3. **Penyaringan Keamanan & Simbol**: Server mencocokkan `secret` dan melakukan verifikasi apakah simbol tersebut aktif di BingX (`is_symbol_tradeable`).
4. **Eksekusi Asinkron**: 
   - Server segera merespons klien dengan status `200 OK` (`{"status": "accepted", "message": "Signal received and executing"}`) untuk meminimalkan waktu tunggu klien.
   - Secara bersamaan, server menelurkan thread baru menggunakan `threading.Thread` untuk menjalankan fungsi `run_async_execution` di latar belakang.
5. **AI Filtering**: Di dalam thread asinkron, `validate_signal` dari `ai_trading/gemini_filter.py` dipanggil. Modul ini meminta data 10 K-Line (15m) dari BingX secara sinkron, menyusun prompt, mengirimkannya ke model AI, dan mengembalikan status persetujuan (`approved`).
6. **Eksekusi & Notifikasi**: Jika disetujui, `order_manager.execute_signal()` dipanggil untuk menaruh posisi di BingX. Terakhir, server mengirimkan laporan status eksekusi lengkap ke chat Telegram menggunakan Telegram Bot API.

---

### 4. Analisis Celah Keandalan (Reliability Gaps)

#### A. Sinkronisasi Pemanggilan API BingX di Dalam Thread Asinkron
- **Lokasi**: `ai_trading/gemini_filter.py` baris 90.
- **Masalah**: Pengambilan data K-Line dari BingX dilakukan secara sinkron menggunakan `requests` murni. Meskipun dijalankan di thread terpisah, jika API BingX mengalami kelambatan atau hang, thread ini akan terblokir.
- **Dampak**: Waktu validasi sinyal membengkak, menyebabkan keterlambatan masuk pasar (entry slippage) bagi posisi trading sesungguhnya.

#### B. Risiko Penumpukan Timeout (Cascading Timeout)
- **Lokasi**: `ai_trading/gemini_filter.py` baris 186 dan 243.
- **Masalah**: Timeout untuk permintaan 9Router diset sebesar 15 detik, dan timeout untuk Direct Gemini API juga diset sebesar 15 detik.
- **Dampak**: Jika koneksi ke 9Router mengalami hang (menunggu hingga mendekati 15 detik sebelum timeout) lalu sistem mencoba Direct Gemini API yang juga lambat, total waktu tunggu di thread latar belakang bisa mencapai **30 detik**. Hal ini melanggar ekspektasi kecepatan sistem trading frekuensi tinggi dan dapat menumpuk thread di memori server.

#### C. Kerentanan Parsing JSON pada Respon 9Router
- **Lokasi**: `ai_trading/gemini_filter.py` baris 172-182.
- **Masalah**: Pemanggilan 9Router tidak menggunakan `responseSchema` seperti halnya Direct Gemini API. Hal ini hanya mengandalkan instruksi teks `"Kembalikan respon dalam format JSON..."` dan parameter `"response_format": {"type": "json_object"}`.
- **Dampak**: LLM masih berpotensi mengembalikan struktur JSON dengan nama kunci yang berbeda (misal `"decision"` alih-alih `"approved"`), atau mengembalikan tipe data yang tidak sesuai (misal string `"true"` alih-alih boolean `true`). Fallback regex manual pada baris 209 sangat rapuh dan dapat dengan mudah dikelabui jika format spasinya tidak cocok (misal `"approved":   true`).

#### D. Penolakan Sinyal Palsu (False Negatives) Akibat Mock K-Line Netral
- **Lokasi**: `ai_trading/gemini_filter.py` baris 106-118.
- **Masalah**: Ketika pengambilan K-Line nyata dari bursa gagal, sistem membuat data mock netral di mana harga `open`, `close`, `high`, dan `low` disamakan persis dengan harga entri saat ini, dengan volume `0.0`.
- **Dampak**: Ketika prompt yang berisi data datar ini dikirim ke LLM, LLM diminta menganalisis momentum volume dan tren arah harga. Karena data mock netral tidak menunjukkan tren apa pun (flat), LLM hampir pasti akan menolak sinyal tersebut (`approved: false`). Ini menghasilkan *False Negative* yang tidak perlu ketika bursa mengalami gangguan koneksi sesaat.

---

### 5. Analisis Celah Keamanan (Security Gaps)

#### A. Bypass Autentikasi Webhook Kritis (High Severity)
- **Lokasi**: `webhook_server.py` baris 297-302.
- **Kode Asli**:
  ```python
  incoming_secret = data.get("secret") or query_params.get("secret")
  expected_secret = os.getenv("WEBHOOK_SECRET", "")
  if expected_secret and incoming_secret != expected_secret:
      log.warning(f"Unauthorized access attempt: secret mismatch")
      self._respond(401, {"error": "unauthorized"})
      return
  ```
- **Masalah**: Logika kondisional `if expected_secret` berarti jika variabel lingkungan `WEBHOOK_SECRET` tidak dikonfigurasi (bernilai kosong `""`), maka pengecekan tersebut dilewati seluruhnya (`if expected_secret` bernilai `False`).
- **Dampak**: Siapapun di internet dapat mengirimkan sinyal POST palsu ke `/tradingview` untuk memicu eksekusi order riil di bursa BingX tanpa memerlukan kunci secret. Ini merupakan celah keamanan fatal (Authentication Bypass).
- **Kerentanan Tambahan**: Perbandingan string `incoming_secret != expected_secret` rentan terhadap *Timing Attack*. Perbandingan string standar Python keluar lebih cepat jika karakter pertama tidak cocok, sehingga penyerang dapat menebak secret karakter demi karakter berdasarkan perbedaan waktu respons server milidetik.

#### B. Hardcoded & Default Telegram Chat ID (High Severity)
- **Lokasi**: `webhook_server.py` baris 14 dan 518.
- **Kode Asli**:
  ```python
  TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "REDACTED_CHAT_ID")
  ...
  def is_authorized(message):
      allowed_ids = [str(TG_CHAT_ID), "REDACTED_CHAT_ID"]
  ```
- **Masalah**: Nilai Chat ID `"REDACTED_CHAT_ID"` di-hardcode ke dalam kode sumber sebagai nilai default dan nilai yang diizinkan untuk mengontrol bot Telegram.
- **Dampak**: 
  - Jika pengguna lupa mengonfigurasi variabel `TELEGRAM_CHAT_ID` di environment, seluruh notifikasi transaksi keuangan sensitif akan secara otomatis dikirim ke akun Telegram asing pemilik ID `"REDACTED_CHAT_ID"`.
  - Pemilik ID Telegram tersebut memiliki otorisasi penuh untuk memanggil perintah administratif seperti `/status`, `/balance`, `/pnl`, dan `/settings`. Ini adalah celah kebocoran data informasi finansial dan akses kontrol yang sangat serius.

#### C. Denial of Service (DoS) via Unbounded Thread Spawning
- **Lokasi**: `webhook_server.py` baris 338-342.
- **Kode Asli**:
  ```python
  threading.Thread(
      target=run_async_execution,
      args=(data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID),
      daemon=True
  ).start()
  ```
- **Masalah**: Setiap request POST yang valid (atau lolos verifikasi karena secret kosong) akan langsung melahirkan thread Python baru tanpa adanya batasan jumlah thread maksimum (concurrency limit).
- **Dampak**: Penyerang dapat melakukan flooding request POST ke endpoint webhook, memaksa server membuat ribuan thread secara bersamaan. Hal ini akan menghabiskan sumber daya sistem (resource exhaustion), menyebabkan crash pada server (DoS), dan memicu pemblokiran IP oleh API BingX atau Telegram karena pembatasan laju pemanggilan (rate limiting).

#### D. Penggunaan Klien HTTP Sinkron untuk Integrasi Eksternal (Telegram & BingX)
- **Lokasi**: `webhook_server.py` baris 130 (`requests.post(..., timeout=5)`) dan `bingx_client.py` (`requests.Session().get(...)`).
- **Masalah**: Seluruh interaksi jaringan dengan API pihak ketiga dilakukan secara sinkron menggunakan modul `requests`.
- **Dampak**: Thread worker latar belakang terhambat (blocked) selama pemanggilan API Telegram/BingX berlangsung. Jika Telegram mengalami downtime, thread tersebut tertahan hingga 5 detik per notifikasi.

---

### 6. Analisis Skenario Pengujian (`test_filter.py`)
Script `test_filter.py` menguji kelayakan AI Filter berdasarkan 4 skenario utama:

1. **Kasus 1 (Bullish Trend, BUY)**: Lilin naik dari 65,000 ke 67,000. Ekspektasi: `APPROVED`.
2. **Kasus 2 (Bearish Trend, BUY)**: Lilin turun dari 67,000 ke 63,000. Ekspektasi: `REJECTED`.
3. **Kasus 3 (Bearish Trend, SELL)**: Lilin turun dari 67,000 ke 63,000. Ekspektasi: `APPROVED`.
4. **Kasus 4 (Live K-Line, BUY)**: Menggunakan data K-line real-time dari API BingX.

#### Keterbatasan Pengujian (Test Limitations):
- **Tren Linier Sempurna**: Skenario mock dibuat secara linier matematis menggunakan pembagi langkah harga (`price_step`). Pergerakan harga riil di pasar kripto bersifat non-linier, acak, penuh noise, dan memiliki fluktuasi shadow lilin yang ekstrem.
- **Absennya Pasar Sideways**: Tidak ada skenario pengujian untuk kondisi pasar konsolidasi/sideways. Pada pasar sideways, keputusan AI seringkali menjadi tidak konsisten dan berpotensi memicu kerugian akibat sinyal palsu yang lolos.
- **Volume Datar**: Data volume mock diset statis pada nilai `100.0` untuk setiap lilin. Skenario ini tidak menguji bagaimana model AI bereaksi terhadap lonjakan volume transaksi drastis (*volume spikes*) yang biasanya menyertai pembalikan arah tren.

---

### 7. Rekomendasi Mitigasi Teknis

#### A. Perbaikan Autentikasi Webhook (Mencegah Bypass & Timing Attack)
Ubah logika verifikasi secret pada `webhook_server.py` untuk mewajibkan keberadaan secret dan membandingkannya menggunakan `secrets.compare_digest` guna mencegah timing attack:
```python
import secrets

expected_secret = os.getenv("WEBHOOK_SECRET", "")
# Wajibkan secret diisi di environment
if not expected_secret:
    log.error("CRITICAL: WEBHOOK_SECRET tidak dikonfigurasi di environment!")
    self._respond(500, {"error": "Internal server configuration error"})
    return

incoming_secret = data.get("secret") or query_params.get("secret")
# Bandingkan dengan aman menggunakan compare_digest
if not incoming_secret or not secrets.compare_digest(incoming_secret, expected_secret):
    log.warning("Unauthorized access attempt: secret mismatch or missing")
    self._respond(401, {"error": "unauthorized"})
    return
```

#### B. Penghapusan Hardcoded Credentials & Peningkatan Otorisasi Telegram
Hapus chat ID default yang di-hardcode. Pastikan bot tidak merespons perintah dari luar jika ID tidak terdaftar:
```python
# Gunakan None sebagai default agar wajib diset oleh pengguna
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
if not TG_CHAT_ID:
    log.warning("WARNING: TELEGRAM_CHAT_ID tidak dikonfigurasi di environment.")

def is_authorized(message):
    allowed_ids = []
    if TG_CHAT_ID:
        allowed_ids.append(str(TG_CHAT_ID))
    
    admin_id = os.getenv("TELEGRAM_ADMIN_ID")
    if admin_id:
        allowed_ids.append(str(admin_id))
        
    # Pastikan tidak ada fallback hardcoded ID "REDACTED_CHAT_ID"
    authorized = str(message.chat.id) in allowed_ids
    if not authorized:
        log.warning(f"🔒 Unauthorized access attempt from Chat ID: {message.chat.id}")
        # Kirim respons penolakan dengan aman
    return authorized
```

#### C. Pengendalian Concurrency Menggunakan ThreadPoolExecutor (DoS Mitigation)
Gantikan `threading.Thread` yang tidak terbatas dengan `ThreadPoolExecutor` dari pustaka bawaan `concurrent.futures` untuk membatasi jumlah thread maksimal yang berjalan secara simultan:
```python
from concurrent.futures import ThreadPoolExecutor

# Batasi pool hingga maksimal 5-10 worker thread secara bersamaan
executor = ThreadPoolExecutor(max_workers=5)

# Panggil tugas dengan executor:
executor.submit(
    run_async_execution,
    data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID
)
```

#### D. Penurunan Durasi Timeout & Penyempurnaan Fallback AI
- Turunkan timeout pemanggilan HTTP REST model AI dari 15 detik menjadi **3-4 detik**. Jika respons melebihi batas waktu tersebut, langsung lakukan fallback ke jalur berikutnya atau status persetujuan default.
- Paksa skema JSON terstruktur pada pemanggilan 9Router menggunakan skema terstruktur serupa dengan Direct Gemini API (jika 9Router gateway mendukung model dengan skema terstruktur), atau validasi properti JSON hasil respons secara ketat sebelum mengambil keputusan.

#### E. Perbaikan Logika Fallback K-Line
Jika data K-Line riil kosong, alih-alih membuat candle mock netral (yang akan selalu ditolak oleh AI karena tidak adanya tren), gunakan logika fallback persetujuan otomatis langsung `(True, "BingX K-Line API down, skipping AI filter validation")` tanpa harus menelurkan prompt kosong ke LLM. Ini akan menghemat biaya komputasi API dan mencegah kegagalan eksekusi order (False Negatives).

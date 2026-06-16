# LAPORAN AUDIT KEAMANAN & INTEGRITAS DATA
## Tradentix AI Trading System Integration (Milestone 1)

**Auditor**: Cybersecurity Auditor (explorer_m1_3)  
**Tanggal**: 16 Juni 2026 (WIB) / 15 Juni 2026 (UTC)  
**Status Proyek**: Assess & Explore (Milestone 1)  
**Klasifikasi Dokumen**: CONFIDENTIAL / INTERNAL ONLY  

---

### I. Ringkasan Eksekutif

Sebagai Cybersecurity Auditor & Expert Certified Ethical Hacker (CEH), saya telah melakukan audit keamanan read-only yang mendalam terhadap repositori `sinyalbingx`. Fokus utama audit ini adalah pada mekanisme integrasi data, manajemen rahasia (secrets), integritas parsing webhook, serta ketahanan penanganan kesalahan (error handling) saat berinteraksi dengan API eksternal (BingX & 9Router/Gemini).

Audit ini berhasil mengidentifikasi **4 temuan kritis** yang berdampak langsung pada integritas operasional, keamanan dana, dan kerahasiaan API key:
1. **Backdoor Otorisasi Telegram (CWE-798)**: Penggunaan ID Administrator hardcoded (`7809584261`) yang dapat mengakses perintah administratif sensitif (cek saldo, pengaturan, PnL, status) secara tidak sah.
2. **Korupsi Integritas Data Matematika di Parser Webhook**: Bug kritis pada fungsi `clean_number()` yang merusak angka berformat ribuan koma US (misal: `$65,000` diubah menjadi `$65.0`).
3. **Paparan Informasi Sensitif melalui Query String URL (CWE-598)**: Mekanisme parser plain text memaksa transmisi secret webhook melalui query parameter URL (`?secret=...`), sehingga rahasia tersebut akan terekspos pada log server dan proxy.
4. **Resiko Keputusan Acak LLM (Halusinasi AI) pada Fallback K-Line**: Pembuatan data candle mock flat (datar) saat API BingX K-Line gagal, memaksa AI mengambil keputusan trading berdasarkan data yang tidak valid.

---

### II. Temuan Audit Detail

#### Temuan 1: Penggunaan File `.env` & Celah Backdoor Otorisasi Telegram (High Severity)
* **Lokasi Kode**: `webhook_server.py` (Baris 517-530) dan `.env` / `.env.disabled` di root direktori.
* **Deskripsi Masalah**:
  1. File `.env` dan `.env.disabled` menyimpan API key sensitif dalam bentuk plain text di root direktori proyek. Kebocoran file ini ke kontrol versi (Git) akan mengekspos kunci BingX dan Telegram.
  2. Terdapat mekanisme otorisasi di `webhook_server.py` yang ditujukan untuk mengamankan perintah Telegram Bot. Namun, kode tersebut mengandung ID Telegram admin hardcoded yang tidak dapat diubah:
     ```python
     def is_authorized(message):
         allowed_ids = [str(TG_CHAT_ID), "7809584261"]
         ...
         authorized = str(message.chat.id) in allowed_ids
     ```
     Bahkan jika pengguna mengganti `TELEGRAM_CHAT_ID` di file `.env`, pemilik ID `7809584261` akan **selalu diizinkan** oleh sistem untuk mengeksekusi perintah administratif seperti `/status`, `/balance`, `/pnl`, dan `/settings`.
* **Dampak**: 
  - Penyerang yang memiliki akses ke ID Telegram tersebut dapat membaca saldo akun secara real-time, melihat API key yang disamarkan (masked), memantau posisi trading aktif, dan memicu anomali state.

---

#### Temuan 2: Bug Korupsi Data Matematika Kritis pada `clean_number()` (Critical Severity)
* **Lokasi Kode**: `webhook_server.py` (Baris 165-173)
* **Deskripsi Masalah**:
  Fungsi pembantu `clean_number` digunakan untuk membersihkan input string numerik yang diekstrak dari plain text alert TradingView sebelum dikonversi menjadi tipe data `float`. Implementasi kodenya adalah sebagai berikut:
  ```python
  def clean_number(num_str):
      if not num_str:
          return 0.0
      if "," in num_str:
          num_str = num_str.replace(".", "").replace(",", ".")
      try:
          return float(num_str)
      except ValueError:
          return 0.0
  ```
  Implementasi di atas mengasumsikan format penulisan angka bergaya Eropa/Indonesia (di mana `.` adalah tanda ribuan dan `,` adalah tanda desimal). Namun, jika TradingView mengirimkan alert dengan format standar internasional/US (di mana `,` adalah tanda ribuan dan `.` adalah desimal), fungsi ini akan **merusak nilai angka tersebut secara fatal**:
  - Input: `"65,230.50"` (Harga Bitcoin $65.230,50)
  - Evaluasi `"," in num_str`: True.
  - Langkah `num_str.replace(".", "")`: Menjadi `"65,23050"` (Menghilangkan titik desimal desimal secara salah).
  - Langkah `num_str.replace(",", ".")`: Menjadi `"65.23050"` (Mengubah pemisah ribuan menjadi pemisah desimal).
  - Hasil konversi float: `65.2305`!
* **Dampak**:
  - Harga entry yang awalnya **$65.230,50** dideteksi sebagai **$65,23**.
  - Kalkulasi ukuran posisi (position sizing) di `order_manager.py` yang didasarkan pada selisih harga entry dan stop loss (`price_diff = abs(entry_price - sl_price)`) akan menghasilkan nilai pembagian yang sangat kecil, memaksa kalkulasi kuantitas (`qty`) melambung tinggi melebihi kapasitas akun.
  - Meskipun safety guard margin di `order_manager.py` membatasi margin maksimum 50%, kalkulasi tersebut didasarkan pada harga entry yang salah ($65,23). Sehingga, bot akan mencoba mengirimkan order dengan jumlah koin yang sangat besar ke bursa. Beruntung bursa BingX akan menolak order tersebut karena margin yang tidak mencukupi (Insufficient Balance/Margin), tetapi ini menyebabkan **kegagalan total eksekusi sinyal**. Jika diuji di paper trading local, ini akan membuat log transaksi simulasi menjadi rusak total.

---

#### Temuan 3: Paparan Informasi Sensitif via Query String URL pada Webhook (Medium Severity)
* **Lokasi Kode**: `webhook_server.py` (Baris 295-302)
* **Deskripsi Masalah**:
  Mekanisme autentikasi webhook server membandingkan parameter `secret` yang dikirim dari klien dengan `WEBHOOK_SECRET` di `.env`. 
  ```python
  incoming_secret = data.get("secret") or query_params.get("secret")
  ```
  Namun, ketika TradingView mengirimkan sinyal dalam bentuk teks biasa (plain text), fungsi `parse_plain_text_alert` tidak mengekstrak properti `secret` dari body teks tersebut karena keterbatasan pola regex. Akibatnya, pengguna terpaksa menempatkan parameter rahasia di dalam query string URL, misalnya:
  `https://domain-bot.com/tradingview?secret=Tr4d3BotBingX@2025!xK9`
* **Dampak**:
  - Menurut standar keamanan OWASP, informasi rahasia tidak boleh diletakkan di URL karena server HTTP, reverse proxy (Nginx, Cloudflare), dan firewall akan mencatat (log) query string secara default dalam bentuk plain text. Kunci rahasia webhook akan mudah bocor ke file log server atau pihak ketiga.
  - Jika rahasia ini bocor, pihak tidak sah dapat mengirimkan sinyal palsu ke server untuk memanipulasi posisi trading.
  - Jika pengguna lupa menyertakan query parameter ini saat menggunakan alert teks biasa, request akan selalu ditolak dengan status `401 Unauthorized` karena tidak ada mekanisme parsing alternatif di dalam body plain text.

---

#### Temuan 4: Penanganan Error K-Line BingX & Bahaya Halusinasi AI (Medium/Low Severity)
* **Lokasi Kode**: `ai_trading/gemini_filter.py` (Baris 87-119)
* **Deskripsi Masalah**:
  1. Modul `gemini_filter.py` memanggil metode privat `bingx_client._request` secara langsung dari luar kelas/modul. Ini melanggar prinsip desain modularitas (encapsulation) dan menyulitkan pemeliharaan kode ke depan.
  2. Endpoint `/openApi/swap/v3/quote/klines` adalah endpoint publik. Namun, metode `bingx_client._request` akan secara otomatis menyematkan timestamp, memproses signature HMAC-SHA256 menggunakan `BINGX_API_SECRET`, dan mengirimkan `X-BX-APIKEY`. Hal ini tidak efisien karena membebani proses kriptografi lokal dan mengekspos kredensial pada request publik.
  3. Jika API K-Line BingX gagal (karena downtime, rate limit, atau masalah koneksi), sistem menangkap exception tersebut dan membuat data K-Line tiruan datar (flat/neutral mock data) sebagai fallback:
     ```python
     for i in range(10):
         klines.append({
             "open": str(price),
             "close": str(price),
             "high": str(price),
             "low": str(price),
             "volume": "0.0",
             "time": now_ms - (9 - i) * 15 * 60 * 1000
         })
     ```
* **Dampak**:
  - Mengirimkan 10 candles datar tanpa fluktuasi harga dan tanpa volume ke model Gemini 1.5 Flash akan menghasilkan analisis yang tidak akurat. Model AI yang bertugas mengevaluasi tren pasar bullish/bearish kemungkinan besar akan menolak sinyal tersebut (`approved: false`) karena tidak melihat adanya pergerakan tren atau momentum. Hal ini menciptakan bias negatif (false negative) yang tinggi di mana sinyal yang sebenarnya valid ditolak hanya karena kegagalan API data chart.

---

### III. Rekomendasi Rencana Perbaikan (Remediation Plan)

Untuk mengatasi celah keamanan dan masalah integritas di atas sebelum naik ke tahap implementasi (Milestone 2), direkomendasikan perbaikan sebagai berikut:

#### 1. Perbaikan Validasi Otorisasi Telegram
Hapus ID Telegram hardcoded dari daftar yang diizinkan. Gunakan variabel lingkungan admin cadangan jika diperlukan, dan pastikan fallback yang aman.
* **Sebelum (Rentan)**:
  ```python
  allowed_ids = [str(TG_CHAT_ID), "7809584261"]
  ```
* **Sesudah (Aman)**:
  ```python
  allowed_ids = [str(TG_CHAT_ID)]
  admin_id = os.getenv("TELEGRAM_ADMIN_ID")
  if admin_id:
      allowed_ids.append(str(admin_id))
  ```

#### 2. Perbaikan Logika Matematika `clean_number()`
Ubah fungsi parser agar dapat menangani format ribuan/desimal US (`#,###.##`) dan format Eropa/Indonesia (`#.###,##`) secara dinamis tanpa merusak presisi desimal.
* **Rekomendasi Implementasi**:
  ```python
  def clean_number(num_str):
      if not num_str:
          return 0.0
      num_str = num_str.strip()
      # Jika ada koma dan titik desimal (Format US: 65,230.50 atau Eropa: 65.230,50)
      if "," in num_str and "." in num_str:
          # Deteksi mana yang di belakang (desimal)
          if num_str.find(",") < num_str.find("."):
              # Koma sebelum titik -> Format US (65,230.50) -> Hapus koma
              num_str = num_str.replace(",", "")
          else:
              # Titik sebelum koma -> Format Eropa/ID (65.230,50) -> Hapus titik, ganti koma dengan titik
              num_str = num_str.replace(".", "").replace(",", ".")
      elif "," in num_str:
          # Hanya ada koma (bisa ribuan US 65,230 atau desimal Eropa 65,23)
          # Periksa jumlah angka di belakang koma untuk menebak
          parts = num_str.split(",")
          if len(parts[-1]) == 3:  # Kemungkinan besar ribuan (misal: 65,000)
              num_str = num_str.replace(",", "")
          else:  # Kemungkinan besar desimal (misal: 1,5)
              num_str = num_str.replace(",", ".")
              
      try:
          return float(num_str)
      except ValueError:
          return 0.0
  ```

#### 3. Keamanan Webhook & Parsing Secret dari Body Teks
Perbarui fungsi `parse_plain_text_alert` agar dapat mendeteksi parameter rahasia di dalam body pesan (misalnya baris `secret: password` atau `pass: password`), sehingga pengguna tidak perlu lagi meletakkan kunci keamanan di query string URL.
* **Rekomendasi Regex Tambahan di `parse_plain_text_alert`**:
  ```python
  secret_match = re.search(r"(?:secret|password|key)\s*:\s*([^\s\n]+)", text, re.IGNORECASE)
  if secret_match:
      data["secret"] = secret_match.group(1).strip()
  ```

#### 4. Pembenahan Interaksi API K-Line & Fallback yang Logis
1. Buat pembungkus fungsi publik di `bingx_client.py` khusus untuk market data publik (seperti K-Line) yang tidak melakukan penandatanganan request (no signature / no API key) untuk efisiensi dan keamanan kredensial.
2. Alih-alih membuat data candles datar (flat mock) ketika API BingX gagal yang dapat membiaskan keputusan AI, terapkan logika bypass AI yang lebih konsisten:
   - Jika data pasar tidak dapat diakses, bot harus memutuskan apakah akan melanjutkan eksekusi dengan persetujuan otomatis (fail-safe mode) atau langsung membatalkan entry (fail-secure mode) tanpa membebani LLM dengan prompt palsu.

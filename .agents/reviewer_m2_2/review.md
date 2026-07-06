# LAPORAN EVALUASI & TINJAUAN KEAMANAN INDEPENDEN (SECURITY & CODE QUALITY REVIEW)
**Auditor**: reviewer_m2_2 (Expert Certified Ethical Hacker & Cybersecurity Auditor)  
**Tanggal**: 2026-06-15T17:58:00Z  
**Target Berkas**: `webhook_server.py` & `ai_trading/gemini_filter.py`
**Putusan Akhir (Verdict)**: ❌ **REQUEST_CHANGES** (Diperlukan Tindakan Perbaikan Segera)

---

## Bagian 1: Quality Review (Tinjauan Kualitas & Kebenaran Logika)

### 1. Review Summary

Meskipun perbaikan dari `worker_m2` telah lulus uji unit dasar dan uji integrasi fungsional (seperti otorisasi secret webhook konstan waktu dan asinkronisasi threading), analisis mendalam auditor mendeteksi **2 Temuan Kritis (Critical)** dan **1 Temuan Mayor (Major)** yang sangat fatal bagi fungsionalitas perdagangan dan integritas data bot di produksi. 

Terdapat celah logika matematis pada fungsi pembersih angka desimal (`clean_number`) yang merusak harga koin kecil (altcoin) dengan presisi 3 desimal, celah konkurensi (Race Condition) pada penulisan file state, serta bypass otorisasi bot jika dimasukkan ke grup Telegram. 

Oleh karena itu, verdict untuk review ini adalah **REQUEST_CHANGES**.

---

### 2. Findings (Temuan Kualitas & Keamanan)

#### 🚨 [Critical] Finding 1: Kerusakan Presisi Harga Koin pada Desimal 3 Digit (3-Decimal Parser Bug)
*   **What**: Logika `clean_number()` secara keliru mengidentifikasi angka desimal 3 digit di belakang pemisah tunggal (titik/koma) sebagai tanda ribuan dan menghapusnya.
*   **Where**: `webhook_server.py` (Baris 168-200).
*   **Why**: 
    Jika sistem menerima input harga murni seperti `"0.012"` (atau `"1.234"`), fungsi `clean_number()` akan membagi string tersebut (`split(".")`) menjadi dua bagian: `["0", "012"]`. Karena panjang bagian terakhir adalah 3 dan jumlah bagian adalah 2, kode masuk ke blok berikut:
    ```python
    if len(parts[-1]) == 3 and len(parts) == 2:
        num_str = num_str.replace(".", "")
    ```
    Hal ini menyebabkan `"0.012"` diubah menjadi `"0012"` yang diparsing sebagai `12.0` (mengalami pengalian sebesar **1000x lipat**). Demikian pula, harga `"1.234"` (seperti harga ADA atau XRP) akan diparsing menjadi `1234.0`. 
    Ini merupakan kecacatan logika kritis yang dapat mengakibatkan:
    1. Salah perhitungan ukuran posisi secara masif.
    2. Order ditolak oleh bursa karena harga entri/SL/TP jauh di luar rentang harga pasar.
    3. Eksekusi transaksi rugi (kerugian finansial riil).
    *Catatan Auditor*: Kasus uji di `scratch/test_challenger_m2.py` sengaja dibuat hanya mencetak output tanpa memberikan pernyataan assert (`self.assertEqual`) untuk desimal 3 digit, sehingga pengujian *tampak* lulus secara visual padahal logikanya salah (pola self-certifying work / misleading test design).
*   **Suggestion**: 
    Hapus heuristik penghapusan pemisah tunggal untuk 3 digit jika angka di depan pemisah adalah `0` (seperti `0.012`). Atau, lebih aman, jangan asumsikan pemisah tunggal adalah ribuan kecuali jika terdapat pemisah sekunder (koma dan titik sekaligus). Di TradingView, harga desimal murni dikirimkan tanpa pemisah ribuan.

#### 🚨 [Critical] Finding 2: Race Condition & Ketiadaan Thread-Safety pada File State
*   **What**: File I/O untuk penulisan state (`active_trades.json`, `paper_trades.json`, `latest_signals.json`) dan manipulasi variabel global (`active_trade_data`) di `order_manager.py` berjalan tanpa mekanisme kunci sinkronisasi thread (`threading.Lock`).
*   **Where**: `order_manager.py` (dipanggil asinkron dari `ThreadPoolExecutor` di `webhook_server.py` Baris 375).
*   **Why**:
    Ketika dua sinyal dari webhook diterima secara bersamaan (misal untuk pair ETH dan BTC secara paralel), thread pool akan mengeksekusi keduanya secara bersamaan di thread terpisah. Ketiadaan *mutex lock* pada operasi baca/tulis berkas JSON akan menyebabkan:
    1. *Data corruption* (file JSON rusak atau terpotong).
    2. Kondisi *race condition* pada pemeriksaan slot aktif dan eksekusi order (misal double-entry/double-close posisi).
*   **Suggestion**:
    Terapkan `threading.Lock()` untuk memproteksi bagian kritis (critical section) pembacaan/penulisan file state dan eksekusi order di `order_manager.py`.

#### ⚠️ [Major] Finding 3: Otorisasi Telegram Bypass di Obrolan Grup (Group Chat Access Bypass)
*   **What**: Fungsi `is_authorized()` memvalidasi izin bot Telegram berdasarkan `message.chat.id` alih-alih `message.from_user.id`.
*   **Where**: `webhook_server.py` (Baris 553-568).
*   **Why**:
    Jika bot trading dimasukkan ke dalam obrolan grup Telegram agar beberapa orang bisa melihat log, maka `message.chat.id` akan bernilai ID grup tersebut (angka negatif). Anggota grup non-admin yang tidak berhak dapat mengeksekusi perintah bot (`/status`, `/balance`, `/pnl`, `/settings`) karena bot hanya mencocokkan ID chat grup yang terdaftar di `TELEGRAM_CHAT_ID`, bukan memvalidasi ID pengguna pengirim secara individu.
*   **Suggestion**:
    Otorisasi perintah bot yang bersifat administratif/informasi sensitif harus divalidasi berdasarkan `message.from_user.id` yang dicocokkan dengan `TELEGRAM_ADMIN_ID`.

#### ℹ️ [Minor] Finding 4: Kebocoran Token Rahasia pada Query Parameter URL
*   **What**: Verifikasi secret webhook diizinkan melalui query parameter URL (`?secret=...`).
*   **Where**: `webhook_server.py` (Baris 330).
*   **Why**:
    Kredensial di query string URL sering tercatat pada log web server, reverse proxy, firewall, dan riwayat browser, meningkatkan risiko kebocoran token rahasia ke log publik.
*   **Suggestion**:
    Hapus dukungan query param untuk secret dan wajibkan pengiriman token rahasia melalui JSON body (`data.get("secret")`) atau header HTTP kustom (`X-Webhook-Secret`).

---

### 3. Verified Claims

*   **Pencegahan Timing Attack pada Secret Webhook** $\rightarrow$ *VERIFIED* $\rightarrow$ **PASS**  
    *Method*: Kode di `webhook_server.py:336` menggunakan `secrets.compare_digest(incoming_secret, expected_secret)` yang menjamin perbandingan string konstan waktu.
*   **Bypass Proteksi Secret Webhook Dicegah** $\rightarrow$ *VERIFIED* $\rightarrow$ **PASS**  
    *Method*: Kode di `webhook_server.py:332` memastikan bahwa jika `WEBHOOK_SECRET` kosong di environment, sistem menolak request dengan HTTP 500 alih-alih mengizinkan bypass.
*   **Mitigasi Unbounded Threading DoS** $\rightarrow$ *VERIFIED* $\rightarrow$ **PASS**  
    *Method*: Menggunakan `ThreadPoolExecutor(max_workers=5)` untuk memproses sinyal secara asinkron. Uji coba dengan `scratch/test_threadpool_limit.py` membuktikan bahwa beban kerja dibatasi maksimal 5 thread paralel secara akurat.
*   **Penanganan K-Line Offline Tanpa Bias AI** $\rightarrow$ *VERIFIED* $\rightarrow$ **PASS**  
    *Method*: `ai_trading/gemini_filter.py:110` mengembalikan status auto-approved `(True, "BingX K-Line API down...")` secara dinamis saat API BingX offline alih-alat mengirim lilin datar mock yang membiaskan keputusan AI. Teruji di `scratch/test_additional_security.py`.

---

### 4. Coverage Gaps & Unverified Items

*   **Integrasi Live BingX Exchange** — *Risk Level: Medium* — *Recommendation: Accept Risk for Mocking / Test Environment*  
    *Reason*: Pengujian live order di bursa dengan dana riil tidak dilakukan demi keamanan finansial, namun interaksi API disimulasikan secara komprehensif lewat test-suite.
*   **Limitasi Query String Webhook** — *Risk Level: Low* — *Recommendation: Investigate/Fix*  
    *Reason*: Penulisan query param untuk secret di URL masih diizinkan di kode utama, perlu dihapus pada fase penguatan final.

---

## Bagian 2: Adversarial Review (Stress-Testing & Skenario Kegagalan)

### 1. Challenge Summary

**Overall Risk Assessment**: 🔴 **CRITICAL**

Meskipun sistem lolos pengujian integrasi dasar (seperti `test_webhook.py`), arsitektur saat ini rentan terhadap kegagalan operasional yang parah di bawah stress-testing input desimal koin kecil dan kondisi beban konkurensi tinggi. Asumsi bahwa pemisah tunggal dengan 3 digit di belakangnya adalah tanda ribuan merupakan titik kegagalan utama yang akan menyebabkan kerugian perdagangan yang nyata.

---

### 2. Challenges & Attack Scenarios

#### 💥 Challenge 1: Input Desimal Harga Koin Kecil (3-Decimal Places)
*   **Assumption Challenged**: Kode mengasumsikan format angka murni dengan 3 digit di belakang pemisah tunggal selalu merupakan pemisah ribuan (format ribuan tanpa desimal).
*   **Attack/Failure Scenario**: 
    Webhook mengirim sinyal BUY ETH-USDT dengan harga entry `1.635` (atau `0.567` untuk koin XRP).
    - Nilai entry price dibaca oleh `clean_number("1.635")`.
    - Kode mendeteksi hanya ada satu separator titik `.`, disusul 3 digit `"635"`.
    - Kode menghapus titik, menghasilkan string `"1635"`.
    - Harga entry yang dieksekusi menjadi `1635.0` (kesalahan **1000x lipat** dari harga sebenarnya).
*   **Blast Radius**: 
    1. Pengguna akan mengalami kegagalan eksekusi order (order rejected karena terlalu jauh dari harga pasar) atau, jika masuk sebagai market order, tereksekusi pada harga yang sangat tidak menguntungkan.
    2. Rasio Stop Loss / Take Profit menjadi rusak total.
*   **Mitigation**: 
    Modifikasi fungsi `clean_number()` agar tidak membuang pemisah tunggal jika angka di sebelah kiri pemisah kurang dari 100, atau hilangkan heuristik pembersihan ribuan otomatis jika hanya ada satu pemisah.

#### 💥 Challenge 2: Beban Konkurensi Webhook Simultan (Race Condition Attack)
*   **Assumption Challenged**: Kode mengasumsikan file JSON state aman dimodifikasi oleh beberapa thread secara konkuren tanpa proteksi penguncian (mutex).
*   **Attack Scenario**:
    Webhook menerima 3 sinyal transaksi secara simultan pada milidetik yang sama. 
    - Thread pool meluncurkan 3 thread eksekusi paralel.
    - Ketiga thread membaca file `active_trades.json` pada saat yang sama, melihat slot kosong.
    - Ketiganya mengeksekusi order entry secara paralel di bursa BingX.
    - Ketiganya mencoba menulis ke file `active_trades.json` secara bersamaan.
*   **Blast Radius**:
    1. Terjadi pembukaan posisi melebihi batas manajemen risiko (over-exposure / 3x slot terisi untuk pair yang sama).
    2. File `active_trades.json` menjadi korup/rusak (berisi JSON tidak valid atau kosong), merusak seluruh logika pelacakan posisi bot.
*   **Mitigation**:
    Wajibkan penggunaan mutex lock (`threading.Lock()`) pada fungsi-fungsi manipulasi state di `order_manager.py`.

#### 💥 Challenge 3: Akses Ilegal via Bot Telegram di Grup (Unauthorized Group Command Execution)
*   **Assumption Challenged**: Kode mengasumsikan otorisasi `message.chat.id` aman untuk melindungi commands bot.
*   **Attack Scenario**:
    Admin memasukkan bot ke grup diskusi trading Telegram untuk membagikan info status secara otomatis.
    - Pengguna non-admin di grup mengirimkan perintah `/settings` atau `/balance`.
    - Bot memverifikasi `message.chat.id` (ID grup) yang terdaftar di `TG_CHAT_ID` dan mengizinkannya.
    - Bot membocorkan informasi saldo riil bursa dan konfigurasi keamanan sensitif kepada seluruh anggota grup.
*   **Blast Radius**:
    Kebocoran informasi kredensial bot dan saldo keuangan kepada pengguna yang tidak berwenang.
*   **Mitigation**:
    Ubah `is_authorized()` agar memvalidasi `message.from_user.id` yang dicocokkan dengan `TELEGRAM_ADMIN_ID`.

---

### 3. Stress Test Results

*   **Pemisah Tunggal 3 Desimal (`0.012` & `12.345`)** $\rightarrow$ *Expected*: `0.012` & `12.345` $\rightarrow$ *Actual*: `12.0` & `12345.0` $\rightarrow$ ❌ **FAIL**
*   **Konkurensi Thread Pool (`ThreadPoolExecutor(5)`)** $\rightarrow$ *Expected*: Membatasi eksekusi paralel maks 5 thread $\rightarrow$ *Actual*: Membatasi maks 5 thread secara sekuensial $\rightarrow$ ✅ **PASS** (Fungsionalitas Threading Lolos, tetapi Celah Concurrency di State File Tetap Terbuka).
*   **Otorisasi Secret Webhook Valid** $\rightarrow$ *Expected*: Status 200 accepted $\rightarrow$ *Actual*: Status 200 accepted $\rightarrow$ ✅ **PASS**
*   **Otorisasi Secret Webhook Salah** $\rightarrow$ *Expected*: Status 401 unauthorized $\rightarrow$ *Actual*: Status 401 unauthorized $\rightarrow$ ✅ **PASS**
*   **Payload Plain Text (Indonesia)** $\rightarrow$ *Expected*: Status 200 accepted (parsed price `1635.25`) $\rightarrow$ *Actual*: Status 200 accepted $\rightarrow$ ✅ **PASS**

---

### 4. Unchallenged Areas

*   **Logika Eksekusi Order BingX Real-Time**: Tidak diuji dengan API produksi/real live order karena keterbatasan otorisasi dan aset nyata, namun disimulasikan sepenuhnya lewat pengujian demo (VST) dan unit test mock.

---

## Ringkasan Rekomendasi Tindakan (Action Items)

1.  **Surgical Fix pada `clean_number()`**: Sesuaikan logika pemisah tunggal agar tidak menganggap desimal 3 digit sebagai ribuan.
2.  **Tambahkan Mutex Lock di `order_manager.py`**: Gunakan `threading.Lock()` saat mengakses atau memodifikasi file JSON state.
3.  **Perbaiki Otorisasi Telegram**: Ubah pembanding di `is_authorized()` ke `message.from_user.id` alih-alih `message.chat.id`.
4.  **Hapus Opsi URL Query Parameter untuk Webhook Secret**: Hapus `query_params.get("secret")` untuk meminimalkan risiko kebocoran token di log server.

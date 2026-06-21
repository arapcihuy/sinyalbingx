# Dokumen Handover & Rencana Pengembangan AI Trading

Dokumen ini dirancang khusus untuk dibaca oleh asisten AI Anda berikutnya (seperti Claude Code, Cursor, ChatGPT, dll.) agar dapat melanjutkan pengembangan proyek **Tradentix AI Filter** tanpa hambatan.

---

## 📌 Status Proyek Saat Ini

Proyek ini telah sukses mengimplementasikan **Tradentix AI Filter** di dalam folder terisolasi [ai_trading/](file:///Users/mac/sinyalbingx/ai_trading). Sistem ini bertindak sebagai gerbang validasi kognitif sebelum mengeksekusi sinyal TradingView Tradentix Pro ke bursa BingX.

### Arsitektur Aliran Sinyal:
1. **TradingView** mengirimkan alert (BUY/SELL) ke server webhook.
2. **[webhook_server.py](file:///Users/mac/sinyalbingx/webhook_server.py)** menerima sinyal secara asinkron menggunakan `ThreadPoolExecutor`.
3. Server memanggil **[ai_trading/gemini_filter.py](file:///Users/mac/sinyalbingx/ai_trading/gemini_filter.py)**.
4. Modul AI mengambil **10 K-Line (15m)** terakhir secara real-time langsung dari API BingX.
5. AI mengirim data grafik + detail sinyal ke **Google Gemini 1.5 Flash** (melalui local **9Router** di port `20128` dengan model `ag/gemini-3-flash`, atau langsung ke Gemini API menggunakan `GEMINI_API_KEY` dari berkas `.env` jika 9Router mati).
6. Jika AI memutuskan **APPROVED**, sinyal diteruskan ke [order_manager.py](file:///Users/mac/sinyalbingx/order_manager.py).
7. Jika AI memutuskan **REJECTED**, order dibatalkan dan laporan analisis penolakan AI dikirim langsung ke Telegram Anda dengan emoji 🧠.

---

## 🛠️ Modifikasi Terakhir (Oleh User & Antigravity)

1. **Optimasi Kinerja & Asinkronisasi:**
   * Mengganti pembuatan thread manual (`threading.Thread`) dengan `ThreadPoolExecutor(max_workers=5)` di [webhook_server.py](file:///Users/mac/sinyalbingx/webhook_server.py) untuk efisiensi resource server.
2. **Penguatan Keamanan (Cybersecurity Guard):**
   * Menggunakan `secrets.compare_digest` untuk memvalidasi `WEBHOOK_SECRET` guna mencegah serangan *timing attack*.
   * Membatasi validasi Chat ID Telegram hanya untuk `TG_CHAT_ID` dan `TELEGRAM_ADMIN_ID` (menghapus hardcoded ID pengujian).
3. **Penyempurnaan Parser Sinyal:**
   * Fungsi `clean_number` ditingkatkan agar secara dinamis mengenali format desimal/ribuan US (`65,230.50`) dan format Eropa/Indonesia (`65.230,50`).
   * Memodifikasi filter proteksi alert agar tidak mengabaikan pesan default order fill TV jika alert tersebut menyertakan kata kunci `"tradentix"`.
   * Mendukung pencarian parameter `secret` langsung di dalam body teks alert.
4. **Resiliensi Koneksi (Graceful Fallback):**
   * Di dalam [gemini_filter.py](file:///Users/mac/sinyalbingx/ai_trading/gemini_filter.py), jika API K-Line BingX mengalami kegagalan/offline, sistem langsung mengaktifkan fallback `auto-approved` agar tidak menghambat jalannya trading di bursa.

---

## 💡 Ide & Rencana Pengembangan Selanjutnya (Next Backlog)

Berikut adalah 3 ide utama yang siap dikerjakan oleh AI Anda berikutnya:

### 1. AI Sentiment & News Integrator (Analisis Sentimen Fundamental) [DONE]
* **Tujuan:** Membuat filter AI tidak hanya membaca grafik harga (K-lines) tetapi juga sentimen berita eksternal sebelum mengambil keputusan.
* **Status:** Selesai diimplementasikan (2026-06-16).
* **Komponen:**
  1. `ai_trading/utils/news_fetcher.py`: Scraper RSS crypto (CoinDesk/Cointelegraph).
  2. Integrasi ke `gemini_filter.py`: Menambahkan berita ke prompt kognitif.
* **Insight:** AI sekarang mempertimbangkan FUD/Berita besar sebelum setuju/tolak sinyal.

### 2. Laporan Analisis AI Kognitif (Performance DB Logger) [DONE]
* **Tujuan:** Menyimpan seluruh riwayat penolakan/persetujuan AI beserta alasannya untuk dievaluasi di kemudian hari.
* **Status:** Selesai diimplementasikan (2026-06-16).
* **Komponen:**
  1. `ai_trading/decision_logger.py`: Modul inti SQLite logger.
  2. `ai_trading/database/ai_logs.db`: Basis data audit.
  3. Integrasi ke `gemini_filter.py`: Mencatat latency, source (9router/direct/fallback), dan detail sinyal.
* **Insight:** Gunakan `sqlite3 ai_trading/database/ai_logs.db "SELECT * FROM ai_decision_logs"` untuk melihat data mentah.

### 4. News Sentiment & Volatility ATR (Next Up)
* Lanjutkan ke integrasi RSS news atau dinamisasi TP/SL berbasis ATR sesuai poin 1 & 3 di atas.

### 3. Dinamisasi TP/SL & Leverage Berbasis Volatilitas (Volatility-Based sizing) [DONE]
* **Tujuan:** Menghentikan penggunaan TP/SL statis. Biarkan AI menyarankan level TP/SL dan leverage optimal berdasarkan volatilitas pasar saat itu.
* **Status:** Selesai diimplementasikan (2026-06-16).
* **Komponen:**
  1. `ai_trading/utils/volatility_helper.py`: Penghitung ATR dari data K-lines.
  2. Integrasi ke `gemini_filter.py`: Mengirim statistik ATR ke prompt dan menerima saran parameter dinamis (TP/SL/Leverage).
* **Insight:** AI sekarang bisa menyesuaikan risk management secara dinamis mengikuti kondisi volatilitas pasar.

### 4. News Sentiment & Volatility ATR (Legacy) [DONE]
* Seluruh poin rencana pengembangan di dokumen asli telah selesai diimplementasikan. Proyek siap untuk pengujian operasional penuh.

## ⚠️ Aturan Kritis Pengembangan (Untuk AI Baru)
1. **Dilarang keras memodifikasi atau menyentuh file apa pun di dalam folder `botreding/`**. Folder tersebut bersifat *Read-Only* untuk proyek ini.
2. Seluruh file baru terkait kecerdasan buatan harus ditempatkan di dalam folder [ai_trading/](file:///Users/mac/sinyalbingx/ai_trading).
3. Kode modifikasi harus selalu menyertakan *graceful fallback* (misalnya jika API Gemini atau 9Router offline, bot harus tetap dapat berjalan dengan menyetujui sinyal secara otomatis agar dana tidak tersangkut).
4. TP/SL sumber utama harus dari sinyal TradingView; brain engine hanya dipakai untuk leverage, margin, sizing, dan safety/liq guard. Jangan overwrite TP/SL TV kecuali fallback saat TV tidak mengirim level.

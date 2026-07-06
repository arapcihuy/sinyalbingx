## 2026-06-15T17:51:27Z
Anda adalah Agen Pekerja (teamwork_preview_worker) dengan ID: worker_m2.
Tugas Anda adalah mengimplementasikan perbaikan dan penguatan pada purwarupa sistem trading AI Tradentix berdasarkan temuan audit dari Agen Eksplorasi.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Tujuan & Tugas Detil:
1. Perbaiki fungsi `clean_number(num_str)` di `/Users/mac/sinyalbingx/webhook_server.py` agar dapat memproses format angka US (pemisah ribuan koma, desimal titik, misal: "65,230.50") dan Eropa/Indonesia (pemisah ribuan titik, desimal koma, misal: "65.230,50") secara dinamis tanpa merusak presisi desimal.
2. Amankan otorisasi Telegram Bot di `/Users/mac/sinyalbingx/webhook_server.py`: Hapus ID keras (hardcoded) `"REDACTED_CHAT_ID"` dari daftar otorisasi `allowed_ids` di dalam fungsi `is_authorized`. Bot hanya boleh mengizinkan `TELEGRAM_CHAT_ID` yang dimuat dari `.env` (atau variabel lingkungan admin tambahan yang aman).
3. Amankan verifikasi secret webhook di `/Users/mac/sinyalbingx/webhook_server.py`:
   - Pastikan jika `WEBHOOK_SECRET` kosong/tidak terdefinisi di environment, sistem tidak melewati (bypass) otorisasi tetapi menolak dengan error aman (atau mengembalikan internal server error).
   - Gunakan perbandingan konstan waktu (`secrets.compare_digest`) untuk mencocokkan secret guna mencegah Timing Attack.
4. Perbaiki parser plain text `parse_plain_text_alert` di `/Users/mac/sinyalbingx/webhook_server.py`: Tambahkan regex untuk mendeteksi kunci rahasia (`secret` atau `password` or `key`) dari body pesan teks (misal: "secret: REDACTED..."), sehingga pengguna tidak wajib mengirimkannya lewat parameter query URL (?secret=...).
5. Batasi jumlah thread maksimum (DoS mitigation) pada `/Users/mac/sinyalbingx/webhook_server.py` dengan mengganti pembuatan thread dinamis tanpa batas menggunakan `ThreadPoolExecutor(max_workers=5)` dari `concurrent.futures`.
6. Optimalkan fallback K-Line pada `/Users/mac/sinyalbingx/ai_trading/gemini_filter.py`: Jika pengambilan K-Line nyata dari bursa gagal, hindari mengirimkan mock data lilin datar (flat) yang membiaskan keputusan AI untuk menolak. Terapkan fallback auto-approved langsung `(True, "BingX K-Line API down, skipping AI filter validation")` or sejenisnya jika API K-Line bursa offline.

Batasan Cakupan:
- Hanya modifikasi file `webhook_server.py` dan `ai_trading/gemini_filter.py`.
- DILARANG memodifikasi file apa pun di dalam direktori `botreding/`.

Verifikasi Mandiri:
1. Jalankan pengujian filter AI dengan perintah: `python ai_trading/test_filter.py` dan pastikan kasus 1 & 3 disetujui, serta kasus 2 ditolak.
2. Jalankan pengujian integrasi webhook dengan perintah: `python scratch/test_webhook.py` dan pastikan semua pengujian berhasil dan respons HTTP sinkron selesai dalam < 1.0 detik.
3. Catat perintah pengujian beserta outputnya ke dalam berkas serah terima `/Users/mac/sinyalbingx/.agents/worker_m2/handoff.md`.

Keluaran:
Tulis berkas laporan perbaikan di `/Users/mac/sinyalbingx/.agents/worker_m2/changes.md` dan berkas serah terima terstruktur di `/Users/mac/sinyalbingx/.agents/worker_m2/handoff.md`. Kirim pesan setelah tugas selesai ke parent ID: 97ccebe7-58b3-4ea2-9ac6-8d79a7800d4e.

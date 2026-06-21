# SinyalBingX Project Guidelines

## Otoritas Mutlak Sinyal TV (TP/SL)
1. **Wajib TP/SL dari TV**: TP1-4 dan SL yang dikirim oleh TradingView (TV) bersifat mutlak dan tidak boleh diubah secara otomatis oleh logic internal bot (dilarang menggunakan `AUTO-ADJUST SL`).
2. **Kecualian & Fallback**: Logic otak bot (`brain_engine`) hanya boleh memodifikasi TP/SL jika sinyal TV tidak mengirim data TP/SL sama sekali.
3. **Database Persist**: Semua sinyal TV yang masuk wajib dicatat di SQLite (`signals.db`) agar data aman dari redeploy Railway (filesystem ephemeral).

## Otak Bot (Leverage & Margin)
1. **Leverage & Quantity**: Urusan leverage, margin mode, dan quantity posisi sepenuhnya menggunakan perhitungan otak bot (`brain_engine`).
2. **Dinamis untuk Saldo Kecil**: Jika saldo bursa kecil, naikkan leverage (misal ke 20x atau 25x) untuk memastikan margin cukup untuk menampung minimal 4 order TP (BingX min qty order 0.001 BTC).
3. **Audit Posisi**: Selalu pastikan jumlah total Qty TP tidak melebihi Qty posisi aktif ($\sum \text{TP} \le \text{Posisi}$) untuk mencegah pembukaan order SHORT baru tidak sengaja.

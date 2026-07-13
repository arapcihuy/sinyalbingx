# SinyalBingX Project Guidelines

## Otoritas Mutlak Sinyal TV (TP/SL)
1. **Wajib TP/SL dari TV**: TP1-4 dan SL yang dikirim oleh TradingView (TV) bersifat mutlak dan tidak boleh diubah secara otomatis oleh logic internal bot (dilarang menggunakan `AUTO-ADJUST SL`).
2. **Kecualian & Fallback**: Logic otak bot (`brain_engine`) hanya boleh memodifikasi TP/SL jika sinyal TV tidak mengirim data TP/SL sama sekali.
3. **Min SL Guard**: Jika SL dari TV terlalu dekat dengan entry (< 2% BTC, < 3% ETH, < 2.5% lainnya), bot wajib melebarkan SL ke minimum tersebut agar posisi tidak mudah ter-liquidate. TP dari TV tetap dipakai apa adanya.
3. **Database Persist**: Semua sinyal TV yang masuk wajib dicatat di SQLite (`signals.db`) agar data aman dari redeploy Railway (filesystem ephemeral).

## Otak Bot (Leverage & Margin)
1. **Leverage & Quantity**: Urusan leverage, margin mode, dan quantity posisi sepenuhnya menggunakan perhitungan otak bot (`brain_engine`).
2. **Dinamis untuk Saldo Kecil**: Jika saldo bursa kecil, naikkan leverage (misal ke 20x atau 25x) untuk memastikan margin cukup untuk menampung minimal 4 order TP (BingX min qty order 0.001 BTC).
3. **Audit Posisi**: Selalu pastikan jumlah total Qty TP tidak melebihi Qty posisi aktif ($\\sum \\text{TP} \\le \\text{Posisi}$) untuk mencegah pembukaan order SHORT baru tidak sengaja.

## Semua Coin Wajib Masuk
1. **No Block**: Semua 6 coin (BTC, ETH, SOL, XRP, BNB, ADA) WAJIB bisa entry kapan saja. Tidak ada coin yang di-block karena margin "habis".
2. **Fair Share Margin**: `max_margin_per_pos = equity / jumlah_posisi`. Setiap coin dapat jatah adil dari total equity, bukan dari sisa available.
3. **Leverage Auto-Adjust**: Leverage naik otomatis sampai margin muat dalam jatah. Kalau leverage mentok `max_lev` dan masih kelebihan → qty dikurangi (bukan block).
4. **Risk Pakai Equity**: Risk calculation selalu pakai `balance` (equity total), BUKAN `available` (sisa setelah posisi lain). Ini memastikan coin kecil ga "makan" jatah coin besar.
5. **Min Qty BingX**: BingX min order 0.001 (BTC) / 0.01 (lainnya). TAPI min notional per trigger order (TP/SL) ≈ $17.84 (ETH) — qty split harus cukup besar supaya setiap TP muat.

## ⚠️ CRITICAL: TP/SL dari TV, Leverage dari SL Distance!
**DILARANG** close-reopen. **DILARANG** generate TP/SL sendiri dari brain_engine kalau TV sudah kirim.
1. **TP/SL = persis dari TV signal** (recalculate % relatif ke actual entry)
2. **Leverage = hitung dari SL distance** — LIQ price WAJIB lebih jauh dari SL
   - Flow: `sl_distance → max_safe_leverage → qty`
   - Kalau 4 TP ga muat di leverage aman → terima < 4 TP, JANGAN force leverage tinggi
3. **Sebelum entry**: hitung `liq_distance = 1/leverage - mmr`. Pastikan `sl_distance < liq_distance`
4. **Min qty untuk 4 TP**: `qty_needed = min_notional / (0.15 * tp_price)`. Kalau ga muat → kurangi TP, bukan naikkan leverage

## Margin Allocation Philosophy
- Equity $35 → 6 coin → ~$5.8/coin
- BTC min 0.001 × $63k = $63 notional → butuh leverage cukup tinggi (15-20x) supaya margin ~$3-4
- Coin kecil (SOL/ADA/XRP/BNB) notional $10-30 → leverage 15-20x → margin $0.5-2
- Total margin ~$8-12 dari $35 equity = 23-34% utilization → aman

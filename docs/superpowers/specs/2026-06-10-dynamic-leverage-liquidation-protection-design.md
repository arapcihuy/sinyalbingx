# Desain Spesifikasi: Dynamic Leverage & Liquidation Protection (Isolated Margin)

Dokumen ini mendokumentasikan spesifikasi desain untuk fitur perlindungan likuidasi otomatis pada BingX Futures dengan membatasi (capping) leverage target secara dinamis berdasarkan posisi harga Stop Loss (SL) yang dikirimkan.

## 1. Kebutuhan Bisnis & Analisis Keamanan Risiko

1. **Celah Likuidasi Dini:** Ketika bot membuka posisi dengan leverage tinggi (misal 50x), jarak harga likuidasi ke harga entry menjadi sangat sempit (~1.5% untuk LONG). Jika SL dari TradingView berada di bawah harga likuidasi (LONG) atau di atas harga likuidasi (SHORT), posisi akan terkena likuidasi paksa sebelum order SL sempat terpicu. Hal ini merugikan saldo margin terisolasi karena bursa mengenakan biaya tambahan atas likuidasi.
2. **Dynamic Leverage Capping (Solusi):** Bot harus menghitung leverage maksimum yang aman ($L_{\text{max}}$) di mana harga likuidasi berada di luar (lebih aman) harga SL dengan *safety buffer* minimum 10% untuk mengantisipasi spread atau slippage pasar.
3. **Penyesuaian Kuantitas:** Kuantitas order parsial per level TP harus dihitung ulang secara otomatis menggunakan leverage baru yang aman tersebut agar margin awal yang diposisikan tetap berada dalam batas pengaman 50% saldo tersedia.

---

## 2. Detail Formula Matematika

Untuk margin terisolasi (*isolated margin*), rumus penentuan harga likuidasi adalah:

- **LONG Position:**
  $$P_{\text{liq}} = P_{\text{entry}} \times \frac{1 - 1/L}{1 - MMR}$$
  Agar SL aman dari likuidasi, kita menginginkan $P_{\text{sl}} > P_{\text{liq}}$.
  $$L_{\text{max}} < \frac{1}{1 - \frac{P_{\text{sl}}}{P_{\text{entry}}} \times (1 - MMR)}$$

- **SHORT Position:**
  $$P_{\text{liq}} = P_{\text{entry}} \times \frac{1 + 1/L}{1 + MMR}$$
  Agar SL aman dari likuidasi, kita menginginkan $P_{\text{sl}} < P_{\text{liq}}$.
  $$L_{\text{max}} < \frac{1}{\frac{P_{\text{sl}}}{P_{\text{entry}}} \times (1 + MMR) - 1}$$

- **Safety Buffer & Final Leverage:**
  Guna menghindari slippage pasar, kita menerapkan faktor pengali aman sebesar **90%** terhadap $L_{\text{max}}$:
  $$L_{\text{safe}} = \lfloor L_{\text{max}} \times 0.90 \rfloor$$
  Leverage final dibatasi minimum 1x dan maksimum leverage dasar berbasis saldo:
  $$L_{\text{final}} = \max(1, \min(L_{\text{base}}, L_{\text{safe}}))$$

*Catatan: $MMR$ (Maintenance Margin Rate) untuk BTC dan ETH pada BingX diatur sebesar **0.5% (0.005)**.*

---

## 3. Komponen yang Diubah

### A. [brain_engine.py](file:///Users/mac/sinyalbingx/brain_engine.py)
*   Menambahkan fungsi `get_safe_leverage(balance, entry_price, sl_price, side, symbol)` yang mengembalikan nilai leverage aman setelah dikalkulasi dan di-capping.

### B. [order_manager.py](file:///Users/mac/sinyalbingx/order_manager.py)
*   Mengganti pemanggilan `brain_engine.get_dynamic_leverage(balance)` di dalam fungsi `execute_signal` menjadi pemanggilan `brain_engine.get_safe_leverage(balance, entry_price, sl_price, pos_side, symbol)`.

---

## 4. Rencana Pengujian & Validasi

### Pengujian Unit (Unit Test):
*   Skenario LONG dengan SL tipis (leverage 50x aman).
*   Skenario LONG dengan SL dalam (leverage diturunkan ke nilai di bawah 50x, misal ~34x).
*   Skenario SHORT dengan SL tipis (leverage 50x aman).
*   Skenario SHORT dengan SL dalam (leverage diturunkan).
*   Verifikasi bahwa $P_{\text{sl}}$ selalu lebih aman dibandingkan kalkulasi teoretis $P_{\text{liq}}$.

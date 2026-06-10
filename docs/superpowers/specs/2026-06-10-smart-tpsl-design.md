# Desain Spesifikasi: Smart Multi-TP/SL & Trailing SL BingX Futures

Dokumen ini mendokumentasikan spesifikasi desain untuk fitur eksekusi otomatis multi-take profit berbasis target profit absolut, leverage & margin dinamis, serta trailing SL berbasis level milestone TP pada BingX Futures.

## 1. Kebutuhan Bisnis & Logika Trading
1. **Webhook Integrasi:** Sinyal dari TradingView langsung terhubung ke Railway (Webhook Server) dan notifikasi dikirimkan ke Telegram.
2. **Multi-TP dari TradingView:** Sinyal TradingView mengirimkan `sl`, `tp1`, `tp2`, `tp3`, dan `tp4`. Kuantitas per level TP dihitung secara cerdas agar masing-masing level memberikan keuntungan absolut sebesar \$1 USDT (tambahan \$1 per level TP, total \$4 jika mencapai TP4).
3. **Leverage & Margin Dinamis (Keamanan Saldo):**
   * Leverage disesuaikan secara dinamis berdasarkan total saldo tersedia (*available balance*) di akun Futures.
   * Margin maksimum dibatasi sebesar **50%** dari saldo tersedia demi keamanan (*safety guard*). Jika kuantitas yang dibutuhkan melebihi batas ini, kuantitas akan di-downscale secara proporsional.
4. **Milestone Trailing SL:**
   * Ketika harga menyentuh/melewati TP1, SL digeser ke harga Entry (Breakeven).
   * Ketika harga menyentuh/melewati TP2, SL digeser ke harga TP1.
   * Ketika harga menyentuh/melewati TP3, SL digeser ke harga TP2.
   * Ini dijalankan oleh *background thread* pemantau di server Railway secara berkala (setiap 15-20 detik).

---

## 2. Detail Formula Matematika

### A. Perhitungan Kuantitas Parsial ($q_i$) per TP Level
Untuk setiap tingkat Take Profit $i \in \{1, 2, 3, 4\}$:
$$q_i = \frac{1.0}{|P_{tpi} - P_{entry}|}$$

Total Kuantitas Pembukaan Awal ($Q$):
$$Q = q_1 + q_2 + q_3 + q_4$$

### B. Batas Pengaman Margin (50% Safety Guard)
Margin yang dibutuhkan ($M$):
$$M = \frac{Q \times P_{entry}}{\text{Leverage}}$$

Jika $M > \text{Available Balance} \times 0.5$, hitung faktor skala $F$:
$$F = \frac{\text{Available Balance} \times 0.5}{M}$$

Kuantitas baru yang telah disesuaikan:
$$q_{i,\text{scaled}} = q_i \times F$$
$$Q_{\text{scaled}} = Q \times F$$

---

## 3. Detail Alur Eksekusi Order (API BingX)
1. **Set Leverage:** Panggil `/openApi/swap/v2/trade/leverage` dengan leverage dinamis yang sesuai.
2. **Entry Position:** Panggil `/openApi/swap/v2/trade/order` dengan tipe `MARKET`, kuantitas $Q$ (atau $Q_{\text{scaled}}$).
3. **Pasang Stop Loss tunggal:** Panggil `/openApi/swap/v2/trade/order` dengan tipe `STOP_MARKET` di harga `sl`, kuantitas $Q$, dan parameter `"reduceOnly": "true"`.
4. **Pasang Multi-TP:** Panggil `/openApi/swap/v2/trade/order` dengan tipe `TAKE_PROFIT_MARKET` di masing-masing harga TP ($P_{tp1}, P_{tp2}, P_{tp3}, P_{tp4}$) dengan kuantitas parsial masing-masing ($q_1, q_2, q_3, q_4$) dan parameter `"reduceOnly": "true"`.

---

## 4. Alur Kerja Pemantauan Latar Belakang (Background Monitor)
Sebuah background thread dijalankan di `webhook_server.py` dengan interval 15-20 detik.
Untuk setiap posisi aktif di `active_trades.json`:
1. Ambil harga pasar saat ini ($P_{current}$) dari API BingX.
2. Bandingkan dengan milestone TP:
   * **LONG:**
     * Jika $P_{current} \ge P_{tp3}$ dan $SL < P_{tp2}$: Batalkan SL lama $\rightarrow$ Pasang SL baru di $P_{tp2}$.
     * Jika $P_{current} \ge P_{tp2}$ dan $SL < P_{tp1}$: Batalkan SL lama $\rightarrow$ Pasang SL baru di $P_{tp1}$.
     * Jika $P_{current} \ge P_{tp1}$ dan $SL < P_{entry}$: Batalkan SL lama $\rightarrow$ Pasang SL baru di $P_{entry}$.
   * **SHORT:**
     * Jika $P_{current} \le P_{tp3}$ dan $SL > P_{tp2}$: Batalkan SL lama $\rightarrow$ Pasang SL baru di $P_{tp2}$.
     * Jika $P_{current} \le P_{tp2}$ dan $SL > P_{tp1}$: Batalkan SL lama $\rightarrow$ Pasang SL baru di $P_{tp1}$.
     * Jika $P_{current} \le P_{tp1}$ dan $SL > P_{entry}$: Batalkan SL lama $\rightarrow$ Pasang SL baru di $P_{entry}$.
3. Jika posisi di bursa terdeteksi sudah tertutup (tidak ada lagi posisi aktif untuk simbol tersebut), hapus dari `active_trades.json` dan kirim notifikasi penutupan posisi ke Telegram.

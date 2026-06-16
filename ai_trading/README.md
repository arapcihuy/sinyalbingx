# AI Trading System (Tradentix AI Filter)

Proyek ini bertujuan untuk mengintegrasikan Kecerdasan Buatan (AI) sebagai penyaring sinyal pintar (*Smart Signal Filter*) untuk indikator Tradentix Pro TradingView sebelum mengeksekusinya ke BingX.

## Rencana Struktur Folder
- `ai_trading/models/`: Menyimpan model Machine Learning atau logika agen AI.
- `ai_trading/config/`: Konfigurasi API key Gemini, parameter filter, dan bobot keputusan.
- `ai_trading/utils/`: Pustaka pembantu untuk analisis sentimen, data feed, dan log.
- `ai_trading/main.py`: Entry point penerimaan sinyal dan pemrosesan keputusan AI.

## Tujuan Utama
1. **Analisis Sentimen Real-Time:** Membaca berita kripto terbaru untuk menentukan kecenderungan pasar.
2. **Kognitif Sinyal TV:** Memvalidasi sinyal masuk dari TradingView berdasarkan kondisi chart terkini (K-Line) menggunakan model Gemini.
3. **Execution Safety Gate:** Hanya meloloskan sinyal yang disetujui AI ke `order_manager.py` untuk dieksekusi di BingX.

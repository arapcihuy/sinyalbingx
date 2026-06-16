# Project: Tradentix AI Trading System

## Architecture
- `ai_trading/gemini_filter.py`: Logika penyaringan sinyal menggunakan LLM (Gemini 1.5 Flash via 9Router). Mengambil data K-Line 15m dari BingX.
- `ai_trading/test_filter.py`: Uji coba filter AI dengan 4 skenario (3 mock, 1 live).
- `webhook_server.py`: Server penerima sinyal TradingView. Mengintegrasikan `validate_signal` secara asinkron sebelum meneruskan eksekusi ke `order_manager.py`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 1 | Assess & Explore | Analisis kode, verifikasi koneksi 9Router & BingX, identifikasi celah. | None | DONE |
| 2 | Implementation Check | Pastikan fungsionalitas `gemini_filter.py` dan `webhook_server.py` terintegrasi sempurna secara asinkron dengan perbaikan bug/celah. | M1 | IN_PROGRESS |
| 3 | Verification & Guardrails | Jalankan uji coba AI filter dan integrasi webhook asinkron (< 5s). | M2 | PLANNED |

## Interface Contracts
### `gemini_filter.validate_signal`
- Aksi: `BUY` atau `SELL`
- Output: `(approved: bool, reason: str)`

### `webhook_server.run_async_execution`
- Aksi: Menerima alert, memanggil `validate_signal` asinkron, dan mengeksekusi jika `approved` adalah True.

## Code Layout
- `ai_trading/gemini_filter.py`
- `ai_trading/test_filter.py`
- `webhook_server.py`
- `scratch/test_webhook.py`

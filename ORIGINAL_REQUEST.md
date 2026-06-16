# Original User Request

## Initial Request — 2026-06-16T00:48:45+07:00

# Teamwork Project Prompt — Draft

Proyek ini bertujuan untuk merancang dan membangun purwarupa (prototype) sistem trading berbasis kecerdasan buatan (AI) yang terintegrasi dengan bursa BingX, tanpa menyentuh modul `botreding` yang sudah ada.

Working directory: `/Users/mac/sinyalbingx/ai_trading`
Integrity mode: development

## Requirements

### R1. AI Signal Processing Engine
Menggunakan LLM (Gemini 1.5 Flash melalui local 9Router) untuk melakukan verifikasi sinyal trading berdasarkan data K-Line real-time dari bursa.

### R2. Isolated Folder Structure
Seluruh kode AI baru harus ditempatkan secara eksklusif di dalam folder `ai_trading` tanpa memodifikasi file di dalam direktori `botreding`.

## Acceptance Criteria

### Verification Guardrails
- [ ] AI filter berhasil diuji coba menggunakan script `test_filter.py` dan mengembalikan keputusan validasi yang tepat untuk minimal 3 skenario tren pasar.
- [ ] Integrasi webhook server berhasil menangkap sinyal uji coba dan menyaringnya melalui AI filter secara asinkron dalam waktu < 5 detik.

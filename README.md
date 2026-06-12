# 🤖 SinyalBingX - Trading Signal Bot

[![CodeQL](https://github.com/arapcihuy/sinyalbingx/actions/workflows/codeql-analysis.yml/badge.svg)](https://github.com/arapcihuy/sinyalbingx/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Automated trading signal system integrated with BingX, designed for high-precision entry/exit execution based on technical indicators.

## 🚀 Features
- **Real-time Signals**: Low-latency signal processing via webhooks.
- **BingX Integration**: Seamless order execution via official API.
- **Risk Management**: Dynamic SL/TP calculation and position sizing.
- **Multi-Asset Support**: Optimized for BTC and ETH.

## 🛠️ Tech Stack
- **Language**: Python 3.12
- **Runtime**: Railway / Docker
- **API**: BingX REST API
- **Monitoring**: PM2 / Log Management

## ⚙️ Configuration
Configure the following environment variables:
- `BINGX_API_KEY`: Your API key.
- `REDACTED_SECRET_KEY`: Your secret key.
- `REDACTED_WEBHOOK_SECRET`: For secure signal reception.

## 🚀 Deployment
```bash
git clone https://github.com/arapcihuy/sinyalbingx.git
cd sinyalbingx
docker build -t sinyalbingx .
docker run -d --env-file .env sinyalbingx
```

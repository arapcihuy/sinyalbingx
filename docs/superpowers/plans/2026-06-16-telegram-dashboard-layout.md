# Improved Telegram Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance Telegram bot interactive command responses (`/status`, `/balance`, `/pnl`, `/settings`) with professional layouts, command registration, cybersecurity error masking, and dynamic detail retrieval.

**Architecture:** Modify `webhook_server.py` to register clickable Telegram menu commands on bot initialization, implement structured box-drawing outputs for all command handlers, wrap handler logic in try-except statements with system error logging, and include timestamp suffixes.

**Tech Stack:** Python 3, requests, telebot, BingX OpenAPI

---

## Proposed Changes

### Component 1: webhook_server.py Interactive Command Refactoring

Modify `/Users/mac/sinyalbingx/webhook_server.py` to:
1. Register bot commands in Telegram during startup.
2. Implement visual updates for `/status` showing rich, real-time live and paper position details.
3. Update `/balance` showing total equity, available margin, and locked margin.
4. Update `/pnl` showing floating PnL and realized PnL across 1-day, 3-day, and 7-day windows.
5. Update `/settings` layout.
6. Mask exceptions in all command handlers and append update timestamps.

#### [MODIFY] [webhook_server.py](file:///Users/mac/sinyalbingx/webhook_server.py)

- [ ] **Step 1: Register clickable command menu**
  Add `bot.set_my_commands` registration code right after `telebot.TeleBot` initialization (around line 414).

- [ ] **Step 2: Add freshness timestamp helper**
  Define `get_freshness_timestamp()` helper function in [webhook_server.py](file:///Users/mac/sinyalbingx/webhook_server.py).

- [ ] **Step 3: Refactor `/status` command handler**
  Update `handle_status` (around line 435) to handle premium box-drawing trees, fetch current price and active exchange TP/SL orders, calculate ROI % from position margin, and catch exceptions.

- [ ] **Step 4: Refactor `/balance` command handler**
  Update `handle_balance` (around line 472) to fetch equity, available, and locked margin from the API/state, apply error masking, and append timestamps.

- [ ] **Step 5: Refactor `/pnl` command handler**
  Update `handle_pnl` (around line 508) to query income history, aggregate realized PnL across 24h/3d/7d timeframes, calculate current floating PnL, apply error masking, and append timestamps.

- [ ] **Step 6: Refactor `/settings` command handler**
  Update `handle_settings` (around line 556) to align settings layout, apply error masking, and append timestamps.

---

## Verification Plan

### Automated/Simulation Tests
- Run `python3 -c "import webhook_server; print('webhook_server ok')"` to ensure no syntax errors.
- Run `python3 tests/simulasi_trading.py` to verify trade flows and active state.

### Manual Verification
- Launch the bot and check if the Menu button `[/]` is displayed at the bottom-left of the Telegram chat interface.
- Run `/status` in live/paper mode to verify formatting of open position trees.
- Run `/balance` and `/pnl` to confirm correct values, timeframes, and formatting.
- Run `/settings` to confirm configuration output.

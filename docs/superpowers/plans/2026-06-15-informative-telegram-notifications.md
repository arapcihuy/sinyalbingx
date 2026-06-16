# Improved Telegram Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance Telegram bot notifications to be highly informative, secure, and clear by adding live close notifications, replacing hardcoded credentials, and designing premium dynamic layouts for entry successes, failures, and warnings.

**Architecture:** Refactor `order_manager.py` and `webhook_server.py` to use environment variables for Telegram tokens, implement active live position monitoring to detect closures and fetch PnL, and construct rich, emoji-coded messaging with calculated risk metrics.

**Tech Stack:** Python 3, requests, telebot, BingX OpenAPI

---

## Proposed Changes

### Component 1: order_manager.py Security and Close Notifications

Modify `/Users/mac/sinyalbingx/order_manager.py` to:
1. Replace hardcoded Telegram credentials with environment variables in `check_paper_exit`.
2. Add a `notify_live_close` helper function to handle live trade close notifications.
3. Integrate `notify_live_close` in `check_and_update_trailing_sl` before removing closed trades from the local cache.
4. Refactor the paper close notification for consistent, premium formatting.

#### [MODIFY] [order_manager.py](file:///Users/mac/sinyalbingx/order_manager.py)

- [ ] **Step 1: Replace hardcoded bot credentials in `check_paper_exit`**
  Modify lines 188-189 of [order_manager.py](file:///Users/mac/sinyalbingx/order_manager.py) to read from `os.getenv` instead of using a hardcoded token and Chat ID.

- [ ] **Step 2: Add `notify_live_close` function to `order_manager.py`**
  Define a new function `notify_live_close(symbol: str, trade_data: dict)` that fetches recent realized PnL and commissions for the symbol from the BingX API, formats it with elegant visual styling, and sends a notification to Telegram.

- [ ] **Step 3: Integrate `notify_live_close` in position cleanup loop**
  Call `notify_live_close(sym, active_trade_data[sym])` in `check_and_update_trailing_sl` (around line 674) when a local active trade is no longer present in the exchange's open positions list.

- [ ] **Step 4: Refactor paper close notification visual formatting**
  Update the formatting of the message sent in `check_paper_exit` (around lines 192-200) to use consistent emojis and clean typography.

---

### Component 2: webhook_server.py Dynamic and Rich Entry Notifications

Modify `/Users/mac/sinyalbingx/webhook_server.py` to:
1. Implement dynamic status header formatting (🟢 Success, 🟡 Ignored, 🔴 Failed).
2. Fetch transaction details (leverage, risk percent, margin size) from `active_trade_data` to present rich risk metrics on success.
3. Provide descriptive explanations for ignored or failed signals.

#### [MODIFY] [webhook_server.py](file:///Users/mac/sinyalbingx/webhook_server.py)

- [ ] **Step 5: Refactor `run_async_execution` Telegram message formatting**
  Rewrite the message construction logic in `run_async_execution` of [webhook_server.py](file:///Users/mac/sinyalbingx/webhook_server.py) (around lines 33-50) to format the output text based on execution status, including leverage and margin calculations for successful entries.

---

## Verification Plan

### Automated/Simulation Tests
- Run simulation script `/Users/mac/sinyalbingx/tests/simulasi_trading.py` if available to ensure system integrity.
- Run `python -m unittest` or execute the files directly to verify no syntax or runtime import errors are introduced:
  `python -c "import webhook_server; print('webhook_server ok')"`
  `python -c "import order_manager; print('order_manager ok')"`

### Manual Verification
- Deploy to Railway (or run locally in testing environment) and trigger a mock webhook signal to verify correct formatting of:
  1. Success entry notification (displaying leverage, margin, and risk applied).
  2. Ignored signal notification (e.g. sending a duplicate signal to trigger `already_open` or `slots_full`).
- Open a trade, then close it on the exchange (or mock a position removal in paper mode) to verify that the close notification is sent immediately and realized PnL is calculated accurately.

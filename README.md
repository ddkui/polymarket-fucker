# BTC Polymarket 5m/15m Trading Bot

A Python trading bot for BTC up/down prediction markets on Polymarket, combining edges from three open-source bots.

## Reference Bot Analysis

### discountry/polymarket-trading-bot
**Edge:** Clean strategy framework with pluggable strategies, real-time WebSocket orderbook data, and automatic market switching when 15-minute windows expire. Uses a flash-crash detection strategy that buys when a token's probability drops suddenly. Basic position management with take-profit and stop-loss levels.

### Gabagool/polymarket-trading-bot-python
**Edge:** Comprehensive risk management for short-term (5-minute) markets. Features: per-trade risk sizing (0.8% of account), position cap (25% of balance), consecutive-loss cooldowns (pause after 5 losses), session drawdown limits (4%), daily drawdown limits (8%), and pre-trade filters (time-to-resolution, volatility checks, z-score mean-reversion filter). Supports dry-run mode for paper trading. Uses pydantic-settings for clean configuration via environment variables.

### 0xrsydn/polymarket-streak-bot
**Edge:** BTC 5-minute streak reversal — detects when BTC has gone the same direction multiple times in a row and bets on the reversal. Uses historical backtest data showing ~67% reversal rate after 4 consecutive same-direction closes. Implements fractional Kelly criterion (quarter-Kelly) for conservative position sizing. Tracks bankroll, daily bet limits, and daily loss limits.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # Edit .env with your keys
# Review config.yaml          # Adjust thresholds and risk limits

# 3. Run in dry-run mode (no real trades)
python main.py

# 4. Run with real trades (after setting dry_run: false in config.yaml)
python main.py

# 5. Run dashboard only
python dashboard.py
```

## Project Structure

```
btc-polymarket-5m-15m-bot/
├── main.py              ← Bot entry point + main loop
├── config.yaml          ← All settings (thresholds, risk, dashboard)
├── .env.example         ← Template for secrets (copy to .env)
├── requirements.txt     ← Python dependencies
├── polymarket_client.py ← Polymarket API wrapper
├── market_filter.py     ← Liquidity/spread/timing filters
├── strategy.py          ← Combined trading logic
├── streak_filter.py     ← Streak detection + mean reversion
├── risk.py              ← Risk management engine
├── learning.py          ← Adaptive layer (learn from mistakes)
├── logging_utils.py     ← Structured logging + SQLite trade DB
├── dashboard.py         ← Flask web dashboard (password-protected)
├── docs/
│   ├── STRATEGY.md      ← Strategy explanation (plain English)
│   └── DASHBOARD.md     ← Dashboard setup guide
├── logs/                ← Log files (auto-created)
└── data/                ← SQLite database (auto-created)
```

## What To Edit

| Setting | File | Section |
|---------|------|---------|
| Risk limits (max loss, position size) | `config.yaml` | `risk:` |
| Strategy thresholds (edge, streak) | `config.yaml` | `price_edge:` and `streak_filter:` |
| Learning/adaptation behaviour | `config.yaml` | `learning:` |
| Dashboard password | `.env` | `DASHBOARD_PASSWORD` |
| Dashboard port | `config.yaml` | `dashboard: port:` |
| API keys & wallet | `.env` | All `*_KEY` / `*_SECRET` vars |

## Commands

```bash
# Install
pip install -r requirements.txt

# Run bot (dry-run by default)
python main.py

# Force dry-run from CLI
python main.py --dry-run

# Run without dashboard
python main.py --no-dashboard

# Run dashboard standalone
python dashboard.py
```

# Combined Strategy — Plain-English Explanation

This document explains how the bot decides when and what to trade, in simple language.

---

## What We Trade

The bot only trades **BTC (Bitcoin) 5-minute and 15-minute up/down markets** on Polymarket. These are prediction markets that ask: _"Will BTC go up or down in the next 5 (or 15) minutes?"_

You can buy "UP" tokens (which pay out if BTC goes up) or "DOWN" tokens (which pay out if BTC goes down). The prices of these tokens act like probabilities — if "UP" costs $0.60, the market thinks there's a ~60% chance BTC will go up.

---

## How the Bot Finds an Edge

The bot uses **three layers** of logic before placing a trade:

### Layer 1: Market & Liquidity Filter

Before even looking at a trade, the bot checks:

- **Is this actually a BTC 5m or 15m market?** (Ignores everything else.)
- **Is the spread small enough?** The "spread" is the gap between the best buy and sell prices. A big spread means it's expensive to trade. The bot skips markets where the spread is too wide.
- **Is there enough liquidity?** If nobody is trading the market, it's hard to get in and out. The bot skips illiquid markets.
- **Is there enough time left?** The bot won't try to enter a market that's about to close.

### Layer 2: Price-Move Edge (The Main Signal)

This is the core idea: **Polymarket prices sometimes lag behind real BTC price moves.**

Here's how it works:

1. The bot watches the actual BTC price on an exchange (Binance, Coinbase, or CoinGecko).
2. It compares BTC's real move to what Polymarket's odds are saying.
3. If BTC has moved up significantly but the Polymarket "UP" token hasn't caught up yet, there's an opportunity: the "UP" token is underpriced relative to reality.
4. The bot only trades when this "lag" exceeds a configurable threshold.

**In plain terms:** The bot buys a prediction that's cheaper than it should be, based on what Bitcoin is actually doing right now.

### Layer 3: Streak / Mean-Reversion Filter (Confirmation)

This layer looks at recent history:

- If BTC has gone UP four times in a row (a "streak"), historical data says it's more likely to go DOWN next time.
- The bot tracks these streaks and uses them to confirm or add confidence to trades.
- It uses real backtest data showing reversal rates: after 4 consecutive ups, the reversal rate is about 67%.

**This filter doesn't override the price-edge signal** — it adds extra confidence when both signals agree.

---

## Risk Management

The bot has strict limits to prevent catastrophic losses:

| Rule | What It Does |
|------|-------------|
| **Max position per trade** | Never risk more than $1 (configurable) on a single trade. |
| **Max total open exposure** | Never have more than $75 (configurable) at risk across all positions. |
| **Max daily loss** | Stop trading for the day after losing $50 (configurable). |
| **Cooldown after losses** | After 3 consecutive losses, sit out 6 windows before trading again. |
| **Kill switch** | A flag in config.yaml that instantly stops all trading. |

---

## Adaptive Learning (Learning from Mistakes)

The bot keeps track of how each strategy performs and adjusts automatically:

1. **Every trade is tagged** with the strategy parameters used and the market "regime" (trending, choppy, or mixed).
2. The bot tracks win rates per regime and per parameter set over a rolling window of the last 50 trades.
3. **If a particular combination is losing**, the bot automatically:
   - Reduces position sizes for that combo (e.g., cuts them in half).
   - Requires a stronger edge before trading (tightens the threshold).
4. **If the overall win rate drops below 30%**, the bot disables itself entirely until conditions improve.

---

## Position Sizing

The bot uses **quarter-Kelly criterion** for sizing:

- The Kelly formula calculates the optimal bet size based on your edge and the odds.
- "Quarter Kelly" means the bot bets only 25% of what Kelly says — this is very conservative and reduces variance.
- The final size is then capped by all the risk limits above.

---

## Summary of Where Each Idea Comes From

| Feature | Inspired By |
|---------|-------------|
| Clean structure + strategy framework | discountry/polymarket-trading-bot |
| Risk management + daily limits + cooldowns | Gabagool/polymarket-trading-bot-python |
| Streak detection + mean reversion + Kelly sizing | 0xrsydn/polymarket-streak-bot |
| Price-move / latency edge | Common to many 5-minute market bots |
| Adaptive learning layer | Custom addition for this bot |

"""
strategy.py – Combined Trading Logic
=====================================
Brings together all three edges:

  1. Market + liquidity filter   (from market_filter.py)
  2. Price-move / latency edge   (BTC price vs Polymarket odds)
  3. Streak / mean-reversion     (from streak_filter.py)

Plus risk management (risk.py) and adaptive adjustments (learning.py).
"""

import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from polymarket_client import PolymarketClient
from market_filter import MarketFilter
from streak_filter import StreakFilter, StreakSignal
from risk import RiskManager
from learning import AdaptiveLayer
from logging_utils import TradeDB

logger = logging.getLogger("btc_bot")


class CombinedStrategy:
    """
    Main trading strategy for BTC 5-minute and 15-minute
    Polymarket up/down markets.

    On each tick:
      1. Discover available BTC markets.
      2. Filter by liquidity / spread / time.
      3. For each market, check the price-move edge.
      4. If edge exists, check the streak filter for confirmation.
      5. Apply risk and adaptive checks.
      6. Place the trade (or log it in dry-run mode).
    """

    def __init__(self, config: Dict[str, Any], trade_db: TradeDB):
        self.config = config
        self.db = trade_db

        # Sub-components
        self.client = PolymarketClient(config)
        self.market_filter = MarketFilter(config)
        self.streak_filter = StreakFilter(config)
        self.risk_manager = RiskManager(config)
        self.adaptive = AdaptiveLayer(config)

        # Price-edge settings
        pe = config.get("price_edge", {})
        self.btc_price_source = pe.get("btc_price_source", "coingecko")
        self.latency_threshold = pe.get("latency_threshold", 0.02)
        self.price_poll_interval = pe.get("price_poll_interval", 3)

        # Bankroll tracking (starts with a notional value; in real use
        # this would be read from the wallet or a state file)
        self.bankroll = 1000.0

        # Track BTC price at the start of each window
        self._window_start_prices: Dict[str, float] = {}  # market_slug -> btc_price

        # Track open exposure
        self._open_exposure_usd = 0.0

    # ------------------------------------------------------------------
    # Main tick — called once per cycle from main.py
    # ------------------------------------------------------------------

    def tick(self):
        """
        Run one full strategy cycle:
        discover → filter → edge check → streak check → risk → trade.
        """
        # 0) Quick risk gate
        allowed, reason = self.risk_manager.is_trading_allowed()
        if not allowed:
            logger.info(f"Trading paused: {reason}")
            self.db.set_status("paused" if "Cooldown" in reason else "daily_limit")
            self.risk_manager.tick_cooldown()
            return

        self.db.set_status("running")

        # 1) Discover BTC markets
        markets = self.client.find_btc_markets(
            timeframes=self.config.get("timeframes", [5, 15])
        )
        if not markets:
            logger.debug("No active BTC markets found")
            return

        # 2) Filter markets
        def get_ob(token_id):
            return self.client.get_orderbook(token_id)

        def get_seconds_remaining(m):
            end = m.get("end_date", "")
            if not end:
                return 999
            try:
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                return (end_dt - datetime.now(timezone.utc)).total_seconds()
            except Exception:
                return 999

        tradeable = self.market_filter.filter_markets(
            markets,
            get_orderbook_fn=get_ob,
            get_seconds_remaining_fn=get_seconds_remaining,
        )

        if not tradeable:
            logger.debug("No markets passed filters")
            return

        # 3) For each tradeable market, check for an edge
        btc_price = self.client.get_btc_price(self.btc_price_source)
        if btc_price is None:
            logger.warning("Could not fetch BTC price — skipping this cycle")
            return

        for market in tradeable:
            self._evaluate_market(market, btc_price)

    # ------------------------------------------------------------------
    # Per-market evaluation
    # ------------------------------------------------------------------

    def _evaluate_market(self, market: Dict[str, Any], btc_price: float):
        """Check a single market for a trade opportunity."""
        slug = market.get("slug", "")
        tf = market.get("timeframe", 5)
        prices = market.get("prices", {})
        up_price = prices.get("up", 0.5)
        down_price = prices.get("down", 0.5)

        # --- Price-Move Edge -------------------------------------------
        # Compare current BTC price to the window's starting price.
        # If we haven't seen this market before, record the start price.
        if slug not in self._window_start_prices:
            self._window_start_prices[slug] = btc_price
            logger.debug(f"Recorded start price for {slug}: ${btc_price:,.2f}")
            return  # need at least one more tick to compute move

        start_price = self._window_start_prices[slug]
        btc_move_pct = (btc_price - start_price) / start_price

        # Polymarket implied probability
        # If BTC moves UP, the "up" token should be > 0.5
        # The "lag" is the difference between BTC's actual move direction
        # and what Polymarket odds imply.
        if btc_move_pct > 0:
            # BTC went up — "up" should be expensive
            poly_implied_up = up_price
            edge = btc_move_pct - (poly_implied_up - 0.5)
            direction = "up"
        elif btc_move_pct < 0:
            # BTC went down — "down" should be expensive
            poly_implied_down = down_price
            edge = abs(btc_move_pct) - (poly_implied_down - 0.5)
            direction = "down"
        else:
            return  # no move yet

        # Get adaptive threshold bump
        # Classify regime from recent outcomes
        outcomes = self.client.get_recent_outcomes(tf, count=10)
        regime = self.streak_filter.classify_regime(outcomes) if outcomes else "unknown"
        strategy_tag = f"tf{tf}_{regime}"

        adjustments = self.adaptive.get_adjustments(regime, strategy_tag)
        effective_threshold = self.latency_threshold + adjustments["threshold_bump"]

        if edge < effective_threshold:
            logger.debug(
                f"[{slug}] Edge {edge:.4f} < threshold {effective_threshold:.4f}"
            )
            return

        logger.info(
            f"[{slug}] Price edge detected: BTC move {btc_move_pct:+.4f}, "
            f"edge={edge:.4f} ≥ threshold {effective_threshold:.4f}, "
            f"direction={direction}"
        )

        # --- Streak Filter (confirmation) --------------------------------
        if self.streak_filter.enabled and outcomes:
            streak_signal = self.streak_filter.evaluate(outcomes)
            if streak_signal.should_trade:
                # Streak agrees with our direction? Use it.
                # Streak disagrees? Still trade the price-edge direction,
                # but streak adds extra confidence.
                if streak_signal.direction == direction:
                    logger.info(
                        f"[{slug}] Streak confirms direction ({streak_signal.reason})"
                    )
                else:
                    logger.info(
                        f"[{slug}] Streak suggests {streak_signal.direction}, "
                        f"but price-edge points {direction}. Going with price-edge."
                    )
            # If streak says NO signal, the price edge alone is enough.

        # --- Position Sizing with Risk + Adaptive adjustments -------------
        entry_price = up_price if direction == "up" else down_price
        if entry_price <= 0:
            entry_price = 0.5

        # Kelly-based size (from streak filter helper)
        confidence = 0.55 + edge  # edge adds to baseline confidence
        odds = 1.0 / entry_price
        kelly_size = self.streak_filter.kelly_size(
            confidence, odds, self.bankroll, fraction=0.25
        )

        # Apply adaptive size reduction
        desired_size = kelly_size * adjustments["size_multiplier"]

        # Cap with risk manager
        final_size = self.risk_manager.cap_position_size(
            desired_size,
            self._open_exposure_usd,
        )

        # Floor: if calculated size is below $1, round up to $1
        if 0 < final_size < 1.0:
            final_size = 1.0

        if final_size <= 0:
            logger.info(f"[{slug}] Position size capped to $0 — skipping")
            return

        # Run full risk check
        allowed, reason = self.risk_manager.check_trade(
            final_size, self._open_exposure_usd,
        )
        if not allowed:
            logger.warning(f"[{slug}] Risk blocked: {reason}")
            return

        # --- Execute Trade ------------------------------------------------
        token_id = market["token_ids"].get(direction, "")
        if not token_id:
            logger.error(f"[{slug}] No token_id for direction '{direction}'")
            return

        # Calculate number of shares
        shares = final_size / entry_price
        buy_price = min(entry_price + 0.02, 0.99)  # small buffer for fill

        result = self.client.place_order(
            token_id=token_id,
            side="BUY",
            price=buy_price,
            size=round(shares, 1),
        )

        if result.get("success"):
            logger.info(
                f"✅ TRADE: {direction.upper()} on {slug} | "
                f"${final_size:.2f} @ {entry_price:.4f} | "
                f"regime={regime}"
            )
            # Record in database
            trade_id = self.db.record_trade({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market": slug,
                "timeframe": tf,
                "side": "BUY",
                "direction": direction,
                "entry_price": entry_price,
                "size_usd": final_size,
                "strategy_tag": strategy_tag,
                "regime": regime,
                "params": {
                    "edge": round(edge, 4),
                    "threshold": round(effective_threshold, 4),
                    "btc_move": round(btc_move_pct, 4),
                    "confidence": round(confidence, 3),
                    "kelly_raw": round(kelly_size, 2),
                    "adaptive_mult": adjustments["size_multiplier"],
                },
            })

            self._open_exposure_usd += final_size

            # Clean up window start price (trade placed)
            self._window_start_prices.pop(slug, None)
        else:
            logger.warning(
                f"❌ Order failed for {slug}: {result.get('message', 'unknown')}"
            )

    # ------------------------------------------------------------------
    # Settlement — called when a market resolves
    # ------------------------------------------------------------------

    def settle_open_trades(self):
        """
        Check all open trades in the DB.  For any whose market has
        resolved, settle and record the PnL.
        """
        open_trades = self.db.get_open_trades()
        for trade in open_trades:
            market_slug = trade["market"]
            tf = trade["timeframe"]
            direction = trade["direction"]

            # Fetch recent outcomes to see if this market has resolved
            outcomes = self.client.get_recent_outcomes(tf, count=3)
            if not outcomes:
                continue

            # The most recent outcome is for the most recent closed market.
            # We match by checking if the trade's market is now closed.
            # For simplicity, we assume the trade was for the previous window
            # and check the latest outcome.
            latest_outcome = outcomes[-1] if outcomes else None
            if latest_outcome is None:
                continue

            # Determine win/loss
            won = (direction == latest_outcome)
            entry_price = trade["entry_price"]
            size_usd = trade["size_usd"]

            if won:
                # Win: payout is (1/entry_price - 1) * size_usd
                # minus fees (approximately 2%)
                payout = size_usd * (1.0 / entry_price - 1) * 0.98
                pnl = payout
                result = "win"
            else:
                # Loss: lose the entire stake
                pnl = -size_usd
                result = "loss"

            # Close trade in DB
            exit_price = 1.0 if won else 0.0
            self.db.close_trade(trade["id"], exit_price, pnl, result)

            # Update risk manager
            self.risk_manager.record_result(pnl)
            self.bankroll += pnl
            self._open_exposure_usd = max(0, self._open_exposure_usd - size_usd)

            # Update adaptive layer
            regime = trade.get("regime", "unknown")
            strategy_tag = trade.get("strategy_tag", "default")
            self.adaptive.record({
                "result": result,
                "pnl": pnl,
                "regime": regime,
                "strategy_tag": strategy_tag,
            })

            emoji = "✓" if won else "✗"
            logger.info(
                f"[{emoji}] Settled {trade['market']}: {direction} → {latest_outcome} | "
                f"PnL: ${pnl:+.2f} | Bankroll: ${self.bankroll:.2f}"
            )

        # Record equity snapshot
        stats = self.db.get_stats()
        self.db.record_equity(
            equity=self.bankroll,
            realized=stats["total_pnl"],
            unrealized=0,  # simple model: no unrealized tracking
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def push_status_update(self):
        """Push current bot health/market state to DB for dashboard."""
        btc_price = self.client.get_btc_price(self.btc_price_source)
        
        # Get active markets to show countdowns/edges
        markets = self.client.find_btc_markets(
            timeframes=self.config.get("timeframes", [5, 15])
        )
        
        market_states = []
        for m in (markets or []):
            end_date = m.get("end_date", "")
            seconds_left = 0
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    seconds_left = (end_dt - datetime.now(timezone.utc)).total_seconds()
                except:
                    pass
            
            market_states.append({
                "slug": m.get("slug", ""),
                "timeframe": m.get("timeframe", 5),
                "seconds_left": int(seconds_left),
                "up_price": m.get("prices", {}).get("up", 0.5),
                "down_price": m.get("prices", {}).get("down", 0.5)
            })

        state = {
            "btc_price": btc_price,
            "btc_source": self.btc_price_source,
            "markets": market_states,
            "bankroll": self.bankroll,
            "open_exposure": self._open_exposure_usd,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        self.db.set_status("running", state=state)

    def cleanup_stale_windows(self):
        """Remove stale window-start-price entries for markets that expired."""
        # Keep only recent entries (max 20)
        if len(self._window_start_prices) > 20:
            # Remove oldest entries
            keys = list(self._window_start_prices.keys())
            for k in keys[:-10]:
                del self._window_start_prices[k]

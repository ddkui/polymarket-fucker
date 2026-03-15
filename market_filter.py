"""
market_filter.py – Decide which markets are tradeable
=====================================================
Checks:
  1. Is this a BTC 5-minute or 15-minute up/down market?
  2. Does the orderbook spread pass the max-spread filter?
  3. Is there enough liquidity?
  4. Is there enough time left before the market closes?
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("btc_bot")


class MarketFilter:
    """
    Filters Polymarket BTC markets based on liquidity, spread,
    and time-to-close constraints loaded from config.yaml.
    """

    def __init__(self, config: Dict[str, Any]):
        mf = config.get("market_filter", {})
        self.min_liquidity = mf.get("min_liquidity_usd", 500)
        self.max_spread = mf.get("max_spread", 0.08)
        self.min_seconds_before_close = mf.get("min_seconds_before_close", 45)
        self.timeframes = config.get("timeframes", [5, 15])

    # ------------------------------------------------------------------

    def passes(
        self,
        market: Dict[str, Any],
        orderbook: Optional[Dict[str, Any]] = None,
        seconds_remaining: Optional[float] = None,
    ) -> tuple[bool, str]:
        """
        Check whether a market should be traded.

        Returns:
            (True/False, reason string)
        """
        # 1) Timeframe check
        tf = market.get("timeframe")
        if tf not in self.timeframes:
            return False, f"Timeframe {tf} not in configured list {self.timeframes}"

        # 2) Must be accepting orders
        if not market.get("accepting_orders", False):
            return False, "Market not accepting orders"

        # 3) Time-to-close check
        if seconds_remaining is not None and seconds_remaining < self.min_seconds_before_close:
            return False, (
                f"Only {seconds_remaining:.0f}s left, need ≥{self.min_seconds_before_close}s"
            )

        # 4) Spread check (requires orderbook data)
        if orderbook:
            spread = orderbook.get("spread", 1.0)
            if spread > self.max_spread:
                return False, f"Spread {spread:.4f} > max {self.max_spread}"

            # 5) Liquidity check
            liq = orderbook.get("total_liquidity_usd", 0)
            if liq < self.min_liquidity:
                return False, f"Liquidity ${liq:.0f} < min ${self.min_liquidity}"

        return True, "OK"

    # ------------------------------------------------------------------

    def filter_markets(
        self,
        markets: List[Dict[str, Any]],
        get_orderbook_fn=None,
        get_seconds_remaining_fn=None,
    ) -> List[Dict[str, Any]]:
        """
        Given a list of active BTC markets, return only those that pass
        all filters.

        Args:
            markets: list of market dicts from PolymarketClient.find_btc_markets()
            get_orderbook_fn: callable(token_id) -> orderbook dict
            get_seconds_remaining_fn: callable(market) -> float seconds

        Returns:
            Filtered list of markets.
        """
        passed = []
        for m in markets:
            # Get orderbook for the UP token (if available)
            ob = None
            if get_orderbook_fn and m.get("token_ids", {}).get("up"):
                ob = get_orderbook_fn(m["token_ids"]["up"])

            secs = None
            if get_seconds_remaining_fn:
                secs = get_seconds_remaining_fn(m)

            ok, reason = self.passes(m, ob, secs)
            if ok:
                passed.append(m)
            else:
                logger.debug(f"Market filtered out ({m.get('slug','')}): {reason}")

        return passed

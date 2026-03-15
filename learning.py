"""
learning.py – Adaptive Layer (Simple "Learn from Mistakes")
===========================================================
Tracks recent bot performance and automatically adjusts behaviour:

  • Tags every trade with the strategy parameters and market regime.
  • Evaluates rolling win-rate per regime and parameter set.
  • Reduces position size (or disables) underperforming parameter combos.
  • Tightens entry thresholds after losing streaks.
"""

import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger("btc_bot")


class AdaptiveLayer:
    """
    Reads recent trade results and returns adjustments that the
    strategy should apply before placing the next trade.

    Usage:
        al = AdaptiveLayer(config)
        al.record(trade_result)              # after each trade settles
        adj = al.get_adjustments(regime)      # before each new trade
        # adj["size_multiplier"]  — 0.0 to 1.0
        # adj["threshold_bump"]   — extra edge required (0 to 0.05+)
    """

    def __init__(self, config: Dict[str, Any]):
        lc = config.get("learning", {})
        self.enabled = lc.get("enabled", True)
        self.rolling_window = lc.get("rolling_window", 50)
        self.min_trades = lc.get("min_trades_to_judge", 10)
        self.underperformance_threshold = lc.get("underperformance_threshold", 0.42)
        self.size_reduction = lc.get("size_reduction_factor", 0.5)
        self.tighten_after_losses = lc.get("tighten_threshold_after_losses", True)

        # Trade history ring-buffer (most recent N)
        self._history: List[Dict[str, Any]] = []

        # Performance by regime
        self._regime_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"wins": 0, "losses": 0, "total": 0}
        )

        # Performance by strategy tag / parameter combo
        self._tag_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"wins": 0, "losses": 0, "total": 0}
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, trade_result: Dict[str, Any]):
        """
        Record a settled trade for future adaptation.

        Expected keys:
            result:       "win" or "loss"
            pnl:          float
            regime:       "trend", "chop", or "mixed"
            strategy_tag: free-form string identifying the param set
        """
        if not self.enabled:
            return

        self._history.append(trade_result)
        # Trim to rolling window
        if len(self._history) > self.rolling_window:
            self._history = self._history[-int(self.rolling_window):]

        # Update per-regime stats
        regime = trade_result.get("regime", "unknown")
        is_win = trade_result.get("result") == "win"
        self._regime_stats[regime]["total"] += 1
        if is_win:
            self._regime_stats[regime]["wins"] += 1
        else:
            self._regime_stats[regime]["losses"] += 1

        # Update per-tag stats
        tag = trade_result.get("strategy_tag", "default")
        self._tag_stats[tag]["total"] += 1
        if is_win:
            self._tag_stats[tag]["wins"] += 1
        else:
            self._tag_stats[tag]["losses"] += 1

        # Rebuild stats from the rolling window to stay fresh
        self._rebuild_stats()

    # ------------------------------------------------------------------
    # Adjustments
    # ------------------------------------------------------------------

    def get_adjustments(
        self, regime: str = "unknown", strategy_tag: str = "default"
    ) -> Dict[str, Any]:
        """
        Return adjustments the strategy should apply before trading.

        Returns dict with:
            size_multiplier:  float 0.0–1.0  (1.0 = full size, 0.0 = disabled)
            threshold_bump:   float ≥ 0      (extra latency edge required)
            reason:           human-readable explanation
        """
        if not self.enabled:
            return {
                "size_multiplier": 1.0,
                "threshold_bump": 0.0,
                "reason": "Adaptive layer disabled",
            }

        size_mult = 1.0
        threshold_bump = 0.0
        reasons = []

        # 1) Check regime-specific win-rate
        regime_data = self._regime_stats.get(regime)
        if regime_data and regime_data["total"] >= self.min_trades:
            regime_wr = regime_data["wins"] / regime_data["total"]
            if regime_wr < self.underperformance_threshold:
                size_mult = min(size_mult, self.size_reduction)
                reasons.append(
                    f"Regime '{regime}' win-rate {regime_wr:.1%} "
                    f"< {self.underperformance_threshold:.1%} → size reduced"
                )

        # 2) Check strategy-tag win-rate
        tag_data = self._tag_stats.get(strategy_tag)
        if tag_data and tag_data["total"] >= self.min_trades:
            tag_wr = tag_data["wins"] / tag_data["total"]
            if tag_wr < self.underperformance_threshold:
                size_mult = min(size_mult, self.size_reduction)
                reasons.append(
                    f"Tag '{strategy_tag}' win-rate {tag_wr:.1%} "
                    f"< {self.underperformance_threshold:.1%} → size reduced"
                )

        # 3) Tighten thresholds after recent losing streak
        if self.tighten_after_losses and len(self._history) >= 3:
            recent = self._history[-5:]  # last 5 trades
            recent_losses = sum(1 for t in recent if t.get("result") == "loss")
            if recent_losses >= 3:
                threshold_bump = 0.01 * (recent_losses - 2)  # +1% per extra loss
                reasons.append(
                    f"{recent_losses}/5 recent trades lost → "
                    f"threshold tightened by +{threshold_bump:.2f}"
                )

        # 4) If overall rolling win-rate is very bad, disable completely
        if len(self._history) >= self.min_trades:
            overall_wins = sum(1 for t in self._history if t.get("result") == "win")
            overall_wr = overall_wins / len(self._history)
            if overall_wr < 0.30:
                size_mult = 0.0
                reasons.append(
                    f"Overall win-rate {overall_wr:.1%} dangerously low → DISABLED"
                )

        reason = "; ".join(reasons) if reasons else "No adjustments needed"
        if reasons:
            logger.info(f"[Adaptive] {reason}")

        return {
            "size_multiplier": round(float(size_mult), 2),
            "threshold_bump": round(float(threshold_bump), 4),
            "reason": str(reason),
        }

    # ------------------------------------------------------------------
    # Stats for dashboard
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return learning layer stats for the dashboard."""
        overall_wins = sum(1 for t in self._history if t.get("result") == "win")
        overall_total = len(self._history)

        return {
            "enabled": self.enabled,
            "rolling_window_size": int(overall_total),
            "rolling_win_rate": (
                round(float(overall_wins) / float(overall_total) * 100.0, 1)
                if overall_total > 0 else 0.0
            ),
            "regime_stats": dict(self._regime_stats),
            "tag_stats": dict(self._tag_stats),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_stats(self):
        """Rebuild per-regime and per-tag stats from the rolling window."""
        self._regime_stats.clear()
        self._tag_stats.clear()

        for t in self._history:
            regime = t.get("regime", "unknown")
            tag = t.get("strategy_tag", "default")
            is_win = t.get("result") == "win"

            if regime not in self._regime_stats:
                self._regime_stats[regime] = {"wins": 0, "losses": 0, "total": 0}
            self._regime_stats[regime]["total"] += 1
            if is_win:
                self._regime_stats[regime]["wins"] += 1
            else:
                self._regime_stats[regime]["losses"] += 1

            if tag not in self._tag_stats:
                self._tag_stats[tag] = {"wins": 0, "losses": 0, "total": 0}
            self._tag_stats[tag]["total"] += 1
            if is_win:
                self._tag_stats[tag]["wins"] += 1
            else:
                self._tag_stats[tag]["losses"] += 1

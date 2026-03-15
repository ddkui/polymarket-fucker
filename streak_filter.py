"""
streak_filter.py – Streak / Mean-Reversion Detection
=====================================================
Tracks recent BTC 5-minute (and 15-minute) window outcomes
and decides whether a streak-reversal signal is present.

Inspired by 0xrsydn's polymarket-streak-bot.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("btc_bot")


@dataclass
class StreakSignal:
    """Result of the streak analysis."""
    should_trade: bool        # True if there is a streak signal
    direction: str            # "up" or "down" — the side to BET on (opposite of streak)
    streak_length: int        # how many consecutive same-direction closes
    streak_direction: str     # the direction of the streak itself
    confidence: float         # estimated win probability
    reason: str               # human-readable explanation


# Historical reversal rates from backtests
# (key = streak length, value = probability the streak reverses)
DEFAULT_REVERSAL_RATES = {
    2: 0.540,
    3: 0.579,
    4: 0.667,
    5: 0.824,
}


class StreakFilter:
    """
    Analyzes recent market outcomes to detect streak / mean-reversion
    opportunities.

    Usage:
        sf = StreakFilter(config)
        signal = sf.evaluate(recent_outcomes)
        if signal.should_trade:
            # place bet in signal.direction
    """

    def __init__(self, config: Dict[str, Any]):
        sf_cfg = config.get("streak_filter", {})
        self.enabled = sf_cfg.get("enabled", True)
        self.streak_trigger = sf_cfg.get("streak_trigger", 4)
        self.lookback_windows = sf_cfg.get("lookback_windows", 10)
        self.min_confidence = sf_cfg.get("min_confidence", 0.55)
        self.reversal_rates = sf_cfg.get("reversal_rates", DEFAULT_REVERSAL_RATES)
        # Convert string keys from YAML to ints
        self.reversal_rates = {int(k): v for k, v in self.reversal_rates.items()}

    # ------------------------------------------------------------------
    # Core streak detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_streak(outcomes: List[str]) -> tuple[int, str]:
        """
        Count the current streak at the END of the outcomes list.

        Args:
            outcomes: list of "up" / "down" strings, oldest first.

        Returns:
            (streak_length, streak_direction)
        """
        if not outcomes:
            return 0, ""

        current = outcomes[-1]
        streak = 1
        for i in range(len(outcomes) - 2, -1, -1):
            if outcomes[i] == current:
                streak += 1
            else:
                break
        return streak, current

    # ------------------------------------------------------------------

    def evaluate(self, outcomes: List[str]) -> StreakSignal:
        """
        Decide whether the recent outcomes show a tradeable streak.

        Args:
            outcomes: list of recent outcomes ('up'/'down'), oldest first.

        Returns:
            StreakSignal with the recommendation.
        """
        if not self.enabled:
            return StreakSignal(
                should_trade=False, direction="", streak_length=0,
                streak_direction="", confidence=0,
                reason="Streak filter disabled",
            )

        if len(outcomes) < self.streak_trigger:
            return StreakSignal(
                should_trade=False, direction="", streak_length=0,
                streak_direction="", confidence=0,
                reason=f"Not enough data ({len(outcomes)} outcomes, need ≥{self.streak_trigger})",
            )

        streak_len, streak_dir = self.detect_streak(outcomes)

        if streak_len < self.streak_trigger:
            return StreakSignal(
                should_trade=False,
                direction="",
                streak_length=streak_len,
                streak_direction=streak_dir,
                confidence=0,
                reason=f"Streak {streak_len}× {streak_dir} < trigger {self.streak_trigger}",
            )

        # Bet AGAINST the streak (mean-reversion)
        bet_direction = "down" if streak_dir == "up" else "up"

        # Look up estimated reversal probability; cap at max known length
        max_key = max(self.reversal_rates.keys()) if self.reversal_rates else 5
        confidence = self.reversal_rates.get(
            min(streak_len, max_key),
            self.reversal_rates.get(max_key, 0.6),
        )

        if confidence < self.min_confidence:
            return StreakSignal(
                should_trade=False,
                direction=bet_direction,
                streak_length=streak_len,
                streak_direction=streak_dir,
                confidence=confidence,
                reason=(
                    f"Streak {streak_len}× {streak_dir} reversal rate "
                    f"{confidence:.1%} < min {self.min_confidence:.1%}"
                ),
            )

        return StreakSignal(
            should_trade=True,
            direction=bet_direction,
            streak_length=streak_len,
            streak_direction=streak_dir,
            confidence=confidence,
            reason=(
                f"Streak of {streak_len}× {streak_dir} detected. "
                f"Historical reversal rate: {confidence:.1%}. "
                f"Betting {bet_direction}."
            ),
        )

    # ------------------------------------------------------------------
    # Volatility helpers (optional extra features)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_volatility(outcomes: List[str]) -> float:
        """
        Simple volatility proxy: fraction of direction changes over the
        lookback window.  High value = choppy, low value = trending.
        """
        if len(outcomes) < 2:
            return 0.0
        changes = sum(
            1 for i in range(1, len(outcomes))
            if outcomes[i] != outcomes[i - 1]
        )
        return changes / (len(outcomes) - 1)

    @staticmethod
    def classify_regime(outcomes: List[str]) -> str:
        """
        Classify the recent market regime as 'trend' or 'chop'
        based on simple direction-change volatility.
        """
        vol = StreakFilter.compute_volatility(outcomes)
        if vol > 0.60:
            return "chop"
        elif vol < 0.35:
            return "trend"
        return "mixed"

    # ------------------------------------------------------------------
    # Kelly sizing helper
    # ------------------------------------------------------------------

    @staticmethod
    def kelly_size(
        confidence: float,
        odds: float,
        bankroll: float,
        fraction: float = 0.25,
    ) -> float:
        """
        Calculate bet size using fractional Kelly criterion.

        Args:
            confidence: estimated win probability (0–1)
            odds: decimal odds (1/price)
            bankroll: current bankroll in USD
            fraction: Kelly fraction (0.25 = quarter-Kelly, conservative)

        Returns:
            Recommended bet size in USD.
        """
        if confidence <= 0 or odds <= 1:
            return 0.0
        b = odds - 1
        p = confidence
        q = 1 - p
        kelly = (b * p - q) / b
        if kelly <= 0:
            return 0.0
        return max(1.0, round(bankroll * kelly * fraction, 2))

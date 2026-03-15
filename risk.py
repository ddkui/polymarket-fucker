"""
risk.py – Risk Management Engine
=================================
Enforces:
  • Max position size per trade.
  • Max total open exposure.
  • Max daily loss limit.
  • Cooldown after consecutive losing trades.
  • Global kill switch.

Inspired by Gabagool's comprehensive risk management.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("btc_bot")


class RiskManager:
    """
    Checks every trade against configurable risk limits.

    Usage:
        rm = RiskManager(config)
        allowed, reason = rm.check_trade(size_usd, current_open_exposure)
        if not allowed:
            logger.warning(f"Trade blocked: {reason}")
    """

    def __init__(self, config: Dict[str, Any]):
        r = config.get("risk", {})
        self.max_position_usd = r.get("max_position_usd", 25)
        self.max_open_exposure_usd = r.get("max_open_exposure_usd", 75)
        self.max_daily_loss_usd = r.get("max_daily_loss_usd", 50)
        self.cooldown_after_losses = r.get("cooldown_after_losses", 3)
        self.cooldown_windows = r.get("cooldown_windows", 6)
        self.kill_switch = r.get("kill_switch", False)

        # Runtime state
        self._daily_pnl = 0.0
        self._daily_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._consecutive_losses = 0
        self._cooldown_remaining = 0  # windows left to sit out

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check_trade(
        self,
        proposed_size_usd: float,
        current_open_exposure_usd: float,
    ) -> tuple[bool, str]:
        """
        Run all risk checks for a proposed trade.

        Returns:
            (allowed: bool, reason: str)
        """
        # 0) Kill switch
        if self.kill_switch:
            return False, "Kill switch is ON — all trading halted"

        # 1) Daily loss limit
        self._maybe_reset_daily()
        if self._daily_pnl <= -abs(self.max_daily_loss_usd):
            return False, (
                f"Daily loss limit reached (${self._daily_pnl:.2f} "
                f"vs max -${self.max_daily_loss_usd})"
            )

        # 2) Cooldown
        if self._cooldown_remaining > 0:
            return False, (
                f"Cooling down ({self._cooldown_remaining} windows remaining "
                f"after {self.cooldown_after_losses} consecutive losses)"
            )

        # 3) Max position size
        if proposed_size_usd > self.max_position_usd:
            return False, (
                f"Position ${proposed_size_usd:.2f} > max ${self.max_position_usd}"
            )

        # 4) Max open exposure
        if current_open_exposure_usd + proposed_size_usd > self.max_open_exposure_usd:
            return False, (
                f"Total exposure ${current_open_exposure_usd + proposed_size_usd:.2f} "
                f"> max ${self.max_open_exposure_usd}"
            )

        return True, "OK"

    def cap_position_size(
        self,
        desired_size: float,
        current_open_exposure: float,
    ) -> float:
        """
        Return the largest position size that passes all risk checks,
        up to the desired_size.
        """
        caps = [
            desired_size,
            self.max_position_usd,
            max(0, self.max_open_exposure_usd - current_open_exposure),
        ]
        return max(0.0, min(caps))

    # ------------------------------------------------------------------
    # Trade outcome recording
    # ------------------------------------------------------------------

    def record_result(self, pnl: float):
        """
        Record a trade's PnL to update daily totals and streak tracking.
        Call this after every trade is settled.
        """
        self._maybe_reset_daily()
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.cooldown_after_losses:
                self._cooldown_remaining = self.cooldown_windows
                logger.warning(
                    f"Entering cooldown: {self._consecutive_losses} consecutive losses. "
                    f"Sitting out {self.cooldown_windows} windows."
                )
        else:
            self._consecutive_losses = 0

    def tick_cooldown(self):
        """
        Call once per window to count down the cooldown timer.
        """
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            if self._cooldown_remaining == 0:
                logger.info("Cooldown period ended — trading resumes.")
                self._consecutive_losses = 0

    # ------------------------------------------------------------------
    # Status helpers (for dashboard / logging)
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return current risk state for display."""
        self._maybe_reset_daily()
        if self.kill_switch:
            status = "killed"
        elif self._cooldown_remaining > 0:
            status = "cooldown"
        elif self._daily_pnl <= -abs(self.max_daily_loss_usd):
            status = "daily_limit"
        else:
            status = "active"

        return {
            "status": status,
            "daily_pnl": round(self._daily_pnl, 2),
            "consecutive_losses": self._consecutive_losses,
            "cooldown_remaining": self._cooldown_remaining,
            "kill_switch": self.kill_switch,
        }

    def is_trading_allowed(self) -> tuple[bool, str]:
        """Quick check: is trading currently allowed (ignoring position sizing)?"""
        if self.kill_switch:
            return False, "Kill switch ON"
        self._maybe_reset_daily()
        if self._daily_pnl <= -abs(self.max_daily_loss_usd):
            return False, "Daily loss limit reached"
        if self._cooldown_remaining > 0:
            return False, f"Cooldown ({self._cooldown_remaining} windows left)"
        return True, "OK"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_reset_daily(self):
        """Reset daily counters when the UTC date rolls over."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._daily_date:
            logger.info(
                f"New day ({today}). Resetting daily PnL "
                f"(yesterday: ${self._daily_pnl:+.2f})."
            )
            self._daily_pnl = 0.0
            self._daily_date = today

    def set_kill_switch(self, value: bool):
        """Programmatically set the kill switch."""
        self.kill_switch = value
        state = "ON — all trading halted" if value else "OFF — trading allowed"
        logger.warning(f"Kill switch set to {state}")

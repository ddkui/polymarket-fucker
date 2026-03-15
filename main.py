"""
main.py – Bot Entry Point
==========================
Starts the trading bot loop.

Usage:
    python main.py              # runs with defaults from config.yaml
    python main.py --dry-run    # force dry-run mode
"""

import os
import sys
import time
import signal
import argparse
import threading
import yaml
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv(override=True)

from logging_utils import setup_logger, TradeDB
from strategy import CombinedStrategy

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_running = True

def _handle_signal(sig, frame):
    global _running
    print("\n[bot] Shutting down gracefully...")
    _running = False

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_config(path: str = "config.yaml") -> dict:
    """Load config.yaml and return as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def start_dashboard(config: dict):
    """Start the Flask dashboard in a background thread."""
    if not config.get("dashboard", {}).get("enabled", False):
        return

    try:
        from dashboard import create_app
        app = create_app(config)
        port = config["dashboard"].get("port", 8050)
        host = config["dashboard"].get("host", "0.0.0.0")

        # Run Flask in a daemon thread so it dies with the main process
        thread = threading.Thread(
            target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
            daemon=True,
        )
        thread.start()
        print(f"[dashboard] Web dashboard running at http://{host}:{port}")
    except Exception as e:
        print(f"[dashboard] Failed to start: {e}")


def main():
    global _running

    # --- Parse CLI args ---
    parser = argparse.ArgumentParser(description="BTC Polymarket 5m/15m Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Override config: force dry-run mode")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable web dashboard")
    args = parser.parse_args()

    # --- Load config ---
    config = load_config(args.config)

    if args.dry_run:
        config["dry_run"] = True
    if args.no_dashboard:
        config.setdefault("dashboard", {})["enabled"] = False

    # --- Setup logging ---
    log_cfg = config.get("logging", {})
    logger = setup_logger(
        level=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("log_file", "logs/bot.log"),
    )

    # --- Setup trade database ---
    db = TradeDB(db_path=log_cfg.get("db_file", "data/trades.db"))

    # --- Print startup banner ---
    mode = "DRY RUN" if config.get("dry_run", True) else "LIVE"
    timeframes = config.get("timeframes", [5, 15])

    logger.info("=" * 60)
    logger.info(f"  BTC Polymarket Bot — {mode} mode")
    logger.info(f"  Timeframes:    {timeframes}")
    logger.info(f"  Max position:  ${config.get('risk', {}).get('max_position_usd', 25)}")
    logger.info(f"  Max daily loss: ${config.get('risk', {}).get('max_daily_loss_usd', 50)}")
    logger.info(f"  Kill switch:   {config.get('risk', {}).get('kill_switch', False)}")
    logger.info(f"  Dashboard PWD: '{os.getenv('DASHBOARD_PASSWORD', 'admin')}'")
    logger.info("=" * 60)

    # --- Start dashboard ---
    if not args.no_dashboard:
        start_dashboard(config)

    # --- Create strategy ---
    strategy = CombinedStrategy(config, db)
    db.set_status("running")

    # --- Main loop ---
    poll_interval = config.get("price_edge", {}).get("price_poll_interval", 3)
    settle_interval = 30  # check for settled trades every 30s
    last_settle = 0

    logger.info(f"Bot started. Polling every {poll_interval}s.")

    while _running:
        try:
            now = time.time()

            # Run strategy tick
            strategy.tick()

            # Periodically settle open trades
            if now - last_settle > settle_interval:
                strategy.settle_open_trades()
                strategy.cleanup_stale_windows()
                last_settle = now

            # Push detailed status to DB for dashboard
            strategy.push_status_update()

            # Wait
            time.sleep(poll_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(10)

    # --- Shutdown ---
    db.set_status("stopped")
    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()

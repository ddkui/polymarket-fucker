"""
test_trade.py – Place a single fake simulated trade to test the full pipeline.
Run with: py test_trade.py
"""
import os
import yaml
from dotenv import load_dotenv
load_dotenv(override=True)

from logging_utils import setup_logger, TradeDB

# Setup
logger = setup_logger(level="INFO", log_file="logs/bot.log")
config = {}
if os.path.exists("config.yaml"):
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

db_path = config.get("logging", {}).get("db_file", "data/trades.db")
db = TradeDB(db_path)

# Place a fake test trade
import time
trade = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "market": "TEST - Will BTC go up in the next 5 minutes?",
    "condition_id": "test-condition-001",
    "token_id": "test-token-001",
    "direction": "up",
    "timeframe": 5,
    "entry_price": 0.52,
    "size_usd": 1.00,
    "confidence": 0.62,
    "strategy_tag": "test_trade",
    "regime": "test",
    "dry_run": True,
    "result": None,  # still "open"
    "pnl": None,
}

db.record_trade(trade)
db.record_equity(0.0, 0.0, 0.0)  # starting equity

print("=" * 50)
print("  [SUCCESS] TEST TRADE PLACED SUCCESSFULLY!")
print("=" * 50)
print(f"  Market:    {trade['market']}")
print(f"  Direction: {trade['direction'].upper()}")
print(f"  Size:      ${trade['size_usd']:.2f}")
print(f"  Price:     {trade['entry_price']}")
print(f"  Time:      {trade['timestamp']}")
print("=" * 50)
print()
print("  Now go to http://localhost:8050 and check:")
print("    -> Overview page: should show 1 open position")
print("    -> Positions page: should show the test trade")
print("    -> History page: should show it as 'OPEN'")
print()
print("  To simulate a WIN, run:  py test_trade.py win")
print("  To simulate a LOSS, run: py test_trade.py loss")
print()

# If user passed 'win' or 'loss' as argument, settle the test trade
import sys
if len(sys.argv) > 1 and sys.argv[1].lower() in ("win", "loss"):
    result = sys.argv[1].lower()
    pnl = 0.92 if result == "win" else -1.00

    # Update the most recent test trade
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE trades SET result = ?, pnl = ? WHERE strategy_tag = 'test_trade' AND result IS NULL ORDER BY rowid DESC LIMIT 1",
            (result, pnl)
        )
        conn.commit()
        conn.close()

        db.record_equity(pnl, pnl, 0.0)

        color = "WIN" if result == "win" else "LOSS"
        print(f"  {color} Test trade settled as {result.upper()}! PnL: ${pnl:+.2f}")
        print("  Refresh your dashboard to see the updated stats!")
    except Exception as e:
        print(f"  Error settling trade: {e}")

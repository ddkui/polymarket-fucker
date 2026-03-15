"""
force_live_trade.py
-------------------
Forces a REAL live trade on the current BTC 5-minute market.
Uses your actual config (dry_run: false) and real API credentials.
"""
import os
import json
import yaml
import time
from dotenv import load_dotenv

load_dotenv(override=True)
config = {}
if os.path.exists("config.yaml"):
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

# Use the real config — do NOT override dry_run
print(f"[CONFIG] dry_run = {config.get('dry_run', True)}")

from polymarket_client import PolymarketClient
from logging_utils import setup_logger, TradeDB

logger = setup_logger(level="INFO", log_file="logs/bot.log")
db_path = config.get("logging", {}).get("db_file", "data/trades.db")
db = TradeDB(db_path)

client = PolymarketClient(config)

# Find the current active 5m BTC market
print("[SEARCH] Looking for active BTC 5-minute market...")
markets = client.find_btc_markets(timeframes=[5])

if not markets:
    print("[ERROR] No active 5m BTC market found right now.")
    print("        Try again in a minute when the next 5-min window opens.")
    exit(0)

market = markets[0]
question = market["question"]
token_id_up = market["token_ids"].get("up", "")

if not token_id_up:
    print("[ERROR] No UP token found for this market.")
    exit(0)

print(f"[FOUND] {question}")
print(f"[FETCH] Getting real-time orderbook...")

orderbook = client.get_orderbook(token_id_up)
best_ask = orderbook.get("best_ask", 0.5)
best_bid = orderbook.get("best_bid", 0.5)
spread = orderbook.get("spread", 0)
liquidity = orderbook.get("total_liquidity_usd", 0)

btc_price = client.get_btc_price()
if not btc_price:
    btc_price = 0.0

print("=" * 60)
print(f"FORCING A LIVE TRADE - BTC UP 5 MIN")
print("=" * 60)
print(f"BTC Price   : ${btc_price:,.2f}")
print(f"Market      : {question}")
print(f"Best Bid    : ${best_bid:.4f}")
print(f"Best Ask    : ${best_ask:.4f}")
print(f"Spread      : ${spread:.4f}")
print(f"Liquidity   : ${liquidity:,.2f}")
print(f"Mode        : {'LIVE' if not config.get('dry_run') else 'DRY RUN'}")
print("=" * 60)

# Target a price that we can afford with our current $2.04 balance
# 5 shares is the minimum. We set max price to $0.35 so total cost stays under $2.04.
buy_price = min(best_ask + 0.01, 0.35)
size_shares = 5.0
total_cost = round(size_shares * buy_price, 2)

print(f"[ORDER] Target: ~$1.75 | Actual: {size_shares} shares @ ${buy_price:.4f} (Total: ${total_cost:.2f})")
print("[ORDER] Placing BUY UP order...")
result = client.place_order(token_id_up, "BUY", buy_price, size_shares)
print(f"[RESULT] {result}")

# Log to database only if successful
if result.get("success"):
    trade = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "market": question,
        "timeframe": 5,
        "condition_id": market.get("condition_id", ""),
        "token_id": token_id_up,
        "side": "BUY",
        "direction": "up",
        "entry_price": buy_price,
        "size_usd": round(size_shares * buy_price, 2),
        "confidence": 0.99,
        "strategy_tag": "forced_live_test",
        "regime": "forced",
        "dry_run": config.get("dry_run", True),
        "result": None,
        "pnl": None,
    }
    db.record_trade(trade)
    print("=" * 60)
    print("[DONE] Trade placed and logged to database!")
    print("Check dashboard at http://localhost:8050")
    print("=" * 60)
else:
    print("=" * 60)
    print(f"[FAILED] Trade was NOT placed: {result.get('message')}")
    print("=" * 60)

"""
force_live_test_trade.py
------------------------
Fetches a REAL, currently active Polymarket BTC market (or forces a hardcoded one if the API is empty),
bypasses the strategy filters, and forces the bot to simulate placing a trade on it right now.
"""
import os
import yaml
import time
from dotenv import load_dotenv

# Load config and environment
load_dotenv(override=True)
config = {}
if os.path.exists("config.yaml"):
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

# Ensure we are in Dry Run mode so we don't accidentally spend real money!
config["dry_run"] = True

from polymarket_client import PolymarketClient
from logging_utils import setup_logger, TradeDB

logger = setup_logger(level="INFO", log_file="logs/bot.log")
db_path = config.get("logging", {}).get("db_file", "data/trades.db")
db = TradeDB(db_path)

client = PolymarketClient(config)

print("[SEARCH] Searching for active live BTC markets on Polymarket...")
markets = client.find_btc_markets(timeframes=[5, 15, 60, 1440])  # include broader timeframes just in case

# Fallback: manually fetch any active BTC market if the main search fails
if not markets:
    print("[SEARCH] No 5m/15m markets found. Expanding search to any active BTC market...")
    try:
        import requests
        GAMMA_API = "https://gamma-api.polymarket.com"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(f"{GAMMA_API}/markets", params={"active": "true", "closed": "false", "limit": 25}, headers=headers, timeout=10)
        data = resp.json()
        for m in data:
            question = (m.get("question") or "").lower()
            if True: # Just grab the first active market we see
                tokens = m.get("tokens", [])
                token_ids = {}
                prices = {}
                for tok in tokens:
                    outcome = (tok.get("outcome") or "").lower()
                    if outcome in ("up", "yes"):
                        token_ids["up"] = tok.get("token_id", "")
                        prices["up"] = float(tok.get("price", 0.5))
                if token_ids:
                    markets.append({
                        "slug": m.get("slug", ""),
                        "question": m.get("question", "") + " [LIVE TEST]",
                        "token_ids": token_ids,
                        "prices": prices,
                        "timeframe": "fallback",
                        "accepting_orders": m.get("accepting_orders", False),
                        "condition_id": m.get("condition_id", ""),
                    })
                    break
    except Exception as e:
        print(f"[ERROR] Failed fallback search: {e}")

if not markets:
    print("[ERROR] No active BTC markets found on Polymarket right now.")
    print("[FALLBACK] Because you requested a forced test trade, creating a completely synthetic LIVE trade from current BTC price.")
    
btc_price = client.get_btc_price()
if not btc_price:
    btc_price = 0.0

market_question = "TEST - Will BTC be above current price in 5 mins?"
best_ask = 0.52
token_id_up = "test_token_up_forced"
timeframe = 5

if markets:
    market = markets[0]
    market_question = market['question']
    token_id_up = market["token_ids"].get("up", token_id_up)
    
    print(f"[FETCH] Fetching real-time orderbook...")
    orderbook = client.get_orderbook(token_id_up)
    best_ask = orderbook.get("best_ask", 0.5)

print("=" * 60)
print(f"[*] FORCING A DRY-RUN TRADE ON A LIVE MARKET!")
print("=" * 60)
print(f"Current BTC Price: ${btc_price:,.2f}")
print(f"Market: {market_question}")
print(f"Best Ask Price: ${best_ask:.4f}")

# Call the actual client method to simulate placing the order
order_result = client.place_order(token_id_up, "BUY", best_ask, 1.0)
print(f"Polymarket API Response: {order_result['message']}")

# Log it to the database so it shows up in the dashboard
trade = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "market": market_question,
    "timeframe": timeframe,
    "condition_id": "forced-test-condition",
    "token_id": token_id_up,
    "side": "BUY",
    "direction": "up",
    "entry_price": best_ask,
    "size_usd": 1.00,
    "confidence": 0.99,
    "strategy_tag": "forced_live_test",
    "regime": "forced",
    "dry_run": True,
    "result": None,
    "pnl": None,
}

db.record_trade(trade)
print("=" * 60)
print("[SUCCESS] Trade successfully processed and logged to the database!")
print("Check your dashboard at http://localhost:8050 to see it in your Positions page.")
print("=" * 60)

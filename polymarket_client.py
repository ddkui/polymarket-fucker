"""
polymarket_client.py – Wrapper around Polymarket CLOB + Gamma APIs
==================================================================
Provides helpers to:
  • Discover current BTC 5-minute and 15-minute markets.
  • Read orderbook data (spread, liquidity).
  • Fetch recent market outcomes (for streak detection).
  • Place and cancel orders (respects dry_run mode).
"""

import os
import json
import time
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger("btc_bot")

# Polymarket public endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class PolymarketClient:
    """
    Lightweight wrapper around Polymarket's REST APIs.

    In dry_run mode every order-related call is logged but not executed.
    """

    def __init__(self, config: Dict[str, Any]):
        self.clob_host = os.getenv("CLOB_HOST", CLOB_API)
        self.chain_id = int(os.getenv("CHAIN_ID", "137"))
        self.dry_run = config.get("dry_run", True)

        # API credentials (only needed for real orders)
        self.api_key = os.getenv("API_KEY", "")
        self.api_secret = os.getenv("API_SECRET", "")
        self.api_passphrase = os.getenv("API_PASSPHRASE", "")
        self.private_key = os.getenv("PRIVATE_KEY", "")

        # CLOB client — only initialised if we have credentials and not dry-run
        self._clob_client = None
        if not self.dry_run and self.private_key:
            self._init_clob_client()

        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_clob_client(self):
        """Initialise the py-clob-client for order signing via Gnosis Safe Proxy.

        signature_type=2 + funder=proxy_address routes all trades through
        the Gnosis Safe Proxy Wallet shown on polymarket.com Portfolio.
        """
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            # Proxy wallet address — the account visible on polymarket.com
            proxy_wallet = os.getenv("PROXY_WALLET", "0x03d8D90B5cF01171345539e8fC08c79210B877aB")

            creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase=self.api_passphrase,
            )
            self._clob_client = ClobClient(
                self.clob_host,
                key=self.private_key,
                chain_id=self.chain_id,
                creds=creds,
                signature_type=2,    # Gnosis Safe Proxy — trades visible on website
                funder=proxy_wallet, # The proxy contract that holds the funds
            )
            logger.info("CLOB client initialised (live trading via Proxy Wallet)")
        except Exception as e:
            logger.error(f"Failed to initialise CLOB client: {e}")
            self._clob_client = None

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------

    def find_btc_markets(self, timeframes: List[int] = [5, 15]) -> List[Dict[str, Any]]:
        """
        Deterministically find currently active BTC up/down markets by calculating
        their exact Polymarket slug based on the current UTC time.
        
        Returns a list of market dicts with keys:
            slug, question, end_date, token_ids, prices, timeframe,
            accepting_orders, condition_id
        """
        markets = []
        now = time.time()
        
        try:
            for tf in timeframes:
                # Polymarket slugs are formatted as btc-updown-<tf>m-<timestamp>
                # Where the timestamp is the exact UNIX close time of the market
                tf_secs = tf * 60
                base_time = int(now / tf_secs) * tf_secs
                
                # Wait, Polymarket uses exact start time of the window for the slug (e.g. 11:25:00 for the 11:25-11:30 block)
                for target_time in [base_time, base_time + tf_secs]:
                    slug = f"btc-updown-{tf}m-{int(target_time)}"
                    
                    resp = self._session.get(
                        f"{GAMMA_API}/events",
                        params={"slug": slug},
                        timeout=5,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    
                    if not data:
                        continue
                        
                    event = data[0]
                    found = False
                    for m in event.get("markets", []):
                        if not m.get("active") or m.get("closed"):
                            continue
                            
                        # Extract token IDs — /events endpoint uses clobTokenIds (JSON string)
                        # while /markets endpoint uses tokens (array of dicts)
                        token_ids = {}
                        prices = {}
                        
                        # Try clobTokenIds first (from /events endpoint)
                        clob_ids_raw = m.get("clobTokenIds", "")
                        outcomes_raw = m.get("outcomes", "")
                        outcome_prices_raw = m.get("outcomePrices", "")
                        
                        try:
                            clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
                            outcomes_list = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                            price_list = json.loads(outcome_prices_raw) if isinstance(outcome_prices_raw, str) else outcome_prices_raw
                        except Exception:
                            clob_ids = []
                            outcomes_list = []
                            price_list = []
                        
                        if clob_ids and outcomes_list:
                            for i, label in enumerate(outcomes_list):
                                lbl = label.lower()
                                tid = clob_ids[i] if i < len(clob_ids) else ""
                                price = float(price_list[i]) if i < len(price_list) else 0.5
                                if lbl in ("up", "yes"):
                                    token_ids["up"] = tid
                                    prices["up"] = price
                                elif lbl in ("down", "no"):
                                    token_ids["down"] = tid
                                    prices["down"] = price
                        else:
                            # Fallback: try tokens array (from /markets endpoint)
                            tokens = m.get("tokens", [])
                            for tok in tokens:
                                outcome = (tok.get("outcome") or "").lower()
                                if outcome in ("up", "yes"):
                                    token_ids["up"] = tok.get("token_id", "")
                                    prices["up"] = float(tok.get("price", 0.5))
                                elif outcome in ("down", "no"):
                                    token_ids["down"] = tok.get("token_id", "")
                                    prices["down"] = float(tok.get("price", 0.5))

                        if token_ids:
                            markets.append({
                                "slug": m.get("slug", ""),
                                "question": m.get("question", ""),
                                "end_date": m.get("end_date_iso", m.get("end_date", "")),
                                "token_ids": token_ids,
                                "prices": prices,
                                "timeframe": tf,
                                "accepting_orders": m.get("acceptingOrders", m.get("accepting_orders", False)),
                                "condition_id": m.get("conditionId", m.get("condition_id", "")),
                            })
                            found = True
                            break # don't double count markets inside the event
                            
                    if found:
                        break # Found a valid market for this timeframe, move to the next timeframe

        except Exception as e:
            logger.error(f"Error fetching exact BTC markets: {e}")

        return markets

    def get_recent_outcomes(self, timeframe: int = 5, count: int = 10) -> List[str]:
        """
        Fetch the most recent resolved BTC windows for a given timeframe
        and return their outcomes as a list of 'up' or 'down' strings
        (oldest first).
        Uses deterministic slug lookup — walks backwards through recent 5m/15m windows.
        """
        outcomes: List[str] = []
        try:
            tf_secs = timeframe * 60
            now = time.time()
            base_time = int(now / tf_secs) * tf_secs

            offset = 1  # start one window back (most recently closed)
            checked = 0
            while len(outcomes) < count and checked < count + 15:
                target_time = base_time - (offset * tf_secs)
                offset += 1
                checked += 1

                slug = f"btc-updown-{timeframe}m-{int(target_time)}"
                resp = self._session.get(
                    f"{GAMMA_API}/events",
                    params={"slug": slug},
                    timeout=5,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data:
                    continue

                event = data[0]
                for m in event.get("markets", []):
                    if not m.get("closed", False):
                        continue  # skip still-open markets

                    raw_prices = m.get("outcomePrices", "[]")
                    raw_labels = m.get("outcomes", "[]")
                    try:
                        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                        labels = json.loads(raw_labels) if isinstance(raw_labels, str) else raw_labels
                    except Exception:
                        continue

                    for i, label in enumerate(labels):
                        try:
                            if float(prices[i]) >= 0.99:
                                lbl = label.lower()
                                if lbl in ("up", "yes"):
                                    outcomes.append("up")
                                elif lbl in ("down", "no"):
                                    outcomes.append("down")
                                break
                        except (IndexError, ValueError):
                            continue
                    break  # one market per event

        except Exception as e:
            logger.error(f"Error fetching recent outcomes: {e}")

        outcomes.reverse()  # oldest first
        return outcomes

    # ------------------------------------------------------------------
    # Orderbook data
    # ------------------------------------------------------------------

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch the orderbook for a token.
        Returns dict with 'bids', 'asks', 'spread', 'best_bid', 'best_ask'.
        """
        try:
            resp = self._session.get(
                f"{self.clob_host}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 1.0
            spread = best_ask - best_bid

            # Compute total liquidity
            bid_liq = sum(float(b.get("size", 0)) * float(b.get("price", 0)) for b in bids)
            ask_liq = sum(float(a.get("size", 0)) * float(a.get("price", 0)) for a in asks)

            return {
                "bids": bids,
                "asks": asks,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": spread,
                "mid_price": (best_bid + best_ask) / 2 if best_bid > 0 else best_ask,
                "total_liquidity_usd": bid_liq + ask_liq,
            }
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return {
                "bids": [], "asks": [],
                "best_bid": 0, "best_ask": 1, "spread": 1,
                "mid_price": 0.5, "total_liquidity_usd": 0,
            }

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Dict[str, Any]:
        """
        Place a limit order.  In dry_run mode, just log the order.

        Args:
            token_id: Polymarket token ID
            side:     'BUY' or 'SELL'
            price:    limit price (0-1)
            size:     number of shares

        Returns dict with 'success', 'order_id', 'message'.
        """
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would place {side} order: "
                f"token={token_id[:16]}... price={price:.4f} size={size:.1f}"
            )
            return {
                "success": True,
                "order_id": f"dry-{int(time.time())}",
                "message": "Dry-run order (not sent)",
            }

        if not self._clob_client:
            return {
                "success": False,
                "order_id": None,
                "message": "CLOB client not initialised — check credentials",
            }

        try:
            from py_clob_client.order_builder.constants import BUY, SELL
            from py_clob_client.clob_types import OrderArgs

            order_side = BUY if side.upper() == "BUY" else SELL
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )
            signed_order = self._clob_client.create_order(order_args)
            resp = self._clob_client.post_order(signed_order, "GTC")

            success = resp.get("success", False)
            return {
                "success": success,
                "order_id": resp.get("orderID") or resp.get("order_id"),
                "message": resp.get("errorMsg", "OK") if not success else "Order placed",
            }
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return {"success": False, "order_id": None, "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order by ID. Returns True on success."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel order {order_id}")
            return True

        if not self._clob_client:
            return False

        try:
            self._clob_client.cancel(order_id)
            return True
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False

    # ------------------------------------------------------------------
    # BTC price feeds
    # ------------------------------------------------------------------

    def get_btc_price(self, source: str = "coingecko") -> Optional[float]:
        """
        Fetch the current BTC/USD price from a public API.
        Supported sources: coingecko, binance, coinbase.
        """
        try:
            if source == "binance":
                resp = self._session.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": "BTCUSDT"},
                    timeout=5,
                )
                resp.raise_for_status()
                return float(resp.json()["price"])

            elif source == "coinbase":
                resp = self._session.get(
                    "https://api.coinbase.com/v2/prices/BTC-USD/spot",
                    timeout=5,
                )
                resp.raise_for_status()
                return float(resp.json()["data"]["amount"])

            else:  # coingecko (default)
                resp = self._session.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                    timeout=5,
                )
                resp.raise_for_status()
                return float(resp.json()["bitcoin"]["usd"])

        except Exception as e:
            logger.warning(f"BTC price fetch failed ({source}): {e}")
            return None

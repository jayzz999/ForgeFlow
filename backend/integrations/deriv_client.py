"""ForgeFlow Deriv Integration — Production-quality Deriv WebSocket API client.

Provides real, working Deriv API calls for trading, tick subscriptions,
account management, and market data. Used by generated workflows.

API Docs: https://api.deriv.com/
Auth: API Token via DERIV_API_TOKEN env var, App ID via DERIV_APP_ID env var
Protocol: WebSocket (wss://ws.derivws.com/websockets/v3)
"""

import asyncio
import json
import logging
import os

import websockets

logger = logging.getLogger("forgeflow.integrations.deriv")

WS_URL = "wss://ws.derivws.com/websockets/v3"


class DerivClient:
    """Production Deriv WebSocket API client with reconnection and error handling."""

    def __init__(
        self,
        app_id: str | None = None,
        api_token: str | None = None,
    ):
        self.app_id = app_id or os.getenv("DERIV_APP_ID", "")
        self.api_token = api_token or os.getenv("DERIV_API_TOKEN", "")
        self._ws = None
        self._req_id = 0
        self._authorized = False

        if not self.app_id:
            logger.warning("[Deriv] No DERIV_APP_ID configured")

    @property
    def ws_url(self) -> str:
        return f"{WS_URL}?app_id={self.app_id}"

    async def connect(self):
        """Establish WebSocket connection."""
        if self._ws and not self._ws.closed:
            return
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10,
            )
            logger.info("[Deriv] WebSocket connected")
        except Exception as e:
            logger.error(f"[Deriv] Connection failed: {e}")
            raise

    async def disconnect(self):
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
            self._authorized = False
            logger.info("[Deriv] WebSocket disconnected")

    async def _send(self, payload: dict, timeout: float = 10.0) -> dict:
        """Send a request and wait for response."""
        if not self._ws or self._ws.closed:
            await self.connect()

        self._req_id += 1
        payload["req_id"] = self._req_id

        try:
            await self._ws.send(json.dumps(payload))
            response = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            data = json.loads(response)

            if data.get("error"):
                error_msg = data["error"].get("message", "Unknown error")
                error_code = data["error"].get("code", "")
                logger.error(f"[Deriv] API error: {error_code} — {error_msg}")
                return {"ok": False, "error": error_msg, "error_code": error_code}

            return {"ok": True, **data}

        except asyncio.TimeoutError:
            return {"ok": False, "error": "Request timeout"}
        except websockets.exceptions.ConnectionClosed:
            self._ws = None
            self._authorized = False
            return {"ok": False, "error": "Connection closed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Authentication ───────────────────────────────────────────

    async def authorize(self) -> dict:
        """Authorize with API token.

        Returns:
            {"ok": True, "balance": "1000.00", "currency": "USD",
             "email": "...", "fullname": "..."}
        """
        if not self.api_token:
            return {"ok": False, "error": "No DERIV_API_TOKEN configured"}

        result = await self._send({"authorize": self.api_token})
        if result.get("ok"):
            auth = result.get("authorize", {})
            self._authorized = True
            logger.info(f"[Deriv] Authorized as {auth.get('fullname', 'unknown')}")
            return {
                "ok": True,
                "balance": str(auth.get("balance", "0")),
                "currency": auth.get("currency", "USD"),
                "email": auth.get("email", ""),
                "fullname": auth.get("fullname", ""),
                "loginid": auth.get("loginid", ""),
            }
        return result

    # ── Market Data ──────────────────────────────────────────────

    async def get_active_symbols(self, product_type: str = "basic") -> dict:
        """Get list of active trading symbols.

        Args:
            product_type: "basic" or "full"

        Returns:
            {"ok": True, "symbols": [{"symbol": "R_100", "display_name": "Volatility 100 Index", ...}]}
        """
        result = await self._send({
            "active_symbols": product_type,
        })
        if result.get("ok"):
            symbols = [
                {
                    "symbol": s.get("symbol"),
                    "display_name": s.get("display_name"),
                    "market": s.get("market"),
                    "submarket": s.get("submarket"),
                    "pip": s.get("pip"),
                }
                for s in result.get("active_symbols", [])
            ]
            return {"ok": True, "symbols": symbols, "total": len(symbols)}
        return result

    async def subscribe_ticks(self, symbol: str) -> dict:
        """Subscribe to real-time tick stream for a symbol.

        Args:
            symbol: Trading symbol (e.g., "R_100", "R_75", "frxEURUSD")

        Returns:
            {"ok": True, "tick": {"symbol": "R_100", "quote": 1234.56, "epoch": 1234567890}}
        """
        result = await self._send({
            "ticks": symbol,
            "subscribe": 1,
        })
        if result.get("ok"):
            tick = result.get("tick", {})
            return {
                "ok": True,
                "tick": {
                    "symbol": tick.get("symbol", symbol),
                    "quote": tick.get("quote"),
                    "epoch": tick.get("epoch"),
                    "ask": tick.get("ask"),
                    "bid": tick.get("bid"),
                },
                "subscription_id": result.get("subscription", {}).get("id"),
            }
        return result

    async def get_tick_history(
        self, symbol: str, count: int = 100,
        granularity: int = 60, style: str = "candles"
    ) -> dict:
        """Get historical tick/candle data.

        Args:
            symbol: Trading symbol
            count: Number of data points (max 5000)
            granularity: Candle duration in seconds (60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400)
            style: "candles" or "ticks"

        Returns:
            {"ok": True, "candles": [{"open": ..., "high": ..., "low": ..., "close": ..., "epoch": ...}]}
        """
        payload = {
            "ticks_history": symbol,
            "end": "latest",
            "count": count,
            "style": style,
        }
        if style == "candles":
            payload["granularity"] = granularity

        result = await self._send(payload)
        if result.get("ok"):
            if style == "candles":
                candles = [
                    {
                        "open": c.get("open"),
                        "high": c.get("high"),
                        "low": c.get("low"),
                        "close": c.get("close"),
                        "epoch": c.get("epoch"),
                    }
                    for c in result.get("candles", [])
                ]
                return {"ok": True, "candles": candles, "total": len(candles)}
            else:
                history = result.get("history", {})
                return {
                    "ok": True,
                    "prices": history.get("prices", []),
                    "times": history.get("times", []),
                }
        return result

    # ── Trading ──────────────────────────────────────────────────

    async def get_proposal(
        self, symbol: str, contract_type: str = "CALL",
        duration: int = 5, duration_unit: str = "m",
        amount: float = 10, basis: str = "stake",
        currency: str = "USD"
    ) -> dict:
        """Get a price proposal for a contract.

        Args:
            symbol: Trading symbol (e.g., "R_100")
            contract_type: "CALL" or "PUT" (or "DIGITEVEN", "DIGITODD", etc.)
            duration: Contract duration
            duration_unit: "t" (ticks), "s" (seconds), "m" (minutes), "h" (hours), "d" (days)
            amount: Stake or payout amount
            basis: "stake" or "payout"
            currency: Account currency

        Returns:
            {"ok": True, "proposal_id": "...", "ask_price": 10.00,
             "payout": 19.54, "spot": 1234.56}
        """
        if not self._authorized:
            auth = await self.authorize()
            if not auth.get("ok"):
                return auth

        result = await self._send({
            "proposal": 1,
            "amount": amount,
            "basis": basis,
            "contract_type": contract_type,
            "currency": currency,
            "duration": duration,
            "duration_unit": duration_unit,
            "symbol": symbol,
        })
        if result.get("ok"):
            proposal = result.get("proposal", {})
            return {
                "ok": True,
                "proposal_id": proposal.get("id", ""),
                "ask_price": proposal.get("ask_price"),
                "payout": proposal.get("payout"),
                "spot": proposal.get("spot"),
                "spot_time": proposal.get("spot_time"),
                "date_start": proposal.get("date_start"),
                "date_expiry": proposal.get("date_expiry"),
            }
        return result

    async def buy_contract(self, proposal_id: str, price: float) -> dict:
        """Buy a contract using a proposal ID.

        Args:
            proposal_id: Proposal ID from get_proposal()
            price: Maximum price willing to pay

        Returns:
            {"ok": True, "contract_id": "...", "buy_price": 10.00,
             "balance_after": 990.00, "payout": 19.54}
        """
        if not self._authorized:
            auth = await self.authorize()
            if not auth.get("ok"):
                return auth

        result = await self._send({
            "buy": proposal_id,
            "price": price,
        })
        if result.get("ok"):
            buy = result.get("buy", {})
            logger.info(f"[Deriv] Contract purchased: {buy.get('contract_id')}")
            return {
                "ok": True,
                "contract_id": str(buy.get("contract_id", "")),
                "buy_price": buy.get("buy_price"),
                "balance_after": buy.get("balance_after"),
                "payout": buy.get("payout"),
                "start_time": buy.get("start_time"),
                "longcode": buy.get("longcode", ""),
            }
        return result

    # ── Account ──────────────────────────────────────────────────

    async def get_balance(self, subscribe: bool = False) -> dict:
        """Get account balance.

        Args:
            subscribe: Whether to subscribe to balance updates

        Returns:
            {"ok": True, "balance": "1000.00", "currency": "USD"}
        """
        if not self._authorized:
            auth = await self.authorize()
            if not auth.get("ok"):
                return auth

        payload = {"balance": 1}
        if subscribe:
            payload["subscribe"] = 1

        result = await self._send(payload)
        if result.get("ok"):
            balance = result.get("balance", {})
            return {
                "ok": True,
                "balance": str(balance.get("balance", "0")),
                "currency": balance.get("currency", "USD"),
            }
        return result

    async def get_statement(self, limit: int = 20, offset: int = 0) -> dict:
        """Get account transaction statement.

        Args:
            limit: Number of transactions (max 999)
            offset: Pagination offset

        Returns:
            {"ok": True, "transactions": [...], "count": 20}
        """
        if not self._authorized:
            auth = await self.authorize()
            if not auth.get("ok"):
                return auth

        result = await self._send({
            "statement": 1,
            "description": 1,
            "limit": limit,
            "offset": offset,
        })
        if result.get("ok"):
            stmt = result.get("statement", {})
            transactions = [
                {
                    "action_type": t.get("action_type"),
                    "amount": t.get("amount"),
                    "balance_after": t.get("balance_after"),
                    "transaction_time": t.get("transaction_time"),
                    "longcode": t.get("longcode", ""),
                }
                for t in stmt.get("transactions", [])
            ]
            return {
                "ok": True,
                "transactions": transactions,
                "count": stmt.get("count", len(transactions)),
            }
        return result

    # ── Price Monitoring ─────────────────────────────────────────

    async def monitor_price_movement(
        self, symbol: str, threshold_percent: float = 2.0,
        duration_minutes: int = 5, check_interval: int = 10
    ) -> dict:
        """Monitor a symbol for significant price movement.

        Args:
            symbol: Trading symbol to monitor
            threshold_percent: Percentage change threshold to trigger alert
            duration_minutes: Time window to check (in minutes)
            check_interval: Seconds between checks

        Returns:
            {"ok": True, "triggered": True/False, "change_percent": 2.5,
             "start_price": 1000.00, "current_price": 1025.00}
        """
        await self.connect()

        # Get initial tick
        first_result = await self.subscribe_ticks(symbol)
        if not first_result.get("ok"):
            return first_result

        start_price = first_result["tick"]["quote"]
        start_time = asyncio.get_event_loop().time()
        max_time = duration_minutes * 60

        logger.info(f"[Deriv] Monitoring {symbol} for {threshold_percent}% move over {duration_minutes}min")

        while asyncio.get_event_loop().time() - start_time < max_time:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=check_interval + 5)
                data = json.loads(raw)
                if data.get("msg_type") == "tick":
                    tick = data.get("tick", {})
                    current_price = tick.get("quote", start_price)
                    change = ((current_price - start_price) / start_price) * 100

                    if abs(change) >= threshold_percent:
                        logger.info(f"[Deriv] Alert: {symbol} moved {change:.2f}%")
                        return {
                            "ok": True,
                            "triggered": True,
                            "change_percent": round(change, 2),
                            "start_price": start_price,
                            "current_price": current_price,
                            "symbol": symbol,
                        }
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"[Deriv] Monitor error: {e}")
                break

        return {
            "ok": True,
            "triggered": False,
            "change_percent": 0,
            "start_price": start_price,
            "current_price": start_price,
            "symbol": symbol,
            "message": f"No {threshold_percent}% movement detected in {duration_minutes} minutes",
        }

    # ── Context Manager ──────────────────────────────────────────

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

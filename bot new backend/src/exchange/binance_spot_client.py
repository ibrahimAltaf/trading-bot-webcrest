# src/exchange/binance_spot_client.py

from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN, ROUND_UP

import requests

from src.core.config import get_settings


# ---------------------------
# Helpers for Binance filters
# ---------------------------


def _d(x: str | float | int) -> Decimal:
    return Decimal(str(x))


def _round_down(value: Decimal, step: Decimal) -> Decimal:
    """
    Round DOWN to the nearest multiple of step.
    This is required for Binance LOT_SIZE / PRICE_FILTER compliance.
    """
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _round_up(value: Decimal, step: Decimal) -> Decimal:
    """
    Round UP to the nearest multiple of step.
    Needed when meeting MIN_NOTIONAL requires increasing qty.
    """
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def _step_decimals(step: Decimal) -> int:
    """
    Convert step size to decimal precision:
      1 -> 0
      0.01 -> 2
      0.001 -> 3
    """
    s = format(step.normalize(), "f")
    if "." not in s:
        return 0
    return len(s.split(".")[1])


class BinanceSpotClient:
    """
    Minimal Binance Spot REST client (signed endpoints) using HMAC SHA256,
    compatible with Spot testnet/mainnet based on Settings.
    """

    # per-process cache for exchange filters (avoid calling exchangeInfo repeatedly)
    _exchange_info_cache: Dict[str, Dict[str, str]] = {}

    def __init__(self):
        s = get_settings()

        # Phase 2A: prefer runtime overlay from AppSetting (frontend can rotate keys
        # via /admin/binance-keys without restarting the service). Falls back to
        # .env values when no overlay is configured.
        try:
            from src.exchange.runtime_keys import resolve_runtime_keys

            rk = resolve_runtime_keys()
            api_key = rk.api_key or s.binance_api_key
            api_secret = rk.api_secret or s.binance_api_secret
            testnet = rk.testnet if rk.api_key_set or rk.api_secret_set else s.binance_testnet
        except Exception:
            api_key = s.binance_api_key
            api_secret = s.binance_api_secret
            testnet = s.binance_testnet

        if not api_key or not api_secret:
            raise RuntimeError(
                "BINANCE_API_KEY / BINANCE_API_SECRET missing — set them in .env "
                "or via PUT /admin/binance-keys"
            )

        # Resolve base URL from the (possibly overridden) testnet flag.
        mainnet_url = os.getenv("BINANCE_SPOT_MAINNET_URL", "https://api.binance.com").strip()
        testnet_url = os.getenv(
            "BINANCE_SPOT_TESTNET_URL", "https://testnet.binance.vision"
        ).strip()
        self.base_url = (testnet_url if testnet else mainnet_url).rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = bool(testnet)
        self._base_urls = self._build_base_urls(testnet)
        # Binance signed requests require ms timestamp within recvWindow of server time.
        # Offset = serverTime - localTime fixes -1021 when the OS clock is skewed.
        self._time_offset_ms: int = 0
        self._time_sync_attempted: bool = False

    def _build_base_urls(self, is_testnet: bool) -> list[str]:
        urls: list[str] = [self.base_url]

        # Optional comma-separated overrides in .env (first value has highest priority).
        raw_fallbacks = os.getenv("BINANCE_SPOT_FALLBACK_URLS", "").strip()
        if raw_fallbacks:
            urls.extend(u.strip() for u in raw_fallbacks.split(",") if u.strip())

        if is_testnet:
            # Keep testnet first, but allow failover when DNS/network blocks testnet host.
            urls.extend(["https://testnet.binance.vision", "https://api.binance.com"])

        deduped: list[str] = []
        seen = set()
        for u in urls:
            normalized = u.rstrip("/")
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return deduped

    def _sign(self, query: str) -> str:
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            sha256,
        ).hexdigest()

    def _server_time_ms(self) -> int:
        return int(time.time() * 1000) + self._time_offset_ms

    def _refresh_time_offset(self, base_url: str) -> None:
        """Set ``_time_offset_ms`` from ``GET /api/v3/time`` (fixes error -1021)."""
        url = f"{base_url.rstrip('/')}/api/v3/time"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        server_ms = int(data["serverTime"])
        local_ms = int(time.time() * 1000)
        self._time_offset_ms = server_ms - local_ms

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = params or {}

        headers = {"X-MBX-APIKEY": self.api_key}
        last_network_error: Optional[Exception] = None

        for base_url in self._base_urls:
            last_network_error = None
            url = f"{base_url}{path}"

            max_attempts = 3 if signed else 1
            for attempt in range(max_attempts):
                req_params = dict(params)
                if signed:
                    if not self._time_sync_attempted:
                        try:
                            self._refresh_time_offset(base_url)
                        except Exception:
                            self._time_offset_ms = 0
                        self._time_sync_attempted = True
                    elif attempt > 0:
                        try:
                            self._refresh_time_offset(base_url)
                        except Exception:
                            pass
                    req_params["timestamp"] = self._server_time_ms()
                    req_params["recvWindow"] = 60000
                    query = urlencode(req_params, doseq=True)
                    req_params["signature"] = self._sign(query)

                try:
                    r = requests.request(
                        method,
                        url,
                        params=req_params,
                        headers=headers,
                        timeout=20,
                    )
                except requests.RequestException as exc:
                    last_network_error = exc
                    break

                if r.status_code < 400:
                    if self.base_url != base_url:
                        self.base_url = base_url
                        self._base_urls = [base_url] + [
                            u for u in self._base_urls if u != base_url
                        ]
                    return r.json()

                err_text = r.text
                retry_ts = False
                if signed and attempt < max_attempts - 1:
                    try:
                        code = r.json().get("code")
                        if code == -1021:
                            retry_ts = True
                    except Exception:
                        if "-1021" in err_text or "Timestamp" in err_text:
                            retry_ts = True
                    if retry_ts:
                        continue

                raise RuntimeError(f"Binance error {r.status_code}: {err_text}")

            if last_network_error is not None:
                continue

        tried = ", ".join(self._base_urls)
        if last_network_error is not None:
            raise RuntimeError(
                "Unable to reach Binance API (network/DNS). "
                f"Tried base URLs: {tried}. Last error: {last_network_error}"
            )

        raise RuntimeError(f"Unable to reach Binance API. Tried base URLs: {tried}")

    # ---------------------------
    # Public endpoints
    # ---------------------------

    def klines(self, symbol: str, interval: str, limit: int = 100) -> Any:
        return self._request(
            "GET",
            "/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            signed=False,
        )

    def exchange_info(self, symbol: str) -> Any:
        return self._request(
            "GET",
            "/api/v3/exchangeInfo",
            params={"symbol": symbol},
            signed=False,
        )

    def ticker_price(self, symbol: str) -> Any:
        return self._request(
            "GET",
            "/api/v3/ticker/price",
            params={"symbol": symbol},
            signed=False,
        )

    def get_price(self, symbol: str) -> float:
        """
        Convenience: returns latest price as float.
        """
        data = self.ticker_price(symbol)
        return float(data["price"])

    # ---------------------------
    # Signed endpoints
    # ---------------------------

    def account(self) -> Any:
        return self._request("GET", "/api/v3/account", signed=True)

    def balances_map(self) -> Dict[str, str]:
        """
        Returns balances as a dict: {asset: free}
        Example: {"USDT": "10000.00000000", "BTC": "1.00000000", ...}
        """
        acc = self.account()
        out: Dict[str, str] = {}
        for b in acc.get("balances", []):
            asset = b.get("asset")
            free = b.get("free")
            if asset and free is not None:
                out[asset] = free
        return out

    def create_order_market_buy(self, symbol: str, quote_order_qty: str) -> Any:
        return self._request(
            "POST",
            "/api/v3/order",
            params={
                "symbol": symbol.upper().strip(),
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": quote_order_qty,
            },
            signed=True,
        )

    def create_order_market_sell(self, symbol: str, quantity: str) -> Any:
        return self._request(
            "POST",
            "/api/v3/order",
            params={
                "symbol": symbol.upper().strip(),
                "side": "SELL",
                "type": "MARKET",
                "quantity": quantity,
            },
            signed=True,
        )

    def open_orders(self, symbol: str | None = None) -> Any:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/openOrders", params=params, signed=True)

    def all_orders(self, symbol: str, limit: int = 500) -> Any:
        return self._request(
            "GET",
            "/api/v3/allOrders",
            params={"symbol": symbol, "limit": limit},
            signed=True,
        )

    def my_trades(self, symbol: str, limit: int = 500) -> Any:
        return self._request(
            "GET",
            "/api/v3/myTrades",
            params={"symbol": symbol, "limit": limit},
            signed=True,
        )

    # ---------------------------
    # Filter-aware order helpers
    # ---------------------------

    def get_symbol_filters(self, symbol: str) -> Dict[str, str]:
        """
        Fetch and cache the key filters needed to place valid orders:
        - LOT_SIZE (stepSize, minQty)
        - PRICE_FILTER (tickSize)
        - MIN_NOTIONAL / NOTIONAL (minNotional)
        """
        sym = symbol.upper().strip()

        cached = self._exchange_info_cache.get(sym)
        if cached:
            return cached

        info = self.exchange_info(sym)
        if not info.get("symbols"):
            raise RuntimeError(f"exchangeInfo returned no symbols for {sym}")

        s = info["symbols"][0]
        f_map = {f["filterType"]: f for f in s.get("filters", [])}

        lot = f_map.get("LOT_SIZE", {})
        pricef = f_map.get("PRICE_FILTER", {})
        notional = f_map.get("MIN_NOTIONAL") or f_map.get("NOTIONAL") or {}

        out = {
            "stepSize": lot.get("stepSize", "1"),
            "minQty": lot.get("minQty", "0"),
            "tickSize": pricef.get("tickSize", "0.01"),
            "minNotional": notional.get("minNotional", "0"),
        }

        self._exchange_info_cache[sym] = out
        return out

    def normalize_limit(self, symbol: str, price: str, quantity: str) -> Dict[str, str]:
        """
        Normalizes (price, quantity) to meet Binance filters:
        - PRICE_FILTER (tickSize): round DOWN
        - LOT_SIZE (stepSize): round DOWN initially
        - MIN_NOTIONAL: if too small, bump qty UP to the minimum required
        """
        f = self.get_symbol_filters(symbol)

        step = _d(f["stepSize"])
        min_qty = _d(f["minQty"])
        tick = _d(f["tickSize"])
        min_notional = _d(f["minNotional"])

        p = _d(price)
        q = _d(quantity)

        # price must comply to tick size (round down)
        p2 = _round_down(p, tick)

        # quantity initial normalization (round down)
        q2 = _round_down(q, step)

        # LOT_SIZE check
        if q2 <= 0 or (min_qty > 0 and q2 < min_qty):
            raise ValueError(
                f"LOT_SIZE: quantity invalid. minQty={min_qty}, stepSize={step}, "
                f"requested={q}, normalized={q2}"
            )

        # MIN_NOTIONAL check -> if failing, bump qty UP to meet min notional
        notional_val = p2 * q2
        if min_notional > 0 and notional_val < min_notional:
            # required qty to meet minNotional at normalized price
            required_qty = min_notional / p2

            # must be >= minQty too
            required_qty = max(required_qty, min_qty)

            # bump UP to step size (critical)
            q2 = _round_up(required_qty, step)

            # re-check notional after bum
            notional_val2 = p2 * q2
            if notional_val2 < min_notional:
                raise ValueError(
                    f"MIN_NOTIONAL: still too small after bump. "
                    f"minNotional={min_notional}, price*qty={notional_val2} (price={p2}, qty={q2})"
                )

        price_dp = _step_decimals(tick)
        qty_dp = _step_decimals(step)

        price_str = format(
            p2.quantize(Decimal(10) ** -price_dp, rounding=ROUND_DOWN),
            "f",
        )
        qty_str = format(
            q2.quantize(Decimal(10) ** -qty_dp, rounding=ROUND_DOWN),
            "f",
        )

        return {"price": price_str, "quantity": qty_str}

    def get_order(self, symbol: str, order_id: int) -> Any:
        return self._request(
            "GET",
            "/api/v3/order",
            params={"symbol": symbol.upper().strip(), "orderId": order_id},
            signed=True,
        )

    def cancel_order(self, symbol: str, order_id: int) -> Any:
        return self._request(
            "DELETE",
            "/api/v3/order",
            params={"symbol": symbol.upper().strip(), "orderId": order_id},
            signed=True,
        )

    def create_order_limit_buy(self, symbol: str, price: str, quantity: str) -> Any:
        """
        Places a LIMIT BUY order after normalizing price/qty to comply with Binance filters.
        """
        norm = self.normalize_limit(symbol=symbol, price=price, quantity=quantity)

        return self._request(
            "POST",
            "/api/v3/order",
            params={
                "symbol": symbol.upper().strip(),
                "side": "BUY",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "price": norm["price"],
                "quantity": norm["quantity"],
            },
            signed=True,
        )

    def create_order_limit_sell(self, symbol: str, price: str, quantity: str) -> Any:
        """
        Places a LIMIT SELL order after normalizing price/qty to comply with Binance filters.
        """
        norm = self.normalize_limit(symbol=symbol, price=price, quantity=quantity)

        return self._request(
            "POST",
            "/api/v3/order",
            params={
                "symbol": symbol.upper().strip(),
                "side": "SELL",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "price": norm["price"],
                "quantity": norm["quantity"],
            },
            signed=True,
        )


def build_features_from_klines(klines):
    """
    Builds a feature dataframe from Binance klines.
    """
    try:
        import pandas as pd
    except ModuleNotFoundError as e:
        raise RuntimeError("Missing dependency: pandas") from e

    from src.features.indicators import calculate_rsi

    df = pd.DataFrame(
        klines,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "qav",
            "num_trades",
            "taker_base",
            "taker_quote",
            "ignore",
        ],
    )

    df["close"] = df["close"].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")

    close = df["close"]
    df["ema_20"] = close.ewm(span=20, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()
    df["rsi_14"] = calculate_rsi(df, period=14)

    return df.dropna()

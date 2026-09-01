from binance.client import Client
from binance.exceptions import BinanceAPIException
from src.core.config import get_settings
from decimal import Decimal, ROUND_DOWN

settings = get_settings()

client = Client(
    api_key=settings.binance_api_key,
    api_secret=settings.binance_api_secret,
    testnet=settings.binance_testnet,
)

# ✅ important for testnet
if settings.binance_testnet:
    client.API_URL = "https://testnet.binance.vision/api"



def _d(x) -> Decimal:
    return Decimal(str(x))

def _round_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

def _qty_to_step(symbol: str, qty: float) -> float:
    info = client.get_symbol_info(symbol)
    if not info:
        raise RuntimeError(f"Symbol not found: {symbol}")

    lot = next((f for f in info["filters"] if f["filterType"] == "LOT_SIZE"), None)
    if not lot:
        raise RuntimeError("LOT_SIZE filter not found")

    step = _d(lot["stepSize"])
    min_qty = _d(lot["minQty"])

    q = _round_step(_d(qty), step)

    if q < min_qty:
        raise RuntimeError(f"Quantity too small. minQty={min_qty}, got={q}")

    return float(q)


def get_price(symbol: str) -> float:
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except BinanceAPIException as e:
        raise RuntimeError(f"Binance price error: {e.message}")


def place_market_order(symbol: str, side: str, quantity: float):
    try:
        adj_qty = _qty_to_step(symbol, quantity)

        return client.create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=adj_qty,
        )
    except BinanceAPIException as e:
        raise RuntimeError(f"Binance order error: {e.message}")

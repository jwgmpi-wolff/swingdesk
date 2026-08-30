from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from coinbase.rest import RESTClient


Signal = Literal["BUY", "SELL", "SELL_STOP_LOSS", "HOLD"]
STATE_PATH = Path(os.getenv("TRADE_STATE_PATH", "trade_state.json"))
SETTINGS_PATH = Path(os.getenv("BOT_SETTINGS_PATH", "bot_settings.json"))
EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class TradeState:
    ticker: str
    entry_price: Decimal | None
    position_active: bool


@dataclass(frozen=True)
class StrategySettings:
    ticker: str = "AAPL"
    trade_usd_amount: Decimal = Decimal("100")
    stop_loss_percent: Decimal = Decimal("0.10")


@dataclass(frozen=True)
class BotSettings:
    strategies: tuple[StrategySettings, ...] = (StrategySettings(),)
    live_trading: bool = False


def log(message: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}", flush=True)


def env_decimal(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, default))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def validate_strategy(raw: dict[str, Any]) -> StrategySettings:
    ticker = str(raw.get("ticker", "AAPL")).strip().upper()
    if not ticker or not ticker.replace("-", "").replace(".", "").isalnum():
        raise ValueError("Ticker contains unsupported characters")
    try:
        trade_usd_amount = Decimal(str(raw.get("trade_usd_amount", "100")))
        stop_loss_percent = Decimal(str(raw.get("stop_loss_percent", "0.10")))
    except InvalidOperation as exc:
        raise ValueError("Trade amount and stop-loss must be decimal numbers") from exc
    if trade_usd_amount <= 0:
        raise ValueError("Trade amount must be greater than zero")
    if stop_loss_percent <= 0 or stop_loss_percent >= 1:
        raise ValueError("Stop-loss must be greater than 0 and less than 1")
    return StrategySettings(ticker, trade_usd_amount, stop_loss_percent)


def validate_settings(raw: dict[str, Any]) -> BotSettings:
    strategy_values = raw.get("strategies")
    if strategy_values is None:
        strategy_values = [raw]
    if not isinstance(strategy_values, list) or not strategy_values:
        raise ValueError("At least one stock strategy is required")
    if len(strategy_values) > 20:
        raise ValueError("A maximum of 20 stock strategies is supported")
    strategies = tuple(validate_strategy(value) for value in strategy_values)
    tickers = [strategy.ticker for strategy in strategies]
    if len(set(tickers)) != len(tickers):
        raise ValueError("Each ticker may only be configured once")
    live_trading = raw.get("live_trading", False)
    if not isinstance(live_trading, bool):
        raise ValueError("live_trading must be true or false")
    return BotSettings(strategies, live_trading)


def load_settings(path: Path = SETTINGS_PATH) -> BotSettings:
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Cannot safely read settings file {path}: {exc}") from exc

    strategy_override_names = ("TICKER", "TRADE_USD_AMOUNT", "STOP_LOSS_PERCENT")
    if any(name in os.environ for name in strategy_override_names):
        strategy_values = raw.get("strategies")
        baseline = strategy_values[0] if isinstance(strategy_values, list) and strategy_values else raw
        raw = {
            "ticker": os.getenv("TICKER", str(baseline.get("ticker", "AAPL"))),
            "trade_usd_amount": os.getenv(
                "TRADE_USD_AMOUNT", str(baseline.get("trade_usd_amount", "100"))
            ),
            "stop_loss_percent": os.getenv(
                "STOP_LOSS_PERCENT", str(baseline.get("stop_loss_percent", "0.10"))
            ),
            "live_trading": raw.get("live_trading", False),
        }
    if "DRY_RUN" in os.environ:
        raw["live_trading"] = os.environ["DRY_RUN"].lower() in {"false", "0", "no"}
    return validate_settings(raw)


def save_settings(path: Path, settings: BotSettings) -> None:
    payload = {
        "strategies": [
            {
                "ticker": strategy.ticker,
                "trade_usd_amount": str(strategy.trade_usd_amount),
                "stop_loss_percent": str(strategy.stop_loss_percent),
            }
            for strategy in settings.strategies
        ],
        "live_trading": settings.live_trading,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_state(path: Path, ticker: str) -> TradeState:
    if not path.exists():
        return TradeState(ticker=ticker, entry_price=None, position_active=False)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        positions = raw.get("positions")
        if isinstance(positions, dict):
            position = positions.get(ticker, {})
            state_ticker = ticker
            position_active = bool(position.get("position_active", False))
            entry_price = Decimal(str(position["entry_price"])) if position.get("entry_price") is not None else None
        else:
            state_ticker = str(raw["ticker"]).upper()
            position_active = bool(raw["position_active"])
            entry_price = Decimal(str(raw["entry_price"])) if raw.get("entry_price") is not None else None
    except (OSError, json.JSONDecodeError, KeyError, InvalidOperation, TypeError) as exc:
        raise ValueError(f"Cannot safely read state file {path}: {exc}") from exc

    if position_active and state_ticker != ticker:
        raise ValueError(f"State contains an active {state_ticker} position, not {ticker}")
    if position_active and (entry_price is None or entry_price <= 0):
        raise ValueError("Active position state requires a positive entry_price")
    return TradeState(ticker=state_ticker, entry_price=entry_price, position_active=position_active)


def save_state(path: Path, state: TradeState) -> None:
    positions: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(current.get("positions"), dict):
                positions = current["positions"]
            elif current.get("ticker"):
                positions[str(current["ticker"]).upper()] = {
                    "entry_price": current.get("entry_price"),
                    "position_active": bool(current.get("position_active", False)),
                }
        except (OSError, json.JSONDecodeError, TypeError):
            positions = {}
    positions[state.ticker] = {
        "entry_price": str(state.entry_price) if state.entry_price is not None else None,
        "position_active": state.position_active,
    }
    payload = {"positions": positions}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch_market_data(ticker: str) -> pd.DataFrame:
    log(f"Fetching six months of daily data for {ticker}...")
    data = yf.download(
        ticker,
        period="6mo",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise ValueError(f"Yahoo Finance returned no data for {ticker}")

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close[ticker] if ticker in close.columns else close.iloc[:, 0]

    candles = pd.DataFrame({"Close": pd.to_numeric(close, errors="coerce")}).dropna()
    now_et = datetime.now(EASTERN)
    if not candles.empty and candles.index[-1].date() == now_et.date() and now_et.time() < time(16, 15):
        candles = candles.iloc[:-1]

    if len(candles) < 51:
        raise ValueError(f"Need at least 51 completed candles; Yahoo Finance returned {len(candles)}")

    candles["SMA20"] = candles["Close"].rolling(window=20).mean()
    candles["SMA50"] = candles["Close"].rolling(window=50).mean()
    log(f"Calculated indicators through {candles.index[-1].date()}")
    return candles


def get_signal(data: pd.DataFrame, state: TradeState, stop_loss_percent: Decimal) -> Signal:
    latest_close = Decimal(str(data["Close"].iloc[-1]))
    if state.position_active and state.entry_price is not None:
        stop_price = state.entry_price * (Decimal("1") - stop_loss_percent)
        if latest_close <= stop_price:
            log(f"Stop-loss triggered: close ${latest_close:.2f} <= ${stop_price:.2f}")
            return "SELL_STOP_LOSS"

    completed = data[["SMA20", "SMA50"]].dropna().tail(2)
    if len(completed) < 2:
        raise ValueError("Not enough completed SMA values to detect a crossover")

    previous, current = completed.iloc[0], completed.iloc[1]
    if previous["SMA20"] <= previous["SMA50"] and current["SMA20"] > current["SMA50"]:
        return "HOLD" if state.position_active else "BUY"
    if previous["SMA20"] >= previous["SMA50"] and current["SMA20"] < current["SMA50"]:
        return "SELL"
    return "HOLD"


def response_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "to_dict"):
        return response.to_dict()
    raise TypeError(f"Unexpected Coinbase response type: {type(response).__name__}")


def resolve_equity_product(client: RESTClient, ticker: str) -> dict[str, Any]:
    cursor: str | None = None
    while True:
        kwargs = {"cursor": cursor} if cursor else {}
        payload = response_dict(client.get_products(product_type="EQUITY", limit=250, **kwargs))
        for product in payload.get("products", []):
            details = product.get("equity_product_details") or {}
            if str(details.get("ticker", "")).upper() == ticker:
                if product.get("trading_disabled") or details.get("trading_halted"):
                    raise RuntimeError(f"Trading is currently disabled or halted for {ticker}")
                return product

        pagination = payload.get("pagination") or {}
        if not pagination.get("has_next"):
            break
        cursor = pagination.get("next_cursor")
        if not cursor:
            break
    raise RuntimeError(f"Coinbase returned no eligible equity product for ticker {ticker}")


def get_holding_size(client: RESTClient, ticker: str) -> str | None:
    cursor: str | None = None
    while True:
        response = client.get_accounts(limit=250, cursor=cursor)
        payload = response_dict(response)
        for account in payload.get("accounts", []):
            if str(account.get("currency", "")).upper() == ticker:
                value = str((account.get("available_balance") or {}).get("value", "0"))
                if Decimal(value) > 0:
                    return value
                return None
        if not payload.get("has_next"):
            return None
        cursor = payload.get("cursor")
        if not cursor:
            return None


def order_id(ticker: str, signal: Signal, candle_timestamp: pd.Timestamp) -> str:
    timestamp = candle_timestamp.strftime("%Y%m%dT%H%M%S")
    return f"swing-{ticker.lower()}-{signal.lower()}-{timestamp}"


def execute_order(
    client: RESTClient,
    ticker: str,
    signal: Signal,
    usd_amount: Decimal,
    candle_timestamp: pd.Timestamp,
) -> bool:
    product = resolve_equity_product(client, ticker)
    product_id = str(product["product_id"])
    flags = (product.get("equity_product_details") or {}).get("equity_trading_flags") or {}
    client_order_id = order_id(ticker, signal, candle_timestamp)
    metadata = {
        "equity_trading_session": "EQUITY_TRADING_SESSION_NORMAL",
        "displayed_order_config": "MARKET_GFD",
    }

    if signal == "BUY":
        if not flags.get("buy_notional", False):
            raise RuntimeError(f"Coinbase does not currently allow notional buys for {ticker}")
        configuration = {"market_market_ioc": {"quote_size": format(usd_amount, "f")}}
        side = "BUY"
        log(f"Submitting ${usd_amount} market buy for {ticker} as {product_id}...")
    else:
        holding_size = get_holding_size(client, ticker)
        if holding_size is None:
            log(f"No available {ticker} holding found; no sell order submitted")
            return False
        if Decimal(holding_size) % 1 and not flags.get("sell_fractional_shares", False):
            raise RuntimeError(f"Coinbase does not currently allow fractional sells for {ticker}")
        configuration = {"market_market_ioc": {"base_size": holding_size}}
        side = "SELL"
        log(f"Submitting market sell for all {holding_size} shares of {ticker} as {product_id}...")

    response = client.create_order(
        client_order_id=client_order_id,
        product_id=product_id,
        side=side,
        order_configuration=configuration,
        equity_order_metadata=metadata,
    )
    result = response_dict(response)
    if not result.get("success"):
        error = result.get("error_response") or result
        raise RuntimeError(f"Coinbase rejected the order: {error}")
    order_reference = (result.get("success_response") or {}).get("order_id", "unknown")
    log(f"Order successful: {order_reference}")
    return True


def create_client() -> RESTClient:
    key_file = os.getenv("COINBASE_KEY_FILE")
    if key_file:
        path = Path(key_file).expanduser()
        if not path.is_file():
            raise ValueError(f"COINBASE_KEY_FILE does not exist: {path}")
        return RESTClient(key_file=str(path), timeout=30)

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        raise ValueError(
            "Set COINBASE_KEY_FILE or both COINBASE_API_KEY and COINBASE_API_SECRET for live trading"
        )
    return RESTClient(api_key=api_key, api_secret=api_secret, timeout=30)


def main() -> int:
    try:
        settings = load_settings()
        dry_run = not settings.live_trading
        client: RESTClient | None = None
        failures = 0
        log(f"Starting daily swing-trader run for {len(settings.strategies)} strategies (dry_run={dry_run})")
        for strategy in settings.strategies:
            try:
                ticker = strategy.ticker
                state = load_state(STATE_PATH, ticker)
                data = fetch_market_data(ticker)
                signal = get_signal(data, state, strategy.stop_loss_percent)
                latest_close = Decimal(str(data["Close"].iloc[-1]))
                log(f"{ticker} signal is: {signal}; latest completed close is ${latest_close:.2f}")
                if signal == "HOLD":
                    log(f"{ticker}: no trade required")
                    continue
                if dry_run:
                    log(f"{ticker}: DRY_RUN is enabled; no order or state change was made")
                    continue
                if client is None:
                    client = create_client()
                submitted = execute_order(client, ticker, signal, strategy.trade_usd_amount, data.index[-1])
                if submitted and signal == "BUY":
                    save_state(STATE_PATH, TradeState(ticker, latest_close, True))
                    log(f"Saved active {ticker} position state to {STATE_PATH}")
                elif submitted:
                    save_state(STATE_PATH, TradeState(ticker, None, False))
                    log(f"Marked {ticker} position inactive in {STATE_PATH}")
            except Exception as exc:
                failures += 1
                log(f"ERROR {strategy.ticker}: {exc}")
        if failures:
            raise RuntimeError(f"{failures} strategy run(s) failed")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
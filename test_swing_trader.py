from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from swing_trader import (
    BotSettings,
    StrategySettings,
    TradeState,
    execute_order,
    get_signal,
    load_settings,
    load_state,
    order_id,
    save_settings,
    save_state,
    validate_settings,
)


def indicator_data(
    previous_fast: float,
    previous_slow: float,
    current_fast: float,
    current_slow: float,
    current_close: float = 100,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Close": [100, current_close],
            "SMA20": [previous_fast, current_fast],
            "SMA50": [previous_slow, current_slow],
        },
        index=pd.to_datetime(["2026-08-27", "2026-08-28"]),
    )


def test_golden_cross_buys_only_without_active_position() -> None:
    data = indicator_data(49, 50, 51, 50)

    assert get_signal(data, TradeState("AAPL", None, False), Decimal("0.10")) == "BUY"
    assert get_signal(data, TradeState("AAPL", Decimal("95"), True), Decimal("0.10")) == "HOLD"


def test_death_cross_sells() -> None:
    data = indicator_data(51, 50, 49, 50)

    assert get_signal(data, TradeState("AAPL", Decimal("100"), True), Decimal("0.10")) == "SELL"


def test_stop_loss_has_priority_over_crossover() -> None:
    data = indicator_data(49, 50, 51, 50, current_close=90)

    signal = get_signal(data, TradeState("AAPL", Decimal("100"), True), Decimal("0.10"))

    assert signal == "SELL_STOP_LOSS"


def test_state_round_trip_preserves_independent_tickers(tmp_path: Path) -> None:
    path = tmp_path / "trade_state.json"
    save_state(path, TradeState("AAPL", Decimal("123.45"), True))
    save_state(path, TradeState("MSFT", Decimal("500"), True))

    assert load_state(path, "AAPL") == TradeState("AAPL", Decimal("123.45"), True)
    assert load_state(path, "MSFT") == TradeState("MSFT", Decimal("500"), True)
    assert load_state(path, "NVDA") == TradeState("NVDA", None, False)


def test_order_id_is_deterministic_for_cron_retries() -> None:
    candle = pd.Timestamp("2026-08-28")

    assert order_id("AAPL", "BUY", candle) == "swing-aapl-buy-20260828T000000"
    assert order_id("AAPL", "BUY", candle) == order_id("AAPL", "BUY", candle)


def test_settings_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TICKER", "TRADE_USD_AMOUNT", "STOP_LOSS_PERCENT", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "settings.json"
    expected = BotSettings(
        (
            StrategySettings("MSFT", Decimal("250"), Decimal("0.08")),
            StrategySettings("NVDA", Decimal("150"), Decimal("0.12")),
        ),
        True,
    )

    save_settings(path, expected)

    assert load_settings(path) == expected


def test_legacy_settings_migrate_and_duplicate_tickers_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TICKER", "TRADE_USD_AMOUNT", "STOP_LOSS_PERCENT", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "settings.json"
    path.write_text(
        '{"ticker":"msft","trade_usd_amount":"125","stop_loss_percent":"0.07","live_trading":false}',
        encoding="utf-8",
    )

    assert load_settings(path).strategies == (StrategySettings("MSFT", Decimal("125"), Decimal("0.07")),)
    with pytest.raises(ValueError, match="configured once"):
        validate_settings(
            {
                "strategies": [
                    {"ticker": "AAPL", "trade_usd_amount": "100", "stop_loss_percent": "0.10"},
                    {"ticker": "aapl", "trade_usd_amount": "200", "stop_loss_percent": "0.08"},
                ]
            }
        )


def test_partial_environment_override_selects_first_saved_strategy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TICKER", raising=False)
    monkeypatch.delenv("STOP_LOSS_PERCENT", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("TRADE_USD_AMOUNT", "300")
    path = tmp_path / "settings.json"
    save_settings(
        path,
        BotSettings(
            (
                StrategySettings("MSFT", Decimal("125"), Decimal("0.07")),
                StrategySettings("NVDA", Decimal("175"), Decimal("0.09")),
            )
        ),
    )

    assert load_settings(path).strategies == (StrategySettings("MSFT", Decimal("300"), Decimal("0.07")),)


class FakeClient:
    def __init__(self) -> None:
        self.created_order: dict[str, Any] | None = None

    def get_products(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "products": [
                {
                    "product_id": "AAPL-US-EQUITY",
                    "trading_disabled": False,
                    "equity_product_details": {
                        "ticker": "AAPL",
                        "trading_halted": False,
                        "equity_trading_flags": {
                            "buy_notional": True,
                            "sell_fractional_shares": True,
                        },
                    },
                }
            ],
            "pagination": {"has_next": False},
        }

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.created_order = kwargs
        return {"success": True, "success_response": {"order_id": "order-123"}}


def test_buy_uses_canonical_product_and_equity_metadata() -> None:
    client = FakeClient()

    submitted = execute_order(
        client,  # type: ignore[arg-type]
        "AAPL",
        "BUY",
        Decimal("100"),
        pd.Timestamp("2026-08-28"),
    )

    assert submitted is True
    assert client.created_order == {
        "client_order_id": "swing-aapl-buy-20260828T000000",
        "product_id": "AAPL-US-EQUITY",
        "side": "BUY",
        "order_configuration": {"market_market_ioc": {"quote_size": "100"}},
        "equity_order_metadata": {
            "equity_trading_session": "EQUITY_TRADING_SESSION_NORMAL",
            "displayed_order_config": "MARKET_GFD",
        },
    }
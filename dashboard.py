from __future__ import annotations

import contextlib
import hmac
import io
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from flask import Flask, Response, current_app, jsonify, render_template, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import swing_trader
from swing_trader import (
    SETTINGS_PATH,
    STATE_PATH,
    BotSettings,
    create_client,
    fetch_market_data,
    get_signal,
    load_settings,
    load_state,
    response_dict,
    save_settings,
    validate_settings,
)


Route = TypeVar("Route", bound=Callable[..., Any])
RUN_LOCK = threading.Lock()
PASSWORD_PATH = Path(os.getenv("DASHBOARD_PASSWORD_PATH", "dashboard_password.json"))


def settings_json(settings: BotSettings) -> dict[str, Any]:
    return {
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


def password_record(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value.get("password_hash"), str) or not isinstance(value.get("revision"), str):
            raise ValueError("missing password fields")
        return value
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot safely read dashboard password file {path}: {exc}") from exc


def verify_password(path: Path, supplied: str) -> tuple[bool, str]:
    record = password_record(path)
    if record:
        return check_password_hash(record["password_hash"], supplied), record["revision"]
    expected = os.getenv("DASHBOARD_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(supplied, expected), "environment"


def save_password(path: Path, password: str) -> str:
    if len(password) < 10:
        raise ValueError("New password must be at least 10 characters")
    revision = secrets.token_urlsafe(18)
    payload = {"password_hash": generate_password_hash(password), "revision": revision}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return revision


def require_login(route: Route) -> Route:
    @wraps(route)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        record = password_record(Path(current_app.config["PASSWORD_PATH"]))
        revision = record["revision"] if record else "environment"
        if not session.get("authenticated") or session.get("password_revision") != revision:
            session.clear()
            return jsonify({"error": "Authentication required"}), 401
        return route(*args, **kwargs)

    return cast(Route, wrapped)


def require_csrf() -> Response | None:
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = str(session.get("csrf_token", ""))
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        return jsonify({"error": "Invalid request token"}), 403
    return None


def all_accounts(client: Any) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        payload = response_dict(client.get_accounts(limit=250, cursor=cursor))
        accounts.extend(payload.get("accounts", []))
        if not payload.get("has_next") or not payload.get("cursor"):
            return accounts
        cursor = payload["cursor"]


def recent_orders(client: Any) -> list[dict[str, Any]]:
    payload = response_dict(client.list_orders(product_type="EQUITY", limit=100))
    return payload.get("orders", [])


def recent_fills(client: Any) -> list[dict[str, Any]]:
    payload = response_dict(client.get_fills(product_types=["EQUITY"], limit=100))
    return payload.get("fills", [])


def clean_balances(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    balances = []
    for account in accounts:
        available = account.get("available_balance") or {}
        hold = account.get("hold") or {}
        try:
            if Decimal(str(available.get("value", "0"))) == 0 and Decimal(str(hold.get("value", "0"))) == 0:
                continue
        except ArithmeticError:
            continue
        balances.append(
            {
                "currency": account.get("currency", "--"),
                "name": account.get("name", account.get("currency", "Account")),
                "available": str(available.get("value", "0")),
                "hold": str(hold.get("value", "0")),
                "type": account.get("type", ""),
            }
        )
    return balances


def clean_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": order.get("order_id", ""),
            "product": order.get("product_id", "--"),
            "side": order.get("side", "--"),
            "status": order.get("status", "--"),
            "type": order.get("order_type", "--"),
            "filled_size": order.get("filled_size", "0"),
            "filled_value": order.get("filled_value", "0"),
            "average_price": order.get("average_filled_price", "0"),
            "fees": order.get("total_fees", "0"),
            "created_at": order.get("created_time", ""),
        }
        for order in orders
    ]


def clean_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": fill.get("entry_id", fill.get("trade_id", "")),
            "product": fill.get("product_id", "--"),
            "side": fill.get("side", "--"),
            "price": fill.get("price", "0"),
            "size": fill.get("size", "0"),
            "commission": fill.get("commission", "0"),
            "liquidity": fill.get("liquidity_indicator", "--"),
            "trade_time": fill.get("trade_time", ""),
        }
        for fill in fills
    ]


def clean_payment_methods(methods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": method.get("name", "Payment method"),
            "type": method.get("type", "UNKNOWN"),
            "allow_deposit": bool(method.get("allow_buy", False)),
            "allow_withdraw": bool(method.get("allow_sell", False)),
        }
        for method in methods
    ]


def strategy_snapshot(strategy: Any, state_path: Path) -> dict[str, Any]:
    state = load_state(state_path, strategy.ticker)
    market = fetch_market_data(strategy.ticker)
    signal = get_signal(market, state, strategy.stop_loss_percent)
    chart = market.dropna(subset=["SMA20", "SMA50"]).tail(90)
    return {
        "ticker": strategy.ticker,
        "trade_usd_amount": str(strategy.trade_usd_amount),
        "stop_loss_percent": str(strategy.stop_loss_percent),
        "signal": signal,
        "latest_close": str(market["Close"].iloc[-1]),
        "sma20": str(market["SMA20"].iloc[-1]),
        "sma50": str(market["SMA50"].iloc[-1]),
        "position_active": state.position_active,
        "entry_price": str(state.entry_price) if state.entry_price is not None else None,
        "chart": [
            {
                "date": index.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 4),
                "sma20": round(float(row["SMA20"]), 4),
                "sma50": round(float(row["SMA50"]), 4),
            }
            for index, row in chart.iterrows()
        ],
    }


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("DASHBOARD_SESSION_SECRET", secrets.token_hex(32)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        MAX_CONTENT_LENGTH=16 * 1024,
        SETTINGS_PATH=SETTINGS_PATH,
        STATE_PATH=STATE_PATH,
        PASSWORD_PATH=PASSWORD_PATH,
    )
    if test_config:
        app.config.update(test_config)

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/service-worker.js")
    def service_worker() -> Response:
        return send_from_directory(app.static_folder or "static", "service-worker.js", mimetype="application/javascript")

    @app.post("/api/login")
    def login() -> Any:
        supplied = str((request.get_json(silent=True) or {}).get("password", ""))
        password_path = Path(app.config["PASSWORD_PATH"])
        if not password_path.exists() and not os.getenv("DASHBOARD_PASSWORD"):
            return jsonify({"error": "DASHBOARD_PASSWORD is not configured"}), 503
        verified, revision = verify_password(password_path, supplied)
        if not verified:
            return jsonify({"error": "Invalid password"}), 401
        session.clear()
        session["authenticated"] = True
        session["password_revision"] = revision
        session["csrf_token"] = secrets.token_urlsafe(24)
        return jsonify({"csrf_token": session["csrf_token"]})

    @app.post("/api/logout")
    @require_login
    def logout() -> Any:
        invalid = require_csrf()
        if invalid:
            return invalid
        session.clear()
        return jsonify({"ok": True})

    @app.put("/api/password")
    @require_login
    def change_password() -> Any:
        invalid = require_csrf()
        if invalid:
            return invalid
        payload = request.get_json(force=True)
        current_password = str(payload.get("current_password", ""))
        new_password = str(payload.get("new_password", ""))
        confirmation = str(payload.get("confirm_password", ""))
        password_path = Path(app.config["PASSWORD_PATH"])
        verified, _ = verify_password(password_path, current_password)
        if not verified:
            return jsonify({"error": "Current password is incorrect"}), 403
        if new_password != confirmation:
            raise ValueError("New password confirmation does not match")
        if hmac.compare_digest(current_password, new_password):
            raise ValueError("New password must be different")
        save_password(password_path, new_password)
        session.clear()
        return jsonify({"ok": True, "reauthenticate": True})

    @app.get("/api/settings")
    @require_login
    def get_settings() -> Any:
        settings = load_settings(Path(app.config["SETTINGS_PATH"]))
        return jsonify(settings_json(settings))

    @app.put("/api/settings")
    @require_login
    def update_settings() -> Any:
        invalid = require_csrf()
        if invalid:
            return invalid
        settings = validate_settings(request.get_json(force=True))
        save_settings(Path(app.config["SETTINGS_PATH"]), settings)
        return jsonify(settings_json(settings))

    @app.get("/api/overview")
    @require_login
    def overview() -> Any:
        settings = load_settings(Path(app.config["SETTINGS_PATH"]))
        client = create_client()
        accounts = all_accounts(client)
        orders = recent_orders(client)
        fills = recent_fills(client)
        strategies = []
        warnings = []
        for strategy in settings.strategies:
            try:
                strategies.append(strategy_snapshot(strategy, Path(app.config["STATE_PATH"])))
            except Exception as exc:
                warnings.append(f"{strategy.ticker}: {exc}")
                strategies.append(
                    {
                        "ticker": strategy.ticker,
                        "trade_usd_amount": str(strategy.trade_usd_amount),
                        "stop_loss_percent": str(strategy.stop_loss_percent),
                        "error": str(exc),
                        "signal": "ERROR",
                        "chart": [],
                    }
                )
        return jsonify(
            {
                "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "balances": clean_balances(accounts),
                "orders": clean_orders(orders),
                "fills": clean_fills(fills),
                "live_trading": settings.live_trading,
                "strategies": strategies,
                "warnings": warnings,
            }
        )

    @app.get("/api/funding")
    @require_login
    def funding() -> Any:
        client = create_client()
        methods = response_dict(client.list_payment_methods()).get("payment_methods", [])
        permissions = response_dict(client.get_api_key_permissions())
        return jsonify(
            {
                "payment_methods": clean_payment_methods(methods),
                "can_transfer": bool(permissions.get("can_transfer", False)),
                "deposit_url": "https://www.coinbase.com/home",
                "withdraw_url": "https://www.coinbase.com/home",
                "handoff_required": True,
            }
        )

    @app.post("/api/run")
    @require_login
    def run_strategy() -> Any:
        invalid = require_csrf()
        if invalid:
            return invalid
        settings = load_settings(Path(app.config["SETTINGS_PATH"]))
        confirmation = bool((request.get_json(silent=True) or {}).get("confirm_live"))
        if settings.live_trading and not confirmation:
            return jsonify({"error": "Live trading confirmation is required"}), 409
        if not RUN_LOCK.acquire(blocking=False):
            return jsonify({"error": "A strategy run is already in progress"}), 409
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = swing_trader.main()
            return jsonify({"ok": exit_code == 0, "exit_code": exit_code, "log": output.getvalue().splitlines()})
        finally:
            RUN_LOCK.release()

    @app.errorhandler(ValueError)
    @app.errorhandler(RuntimeError)
    def operational_error(error: Exception) -> Any:
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception) -> Any:
        app.logger.exception("Dashboard request failed", exc_info=error)
        return jsonify({"error": "Request failed; check the Windows server log"}), 500

    return app


app = create_app()
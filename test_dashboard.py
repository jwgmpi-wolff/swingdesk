from pathlib import Path

import dashboard


def login(client) -> str:
    response = client.post("/api/login", json={"password": "test-password"})
    assert response.status_code == 200
    return response.get_json()["csrf_token"]


def test_api_requires_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    app = dashboard.create_app({"TESTING": True, "SETTINGS_PATH": tmp_path / "settings.json"})

    response = app.test_client().get("/api/settings")

    assert response.status_code == 401


def test_app_shell_and_red_c_icon_are_served(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    app = dashboard.create_app({"TESTING": True, "SETTINGS_PATH": tmp_path / "settings.json"})
    client = app.test_client()

    page = client.get("/")
    icon = client.get("/static/mark.svg")

    assert page.status_code == 200
    assert b"Swingdesk" in page.data
    assert b'id="password-toggle"' in page.data
    assert b'aria-label="Show password"' in page.data
    assert b'id="strategy-summary-grid"' in page.data
    assert b"renderStrategySummaries" in client.get("/static/app.js").data
    assert b'swingdesk-v5' in client.get("/service-worker.js").data
    assert icon.status_code == 200
    assert b">C</text>" in icon.data
    assert b"#d52b2b" in icon.data
    assert b"icon-192.png" in client.get("/static/manifest.webmanifest").data
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_failed_logins_are_throttled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    dashboard.LOGIN_ATTEMPTS.clear()
    app = dashboard.create_app({"TESTING": True, "PASSWORD_PATH": tmp_path / "password.json"})
    client = app.test_client()

    for _ in range(dashboard.LOGIN_ATTEMPT_LIMIT):
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 401

    assert client.post("/api/login", json={"password": "test-password"}).status_code == 429
    dashboard.LOGIN_ATTEMPTS.clear()


def test_settings_update_requires_csrf(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    monkeypatch.delenv("TICKER", raising=False)
    path = tmp_path / "settings.json"
    app = dashboard.create_app({"TESTING": True, "SETTINGS_PATH": path})
    client = app.test_client()
    token = login(client)
    payload = {
        "strategies": [
            {"ticker": "MSFT", "trade_usd_amount": "225", "stop_loss_percent": "0.07"},
            {"ticker": "NVDA", "trade_usd_amount": "150", "stop_loss_percent": "0.12"},
        ],
        "live_trading": False,
    }

    rejected = client.put("/api/settings", json=payload)
    accepted = client.put("/api/settings", json=payload, headers={"X-CSRF-Token": token})

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.get_json()["strategies"][0]["ticker"] == "MSFT"
    assert accepted.get_json()["strategies"][1]["ticker"] == "NVDA"
    assert path.exists()


def test_password_change_hashes_secret_and_revokes_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    password_path = tmp_path / "password.json"
    app = dashboard.create_app(
        {"TESTING": True, "PASSWORD_PATH": password_path, "SETTINGS_PATH": tmp_path / "settings.json"}
    )
    client = app.test_client()
    token = login(client)

    changed = client.put(
        "/api/password",
        json={
            "current_password": "test-password",
            "new_password": "replacement-password",
            "confirm_password": "replacement-password",
        },
        headers={"X-CSRF-Token": token},
    )

    assert changed.status_code == 200
    assert b"replacement-password" not in password_path.read_bytes()
    assert client.get("/api/settings").status_code == 401
    assert client.post("/api/login", json={"password": "test-password"}).status_code == 401
    assert client.post("/api/login", json={"password": "replacement-password"}).status_code == 200


def test_live_run_requires_explicit_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    for name in ("TICKER", "TRADE_USD_AMOUNT", "STOP_LOSS_PERCENT", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "settings.json"
    dashboard.save_settings(path, dashboard.BotSettings(live_trading=True))
    app = dashboard.create_app({"TESTING": True, "SETTINGS_PATH": path})
    client = app.test_client()
    token = login(client)

    response = client.post("/api/run", json={}, headers={"X-CSRF-Token": token})

    assert response.status_code == 409
    assert "confirmation" in response.get_json()["error"].lower()


def test_overview_keeps_strategy_data_when_coinbase_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    settings_path = tmp_path / "settings.json"
    dashboard.save_settings(settings_path, dashboard.BotSettings())
    monkeypatch.setattr(dashboard, "create_client", lambda: (_ for _ in ()).throw(RuntimeError("unauthorized")))
    monkeypatch.setattr(
        dashboard,
        "strategy_snapshot",
        lambda strategy, state_path: {"ticker": strategy.ticker, "signal": "HOLD", "chart": []},
    )
    app = dashboard.create_app({"TESTING": True, "SETTINGS_PATH": settings_path})
    client = app.test_client()
    login(client)

    response = client.get("/api/overview")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["balances"] == []
    assert payload["strategies"][0]["signal"] == "HOLD"
    assert "Coinbase account data is unavailable" in payload["warnings"][0]

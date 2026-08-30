# Daily Swing Trader

A once-daily Python bot that downloads free Yahoo Finance data, calculates 20/50-day SMA crossovers, applies a 10% close-based stop-loss, and submits eligible U.S. equity orders through Coinbase Advanced Trade.

## Important limitations

- This is software, not investment advice. Test with `DRY_RUN=true` before risking funds.
- A daily close-based stop-loss is not a hard intraday stop. It cannot protect against an intraday move, a price gap, a missed cron run, Yahoo Finance delay/outage, or local disk loss.
- Yahoo Finance data is unofficial and may be delayed or adjusted. It is not an execution-grade feed.
- Coinbase equity availability, eligibility, fractional support, trading hours, and fees can vary by account and product. The bot checks current product flags before ordering.
- Coinbase requires the canonical equity `product_id` returned by its Products API. The bot resolves this from the ticker instead of assuming `AAPL-USD`.
- `trade_state.json` is local durable state. A truly ephemeral cron host must mount persistent storage at `TRADE_STATE_PATH`.

## Setup

Python 3.11 or later is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create a CDP API key with only the required view and trade permissions. Set secrets in the host environment or a secrets manager, not in source control:

```powershell
$env:COINBASE_KEY_FILE = "$PWD\cdp_api_key (1).json"
$env:TICKER = "AAPL"
$env:DRY_RUN = "true"
.\.venv\Scripts\python.exe .\swing_trader.py
```

Configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `COINBASE_KEY_FILE` | none | Preferred path to the downloaded CDP key JSON |
| `COINBASE_API_KEY` | none | Required for live orders |
| `COINBASE_API_SECRET` | none | Required for live orders; PEM newlines must be preserved |
| `TICKER` | `AAPL` | Optional single-strategy environment override |
| `TRADE_USD_AMOUNT` | `100` | Notional USD amount for buys |
| `STOP_LOSS_PERCENT` | `0.10` | Decimal loss threshold |
| `TRADE_STATE_PATH` | `trade_state.json` | Persistent position state path |
| `BOT_SETTINGS_PATH` | `bot_settings.json` | Dashboard-managed strategy settings path |
| `DASHBOARD_PASSWORD_PATH` | `dashboard_password.json` | Local salted dashboard password hash |
| `DRY_RUN` | `true` | Set to `false` to permit live orders |

The script does not load `.env` files. This is intentional: inject secrets through the cron service, OS environment, or a secrets manager.

Settings changed in the dashboard are stored atomically in the Git-ignored `bot_settings.json` file and are used by scheduled runs. Up to 20 stocks can have independent entry amounts, stop-loss thresholds, and persisted positions. Explicit `TICKER`, `TRADE_USD_AMOUNT`, or `STOP_LOSS_PERCENT` environment variables select one environment-managed strategy; `DRY_RUN` overrides the shared execution mode.

## Windows and Android dashboard

Swingdesk is a responsive, authenticated local web app. It shows non-zero balances, equity orders, fills, per-stock strategy state, selectable 90-session price/SMA charts, and editable trading parameters. Coinbase credentials stay on the Windows server and are never returned to the browser.

Start it from PowerShell:

```powershell
.\start_dashboard.ps1
```

The launcher prompts for a password, opens `http://127.0.0.1:8787` on Windows, and prints the private-LAN URL for Android. On Android, open that URL in Chrome while connected to the same trusted network, then choose **Add to Home screen** or **Install app**. The installed app uses the bold red `C` icon.

The launch password bootstraps authentication until it is changed under **Settings > Dashboard password**. A changed password is stored only as a salted local hash in `dashboard_password.json`, takes precedence over later launcher passwords, and signs out all open sessions.

The Funding controls open Coinbase to add or cash out funds. Bank linking, authorization, and transfer confirmation occur only in Coinbase; Swingdesk never collects bank account details and does not submit transfers through the trading API.

If Android cannot connect, allow private-network inbound TCP traffic for port `8787` in Windows Defender Firewall. Do not expose this port through router forwarding, a public IP, or an untrusted network. Plain HTTP is appropriate only on a trusted private LAN; use a private HTTPS tunnel or reverse proxy for remote access.

The dashboard starts in dry-run mode. Enabling live trading permits scheduled runs to submit orders, and each manual live run also requires a separate confirmation. A settings toggle is not a substitute for account-level limits and least-privilege API keys.

### Native Android app

The native Android shell is in `android/` and keeps trading logic and credentials on the Windows dashboard server. It requires Android 8 or newer. Build the release APK and optionally update a connected device in place:

```powershell
.\build_android.ps1
.\build_android.ps1 -Install
```

The published artifact is `dist/Swingdesk.apk`. The install command preserves existing application data, creates an ADB reverse tunnel for port `8787`, and launches the app. Start `start_dashboard.ps1` before using it. This build defaults to `http://10.0.0.112:8787/` for operation on the current trusted Wi-Fi without USB. If the Windows address changes, tap **Server** in the Android toolbar and enter the private-LAN URL printed by the dashboard launcher.

## Cron

Run shortly after the regular market opens. At 9:35 a.m. ET, the script excludes the current incomplete Yahoo candle, evaluates the previous two completed sessions, and can submit a regular-session market order.

```cron
CRON_TZ=America/New_York
35 9 * * 1-5 cd /absolute/path/to/swingtrader && /absolute/path/to/swingtrader/.venv/bin/python swing_trader.py >> swing_trader.log 2>&1
```

Provide `COINBASE_KEY_FILE` and `DRY_RUN=false` through the cron host's protected environment. Use absolute paths for both the key file and `TRADE_STATE_PATH` when the working directory is not guaranteed.

## Test

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The process returns `0` for a successful run or no-op and `1` for invalid state, market-data failure, authentication failure, or rejected API calls.
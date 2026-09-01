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

### Keep the dashboard running

Install Swingdesk as a per-user Windows Scheduled Task so it starts at sign-in, restarts after failures, and remains available when VS Code and terminal windows are closed:

```powershell
.\install_dashboard_service.ps1
```

The first installation securely prompts for the dashboard password and stores only its salted hash. The stable session secret is protected with Windows DPAPI for the current user. Runtime output is written to the Git-ignored `logs/dashboard-service.log` file. Check or control the task with:

```powershell
Get-ScheduledTask -TaskName "Swingdesk Dashboard"
Start-ScheduledTask -TaskName "Swingdesk Dashboard"
Stop-ScheduledTask -TaskName "Swingdesk Dashboard"
.\uninstall_dashboard_service.ps1
```

On Linux, create the virtual environment and install the equivalent systemd user service:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x install_dashboard_service.sh uninstall_dashboard_service.sh
./install_dashboard_service.sh
```

The Linux installer enables automatic restart and startup for the signed-in user. To keep it running after logout, an administrator can enable user lingering once with `sudo loginctl enable-linger "$USER"`. Remove the service with `./uninstall_dashboard_service.sh`; local password, strategy, and position files are preserved.

### Docker

Docker runs the same Waitress dashboard as an unprivileged user and stores mutable state under `/data`:

```powershell
docker build -t swingdesk:local .
docker volume create swingdesk-data
docker run --rm -p 8787:8080 `
	--mount source=swingdesk-data,target=/data `
	-e DASHBOARD_PASSWORD="use-a-long-unique-password" `
	-e DASHBOARD_SESSION_SECRET="use-a-random-session-secret" `
	-e COINBASE_API_KEY="$env:COINBASE_API_KEY" `
	-e COINBASE_API_SECRET="$env:COINBASE_API_SECRET" `
	-e DRY_RUN=true `
	swingdesk:local
```

Open `http://127.0.0.1:8787`. Use a secrets manager or protected environment file for unattended operation; do not put credentials in an image, Compose file, or repository.

### Azure Container Apps

The Azure template provisions a Basic Azure Container Registry, Azure Files storage, one always-on Container Apps replica, and a dedicated image-pull managed identity. Registry admin access and anonymous pulls are disabled. Azure Files currently requires storage shared-key access for the Container Apps storage mount; the key is resolved during deployment and is not exposed to the application.

Azure is not a zero-cost hosting option. Container Apps compute, ACR, Azure Files, image builds, logs, and outbound traffic can incur charges. Review the current Azure pricing calculator and subscription policy before authorizing deployment.

Prerequisites:

- Azure CLI with Bicep and PowerShell 7
- Permission to create resources and role assignments in the target resource group
- A reviewed target subscription, tenant, resource group, and region
- Four secrets in the current process environment: `DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET`, `COINBASE_API_KEY`, and `COINBASE_API_SECRET`

Compile locally without signing in or changing Azure:

```powershell
az bicep build --file .\infra\main.bicep --stdout | Out-Null
.\scripts\Deploy-Azure.ps1 -Subscription "MSFT-ClientCAB-1" -ValidateOnly
```

After the resource group exists, preview the exact Azure changes. The script verifies the active tenant and subscription, keeps secure Bicep values in a temporary owner-only file, and deletes that file in a `finally` block:

```powershell
az login
$env:DASHBOARD_PASSWORD = "use-a-long-unique-password"
$env:DASHBOARD_SESSION_SECRET = "use-a-random-session-secret"
$env:COINBASE_API_KEY = "organizations/.../apiKeys/..."
$env:COINBASE_API_SECRET = @"
-----BEGIN EC PRIVATE KEY-----
...
-----END EC PRIVATE KEY-----
"@

.\scripts\Deploy-Azure.ps1 `
	-Subscription "MSFT-ClientCAB-1" `
	-ResourceGroup "rg-swingdesk-prod" `
	-Location "eastus2" `
	-WhatIf
```

Only after reviewing the preview and explicitly authorizing resource creation, run the same command without `-WhatIf`. It prompts for the exact word `DEPLOY`, creates the resource group if needed, provisions the supporting infrastructure, builds Swingdesk in ACR, and then creates the Container App with the final image. Omit `-LiveTrading` for the default dry-run deployment.

#### GitHub OIDC setup

The workflow is manual-only and targets a protected GitHub environment. The following one-time commands create Azure resources and role assignments, so run them only after deployment is authorized. They create a dedicated CI managed identity with no client secret and scope its permissions to the target resource group:

```powershell
$subscriptionName = "MSFT-ClientCAB-1"
$resourceGroup = "rg-swingdesk-prod"
$location = "eastus2"
$identityName = "swingdesk-github"

az account set --subscription $subscriptionName
$account = az account show --output json | ConvertFrom-Json
az group create --name $resourceGroup --location $location --output none
$identity = az identity create `
	--name $identityName `
	--resource-group $resourceGroup `
	--location $location `
	--output json | ConvertFrom-Json
$scope = "/subscriptions/$($account.id)/resourceGroups/$resourceGroup"
az role assignment create `
	--assignee-object-id $identity.principalId `
	--assignee-principal-type ServicePrincipal `
	--role Contributor `
	--scope $scope `
	--output none
az role assignment create `
	--assignee-object-id $identity.principalId `
	--assignee-principal-type ServicePrincipal `
	--role "Role Based Access Control Administrator" `
	--scope $scope `
	--output none
az identity federated-credential create `
	--name github-production `
	--identity-name $identityName `
	--resource-group $resourceGroup `
	--issuer "https://token.actions.githubusercontent.com" `
	--subject "repo:jwgmpi-wolff/swingdesk:environment:production" `
	--audiences "api://AzureADTokenExchange" `
	--output none

"AZURE_CLIENT_ID=$($identity.clientId)"
"AZURE_TENANT_ID=$($account.tenantId)"
"AZURE_SUBSCRIPTION_ID=$($account.id)"
```

In GitHub repository settings:

1. Create an environment named `production`, add required reviewers, and prevent self-review where available.
2. Add repository variable `AZURE_ENVIRONMENT=production`.
3. Add environment variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP=rg-swingdesk-prod`, and `AZURE_LOCATION=eastus2`.
4. Add environment secrets `DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET`, `COINBASE_API_KEY`, and `COINBASE_API_SECRET`.
5. Run **Deploy Swingdesk to Azure** from the Actions tab and approve the protected environment. The workflow tests Python, compiles Bicep, signs in through OIDC, builds the image, and deploys it in dry-run mode.

To enable deployment on each push to `main` later, add a `push` trigger to the workflow only after the environment approval rules and branch protection have been verified.

#### Verify, roll back, and remove

The deployment prints the HTTPS URL. Confirm the health endpoint and then test login and a dry-run strategy execution:

```powershell
$url = az containerapp list `
	--resource-group "rg-swingdesk-prod" `
	--query "[?tags.application=='swingdesk'].properties.configuration.ingress.fqdn | [0]" `
	--output tsv
Invoke-RestMethod "https://$url/healthz"
```

To roll back, redeploy an existing ACR image tag without rebuilding:

```powershell
.\scripts\Deploy-Azure.ps1 `
	-Subscription "MSFT-ClientCAB-1" `
	-ResourceGroup "rg-swingdesk-prod" `
	-ImageTag "<previous-git-sha>" `
	-SkipBuild
```

Deleting the resource group permanently removes the app, registry images, and Azure Files trading state. Export any state that must be retained, then require an explicit confirmation:

```powershell
az group delete --name "rg-swingdesk-prod" --subscription "MSFT-ClientCAB-1"
```

### Native Android app

The native Android shell is in `android/` and keeps trading logic and credentials on the Windows dashboard server. It requires Android 8 or newer. Build the release APK and optionally update a connected device in place:

```powershell
.\build_android.ps1
.\build_android.ps1 -Install
```

The published artifact is `dist/Swingdesk.apk`. The install command preserves existing application data and launches the app. The release defaults to the public Azure HTTPS endpoint, and upgrades automatically migrate retired generated Swingdesk endpoints while preserving custom server selections. Tap **Server** in the Android toolbar to select another HTTP or HTTPS deployment.

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
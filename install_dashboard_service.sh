#!/usr/bin/env bash
set -euo pipefail

port="${1:-8787}"
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
  echo "Port must be an integer between 1024 and 65535." >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_path="$project_root/.venv/bin/python"
waitress_path="$project_root/.venv/bin/waitress-serve"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/swingdesk"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
environment_path="$config_dir/environment"
unit_path="$unit_dir/swingdesk.service"

if [[ ! -x "$python_path" || ! -x "$waitress_path" ]]; then
  echo "Install dependencies first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "$project_root/dashboard_password.json" ]]; then
  (cd "$project_root" && "$python_path" configure_dashboard_password.py)
fi

mkdir -p "$config_dir" "$unit_dir" "$project_root/logs"
chmod 700 "$config_dir"
if [[ ! -f "$environment_path" ]]; then
  session_secret="$("$python_path" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  {
    printf 'DASHBOARD_SESSION_SECRET=%q\n' "$session_secret"
    printf 'COINBASE_KEY_FILE=%q\n' "${COINBASE_KEY_FILE:-}"
  } > "$environment_path"
  chmod 600 "$environment_path"
fi

cat > "$unit_path" <<EOF
[Unit]
Description=Swingdesk dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$project_root
EnvironmentFile=$environment_path
ExecStart=$waitress_path --listen=0.0.0.0:$port --call dashboard:create_app
Restart=always
RestartSec=10
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$project_root

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now swingdesk.service
echo "Swingdesk is running at http://127.0.0.1:$port"
echo "Use 'systemctl --user status swingdesk' and 'journalctl --user -u swingdesk' for status and logs."
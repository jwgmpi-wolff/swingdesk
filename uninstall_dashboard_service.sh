#!/usr/bin/env bash
set -euo pipefail

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
systemctl --user disable --now swingdesk.service 2>/dev/null || true
rm -f "$config_home/systemd/user/swingdesk.service"
systemctl --user daemon-reload
echo "Swingdesk service removed. Password, settings, state, and protected environment were preserved."
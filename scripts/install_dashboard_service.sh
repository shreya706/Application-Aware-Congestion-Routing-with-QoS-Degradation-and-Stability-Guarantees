#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$ROOT/.venv/bin/osken-manager" ]]; then
  echo 'Run scripts/install_dependencies.sh first.' >&2
  exit 1
fi
UNIT=/etc/systemd/system/aa-routing-dashboard.service
sudo install -d -m 0755 /etc/systemd/system
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Application-Aware Routing Dashboard
After=network.target openvswitch-switch.service
Requires=openvswitch-switch.service

[Service]
Type=simple
User=root
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $ROOT/dashboard_server.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=false
ProtectHome=false
ProtectSystem=full
ReadWritePaths=$ROOT /var/run/openvswitch /var/log/openvswitch

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now aa-routing-dashboard.service
echo 'Dashboard service installed and started at http://127.0.0.1:8765'

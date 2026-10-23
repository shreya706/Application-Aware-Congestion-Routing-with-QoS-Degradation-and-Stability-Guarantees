#!/usr/bin/env bash
set -euo pipefail
unset PYTHONPATH PYTHONHOME
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch iperf3 iproute2 iputils-ping python3 python3-venv python3-pip git
sudo systemctl enable --now openvswitch-switch
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
"$ROOT/.venv/bin/python" -m pip check
printf 'Install complete. Activate with: source .venv/bin/activate\n'

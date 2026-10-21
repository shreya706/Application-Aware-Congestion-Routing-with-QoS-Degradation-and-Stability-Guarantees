#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch iperf3 iproute2 iputils-ping python3 python3-venv python3-pip git
sudo systemctl enable --now openvswitch-switch
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
printf 'Install complete. Activate with: source .venv/bin/activate\n'

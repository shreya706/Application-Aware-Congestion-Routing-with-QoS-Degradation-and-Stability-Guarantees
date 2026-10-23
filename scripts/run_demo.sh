#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
sudo mn -c
sudo env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 topology.py

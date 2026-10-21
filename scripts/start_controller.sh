#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
exec sudo -E .venv/bin/osken-manager controller.py

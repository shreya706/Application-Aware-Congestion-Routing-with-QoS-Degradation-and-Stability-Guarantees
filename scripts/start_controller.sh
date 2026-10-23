#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$ROOT/.venv/bin/osken-manager" ]]; then
  echo 'Missing controller environment. Run scripts/install_dependencies.sh first.' >&2
  exit 1
fi
cd "$ROOT"
exec sudo env -u PYTHONPATH -u PYTHONHOME \
  AA_MODE="${AA_MODE:-proposed}" AA_SCENARIO="${AA_SCENARIO:-normal}" \
  "$ROOT/.venv/bin/osken-manager" "$ROOT/controller.py"

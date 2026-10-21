#!/usr/bin/env bash
set -euo pipefail
# Stops Mininet leftovers and removes this demo's QoS object from S4's bottleneck port.
sudo mn -c
if command -v ovs-vsctl >/dev/null 2>&1; then
  sudo ovs-vsctl --if-exists clear Port s4-eth3 qos
fi
echo "Mininet cleanup complete. Controller processes are stopped separately with Ctrl-C."

#!/usr/bin/env bash
set -euo pipefail

modprobe vcan

if ! ip link show vcan0 >/dev/null 2>&1; then
    ip link add dev vcan0 type vcan
fi

ip link set up vcan0

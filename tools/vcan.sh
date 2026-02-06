#!/usr/bin/env bash
set -euo pipefail

IFACE="${1:-vcan0}"

modprobe vcan

if ! ip link show "${IFACE}" >/dev/null 2>&1; then
    ip link add dev "${IFACE}" type vcan
fi

ip link set up "${IFACE}"

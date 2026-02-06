#!/usr/bin/env bash
set -euo pipefail

CAN_IF="${1:-vcan0}"
ECU="${2:-01}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

exec uv run autosvc-ecu-sim --can "${CAN_IF}" --ecu "${ECU}"

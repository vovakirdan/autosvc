#!/usr/bin/env bash
set -euo pipefail

CAN_IF="${1:-vcan0}"
ECU="${2:-01}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOLDENS_DIR="${ROOT_DIR}/fixtures/goldens"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

TMP_DIR="$(mktemp -d)"
EMU_PID=""

cleanup() {
  set +e
  if [[ -n "${EMU_PID}" ]]; then
    kill "${EMU_PID}" >/dev/null 2>&1 || true
    wait "${EMU_PID}" >/dev/null 2>&1 || true
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT INT TERM

setup_vcan() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "${ROOT_DIR}/tools/vcan.sh" "${CAN_IF}"
    return 0
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "${ROOT_DIR}/tools/vcan.sh" "${CAN_IF}"
    return 0
  fi
  echo "error: vcan setup requires root (run as root or install sudo)" >&2
  return 1
}

run_case() {
  local name="$1"
  shift

  uv run autosvc "$@" >"${TMP_DIR}/${name}.raw"
  python3 - "${TMP_DIR}/${name}.raw" "${TMP_DIR}/${name}.json" <<'PY'
import json
import sys

raw_path, out_path = sys.argv[1], sys.argv[2]
raw = open(raw_path, "r", encoding="utf-8").read()
start = raw.find("{")
end = raw.rfind("}")
if start == -1 or end == -1 or end < start:
    raise SystemExit("no JSON object found in output")
obj = json.loads(raw[start : end + 1])
open(out_path, "w", encoding="utf-8").write(json.dumps(obj, sort_keys=True, indent=2) + "\n")
PY

  if diff -u "${GOLDENS_DIR}/${name}.json" "${TMP_DIR}/${name}.json" >/dev/null; then
    echo "OK ${name}"
    return 0
  fi

  echo "MISMATCH ${name}"
  diff -u "${GOLDENS_DIR}/${name}.json" "${TMP_DIR}/${name}.json" || true
  return 1
}

setup_vcan

uv run autosvc-ecu-sim --can "${CAN_IF}" --ecu "${ECU}" >"${TMP_DIR}/emulator.log" 2>&1 &
EMU_PID="$!"

# Give the emulator a moment to attach to the interface.
sleep 0.2

ok=0
run_case "scan" scan --can "${CAN_IF}" || ok=1
run_case "topo_scan_11bit_both" topo scan --can "${CAN_IF}" --can-id-mode 11bit --addressing both || ok=1
run_case "dtc_read_before" dtc read --ecu "${ECU}" --can "${CAN_IF}" || ok=1
run_case "dtc_clear" dtc clear --ecu "${ECU}" --can "${CAN_IF}" || ok=1
run_case "dtc_read_after" dtc read --ecu "${ECU}" --can "${CAN_IF}" || ok=1

kill "${EMU_PID}" >/dev/null 2>&1 || true
wait "${EMU_PID}" >/dev/null 2>&1 || true
EMU_PID=""

uv run autosvc-ecu-sim --can "${CAN_IF}" --can-id-mode 29bit >"${TMP_DIR}/emulator-29bit.log" 2>&1 &
EMU_PID="$!"
sleep 0.2
run_case "topo_scan_29bit_both" topo scan --can "${CAN_IF}" --can-id-mode 29bit --addressing both || ok=1

if [[ "${ok}" -ne 0 ]]; then
  echo "FAIL"
  exit 1
fi

echo "PASS"

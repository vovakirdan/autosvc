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
  # If the interface already exists, don't require root.
  if ip link show "${CAN_IF}" >/dev/null 2>&1; then
    return 0
  fi
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

run_case_env() {
  local name="$1"
  local env_kv="$2"
  shift 2

  env "${env_kv}" uv run autosvc "$@" >"${TMP_DIR}/${name}.raw"
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

run_case_jsonl() {
  local name="$1"
  shift

  uv run autosvc "$@" >"${TMP_DIR}/${name}.raw"
  python3 - "${TMP_DIR}/${name}.raw" "${TMP_DIR}/${name}.jsonl" <<'PY'
import json
import sys

raw_path, out_path = sys.argv[1], sys.argv[2]
out_lines: list[str] = []
with open(raw_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            # Ignore non-JSON noise lines.
            continue
        out_lines.append(json.dumps(obj, sort_keys=True, separators=(",", ":")))
with open(out_path, "w", encoding="utf-8") as f:
    if out_lines:
        f.write("\n".join(out_lines) + "\n")
    else:
        f.write("")
PY

  if diff -u "${GOLDENS_DIR}/${name}.jsonl" "${TMP_DIR}/${name}.jsonl" >/dev/null; then
    echo "OK ${name}"
    return 0
  fi

  echo "MISMATCH ${name}"
  diff -u "${GOLDENS_DIR}/${name}.jsonl" "${TMP_DIR}/${name}.jsonl" || true
  return 1
}

run_case_env_jsonl() {
  local name="$1"
  local env_kv="$2"
  shift 2

  env "${env_kv}" uv run autosvc "$@" >"${TMP_DIR}/${name}.raw"
  python3 - "${TMP_DIR}/${name}.raw" "${TMP_DIR}/${name}.jsonl" <<'PY'
import json
import sys

raw_path, out_path = sys.argv[1], sys.argv[2]
out_lines: list[str] = []
with open(raw_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        out_lines.append(json.dumps(obj, sort_keys=True, separators=(",", ":")))
with open(out_path, "w", encoding="utf-8") as f:
    if out_lines:
        f.write("\n".join(out_lines) + "\n")
    else:
        f.write("")
PY

  if diff -u "${GOLDENS_DIR}/${name}.jsonl" "${TMP_DIR}/${name}.jsonl" >/dev/null; then
    echo "OK ${name}"
    return 0
  fi

  echo "MISMATCH ${name}"
  diff -u "${GOLDENS_DIR}/${name}.jsonl" "${TMP_DIR}/${name}.jsonl" || true
  return 1
}

setup_vcan

uv run autosvc-ecu-sim --can "${CAN_IF}" --ecu "${ECU}" >"${TMP_DIR}/emulator.log" 2>&1 &
EMU_PID="$!"

# Give the emulator a moment to attach to the interface.
sleep 0.2

ok=0
run_case "scan" scan --can "${CAN_IF}" || ok=1
run_case_env "scan_vag" "AUTOSVC_BRAND=vag" scan --can "${CAN_IF}" || ok=1
run_case "topo_scan_11bit_both" topo scan --can "${CAN_IF}" --can-id-mode 11bit --addressing both || ok=1
run_case "dtc_read_before" dtc read --ecu "${ECU}" --can "${CAN_IF}" || ok=1
run_case_env "dtc_read_before_vag" "AUTOSVC_BRAND=vag" dtc read --ecu "${ECU}" --can "${CAN_IF}" || ok=1
run_case "dtc_clear" dtc clear --ecu "${ECU}" --can "${CAN_IF}" || ok=1
run_case "dtc_read_after" dtc read --ecu "${ECU}" --can "${CAN_IF}" || ok=1
run_case "did_read_f190" did read --ecu "${ECU}" --did F190 --can "${CAN_IF}" || ok=1
run_case_jsonl "watch_rpm_changed_5" watch --items "${ECU}:1234" --emit changed --ticks 5 --can "${CAN_IF}" || ok=1

kill "${EMU_PID}" >/dev/null 2>&1 || true
wait "${EMU_PID}" >/dev/null 2>&1 || true
EMU_PID=""

uv run autosvc-ecu-sim --can "${CAN_IF}" --can-id-mode 11bit --ecu 09 >"${TMP_DIR}/emulator-adapt.log" 2>&1 &
EMU_PID="$!"
sleep 0.2

export AUTOSVC_BRAND="vag"
export AUTOSVC_DATA_DIR="${ROOT_DIR}/datasets"
export AUTOSVC_BACKUPS_DIR="${TMP_DIR}/backups"

run_case "adapt_list_09" adapt list --ecu 09 --can "${CAN_IF}" --json || ok=1
run_case "adapt_read_09_ccwr_before" adapt read --ecu 09 --key comfort_close_windows_remote --can "${CAN_IF}" --json || ok=1
run_case "adapt_write_09_ccwr_true" adapt write --ecu 09 --key comfort_close_windows_remote --value true --mode advanced --yes --can "${CAN_IF}" --json || ok=1
run_case "adapt_read_09_ccwr_after" adapt read --ecu 09 --key comfort_close_windows_remote --can "${CAN_IF}" --json || ok=1
run_case "adapt_revert_000001" adapt revert --backup-id 000001 --yes --can "${CAN_IF}" --json || ok=1
run_case "adapt_read_09_ccwr_restored" adapt read --ecu 09 --key comfort_close_windows_remote --can "${CAN_IF}" --json || ok=1
run_case "adapt_write_09_security_fail" adapt write --ecu 09 --key security_demo_protected --value 1 --mode advanced --yes --can "${CAN_IF}" --json || ok=1

unset AUTOSVC_BRAND

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

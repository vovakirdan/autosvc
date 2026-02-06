# Status Report

Date: 2026-02-06

## What Works Today

- Core (client-agnostic):
  - CAN transport abstraction (`CanTransport`)
  - SocketCAN transport (`can0`/`vcan0`)
  - ISO-TP request/response transport (client side)
  - UDS client subset:
    - DiagnosticSessionControl (`0x10`)
    - ReadDTCInformation (`0x19 0x02`)
    - ClearDiagnosticInformation (`0x14`)
  - Domain API: `DiagnosticService`
    - `scan_ecus()`
    - `read_dtcs(ecu)` returning decoded, human-friendly dicts
    - `clear_dtcs(ecu)`
  - DTC decoding + description registry
  - Brand overrides:
    - Generic registry
    - VAG overrides (optional via `AUTOSVC_BRAND=vag` or daemon `--brand vag`)
  - Deterministic record/replay transports for offline runs

- Apps:
  - CLI (`autosvc`)
  - Textual TUI (`autosvc tui`)
  - Optional daemon (`autosvc daemon`) using JSONL over Unix socket

## What Is Tested Via Emulator

The Debian emulator validates:
- SocketCAN wiring via `vcan0`
- ISO-TP multi-frame ECU responses (DTC list)
- UDS service flow for the scenario:
  - scan
  - read_dtcs
  - clear_dtcs
  - read_dtcs

## Autotest Pipeline (Debian)

1. Setup `vcan0`

```bash
sudo tools/vcan.sh vcan0
```

2. Run the emulator (background)

```bash
uv run autosvc-ecu-sim --can vcan0 --ecu 01
```

3. Run scenario commands (CLI, in-process)

```bash
uv run autosvc scan --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
uv run autosvc dtc clear --ecu 01 --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
```

4. Compare against goldens

- Expected JSON outputs are stored in `fixtures/goldens/`.
- `tools/autotest.sh` runs the full flow and diffs outputs.

```bash
sudo tools/autotest.sh vcan0 01
```

## Limitations / Non-Goals

- Only 11-bit CAN IDs (no 29-bit IDs)
- No CAN FD
- ECU discovery strategy is simple (iterates a small address range)
- UDS coverage is intentionally minimal (service diagnostics only)
- No security access, no long sessions, no live data streaming


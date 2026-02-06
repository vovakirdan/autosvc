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
    - `scan_topology(config)` (Discovery 2.0)
    - `read_dtcs(ecu)` returning decoded, human-friendly dicts
    - `clear_dtcs(ecu)`
  - Discovery 2.0
    - Functional scan, physical scan, or both (configurable)
    - Optional UDS session confirmation probing
    - 11-bit and 29-bit CAN identifier modes (flagged)
    - Topology report model (`Topology`, `EcuNode`) with stable serialization
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
  - topology scan (Discovery 2.0)
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
uv run autosvc-ecu-sim --can vcan0 --can-id-mode 11bit
```

3. Run scenario commands (CLI, in-process)

```bash
uv run autosvc scan --can vcan0
uv run autosvc topo scan --can vcan0 --can-id-mode 11bit --addressing both
uv run autosvc dtc read --ecu 01 --can vcan0
uv run autosvc dtc clear --ecu 01 --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
```

Discovery 2.0 flags:
- `--addressing functional|physical|both`
- `--can-id-mode 11bit|29bit`
- `--timeout-ms N`
- `--retries N`
- `--probe-session` / `--no-probe-session`

4. Compare against goldens

- Expected JSON outputs are stored in `fixtures/goldens/`.
- `tools/autotest.sh` runs the full flow and diffs outputs.

```bash
sudo tools/autotest.sh vcan0 01
```

## Limitations / Non-Goals

- 29-bit support uses a single documented convention:
  - physical: `0x18DA<ecu><tester>` / `0x18DA<tester><ecu>` (tester SA = `0xF1`)
  - functional: `0x18DB33F1`
- No support for alternative 29-bit addressing schemes
- No CAN FD
- ECU discovery uses deterministic defaults (small physical range + functional sweep)
- UDS coverage is intentionally minimal (service diagnostics only)
- No security access, no long sessions, no live data streaming

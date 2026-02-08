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
    - Freeze-frame / snapshot context (best-effort, ECU-dependent):
      - Snapshot identification (`0x19 0x04`)
      - Snapshot record (`0x19 0x05`)
    - ClearDiagnosticInformation (`0x14`)
    - ReadDataByIdentifier (`0x22`) (minimal DID registry)
  - Domain API: `DiagnosticService`
    - `scan_ecus()`
    - `scan_topology(config)` (Discovery 2.0)
    - `read_dtcs(ecu)` returning decoded, human-friendly dicts
    - `clear_dtcs(ecu)`
    - `read_did(ecu, did)` and `read_dids(ecu, dids)`
  - Discovery 2.0
    - Functional scan, physical scan, or both (configurable)
    - Optional UDS session confirmation probing
    - 11-bit and 29-bit CAN identifier modes (flagged)
    - Topology report model (`Topology`, `EcuNode`) with stable serialization
  - DTC decoding + description registry
  - Brand overrides:
    - Generic registry
    - VAG overrides (optional via `AUTOSVC_BRAND=vag` or daemon `--brand vag`)
    - VAG semantics v1 (offline, deterministic):
      - ECU name mapping (address -> name) using curated JSON data
      - DTC description dictionaries for `P`/`U`/`C`/`B` starter coverage
      - Generic fallback for unknown codes remains intact
  - Deterministic record/replay transports for offline runs
  - Live data (minimal):
    - tick-based watch list (`autosvc watch`) emitting deterministic JSONL events
    - daemon can stream watch events over the existing JSONL socket connection

- Apps:
  - CLI (`autosvc`)
  - Textual TUI (`autosvc tui`)
  - Optional daemon (`autosvc daemon`) using JSONL over Unix socket

## VAG Semantics v1

VAG semantics are optional and fully offline. They are enabled by selecting the `vag` brand:

- in-process:

```bash
AUTOSVC_BRAND=vag uv run autosvc scan --can can0
AUTOSVC_BRAND=vag uv run autosvc dtc read --ecu 01 --can can0
```

- daemon:

```bash
uv run autosvc daemon --can can0 --sock /tmp/autosvc.sock --brand vag
uv run autosvc --connect /tmp/autosvc.sock scan
```

What is covered (v1):

- ECU names from a VAG-common address map (`autosvc/data/vag/ecu_map.json`)
- Curated, offline DTC descriptions for:
  - `P` (powertrain), `U` (network), `C` (chassis), `B` (body)
- Generic fallback remains for unknown codes

What is NOT covered yet:

- ODX parsing
- VIN/model-specific decoding
- coding/adaptations and flashing/programming

## What Is Tested Via Emulator

The Debian emulator validates:
- SocketCAN wiring via `vcan0`
- ISO-TP multi-frame ECU responses (DTC list)
- UDS service flow for the scenario:
  - scan
  - scan (VAG brand semantics: ECU names)
  - topology scan (Discovery 2.0)
  - read_dtcs
  - read_dtcs (VAG brand semantics: curated descriptions)
  - read_dtcs with freeze-frame (manual; `--with-freeze-frame`)
  - clear_dtcs
  - read_dtcs
  - read_did (VIN)
  - watch (JSONL live DID events)

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
uv run autosvc did read --ecu 01 --did F190 --can vcan0
uv run autosvc watch --items 01:1234 --emit changed --ticks 5 --can vcan0
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
- No security access, no long sessions, and live data coverage is minimal
- VAG semantics are offline and curated (no ODX, no online databases, no freeze-frame)
- No coding/adaptations and no flashing/programming

## Manual Coverage vs Features

Major features and their manual coverage:

- Setup + safety baseline: `docs/manual/SETUP.md`
- First real diagnostic session walkthrough: `docs/manual/FIRST_DIAG.md`
- Discovery 2.0 (functional/physical/both; 11-bit/29-bit): `docs/manual/DISCOVERY.md`
- DTC read/clear + decode: `docs/manual/DTC.md`
- Live data (`0x22`) and watch lists: `docs/manual/LIVE_DATA.md`
- Emulator + Debian autotest flow: `docs/manual/EMULATOR.md`
- Troubleshooting: `docs/manual/COMMON_PROBLEMS.md`
- Limitations / non-goals: `docs/manual/LIMITATIONS.md`

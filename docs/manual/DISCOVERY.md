# ECU Discovery (Discovery 2.0)

Discovery is the step where you try to identify which ECUs are listening for UDS requests.

In practice, discovery is the most fragile part of diagnostics because it depends on:

- gateway behavior
- ignition state / ECU sleep states
- whether an ECU answers functional requests
- 11-bit vs 29-bit addressing conventions

## Functional vs Physical Addressing

Functional addressing:

- You send one request to a well-known "broadcast" CAN ID.
- Any ECU that supports it may respond with its own physical response ID.
- Fast and convenient, but not all ECUs respond.

Physical addressing:

- You send a request to a specific ECU request ID.
- Only that ECU should respond.
- Slower (you need to iterate), but can find ECUs that ignore functional requests.

`autosvc` supports both, and can run them in either order.

## 11-bit vs 29-bit CAN IDs

11-bit (standard IDs):

- Common for UDS on passenger vehicles.
- Typical UDS functional request ID: `0x7DF`
- Typical UDS physical request/response ranges:
  - request: `0x7E0..0x7E7`
  - response: `0x7E8..0x7EF`

29-bit (extended IDs):

- Some vehicles use 29-bit UDS addressing.
- `autosvc` supports one fixed convention (not multiple variants).
- Physical IDs use "normal fixed addressing" with tester source address `0xF1`:
  - request: `0x18DA<ECU><TESTER>` (example: ECU `01` -> `0x18DA01F1`)
  - response: `0x18DA<TESTER><ECU>` (example: ECU `01` -> `0x18DAF101`)
- Functional ID (as used in this repo): `0x18DB33F1`

If your vehicle uses a different 29-bit scheme, discovery may fail even if you see traffic in `candump`.

## What Discovery 2.0 Does

Discovery 2.0 is configurable via `DiscoveryConfig` (core) and flags (CLI/TUI).

Strategy (`--addressing`):

- `functional`: send one functional request and collect responders
- `physical`: probe a small default physical range
- `both`: functional first, then verify via physical probing and merge

CAN ID mode (`--can-id-mode`):

- `11bit` (default)
- `29bit` (extended IDs, behind a flag)

Timing:

- `--timeout-ms N`: per-request timeout
- `--retries N`: retry count for probes

UDS confirmation:

- `--probe-session` (default): send `DiagnosticSessionControl (0x10 0x01)` to confirm the ECU speaks UDS
- `--no-probe-session`: useful if probing causes false negatives

## CLI Examples

Simple scan (returns ECU list):

```bash
uv run autosvc scan --can can0
```

Scan with explicit strategy and timing:

```bash
uv run autosvc scan --can can0 --addressing physical --timeout-ms 500 --retries 2
```

Full topology report (in-process only):

```bash
uv run autosvc topo scan --can can0 --can-id-mode 11bit --addressing both
```

Notes:

- `autosvc topo scan` currently runs only in-process mode (no `--connect` support).
- Topology output includes ECU, tx/rx CAN IDs, and whether UDS was confirmed.

## How The Emulator Mimics Discovery

The Debian `vcan` ECU simulator (`autosvc-ecu-sim`) implements:

- Functional discovery responses for both 11-bit and 29-bit modes
- Physical probe responses for at least ECUs `01` and `03`
- Optional UDS session control behavior (always accepts `0x10 0x01` in the simulator)

This makes discovery deterministic for local tests, but it is not a full vehicle gateway model.


# AGENTS.md (Project Constitution)

This document is the canonical reference for how work in this repo must be done. Follow it for all future changes (humans and coding agents).

## Project Mission

- Goal: plug a laptop into a CAN-based car and quickly obtain service diagnostics results.
- Primary user outcomes: ECU discovery (scan); DTC read/clear with human-friendly decoding; basic live data reads (UDS DIDs) and watch/polling.
- Service-level diagnostics only. This project is not a vehicle programming tool.

## Scope (What We Support)

- Linux-first operation using SocketCAN (`can0`, `vcan0`).
- Protocol stack: CAN -> ISO-TP -> UDS (subset needed for service diagnostics).
- Client frontends: CLI (`autosvc`) for scripting and automation; Textual TUI (`autosvc tui`) for interactive use; optional local daemon (`autosvc daemon`) using JSON Lines over a Unix socket.
- Debian-friendly ECU emulator (`autosvc-ecu-sim`) for development and deterministic automated tests.
- Deterministic golden-based regression tests under `fixtures/goldens/`.

## Non-Goals (What We Do NOT Do)

- No flashing/programming/calibration.
- No coding/adaptations/immobilizer work.
- No cloud services, no telemetry, no background data collection.
- No K-line / KWP2000 support (unless explicitly added later).
- No heavy RPC frameworks (no gRPC, no JSON-RPC).
- No async or threading in our code unless explicitly planned and documented.
- No promise of full OEM coverage; real vehicles vary widely.

## Architecture Rules (Must Not Break)

Layering contract (top to bottom):

- Clients (apps): thin frontends only.
- `autosvc/apps/*` (CLI/TUI/daemon) may format output and orchestrate user flows.
- Apps must not contain protocol logic (UDS/ISO-TP) beyond wiring to the core.
- Core: client-agnostic engine.
- `autosvc/core/*` must not depend on argparse, Textual, sockets/IPC, or daemon lifecycle.
- The core exposes stable service APIs via `autosvc.core.service.DiagnosticService`.
- Transport boundary:
- `autosvc.core.transport.*` provides `CanTransport` implementations (SocketCAN, replay/record, etc.).
- Core services depend only on `CanTransport`, not on `python-can` directly.
- Protocol stacking:
- ISO-TP lives under UDS.
- UDS lives under domain services (discovery/DTC/live data).
- Brand modules:
- Generic baseline must always work.
- Optional brand overrides may extend decoding semantics but must not break generic behavior.

ASCII diagram:

```
                 +------------------------------+
                 |            Apps              |
                 |  CLI  |  TUI  |  Daemon IPC  |
                 +---------------+--------------+
                                 |
                                 v
                 +------------------------------+
                 |       Core (client-agnostic) |
                 |  DiagnosticService + domains |
                 +---------------+--------------+
                                 |
                                 v
                 +------------------------------+
                 |            UDS               |
                 +---------------+--------------+
                                 |
                                 v
                 +------------------------------+
                 |           ISO-TP             |
                 +---------------+--------------+
                                 |
                                 v
                 +------------------------------+
                 |   Transport (CanTransport)   |
                 |  SocketCAN | Replay | Record  |
                 +------------------------------+
```

## Public Interfaces That Must Remain Stable

### CLI compatibility

- Prefer backward compatibility for commands and flags.
- If a flag or output must change, update docs (manual + STATUS), update emulator/goldens, and provide a migration note in docs when practical.

CLI philosophy:

- In-process mode is the default (`--can <iface>`).
- Daemon mode is optional (`--connect <sock>`).
- Outputs used by tests must be deterministic (sorted keys, stable ordering).

### IPC protocol compatibility (JSONL)

- IPC is JSON Lines: one JSON object per line.
- Existing `cmd` requests must keep working.
- Adding new commands/fields is allowed; removing/renaming is not, unless explicitly versioned.
- Event streaming (JSONL) must remain backward compatible: event lines must be distinguishable (e.g. `{"event":"..."}`); non-watching clients must not receive unsolicited events.

### Golden determinism

- `fixtures/goldens/*` are contracts.
- Golden JSON must remain deterministic: stable key ordering (`sort_keys`); stable item ordering (explicit sorting in code); no wall-clock timestamps.

## Development Workflow (How We Change Code)

- Keep tasks small and scoped. Avoid unrelated refactors in feature PRs.
- Keep dependencies minimal. Prefer standard library.
- English only for code comments and user-facing messages.
- Type hints are required for new code; use dataclasses where appropriate.
- Preserve the client-agnostic core:
- do not import CLI/TUI/IPC modules from `autosvc/core/*`.
- do not leak SocketCAN details into core logic; keep them inside transport.
- When behavior changes:
- update emulator (`autosvc/emulator/ecu_sim.py`) if tests or demos depend on it
- update goldens under `fixtures/goldens/`
- update docs (manual + STATUS)

## Testing & Determinism Rules

- Primary test target is Debian with `vcan` + emulator and `tools/autotest.sh` comparing output to goldens.
- Prefer deterministic "ticks" over wall-clock time for emulator and watch flows.
- Avoid non-deterministic iteration order:
- sort ECU lists by ECU string
- sort topology nodes deterministically
- Do not add timestamps, random values, or environment-specific paths to golden outputs.
- If you add a new CLI output used by tests:
- ensure it is stable across runs
- add a golden fixture and extend `tools/autotest.sh`

## Documentation Rules

- User-facing playbook: `docs/manual/*` ("how to diagnose cars" with concrete workflows and debugging steps).
- Technical design: `docs/ARCHITECTURE.md`
- Current capabilities and limitations: `docs/STATUS.md`

When adding a feature:

- If user-facing:
- add/update the relevant manual page under `docs/manual/`
- Always:
- update `docs/STATUS.md`
- update emulator/tests/goldens if behavior is exercised

## Roadmap (Non-Binding)

Ordered list of likely next steps (may change):

- VAG-specific semantics (real DTC dictionaries, ECU naming).
- Discovery/topology improvements (more addressing schemes, better heuristics).
- Live data improvements (DID registry expansion, better scaling/units, watch UX).
- K-line / KWP feasibility spike (separate, explicit project decision).
- Daemon/IPC UX polish (more commands, stronger error reporting, stability tests).
- Packaging/UX polish (better defaults, clearer output modes).

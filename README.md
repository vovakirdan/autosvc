# autosvc

Local automotive service diagnostics with a client-agnostic Python core, a CLI/TUI, and an optional Unix-socket daemon.

## What We Do / What We Don't Do

We do:
- ECU discovery (basic scan)
- Read DTCs and decode them into human-friendly records
- Clear DTCs
- Read a small set of UDS live data (ReadDataByIdentifier / DIDs)
- Watch/poll live data and print JSONL events (tick-based)
- Dataset-driven adaptations (safe configuration writes) with backup/revert (limited)

We don't:
- Flash ECUs
- Do long coding (yet)
- Do immobilizer work
- Support safety-critical operations

## Requirements

- Python 3.11+
- `uv` (package manager)
- Linux with SocketCAN (real `can0` or `vcan0` for local testing)
- Root/sudo for `vcan` setup

## Quick Start (vcan + emulator)

```bash
uv sync
sudo tools/vcan.sh vcan0
```

Terminal 1, start an ECU simulator:

```bash
uv run autosvc-ecu-sim --can vcan0 --ecu 01
```

Terminal 2, run CLI against the simulator (in-process mode):

```bash
uv run autosvc scan --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
uv run autosvc dtc clear --ecu 01 --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
uv run autosvc did read --ecu 01 --did F190 --can vcan0
uv run autosvc watch --items 01:1234 --emit changed --ticks 5 --can vcan0
```

## How To Diagnose A Real Car

- Setup: `docs/manual/SETUP.md`
- First diagnostic session: `docs/manual/FIRST_DIAG.md`
- Adaptations (safe writes): `docs/manual/ADAPTATIONS.md`

## Run The TUI (Textual)

In-process mode:

```bash
uv run autosvc tui --can vcan0
```

Daemon mode:

```bash
uv run autosvc tui --connect /tmp/autosvc.sock
```

## Daemon Mode (JSONL over Unix Socket)

Start daemon:

```bash
uv run autosvc daemon --can vcan0 --sock /tmp/autosvc.sock
```

Use CLI against daemon:

```bash
uv run autosvc --connect /tmp/autosvc.sock scan
uv run autosvc --connect /tmp/autosvc.sock dtc read --ecu 01
uv run autosvc --connect /tmp/autosvc.sock dtc clear --ecu 01
```

Why daemon exists:
- Share a single CAN/ISO-TP/UDS session between multiple clients
- Keep long-lived transport state (and avoid repeated bus init)
- Allow alternative clients later (e.g. HTTP) without touching the core

## Debian Autotest Flow

```bash
sudo tools/autotest.sh vcan0 01
```

Goldens live in `fixtures/goldens/`.

## Brand Overrides (optional)

Brand can be set via environment:

```bash
AUTOSVC_BRAND=vag uv run autosvc dtc read --ecu 01 --can vcan0
```

Or on daemon startup:

```bash
uv run autosvc daemon --can vcan0 --sock /tmp/autosvc.sock --brand vag
```

## Docs

- `docs/ARCHITECTURE.md`
- `docs/EMULATOR.md`
- `docs/STATUS.md`
- `docs/manual/README.md`

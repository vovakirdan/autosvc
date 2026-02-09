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
- Adaptations (dataset-driven writes): `docs/manual/ADAPTATIONS.md`

## Directories / portability

Base directories can be overridden (CLI flags or env):

- `--config-dir` / `AUTOSVC_CONFIG_DIR` (default: `~/.config/autosvc`)
- `--cache-dir` / `AUTOSVC_CACHE_DIR` (default: `~/.cache/autosvc`)
- `--data-dir` / `AUTOSVC_DATA_DIR` (datasets root)
- `--backups-dir` / `AUTOSVC_BACKUPS_DIR` (backup store, default: `<cache>/backups`)

## Adaptations safety UX (Phase 4.1)

- `--mode safe` is **read-only**.
- `--mode advanced` allows allowlisted dataset writes and requires typing `APPLY` (or add `--yes`).
- `--mode unsafe` is password-gated (configure via `autosvc unsafe set-password`).

## Real car troubleshooting / tuning

On a real vehicle, discovery and UDS reads are sensitive to bus setup and timing.
If your results are inconsistent (or empty), try the knobs below.

Common failure modes and what to tweak:

- **Nothing found / empty scan**
  - Try the other CAN ID mode: `--can-id-mode 11bit` vs `--can-id-mode 29bit`.
  - Try addressing selection: `--addressing functional` (broadcast) or `--addressing physical` (direct).
  - Increase timeouts: `--timeout-ms 500` or `--timeout-ms 1000`.
  - Increase retries: `--retries 2` or `--retries 3`.

- **Intermittent timeouts / flaky responses**
  - Increase `--timeout-ms` and `--retries`.
  - Prefer `--addressing physical` if functional requests are noisy on your bus.
  - Verify adapter/bitrate/wiring on the Linux side (SocketCAN must be up and error-free).

- **ECU answers once, then stops responding**
  - Some ECUs dislike extra session probing during discovery.
    Try `--no-probe-session` (i.e. `--probe-session false`).

Examples (real car, in-process mode):

```bash
# Scan with more conservative timing
uv run autosvc --log-dir /tmp/autosvc-bundles scan --can can0 \
  --timeout-ms 500 --retries 2 --addressing both --can-id-mode 11bit

# Deterministic topology scan (physical only)
uv run autosvc --log-dir /tmp/autosvc-bundles topo scan --can can0 \
  --timeout-ms 500 --retries 2 --addressing physical --can-id-mode 11bit

# Read DTCs from a known ECU address (example: 0x01)
uv run autosvc --log-dir /tmp/autosvc-bundles dtc read --ecu 01 --can can0 --can-id-mode 11bit

# If you suspect 29-bit addressing on your platform
uv run autosvc --log-dir /tmp/autosvc-bundles dtc read --ecu 01 --can can0 --can-id-mode 29bit
```

Collecting a log bundle for bug reports:

- Add `--log-dir DIR` to create a per-run folder with:
  - `autosvc.log` (stderr logs)
  - `result.json` (stdout capture)
  - `metadata.json` (timestamp, argv, trace_id)
- For deep diagnostics, also add `--log-level debug` (UDS payloads) or `--trace` (very noisy).

## Logging

By default, `autosvc` prints **command results to stdout** and **logs to stderr**.
This makes it safe to pipe JSON outputs while still seeing diagnostics.

Examples:

```bash
# High-level info logs (default)
uv run autosvc scan --can vcan0

# Debug: UDS request/response (payload hex), timings, IPC request flow
uv run autosvc --log-level debug dtc read --ecu 01 --can vcan0
# (alias)
uv run autosvc -v dtc read --ecu 01 --can vcan0

# Trace: raw CAN frames + ISO-TP frames (very noisy)
uv run autosvc --trace dtc read --ecu 01 --can vcan0

# JSON logs to a file, while stdout stays machine-readable
uv run autosvc --log-format json --log-file /tmp/autosvc.jsonl dtc read --ecu 01 --can vcan0 > /tmp/result.json

# Create a per-run log bundle folder (autosvc.log + result.json + metadata.json)
uv run autosvc --log-dir /tmp/autosvc-bundles dtc read --ecu 01 --can vcan0
```

Log levels:
- `info`: high-level steps and summaries (default)
- `debug`: request/response payloads and timings
- `trace`: CAN + ISO-TP frame-level logging

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

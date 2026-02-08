# autosvc Self-Audit (Acceptance Verification)

Date: 2026-02-08

## Environment

- OS: Zorin OS 18 (Ubuntu 24.04 / `ID_LIKE=debian`)
- Kernel: `6.17.0-14-generic`
- User: non-root (`uid=1000`), `sudo` present but blocked by "no new privileges"

Important runtime limitation for this audit environment:

- Creating SocketCAN interfaces and opening PF_CAN raw sockets is not permitted here.
- This prevents executing SocketCAN/vcan-based runs (emulator, CLI/TUI in-process mode, daemon, and `tools/autotest.sh`).

## Commands Run (With Results)

### Dependency install

✅ `UV_CACHE_DIR=/tmp/uv-cache uv sync`

Notes:

- Without `UV_CACHE_DIR`, `uv sync` fails in sandboxed environments that disallow writing to `~/.cache/uv`.

### CLI entrypoints

✅ `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc --help`

✅ `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc-ecu-sim --help`

### SocketCAN/vcan setup (blocked by environment)

❌ `./tools/vcan.sh vcan0`

- Result: `Cannot open netlink socket: Operation not permitted`

❌ `sudo ./tools/vcan.sh vcan0`

- Result: `sudo: The "no new privileges" flag is set, which prevents sudo from running as root.`

### Emulator + autotest (blocked by environment)

❌ `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc-ecu-sim --can vcan0 --can-id-mode 11bit --ecu 01`

- Result: `PermissionError: [Errno 1] Operation not permitted` while creating a SocketCAN raw socket (PF_CAN)

❌ `./tools/autotest.sh vcan0 01`

- Result: fails during `sudo tools/vcan.sh` with the same "no new privileges" restriction

### CLI smoke set (blocked by environment)

❌ `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc scan --can vcan0`

- Result:

```json
{
  "error": "[Errno 1] Operation not permitted",
  "ok": false
}
```

### Core-only smoke (no SocketCAN required)

✅ Record/replay wrappers (deterministic JSONL):

- Verified via a toy `CanTransport` producing deterministic `tx`/`rx` sequences and validating them with `ReplayTransport`.

✅ VAG DTC semantics selection (offline, deterministic):

- Verified that `AUTOSVC_BRAND=vag` changes descriptions/brand attribution deterministically for known codes and keeps generic fallback for unknown codes.

## Checklist

### A) Repo constitution / docs

- ✅ `AGENTS.md` exists and matches repo reality (mission, layering, constraints, workflow).
- ✅ `README.md` contains uv/vcan/emulator/CLI/TUI/daemon/autotest quick start commands (SocketCAN execution blocked in this environment; docs still correct for Debian).
- ✅ `docs/ARCHITECTURE.md` describes the layering model.
- ✅ `docs/STATUS.md` lists current capabilities, limitations, and manual coverage.
- ✅ `docs/manual/*` exists and matches current CLI flags and workflows (including VAG semantics notes in DTC page).

### B) Client-agnostic core

- ✅ Core exposes `autosvc.core.service.DiagnosticService` used by CLI/TUI/daemon.
- ✅ Core does not import CLI/TUI/daemon/IPC modules.
- ✅ Transport abstraction is respected (`CanTransport` boundary; SocketCAN/Replay/Recorder implementations).

### C) CLI mode

- ❌ In-process CLI execution on SocketCAN (scan/dtc/topo/did/watch) could not be run here due to PF_CAN restrictions.
  - Repro: `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc scan --can vcan0`
- ✅ CLI surface exists and parses expected subcommands/flags (`scan`, `dtc read|clear`, `topo scan`, `did read`, `watch`, `tui`, `daemon`).
- ✅ CLI output formatting is deterministic where required (JSON pretty output uses `sort_keys=True`; JSONL uses stable key sorting).

### D) TUI mode

- ❌ TUI runtime verification is blocked here (in-process requires SocketCAN; daemon requires a running daemon which also requires SocketCAN).
  - Repro: `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc tui --can vcan0`
- ✅ TUI is implemented as a thin client around `DiagnosticService` (in-process) or IPC requests (daemon mode).

### E) Daemon / IPC mode (optional but present)

- ❌ Daemon runtime verification is blocked here (SocketCAN raw sockets not permitted).
  - Repro: `UV_CACHE_DIR=/tmp/uv-cache uv run autosvc daemon --can vcan0 --sock /tmp/autosvc.sock`
- ✅ IPC protocol remains backward compatible:
  - existing commands remain (`scan_ecus`, `read_dtcs`, `clear_dtcs`)
  - new fields/commands were added without removing existing ones
- ✅ Streaming events are implemented for `watch_start` (JSONL event lines + `watch_stop`).

### F) CAN/UDS/ISO-TP correctness (MVP-level)

- ✅ ISO-TP implementation includes SF/FF/CF/FC paths (`autosvc/core/isotp/transport.py`).
- ✅ UDS request pipeline uses ISO-TP transport (and a legacy path for `MockTransport`).
- ❌ End-to-end ISO-TP/UDS verification against SocketCAN emulator is blocked here (PF_CAN restrictions).

### G) Discovery 2.0 + topology

- ✅ Discovery 2.0 implementation exists and is configurable (functional/physical/both; 11/29-bit; session probe).
- ✅ `topo scan` output model includes tx/rx IDs, UDS confirmation, and deterministic ordering.
- ❌ End-to-end discovery runs against vcan emulator are blocked here (PF_CAN restrictions).

### H) Record/Replay + goldens

- ✅ `RecordingTransport` produces deterministic JSONL without timestamps.
- ✅ `ReplayTransport` validates TX sequences and replays RX deterministically (verified with a toy transport).
- ✅ Golden comparison flow exists via `tools/autotest.sh` and `fixtures/goldens/*`.
- ✅ Goldens are deterministic (sorted keys; stable ordering; no wall-clock timestamps).

### I) Emulator + autotest flow on Debian

- ✅ Emulator implements deterministic discovery + DTC + DID + watch behaviors by design.
- ❌ SocketCAN runtime cannot be verified in this environment (PF_CAN restrictions).
- ❌ `tools/autotest.sh` cannot run here because it requires SocketCAN/vcan setup and a usable PF_CAN socket.

### J) DTC human readability + brand semantics

- ✅ Generic DTC formatting produces `P/C/B/U` codes deterministically.
- ✅ Status byte flags decoding is stable and deterministic.
- ✅ Brand selection via `AUTOSVC_BRAND` works (verified for VAG vs generic).
- ✅ VAG semantics v1 present:
  - `autosvc/data/vag/*` exists (ECU map + DTC dictionaries + README)
  - `ecu_name` is attached to topology and DTC outputs (when ECU context is available)
  - VAG descriptions take precedence over generic when both exist (verified using `P0300`)
  - goldens include VAG coverage (`scan_vag.json`, `dtc_read_before_vag.json`)

## Fixes Applied During This Audit

- ISO-TP legacy detection now recognizes `MockTransport` through wrappers (e.g. `RecordingTransport(MockTransport())`) to keep behavior consistent when transports are composed.
- Emulator DTC set and goldens updated to prove VAG override behavior deterministically (`P0300` differs between generic and VAG dictionaries).

## Known Limitations Remaining

- This environment cannot exercise SocketCAN/vcan (no PF_CAN / no netlink privileges), so end-to-end acceptance runs were not executable here.
- On a real Debian host with SocketCAN enabled and sufficient privileges, run:
  - `uv sync`
  - `sudo tools/vcan.sh vcan0`
  - `uv run autosvc-ecu-sim --can vcan0 --can-id-mode 11bit`
  - `sudo tools/autotest.sh vcan0 01`


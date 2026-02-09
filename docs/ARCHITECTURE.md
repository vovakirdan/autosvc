# Architecture

`autosvc` is structured as a client-agnostic diagnostic core with thin client frontends.

## Layers

1. Transport
- `autosvc.core.transport.*`
- Lowest layer: sending/receiving raw CAN frames.
- Implementations:
  - `SocketCanTransport` (SocketCAN/vcan)
  - `MockTransport` (in-memory, legacy single-frame mode)
  - `RecordingTransport` / `ReplayTransport` (deterministic record/replay)

2. ISO-TP
- `autosvc.core.isotp.*`
- Segmentation/reassembly on top of CAN frames.
- Used by the UDS client for request/response payloads.

3. UDS
- `autosvc.core.uds.*`
- Unified Diagnostic Services client.
- Implements the subset needed for service diagnostics (session control, read/clear DTCs).

4. Domain services
- `autosvc.core.service.DiagnosticService`
- Stable client-facing API:
  - `scan_ecus()`
  - `read_dtcs(ecu)`
  - `clear_dtcs(ecu)`
- Performs decoding (DTC formatting + description registry).

5. Clients (frontends)
- `autosvc.apps.*`
- CLI (`autosvc scan`, `autosvc dtc ...`)
- TUI (`autosvc tui`)
- Optional daemon (`autosvc daemon`) exposing a JSONL IPC surface.

## Client-Agnostic Core

The core (`autosvc.core.*`) must not depend on:
- Unix sockets / IPC protocol
- Textual / TUI widgets
- argparse / CLI parsing
- daemon lifecycle concerns

Clients provide a `CanTransport` (in-process mode) or delegate to a daemon (IPC mode).
This keeps the diagnostic engine reusable and makes it easy to add more clients later
(for example, an HTTP client) without refactoring the core.

## Logging

`autosvc` uses Python stdlib `logging` with an additional `TRACE` level (numeric level 5).

Guidelines:
- **INFO**: high-level operations and summaries (scan/read/clear)
- **DEBUG**: request/response payloads, elapsed time, IPC requests
- **TRACE**: raw CAN frames and ISO-TP framing (very noisy)

The default configuration is set up by clients (`autosvc.apps.*`) via `autosvc.logging.setup_logging()`.
The core stays client-agnostic: it only emits logs via module loggers (`logging.getLogger(__name__)`).

To enable trace:

```bash
uv run autosvc --trace dtc read --ecu 01 --can vcan0
```

## Daemon IPC (optional)

- `autosvc.ipc.*`
- Protocol is JSON Lines (one JSON object per line).
- The daemon maps IPC requests to `DiagnosticService` calls and returns JSON responses.
- IPC exists for process separation and for supporting multiple clients without reinitializing the CAN stack.


# Live Data (UDS ReadDataByIdentifier + Watch Lists)

Live data is where `autosvc` reads real-time-ish values from an ECU and keeps polling them.

This is still service diagnostics:

- You are not flashing.
- You are not changing coding/adaptations.
- You are reading values the ECU already exposes via UDS.

## ReadDataByIdentifier (UDS `0x22`)

UDS ReadDataByIdentifier (RDBI) is service `0x22`.

- Request: `22 <DID_hi> <DID_lo>`
- Response: `62 <DID_hi> <DID_lo> <data...>`

A DID ("data identifier") is OEM-specific. Some DIDs (like VIN) are commonly supported, but many are not portable.

`autosvc` has a small built-in DID registry and decoders:

- `F190`: VIN (ASCII)
- `F187`: ECU part number (ASCII, best-effort)
- `1234`: Engine RPM (u16 big-endian)

Important:

- `1234` is an emulator-defined DID used for deterministic tests in this repo. Do not expect it to work on real cars.

## One-Shot DID Read (CLI)

Read VIN from ECU `01`:

```bash
uv run autosvc did read --ecu 01 --did F190 --can can0
```

The output is JSON:

```json
{
  "item": {
    "did": "F190",
    "ecu": "01",
    "name": "VIN",
    "unit": "",
    "value": "WVW..."
  },
  "ok": true
}
```

## Watch Lists (CLI)

A watch list is a list of `(ecu, did)` pairs that `autosvc` polls on each tick.

Watch a DID and stream events as JSONL:

```bash
uv run autosvc watch --items 01:1234 --emit changed --ticks 10 --can can0
```

Event lines look like:

```json
{"did":"1234","ecu":"01","event":"live_did","name":"Engine RPM","tick":1,"unit":"rpm","value":850}
```

Notes:

- `--emit changed` emits only when the value changes.
- `--emit always` emits every tick.
- `--ticks N` is a deterministic stop condition (useful for captures and tests).
- In in-process mode, the watch loop runs ticks back-to-back (no sleeping). `--tick-ms` is currently used only for daemon-side pacing.

## When Live Data Is Useful (And When It Is Misleading)

Useful:

- Sanity-checking that you are talking to the right ECU (VIN, part number).
- Watching a value that changes with an action (pedal pressed, fan commanded, etc.).
- Capturing an intermittent condition where DTCs are not yet stored.

Misleading:

- Assuming DIDs are standardized. Many are not.
- Interpreting values without OEM scaling/units documentation.
- Polling too aggressively on a busy bus (can cause timeouts and false conclusions).

## TUI Live Screen

The Textual TUI includes a basic "Live" screen that polls a small predefined set of DIDs.

- Start TUI in-process:

```bash
uv run autosvc tui --can can0
```

- Or connect to a daemon:

```bash
uv run autosvc tui --connect /tmp/autosvc.sock
```

Behavior:

- The screen polls a fixed set (VIN, part number, and the emulator RPM DID).
- It currently uses polling, not daemon streaming events.

## Daemon Mode: Streaming Events

Daemon mode can stream live DID events to a client over the existing JSONL socket connection.

Practical usage from CLI:

```bash
uv run autosvc --connect /tmp/autosvc.sock watch --items 01:1234 --emit changed --ticks 10 --tick-ms 200
```

Limitations:

- The daemon streams events only after a `watch_start` request.
- While a watch is active, the connection accepts only `watch_stop` (to keep the model simple and thread-free).

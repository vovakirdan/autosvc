# DTCs (Fault Codes): Read, Interpret, Clear

This page focuses on service diagnostics. DTC handling is usually the first useful thing you can do on an unknown car.

## What A DTC Is (In Practice)

A Diagnostic Trouble Code (DTC) is an ECU-owned record that some monitor detected a condition outside expected limits.

Important:

- A DTC is not a full diagnosis. It is a symptom and a hint.
- Many DTCs are consequences (for example, a misfire can trigger a catalytic efficiency code).

## Status: Stored vs Pending vs Confirmed

Terminology varies by OEM, but a common model is:

- Pending: seen once, not yet confirmed (may disappear after a good drive cycle).
- Confirmed: seen enough times to be considered real (often triggers a warning light).
- Stored: persisted in memory (can include confirmed and historical codes, depending on ECU).

`autosvc` currently reports a best-effort `status` label based on UDS status bits:

- `active`: test failed or confirmed bit is set (usually "currently relevant")
- `pending`: pending bit set
- `stored`: everything else (historical/non-active in many ECUs)

If you need the raw view, `autosvc` includes `status_byte` and `flags` in the JSON output.

## Reading DTCs

1. Scan for ECUs:

```bash
uv run autosvc scan --can can0
```

2. Read DTCs from an ECU:

```bash
uv run autosvc dtc read --ecu 01 --can can0
```

The output is JSON with fields like:

- `code` (example `P0420`)
- `status` (`active|pending|stored`)
- `description` (best-effort registry lookup; brand-specific if enabled)
- `flags`, `status_byte` (debugging)
- `severity` (heuristic)

## Generic vs VAG-Specific Descriptions

By default, `autosvc` uses the generic (brand-agnostic) description registry.

If you work primarily with VAG vehicles, you can enable VAG semantics:

- In-process (env var):

```bash
AUTOSVC_BRAND=vag uv run autosvc dtc read --ecu 01 --can can0
```

- Daemon:

```bash
uv run autosvc daemon --can can0 --sock /tmp/autosvc.sock --brand vag
uv run autosvc --connect /tmp/autosvc.sock dtc read --ecu 01
```

Notes:

- VAG descriptions are offline and curated. No network lookups are performed.
- Coverage is intentionally incomplete. Unknown codes fall back to generic or to `Unknown DTC`.

## Freeze-Frame (Snapshot Context)

Some ECUs store a "snapshot" of conditions when a DTC was recorded (commonly called freeze-frame).
This context can make a DTC materially more useful, because it answers "under what conditions did it happen".

`autosvc` can request freeze-frame data via UDS ReadDTCInformation (0x19) snapshot records when available.

To request freeze-frame:

```bash
uv run autosvc dtc read --ecu 01 --can can0 --with-freeze-frame
```

Notes:

- Freeze-frame is ECU-dependent. Many ECUs do not support it, or only provide it for some DTCs.
- If freeze-frame is not available for a DTC, `freeze_frame` will be `null`.
- Unknown parameters are still included with raw hex for offline analysis.
- This is read-only diagnostics. `autosvc` does not write freeze-frame data.
- Daemon mode does not currently support freeze-frame requests (in-process only).

## Clearing DTCs

Clearing codes does NOT fix the root cause. It only removes stored records (until the fault reappears).

To clear:

```bash
uv run autosvc dtc clear --ecu 01 --can can0
```

Then re-read:

```bash
uv run autosvc dtc read --ecu 01 --can can0
```

Practical notes:

- Always save a DTC snapshot before clearing.
- Some ECUs require a specific session or conditions to clear; if clear fails, treat that as signal.
- Clearing may reset readiness and can hide intermittent faults for a while.

## Engine ECU vs Other ECUs

Many vehicles expose a conventional "engine ECU" around ECU address `01` in the 11-bit scheme, but do not assume it.
Use `autosvc scan` output and read DTCs from any ECU that responds.

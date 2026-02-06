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
- `description` (best-effort registry lookup)
- `flags`, `status_byte` (debugging)
- `severity` (heuristic)

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


# Emulator (Debian `vcan`)

The emulator exists so you can:

- develop without access to a car
- run deterministic autotests on Debian
- debug protocol behavior without gateway/vehicle variability

It is intentionally minimal and deterministic.

## Setup `vcan0`

On Debian:

```bash
sudo tools/vcan.sh vcan0
```

This creates a virtual CAN interface (`vcan0`) that behaves like a CAN bus but stays local to your machine.

## Run The ECU Simulator

Terminal 1:

```bash
uv run autosvc-ecu-sim --can vcan0 --can-id-mode 11bit
```

The simulator supports both `11bit` and `29bit` modes:

```bash
uv run autosvc-ecu-sim --can vcan0 --can-id-mode 29bit
```

By default it simulates at least ECUs `01` and `03`.

## Run CLI Against The Emulator

Terminal 2:

```bash
uv run autosvc scan --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
uv run autosvc dtc clear --ecu 01 --can vcan0
uv run autosvc dtc read --ecu 01 --can vcan0
```

Live data examples (emulator-defined DIDs):

```bash
uv run autosvc did read --ecu 01 --did F190 --can vcan0
uv run autosvc did read --ecu 01 --did F187 --can vcan0
uv run autosvc watch --items 01:1234 --emit changed --ticks 5 --can vcan0
```

## How Autotests Use The Emulator

`tools/autotest.sh`:

- sets up `vcan0`
- starts the emulator in the background
- runs a deterministic CLI scenario
- normalizes JSON output and compares against goldens in `fixtures/goldens/`

Run it:

```bash
sudo tools/autotest.sh vcan0 01
```

## Emulator Behavior (What It Implements)

UDS services implemented:

- `0x10` DiagnosticSessionControl (accepts default session)
- `0x19 0x02` ReadDTCInformation (deterministic list for ECU `01`)
- `0x14` ClearDiagnosticInformation (clears stored DTC list)
- `0x22` ReadDataByIdentifier (DID)
  - `F190` VIN (ASCII)
  - `F187` ECU part number (ASCII)
  - `1234` Engine RPM (u16 big-endian; scripted)

Tick scripting for RPM DID `0x1234`:

- The simulator increments an internal counter only when `0x22` reads DID `0x1234`.
- Returned RPM sequence is deterministic per ECU per run:
  - 850, 900, 950, ...

Discovery behavior:

- Responds to functional discovery requests in both 11-bit and 29-bit modes.
- Responds to physical probes for at least ECUs `01` and `03`.

## How To Extend The Emulator

`autosvc/emulator/ecu_sim.py` is the single file simulator.

Practical extension pattern:

1. Add a new SID handler in `EcuSimulator.handle_uds()`.
2. Add deterministic state to `EcuSimulator` (avoid wall-clock time).
3. Add a CLI scenario and golden under `fixtures/goldens/`.
4. Document the new behavior in the manual and in `docs/STATUS.md`.

If you need multi-frame behavior, keep ISO-TP compliant even if your initial payload fits in a single frame.


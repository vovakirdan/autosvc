# ECU Emulator (Debian / vcan)

The emulator provides a minimal ECU that responds to the subset of UDS used by `autosvc`.
It exists so the project can be tested on Debian without a real vehicle.

## Run

```bash
sudo tools/vcan.sh vcan0
uv run autosvc-ecu-sim --can vcan0 --ecu 01
```

## Addressing

For ECU `01`:
- Request ID: `0x7E0 + 0x01` (0x7E1)
- Response ID: `0x7E8 + 0x01` (0x7E9)

## Implemented UDS Services

- DiagnosticSessionControl (`0x10`)
  - Request: `10 <session_type>`
  - Response: `50 <session_type>`

- ReadDTCInformation (`0x19`, subfunction `0x02`)
  - Request: `19 02 <status_mask>`
  - Response: `59 02 <status_mask> <dtc_hi> <dtc_lo> <status> ...`
  - The emulator starts with two deterministic DTCs:
    - `P2002` (active)
    - `P0420` (stored)

- ClearDiagnosticInformation (`0x14`)
  - Request: `14 FF FF FF`
  - Response: `54`
  - Clears the in-memory DTC list.

## ISO-TP Behavior

The emulator implements ISO-TP framing for both single-frame and multi-frame messages.
The DTC response is intentionally long enough to require a multi-frame response so the stack is exercised.

## Extending

Common extensions live in `autosvc/emulator/ecu_sim.py`:
- Add more ECUs by instantiating multiple simulators and dispatching by CAN ID.
- Add more UDS services by extending `EcuSimulator._handle_uds()`.
- Add larger payloads to validate ISO-TP handling (multi-frame requests and responses).


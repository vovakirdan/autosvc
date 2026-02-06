# First Diagnostic Session (Step-by-Step)

This is the "I just plugged a laptop into an older Skoda and I want to see errors" workflow.

Assumptions:

- You have a SocketCAN adapter and a working `can0`.
- You are on Linux (Debian-style commands shown).
- You are doing service diagnostics only (no flashing).

## 1) Connect Adapter

1. Plug the adapter into the vehicle (OBD-II port).
2. Put ignition to ON (engine can stay OFF).
3. Confirm the adapter is visible to Linux (device-specific, but `dmesg` should show it).

## 2) Bring Up CAN

Pick a bitrate. Many powertrain buses are 500 kbit/s; some are 250 kbit/s.

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 up type can bitrate 500000
ip -details link show can0
```

If you are not sure, try 250 kbit/s:

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 250000
```

## 3) Verify Bus Traffic

Before running diagnostics, make sure you actually see frames:

```bash
candump -L can0
```

If this is silent, do not proceed with `autosvc` yet. Fix the physical/OS layer first.

## 4) Run ECU Discovery

Start with the default discovery strategy (functional + physical):

```bash
uv run autosvc scan --can can0
```

If that finds nothing, try the other CAN ID mode:

```bash
uv run autosvc scan --can can0 --can-id-mode 29bit --addressing both
```

If you want full addressing metadata (in-process only):

```bash
uv run autosvc topo scan --can can0 --can-id-mode 11bit --addressing both
```

## 5) Read DTCs

Pick an ECU address from the scan output and read codes:

```bash
uv run autosvc dtc read --ecu 01 --can can0
```

Repeat for any other ECUs returned by `autosvc scan`.

## 6) Interpret The Output

`autosvc dtc read` returns JSON with:

- `code`: SAE-like code string (example `P0420`)
- `status`: `active|pending|stored` (best-effort mapping from UDS status bits)
- `description`: best-effort description from the registry (may be `Unknown DTC`)
- `flags` and `status_byte`: raw status information for debugging

Practical notes:

- If `status` is `active`, you typically have a current fault or a currently-failing monitor.
- `pending` often means "seen once, not confirmed yet" (ECU-specific).
- `stored` is usually historical or currently-not-active, but still recorded.

## 7) If Nothing Answers

Work through this list:

1. Verify you are on the right bus.
2. Verify bitrate (500k vs 250k).
3. Verify ignition state (some ECUs sleep).
4. Try both CAN ID modes:
   - `--can-id-mode 11bit`
   - `--can-id-mode 29bit`
5. Try different discovery strategies:
   - `--addressing functional`
   - `--addressing physical`
6. Increase timeouts:
   - `--timeout-ms 500 --retries 2`
7. Disable session probing if it causes false negatives:
   - `--no-probe-session`

If you still get nothing, it may not be UDS on CAN (or it may be gated by a gateway/security).


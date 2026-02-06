# Common Problems (And How To Debug Them)

This is a pragmatic checklist. Fix the physical/OS layer first, then protocol layers.

## No CAN Traffic In `candump`

Symptoms:

- `candump -L can0` prints nothing.

What to check:

- Ignition is ON (many ECUs sleep when the car is off).
- You are on the correct bus (some OBD ports expose only gateway traffic; some cars have multiple buses).
- Bitrate is correct (try 500 kbit/s and 250 kbit/s).
- Your adapter is supported and actually attached (check `dmesg` output).

## `autosvc scan` Finds Nothing, But `candump` Shows Traffic

Symptoms:

- You see frames in `candump`.
- `uv run autosvc scan --can can0` returns an empty list.

What to check:

- Try the other CAN ID mode:

```bash
uv run autosvc scan --can can0 --can-id-mode 29bit --addressing both
```

- Try physical-only scan (some ECUs ignore functional requests):

```bash
uv run autosvc scan --can can0 --addressing physical
```

- Try disabling session probing (some ECUs behave oddly to session control):

```bash
uv run autosvc scan --can can0 --no-probe-session
```

- Increase timeout/retries:

```bash
uv run autosvc scan --can can0 --timeout-ms 500 --retries 2
```

## Scan Works, But `dtc read` Times Out

This usually means one of:

- You discovered a node, but it is not a UDS ECU.
- The ECU requires a different session or a different addressing convention.
- Transport timing is too tight for that ECU.

Try:

- Increase discovery timeout first (to reduce false positives), then retry DTC read.
- Try another ECU from the scan list.
- Verify you are in the correct CAN ID mode (`--can-id-mode`).

## `did read` Returns Negative Response

Symptoms:

- `uv run autosvc did read ...` returns an error like `negative response 0x31`.

Interpretation:

- The ECU does not support that DID, or supports it only in a different session.

Practical approach:

- Start with broadly supported DIDs like `F190` (VIN) on many UDS ECUs.
- Treat emulator-only DIDs (like `1234` in this repo) as test fixtures, not real-vehicle expectations.

## Daemon Socket Problems

Symptoms:

- Client cannot connect, or connects but returns errors.

Checks:

- Is the daemon running?
- Does the socket exist?

```bash
ls -l /tmp/autosvc.sock
```

- Are you pointing at the right path?

```bash
uv run autosvc --connect /tmp/autosvc.sock scan
```

If in doubt, kill the daemon and restart it (socket cleanup is automatic on startup).

## Works On Emulator, Not On A Car

This is expected sometimes. The emulator is intentionally deterministic and implements only a subset.

Common real-world causes:

- Wrong bitrate / wrong bus
- Gateway filtering
- Non-UDS ECUs
- Different 29-bit addressing scheme than the one `autosvc` currently supports

If you can capture a short `candump` trace, you can compare:

- Do you see 0x7DF / 0x7E8.. traffic (11-bit functional/physical)?
- Do you see 0x18DAxxxx frames (29-bit physical addressing)?

## TUI Issues

If the TUI is blank or behaves oddly:

- Ensure your terminal supports full-screen apps.
- Try in-process mode first:

```bash
uv run autosvc tui --can can0
```

If daemon mode is required, confirm the daemon is running and reachable.


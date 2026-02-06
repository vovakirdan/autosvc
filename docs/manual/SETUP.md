# Setup (Real Vehicle)

This page is about wiring, Linux, and a reliable baseline before you run `autosvc`.

## Supported Scope (Practical)

`autosvc` targets CAN-based service diagnostics using ISO-TP + UDS.

- Good fit: vehicles with UDS ECUs on CAN (for example, many VAG vehicles around 2008+).
- Not guaranteed: older VAG (K-line/KWP), motorcycles, heavy-duty (often different conventions), non-UDS ECUs.
- Reality: many cars have multiple CAN buses behind a gateway; you may be on the wrong bus even if you see traffic.

## Hardware

Recommended:

- A SocketCAN-capable CAN adapter with a stable Linux driver (native SocketCAN, not a userspace bridge).
- A proper OBD-II cable/connector for your adapter.

Strongly discouraged for serious diagnostics:

- ELM327-style OBD dongles (often slow, unreliable for ISO-TP/UDS, and frequently fake).

Notes:

- Your adapter must support the bus bitrate your vehicle uses (commonly 500 kbit/s or 250 kbit/s).
- Ensure your adapter supports the ID mode you need (11-bit is common; 29-bit exists on some platforms).

## Linux Baseline (Debian)

Install CAN tools (highly recommended):

```bash
sudo apt install can-utils
```

Bring up `can0` at a known bitrate (example: 500 kbit/s):

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 up type can bitrate 500000
ip -details link show can0
```

Try 250 kbit/s if 500 kbit/s shows no meaningful traffic:

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 250000
```

Verify you can see CAN traffic:

```bash
candump -L can0
```

What you want to see:

- Frames appear immediately after ignition ON (or after opening a door).
- Arbitration IDs and data bytes change over time.

If `candump` shows nothing:

- Verify ignition state and that you are connected to the correct bus.
- Re-check bitrate.
- Check adapter detection: `dmesg | tail -n 200`.
- Some adapters require extra bring-up steps (device-specific).

## Safety Notes

- Prefer a stable power state: ignition ON, engine OFF for first tests.
- Always read and save DTCs before clearing them.
- Clearing DTCs can reset readiness and may hide intermittent issues.
- Do not run diagnostics while driving.

## `autosvc` Installation (Local)

In the repo root:

```bash
uv sync
```

Run commands via `uv run`:

```bash
uv run autosvc scan --can can0
```

You typically need `sudo` to bring CAN up/down, but you may not need `sudo` to run `autosvc` once the interface is up.


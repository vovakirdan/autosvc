# Adaptations (Safe ECU Configuration Changes)

This page describes dataset-driven UDS adaptations in `autosvc`. This is the first step towards ECU configuration changes, and it is intentionally conservative.

## What Adaptations Are (In Practice)

An adaptation is a configuration value stored inside an ECU. Changing it can affect vehicle behavior.

Examples (varies by ECU and model):

- comfort/locking behavior
- lighting timeouts
- convenience features

Adaptations are not diagnostics. They are ECU configuration writes, and you should treat them as potentially risky.

## Safety Model (Safe, Advanced, Unsafe)

`autosvc` supports three modes for write operations:

- `safe`: only allow dataset settings marked `risk="safe"`
- `advanced`: allow `risk="safe"` and `risk="risky"`
- `unsafe`: allow raw writes by DID and raw bytes (still performs backup-before-write)

Notes:

- Mode only controls what the tool will allow you to attempt. It does not make the ECU accept a write.
- Some DIDs require UDS SecurityAccess (`0x27`). `autosvc` has a scaffold for `0x27` but does not implement seed/key algorithms yet.
  - If an ECU requires security, writes will fail with a clear error.

## Dataset Packs (Offline, Local)

Adaptations are dataset-driven. A dataset pack is a local folder with profiles describing settings for an ECU.

Default lookup:

- `./datasets/` (repo root, when running from source), or
- `AUTOSVC_DATASETS_DIR=/path/to/datasets`

Brand selection:

- `AUTOSVC_BRAND=vag` selects `datasets/vag/`

Minimal structure:

```
datasets/
└─ vag/
   ├─ manifest.json
   └─ adaptations/
      └─ ecu_09.json
```

The loader is strict. If a profile is invalid, `autosvc` will return an error pointing at the file and key.

## Backups And Revert (Must-Use)

Before any write, `autosvc` reads the current raw DID bytes and stores a backup record.

Default backup location:

- `~/.local/share/autosvc/backups/` (Linux)

Override location (useful for testing):

- `AUTOSVC_BACKUP_DIR=/tmp/autosvc-backups`

Backups are sequentially numbered (`000001`, `000002`, ...) and contain no timestamps. This keeps regression tests deterministic.

## CLI Usage

Set the brand so `autosvc` knows which dataset pack to load:

```bash
export AUTOSVC_BRAND=vag
```

List settings for ECU `09`:

```bash
uv run autosvc adapt list --ecu 09 --can can0
```

Read a setting:

```bash
uv run autosvc adapt read --ecu 09 --key comfort_close_windows_remote --can can0
```

Write a setting (dataset-driven, with backup):

```bash
uv run autosvc adapt write --ecu 09 --key comfort_close_windows_remote --value true --mode safe --can can0
```

In `advanced` / `unsafe` mode, the CLI will require confirmation unless you pass `--yes`.

Revert using a backup id:

```bash
uv run autosvc adapt revert --backup-id 000001 --can can0
```

Raw write (unsafe, requires explicit intent):

```bash
uv run autosvc adapt write-raw --ecu 09 --did 1234 --hex 01 --mode unsafe --can can0
```

## TUI Usage

In-process only:

```bash
export AUTOSVC_BRAND=vag
uv run autosvc tui --can can0
```

Workflow:

1. Scan and select an ECU
2. Open `Adapt`
3. Select a setting to read current value
4. Enter a new value and apply (confirm dialog)
5. Revert using the last backup id (session-scoped)

## Emulator Notes

The Debian emulator provides a deterministic adaptation demo for ECU `09`:

- DID `0x1234` (bool) is writable
- DID `0x1237` (u16) is writable
- DID `0x1337` is write-protected and returns a simulated security NRC

This is intentionally simplified. Real ECUs may use different DIDs, require sessions, or require security access.

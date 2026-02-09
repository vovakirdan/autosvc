# Adaptations (Safe ECU Configuration Changes)

This page describes dataset-driven UDS adaptations in `autosvc`. This is the first step towards ECU configuration changes, and it is intentionally conservative.

## What Adaptations Are (In Practice)

An adaptation is a configuration value stored inside an ECU. Changing it can affect vehicle behavior.

Examples (varies by ECU and model):

- comfort/locking behavior
- lighting timeouts
- convenience features

Adaptations are not diagnostics. They are ECU configuration writes, and you should treat them as potentially risky.

## Safety Model (safe, advanced, unsafe)

`autosvc` supports three modes:

- `safe`: **read-only** (no writes)
- `advanced`: allowlisted dataset-driven writes only (`risk="safe"` and `risk="risky"`)
- `unsafe`: unrestricted raw writes, but **password-gated**

Notes:

- Mode only controls what the tool will allow you to attempt. It does not make the ECU accept a write.
- Some DIDs require UDS SecurityAccess (`0x27`). `autosvc` does not implement seed/key algorithms yet.
  - If an ECU requires security, writes will fail with a clear error.

### Advanced mode confirmation

In `advanced` mode, the CLI requires an interactive confirmation token.

- You must type `APPLY` when prompted.
- Add `--yes` to skip the prompt.

### Unsafe mode password gating

Unsafe operations require a password **every time**.

1) Configure the password:

```bash
uv run autosvc unsafe set-password
```

2) Use unsafe mode (you will be prompted):

```bash
uv run autosvc adapt write-raw --ecu 09 --did 1234 --hex 01 --mode unsafe --can can0
```

If you need non-interactive usage, provide the password via stdin:

```bash
echo -n 'YOUR_PASSWORD' | uv run autosvc adapt write-raw --ecu 09 --did 1234 --hex 01 --mode unsafe --unsafe-password-stdin --can can0
```

`autosvc` never logs the password.

## Dataset Packs (Offline, Local)

Adaptations are dataset-driven. A dataset pack is a local folder with profiles describing settings for an ECU.

Brand selection:

- `AUTOSVC_BRAND=vag` selects the VAG dataset pack.

Datasets root lookup:

- `AUTOSVC_DATA_DIR=/path/to/datasets` (recommended), or
- `AUTOSVC_DATASETS_DIR=/path/to/datasets` (back-compat)

Minimal structure:

```
datasets/
└─ vag/
   ├─ manifest.json
   └─ adaptations/
      └─ ecu_09.json
```

The loader is strict. If a profile is invalid, `autosvc` will return an error pointing at the file and key.

## Backups (Global Index + Per-backup Files)

Before any write, `autosvc` reads the current raw DID bytes and stores a backup record.

Default backup location:

- `~/.cache/autosvc/backups/`
  - `index.jsonl` (append-only index)
  - `<backup_id>.json` (per-backup record)

Overrides:

- `AUTOSVC_BACKUPS_DIR=/path`
- `AUTOSVC_BACKUP_DIR=/path` (back-compat)

When `--log-dir DIR` is used, any backup created during that run is also copied into the run bundle:

- `DIR/backups/index.jsonl`
- `DIR/backups/<backup_id>.json`

Backups are sequentially numbered (`000001`, `000002`, ...) and contain no wall-clock timestamps (keeps tests deterministic).

## Manual backups (snapshots)

You can create manual snapshots without writing anything:

Backup a DID directly:

```bash
uv run autosvc backup did --ecu 09 --did F190 --can can0
```

Backup an adaptation key (uses the dataset to resolve DID):

```bash
uv run autosvc adapt backup --ecu 09 --key comfort_close_windows_remote --can can0
```

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
uv run autosvc adapt write --ecu 09 --key comfort_close_windows_remote --value true --mode advanced --can can0
```

Revert using a backup id:

```bash
uv run autosvc adapt revert --backup-id 000001 --can can0
```

Raw write (unsafe, password-gated):

```bash
uv run autosvc adapt write-raw --ecu 09 --did 1234 --hex 01 --mode unsafe --can can0
```

## Emulator Notes

The emulator provides a deterministic adaptation demo for ECU `09`:

- DID `0x1234` (bool) is writable
- DID `0x1237` (u16) is writable
- DID `0x1337` is write-protected and returns a simulated security NRC

This is intentionally simplified. Real ECUs may use different DIDs, require sessions, or require security access.

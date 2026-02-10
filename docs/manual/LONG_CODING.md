# Long Coding (v1)

Long Coding is a **dataset-driven bitfield editor** built on top of UDS `ReadDataByIdentifier`/`WriteDataByIdentifier`.

It is designed to be:

- deterministic and testable (emulator + goldens)
- safe by default (read-only in `safe` mode)
- explicit about risk (allowlist + `--mode unsafe` for dangerous fields)

## Concepts

- **Profile**: per-ECU mapping from a DID (coding blob) to named fields.
- **Field**: a named bitfield inside a coding blob.

Dataset format lives in:

- `datasets/<brand>/longcoding/*.json` (repo fixtures for tests)
- `autosvc/data/datasets/<brand>/longcoding/*.json` (packaged datasets)

### v1 limitations

- fields must fit within a single byte (`bit + len <= 8`)
- only these kinds are supported:
  - `bool`
  - `u8` (bitfield interpreted as integer)
  - `enum` (integer with labels)

## CLI

All commands require a dataset brand, e.g.:

```bash
export AUTOSVC_BRAND=vag
export AUTOSVC_DATA_DIR=./datasets
```

### List fields

```bash
autosvc coding list --ecu 09 --can vcan0
```

### Read a field

```bash
autosvc coding read --ecu 09 --key auto_lock --can vcan0
```

### Write a field (creates a backup)

`safe` mode is **read-only**.

```bash
autosvc coding write --ecu 09 --key auto_lock --value true --mode advanced --can vcan0
```

Before writing, the CLI requires an explicit confirmation token (`APPLY`) unless `--yes` is provided.

### Revert using a backup id

```bash
autosvc coding revert --backup-id 000002 --can vcan0
```

### Unsafe fields

Some dataset fields are marked `risk=unsafe`.

- `--mode advanced` refuses them
- `--mode unsafe` requires the unsafe password (see `autosvc unsafe set-password`)

This is an **allowlist** mechanism: you must opt in to unsafe writes.

## Emulator demo

The built-in emulator includes a deterministic long coding demo for ECU `09`:

- DID `0600` (4 bytes) – demo coding blob
- DID `0601` (1 byte) – demo protected DID (write returns `securityAccessDenied`)

These DIDs are **emulator-only fixtures**. Do not expect them to exist on real vehicles.

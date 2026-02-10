# UDS SecurityAccess (0x27)

SecurityAccess (UDS service `0x27`) is used by ECUs to gate certain operations (e.g. coding/adaptations) behind an unlock.

## Safety / policy

- **autosvc does not ship any OEM seed-key algorithms.**
- The default workflow is **manual**:
  1) request a seed for a level
  2) compute the key externally (tooling you already have / vendor docs)
  3) send the key back

If you provide a key or your own algorithm module, you are responsible for ensuring you are allowed to do so.

## CLI

### Request seed

```bash
autosvc security seed --ecu 09 --level 01 --can vcan0 --json
```

Notes:
- `--level` is the **seed request sub-function** (typically odd, e.g. `0x01`, `0x03`, ...).

### Unlock (send key)

Manual key:

```bash
autosvc security unlock --ecu 09 --level 01 --key-hex DEADBEEF --can vcan0 --json
```

Recommended (avoid putting secrets in shell history):

```bash
echo DEADBEEF | autosvc security unlock --ecu 09 --level 01 --key-hex-stdin --can vcan0 --json
```

`autosvc security unlock` will:
- request seed using sub-function `--level`
- send the key using sub-function `level + 1`

### Optional user-provided algorithm (no built-in OEM algorithms)

You may supply a Python module name or a path to a `.py` file implementing:

```python
def compute_key(seed: bytes, level: int, ecu: str) -> bytes:
    ...
```

Then:

```bash
autosvc security unlock --ecu 09 --level 01 --algo-module /path/to/my_algo.py --can vcan0 --json
```

You can also set `AUTOSVC_SECURITY_ALGO` to the module reference.

## Using SecurityAccess as a pre-unlock for writes

Some dataset-driven writes are marked as requiring SecurityAccess.

For `adapt write`, `adapt write-raw`, `coding write`, and `coding write-raw` you can optionally request an unlock first:

```bash
autosvc coding write \
  --ecu 09 --key security_demo_protected --value true \
  --mode advanced --yes \
  --security-level 01 --security-key-hex-stdin \
  --can vcan0 --json
```

If `--security-level` is not provided, **autosvc will not attempt any unlocking**.

# VAG Data (Offline, Curated)

This directory contains offline, curated VAG-common semantics used by the `vag` brand module.

Goals:

- Fully offline and deterministic (no runtime lookups, no network).
- Minimal but useful starter coverage.
- Easy to extend by editing JSON files.

Non-goals:

- No ODX parsing.
- No VIN/model-specific decoding.
- No freeze-frame or guided fault finding.

## Files

- `ecu_map.json`: maps ECU diagnostic addresses (e.g. `"01"`) to human-readable names (VAG-common).
- `dtc_powertrain.json`: `P` codes (powertrain).
- `dtc_network.json`: `U` codes (network/communication).
- `dtc_chassis.json`: `C` codes (chassis).
- `dtc_body.json`: `B` codes (body).

## Extension Guidelines

- Keys must be uppercase formatted codes (`P0300`, `U0100`, ...).
- Descriptions must be concise, technical, and neutral.
- Do not add trailing punctuation.
- Keep wording stable and avoid synonyms churn (golden tests depend on determinism).
- If you are unsure about a description, prefer leaving the code absent so generic fallback applies.


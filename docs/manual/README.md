# Diagnostic Manual

This manual is a practical playbook for using `autosvc` on real vehicles.

- Audience: engineers / advanced enthusiasts.
- Scope: service diagnostics only (discovery, DTCs, a minimal set of live data).
- Assumption: you already know what CAN, ISO-TP, and UDS are at a basic level.

## Index

- Setup: `docs/manual/SETUP.md`
- First real diagnostic session: `docs/manual/FIRST_DIAG.md`
- Common problems: `docs/manual/COMMON_PROBLEMS.md`
- ECU discovery (Discovery 2.0): `docs/manual/DISCOVERY.md`
- Fault codes (DTCs): `docs/manual/DTC.md`
- Live data (DIDs + watch lists): `docs/manual/LIVE_DATA.md`
- Adaptations (dataset-driven, safe writes): `docs/manual/ADAPTATIONS.md`
- Emulator (when you do not have a car): `docs/manual/EMULATOR.md`
- Limitations / non-goals: `docs/manual/LIMITATIONS.md`

## Keeping It In Sync (Living Document)

This manual is part of the product. When you change behavior, update the manual in the same PR/commit:

- CLI flags/subcommands: `autosvc/apps/cli.py`
- TUI behavior/screens: `autosvc/apps/tui.py`
- Daemon IPC commands/events: `autosvc/ipc/protocol.py`, `autosvc/ipc/unix_server.py`
- Emulator behavior: `autosvc/emulator/ecu_sim.py`

If a feature is incomplete or experimental, say so explicitly in the relevant page.

## Feature Coverage Checklist

- [x] Discovery 2.0 (functional/physical/both; 11-bit/29-bit): `docs/manual/DISCOVERY.md`
- [x] DTC read/clear + decoding: `docs/manual/DTC.md`
- [x] Live data: ReadDataByIdentifier (`0x22`) + watch lists: `docs/manual/LIVE_DATA.md`
- [x] Adaptations v1 (dataset-driven, backups + revert): `docs/manual/ADAPTATIONS.md`
- [x] Emulator + Debian `vcan` flow: `docs/manual/EMULATOR.md`
- [x] Troubleshooting playbook: `docs/manual/COMMON_PROBLEMS.md`
- [x] Limitations and non-goals: `docs/manual/LIMITATIONS.md`

If you add a new major feature, also update:

- `docs/manual/README.md` (this checklist)
- `docs/STATUS.md` ("Manual coverage vs features")

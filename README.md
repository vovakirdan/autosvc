# autosvc

Local automotive diagnostic service backend with a minimal TUI client.

## Requirements

- Python 3.11+
- SocketCAN for real hardware (or vcan0 for local testing)

## Quick start

```bash
uv sync
autosvc-backend --transport mock
autosvc-tui
```

## SocketCAN

```bash
sudo tools/vcan.sh
autosvc-backend --transport socketcan --can-if vcan0
```

## IPC protocol

Requests (JSON Lines):

```json
{"cmd":"scan_ecus"}
{"cmd":"read_dtcs","ecu":"01"}
{"cmd":"clear_dtcs","ecu":"01"}
```

Responses:

```json
{"ok":true,"ecus":["01","03","08"]}
```

```json
{"ok":true,"dtcs":[{"code":"P2002","status":"active"}]}
```

Errors:

```json
{"ok":false,"error":"message"}
```

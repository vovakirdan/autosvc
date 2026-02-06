from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from autosvc.core.service import DiagnosticService
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.ipc.unix_client import UnixJsonlClient


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autosvc", description="Automotive service diagnostics (CLI/TUI/daemon).")
    parser.add_argument(
        "--connect",
        dest="global_connect",
        default=None,
        help="Unix socket path to use daemon mode (can be placed before or after the subcommand).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan", help="Scan ECUs")
    _add_can_args(scan_p)
    _add_connect_arg(scan_p)

    dtc_p = sub.add_parser("dtc", help="DTC operations")
    dtc_sub = dtc_p.add_subparsers(dest="dtc_cmd", required=True)

    dtc_read_p = dtc_sub.add_parser("read", help="Read DTCs")
    dtc_read_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    _add_can_args(dtc_read_p)
    _add_connect_arg(dtc_read_p)

    dtc_clear_p = dtc_sub.add_parser("clear", help="Clear DTCs")
    dtc_clear_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    _add_can_args(dtc_clear_p)
    _add_connect_arg(dtc_clear_p)

    tui_p = sub.add_parser("tui", help="Run Textual TUI")
    tui_p.add_argument("--can", default=None, help="SocketCAN interface (in-process mode)")
    _add_connect_arg(tui_p)

    daemon_p = sub.add_parser("daemon", help="Run Unix socket JSONL daemon")
    daemon_p.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")
    daemon_p.add_argument("--sock", default="/tmp/autosvc.sock", help="Unix socket path")
    daemon_p.add_argument("--brand", default=None, help="Optional brand registry (e.g. vag)")

    args = parser.parse_args(argv)

    if args.cmd == "daemon":
        from autosvc.apps.daemon import main as daemon_main

        daemon_main(["--can", args.can, "--sock", args.sock, "--brand", args.brand] if args.brand else ["--can", args.can, "--sock", args.sock])
        return None

    if args.cmd == "tui":
        from autosvc.apps.tui import main as tui_main

        connect = getattr(args, "connect", None) or args.global_connect
        tui_args: list[str] = []
        if connect:
            tui_args.extend(["--connect", connect])
        if args.can:
            tui_args.extend(["--can", args.can])
        tui_main(tui_args)
        return None

    if args.cmd == "scan":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "scan_ecus"})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        can_if = args.can
        response = _run_inprocess(can_if, op="scan")
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    if args.cmd == "dtc" and args.dtc_cmd == "read":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "read_dtcs", "ecu": args.ecu})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(args.can, op="read_dtcs", ecu=args.ecu)
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    if args.cmd == "dtc" and args.dtc_cmd == "clear":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "clear_dtcs", "ecu": args.ecu})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(args.can, op="clear_dtcs", ecu=args.ecu)
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    parser.error("unknown command")


def _add_can_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")


def _add_connect_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--connect", default=None, help="Unix socket path (daemon mode)")


def _print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def _ipc_request(sock_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    client = UnixJsonlClient(sock_path)
    try:
        return client.request(payload)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _run_inprocess(can_if: str, *, op: str, ecu: str | None = None) -> dict[str, Any]:
    transport: SocketCanTransport | None = None
    try:
        transport = SocketCanTransport(channel=can_if)
        service = DiagnosticService(transport)
        if op == "scan":
            return {"ok": True, "ecus": service.scan_ecus()}
        if op == "read_dtcs":
            assert ecu is not None
            return {"ok": True, "dtcs": service.read_dtcs(ecu)}
        if op == "clear_dtcs":
            assert ecu is not None
            service.clear_dtcs(ecu)
            return {"ok": True}
        return {"ok": False, "error": "invalid operation"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if transport is not None:
            transport.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from autosvc.core.service import DiagnosticService
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.core.vehicle.discovery import DiscoveryConfig
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
    _add_discovery_args(scan_p)

    dtc_p = sub.add_parser("dtc", help="DTC operations")
    dtc_sub = dtc_p.add_subparsers(dest="dtc_cmd", required=True)

    dtc_read_p = dtc_sub.add_parser("read", help="Read DTCs")
    dtc_read_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    _add_can_args(dtc_read_p)
    _add_connect_arg(dtc_read_p)
    _add_can_id_mode_arg(dtc_read_p)

    dtc_clear_p = dtc_sub.add_parser("clear", help="Clear DTCs")
    dtc_clear_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    _add_can_args(dtc_clear_p)
    _add_connect_arg(dtc_clear_p)
    _add_can_id_mode_arg(dtc_clear_p)

    tui_p = sub.add_parser("tui", help="Run Textual TUI")
    tui_p.add_argument("--can", default=None, help="SocketCAN interface (in-process mode)")
    _add_connect_arg(tui_p)
    _add_can_id_mode_arg(tui_p)
    tui_p.add_argument("--addressing", choices=["functional", "physical", "both"], default="both")

    daemon_p = sub.add_parser("daemon", help="Run Unix socket JSONL daemon")
    daemon_p.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")
    daemon_p.add_argument("--sock", default="/tmp/autosvc.sock", help="Unix socket path")
    daemon_p.add_argument("--brand", default=None, help="Optional brand registry (e.g. vag)")

    topo_p = sub.add_parser("topo", help="Topology operations")
    topo_sub = topo_p.add_subparsers(dest="topo_cmd", required=True)
    topo_scan_p = topo_sub.add_parser("scan", help="Scan and report topology")
    _add_can_args(topo_scan_p)
    _add_connect_arg(topo_scan_p)
    _add_discovery_args(topo_scan_p)

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
        if args.can_id_mode:
            tui_args.extend(["--can-id-mode", args.can_id_mode])
        if args.addressing:
            tui_args.extend(["--addressing", args.addressing])
        tui_main(tui_args)
        return None

    if args.cmd == "scan":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "scan_ecus"})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(
            args.can,
            can_id_mode=args.can_id_mode,
            op="scan",
            addressing=args.addressing,
            timeout_ms=args.timeout_ms,
            retries=args.retries,
            probe_session=args.probe_session,
        )
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    if args.cmd == "topo" and args.topo_cmd == "scan":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            _print_json({"ok": False, "error": "topology scan is not available in daemon mode"})
            raise SystemExit(1)
        response = _run_inprocess(
            args.can,
            can_id_mode=args.can_id_mode,
            op="scan_topology",
            addressing=args.addressing,
            timeout_ms=args.timeout_ms,
            retries=args.retries,
            probe_session=args.probe_session,
        )
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    if args.cmd == "dtc" and args.dtc_cmd == "read":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "read_dtcs", "ecu": args.ecu})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(args.can, can_id_mode=args.can_id_mode, op="read_dtcs", ecu=args.ecu)
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    if args.cmd == "dtc" and args.dtc_cmd == "clear":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "clear_dtcs", "ecu": args.ecu})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(args.can, can_id_mode=args.can_id_mode, op="clear_dtcs", ecu=args.ecu)
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    parser.error("unknown command")


def _add_can_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")


def _add_connect_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--connect", default=None, help="Unix socket path (daemon mode)")

def _add_can_id_mode_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")


def _add_discovery_args(parser: argparse.ArgumentParser) -> None:
    _add_can_id_mode_arg(parser)
    parser.add_argument("--addressing", choices=["functional", "physical", "both"], default="both")
    parser.add_argument("--timeout-ms", type=int, default=250)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--probe-session", action=argparse.BooleanOptionalAction, default=True)


def _print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def _ipc_request(sock_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    client = UnixJsonlClient(sock_path)
    try:
        return client.request(payload)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _run_inprocess(
    can_if: str,
    *,
    can_id_mode: str = "11bit",
    op: str,
    ecu: str | None = None,
    addressing: str = "both",
    timeout_ms: int = 250,
    retries: int = 1,
    probe_session: bool = True,
) -> dict[str, Any]:
    transport: SocketCanTransport | None = None
    try:
        transport = SocketCanTransport(channel=can_if, is_extended_id=(can_id_mode == "29bit"))
        service = DiagnosticService(transport, can_interface=can_if, can_id_mode=can_id_mode)
        if op == "scan":
            topo = service.scan_topology(
                DiscoveryConfig(
                    addressing=addressing,
                    can_id_mode=can_id_mode,
                    timeout_ms=timeout_ms,
                    retries=retries,
                    probe_session=probe_session,
                )
            )
            return {"ok": True, "ecus": [n.ecu for n in topo.nodes]}
        if op == "scan_topology":
            topo = service.scan_topology(
                DiscoveryConfig(
                    addressing=addressing,
                    can_id_mode=can_id_mode,
                    timeout_ms=timeout_ms,
                    retries=retries,
                    probe_session=probe_session,
                )
            )
            return {"ok": True, "topology": topo.to_dict()}
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

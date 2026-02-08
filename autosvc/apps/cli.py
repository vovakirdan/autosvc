from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any

from autosvc.core.service import DiagnosticService
from autosvc.core.live.watch import WatchItem, Watcher
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.core.uds.did import parse_did
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
    dtc_read_p.add_argument(
        "--with-freeze-frame",
        action="store_true",
        help="Best-effort freeze-frame / snapshot context (in-process mode only).",
    )
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
    daemon_p.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")
    daemon_p.add_argument("--sock", default="/tmp/autosvc.sock", help="Unix socket path")
    daemon_p.add_argument("--brand", default=None, help="Optional brand registry (e.g. vag)")

    topo_p = sub.add_parser("topo", help="Topology operations")
    topo_sub = topo_p.add_subparsers(dest="topo_cmd", required=True)
    topo_scan_p = topo_sub.add_parser("scan", help="Scan and report topology")
    _add_can_args(topo_scan_p)
    _add_connect_arg(topo_scan_p)
    _add_discovery_args(topo_scan_p)

    did_p = sub.add_parser("did", help="DID operations (ReadDataByIdentifier)")
    did_sub = did_p.add_subparsers(dest="did_cmd", required=True)
    did_read_p = did_sub.add_parser("read", help="Read a DID")
    did_read_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    did_read_p.add_argument("--did", required=True, help="DID as hex (e.g. F190, 1234)")
    _add_can_args(did_read_p)
    _add_connect_arg(did_read_p)
    _add_can_id_mode_arg(did_read_p)

    watch_p = sub.add_parser("watch", help="Watch live DIDs and stream events (JSONL)")
    watch_p.add_argument("--items", required=True, help="Comma-separated list like 01:F190,01:1234")
    watch_p.add_argument("--emit", choices=["changed", "always"], default="changed")
    watch_p.add_argument("--ticks", type=int, default=10)
    watch_p.add_argument("--tick-ms", type=int, default=200)
    _add_can_args(watch_p)
    _add_connect_arg(watch_p)
    _add_can_id_mode_arg(watch_p)

    args = parser.parse_args(argv)

    if args.cmd == "daemon":
        from autosvc.apps.daemon import main as daemon_main

        daemon_argv = ["--can", args.can, "--can-id-mode", args.can_id_mode, "--sock", args.sock]
        if args.brand:
            daemon_argv.extend(["--brand", args.brand])
        daemon_main(daemon_argv)
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
            if args.with_freeze_frame:
                _print_json({"ok": False, "error": "freeze-frame is not available in daemon mode"})
                raise SystemExit(1)
            response = _ipc_request(connect, {"cmd": "read_dtcs", "ecu": args.ecu})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(
            args.can,
            can_id_mode=args.can_id_mode,
            op="read_dtcs",
            ecu=args.ecu,
            with_freeze_frame=bool(args.with_freeze_frame),
        )
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

    if args.cmd == "did" and args.did_cmd == "read":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            response = _ipc_request(connect, {"cmd": "read_did", "ecu": args.ecu, "did": args.did})
            _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        response = _run_inprocess(
            args.can,
            can_id_mode=args.can_id_mode,
            op="read_did",
            ecu=args.ecu,
            did=args.did,
        )
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

    if args.cmd == "watch":
        connect = getattr(args, "connect", None) or args.global_connect
        items = _parse_watch_items(args.items)
        if connect:
            _watch_via_daemon(
                connect,
                items=items,
                emit=args.emit,
                tick_ms=args.tick_ms,
                ticks=args.ticks,
            )
            raise SystemExit(0)

        _watch_inprocess(
            args.can,
            can_id_mode=args.can_id_mode,
            items=items,
            emit=args.emit,
            tick_ms=args.tick_ms,
            ticks=args.ticks,
        )
        raise SystemExit(0)

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
    did: str | None = None,
    with_freeze_frame: bool = False,
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
            nodes = [{"ecu": n.ecu, "ecu_name": getattr(n, "ecu_name", "Unknown ECU")} for n in topo.nodes]
            return {"ok": True, "ecus": [n.ecu for n in topo.nodes], "nodes": nodes}
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
            return {"ok": True, "dtcs": service.read_dtcs(ecu, with_freeze_frame=with_freeze_frame)}
        if op == "clear_dtcs":
            assert ecu is not None
            service.clear_dtcs(ecu)
            return {"ok": True}
        if op == "read_did":
            assert ecu is not None
            assert did is not None
            did_int = parse_did(did)
            return {"ok": True, "item": service.read_did(ecu, did_int)}
        return {"ok": False, "error": "invalid operation"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if transport is not None:
            transport.close()


def _parse_watch_items(value: str) -> list[WatchItem]:
    raw = (value or "").strip()
    if not raw:
        raise SystemExit("error: --items is required")
    items: list[WatchItem] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise SystemExit("error: invalid --items format (expected ECU:DID)")
        ecu, did = part.split(":", 1)
        ecu = ecu.strip().upper()
        try:
            did_int = parse_did(did.strip())
        except Exception as exc:
            raise SystemExit("error: invalid DID in --items") from exc
        items.append(WatchItem(ecu=ecu, did=did_int))
    if not items:
        raise SystemExit("error: --items is required")
    return items


def _watch_inprocess(
    can_if: str,
    *,
    can_id_mode: str,
    items: list[WatchItem],
    emit: str,
    tick_ms: int,
    ticks: int,
) -> None:
    transport = SocketCanTransport(channel=can_if, is_extended_id=(can_id_mode == "29bit"))
    service = DiagnosticService(transport, can_interface=can_if, can_id_mode=can_id_mode)
    try:
        watch = Watcher(service, items=items, emit_mode=emit, tick_ms=tick_ms)
        for evt in watch.run_ticks(max_ticks=int(ticks), sleep=False):
            sys.stdout.write(json.dumps(evt.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    finally:
        transport.close()


def _watch_via_daemon(
    sock_path: str,
    *,
    items: list[WatchItem],
    emit: str,
    tick_ms: int,
    ticks: int,
) -> None:
    payload = {
        "cmd": "watch_start",
        "items": [{"ecu": it.ecu, "did": f"{int(it.did) & 0xFFFF:04X}"} for it in items],
        "emit": emit,
        "tick_ms": int(tick_ms),
        "max_ticks": int(ticks),
    }
    data = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2.0)
        sock.connect(sock_path)
        sock.sendall(data)
        fileobj = sock.makefile("rb")
        with fileobj:
            while True:
                line = fileobj.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("event") == "live_did":
                    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
                    sys.stdout.flush()
                if isinstance(obj, dict) and obj.get("ok") and obj.get("done"):
                    break


if __name__ == "__main__":
    main()

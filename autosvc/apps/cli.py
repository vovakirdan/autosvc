from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import uuid
from typing import Any

import os

from autosvc.config import ensure_dirs, load_dirs
from autosvc.runlog import TeeTextIO, create_run_log_dir
from autosvc.unsafe import prompt_password

from autosvc.core.service import DiagnosticService
from autosvc.core.live.watch import WatchItem, Watcher
from autosvc.core.safety.confirm import confirm_or_raise
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.core.uds.did import parse_did
from autosvc.core.vehicle.discovery import DiscoveryConfig
from autosvc.ipc.unix_client import UnixJsonlClient
from autosvc.logging import TRACE_LEVEL, parse_log_level, setup_logging, trace_context


log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autosvc", description="Automotive service diagnostics (CLI/TUI/daemon).")
    _add_logging_args(parser)
    _add_dir_args(parser)
    parser.add_argument(
        "--connect",
        dest="global_connect",
        default=None,
        help="Unix socket path to use daemon mode (can be placed before or after the subcommand).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan", help="Scan ECUs")
    _add_logging_args(scan_p)
    _add_can_args(scan_p)
    _add_connect_arg(scan_p)
    _add_discovery_args(scan_p)

    dtc_p = sub.add_parser("dtc", help="DTC operations")
    dtc_sub = dtc_p.add_subparsers(dest="dtc_cmd", required=True)

    dtc_read_p = dtc_sub.add_parser("read", help="Read DTCs")
    _add_logging_args(dtc_read_p)
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
    _add_logging_args(dtc_clear_p)
    dtc_clear_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    _add_can_args(dtc_clear_p)
    _add_connect_arg(dtc_clear_p)
    _add_can_id_mode_arg(dtc_clear_p)

    tui_p = sub.add_parser("tui", help="Run Textual TUI")
    _add_logging_args(tui_p)
    tui_p.add_argument("--can", default=None, help="SocketCAN interface (in-process mode)")
    _add_connect_arg(tui_p)
    _add_can_id_mode_arg(tui_p)
    tui_p.add_argument("--addressing", choices=["functional", "physical", "both"], default="both")

    daemon_p = sub.add_parser("daemon", help="Run Unix socket JSONL daemon")
    _add_logging_args(daemon_p)
    daemon_p.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")
    daemon_p.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")
    daemon_p.add_argument("--sock", default="/tmp/autosvc.sock", help="Unix socket path")
    daemon_p.add_argument("--brand", default=None, help="Optional brand registry (e.g. vag)")

    topo_p = sub.add_parser("topo", help="Topology operations")
    _add_logging_args(topo_p)
    topo_sub = topo_p.add_subparsers(dest="topo_cmd", required=True)
    topo_scan_p = topo_sub.add_parser("scan", help="Scan and report topology")
    _add_logging_args(topo_scan_p)
    _add_can_args(topo_scan_p)
    _add_connect_arg(topo_scan_p)
    _add_discovery_args(topo_scan_p)

    did_p = sub.add_parser("did", help="DID operations (ReadDataByIdentifier)")
    _add_logging_args(did_p)
    did_sub = did_p.add_subparsers(dest="did_cmd", required=True)
    did_read_p = did_sub.add_parser("read", help="Read a DID")
    _add_logging_args(did_read_p)
    did_read_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 01)")
    did_read_p.add_argument("--did", required=True, help="DID as hex (e.g. F190, 1234)")
    _add_can_args(did_read_p)
    _add_connect_arg(did_read_p)
    _add_can_id_mode_arg(did_read_p)

    watch_p = sub.add_parser("watch", help="Watch live DIDs and stream events (JSONL)")
    _add_logging_args(watch_p)
    watch_p.add_argument("--items", required=True, help="Comma-separated list like 01:F190,01:1234")
    watch_p.add_argument("--emit", choices=["changed", "always"], default="changed")
    watch_p.add_argument("--ticks", type=int, default=10)
    watch_p.add_argument("--tick-ms", type=int, default=200)
    _add_can_args(watch_p)
    _add_connect_arg(watch_p)
    _add_can_id_mode_arg(watch_p)

    backup_p = sub.add_parser("backup", help="Manual backups (DID snapshots)")
    _add_logging_args(backup_p)
    backup_sub = backup_p.add_subparsers(dest="backup_cmd", required=True)

    backup_did_p = backup_sub.add_parser("did", help="Backup a DID value (snapshot)")
    _add_logging_args(backup_did_p)
    backup_did_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 09)")
    backup_did_p.add_argument("--did", required=True, help="DID as hex (e.g. F190, 1234)")
    backup_did_p.add_argument("--notes", default=None, help="Optional notes")
    backup_did_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(backup_did_p)
    _add_connect_arg(backup_did_p)
    _add_can_id_mode_arg(backup_did_p)

    unsafe_p = sub.add_parser("unsafe", help="Unsafe mode password management")
    _add_logging_args(unsafe_p)
    unsafe_sub = unsafe_p.add_subparsers(dest="unsafe_cmd", required=True)
    unsafe_set_p = unsafe_sub.add_parser("set-password", help="Set/replace the unsafe mode password")
    _add_logging_args(unsafe_set_p)

    unsafe_status_p = unsafe_sub.add_parser("status", help="Show whether the unsafe password is configured")
    _add_logging_args(unsafe_status_p)

    adapt_p = sub.add_parser("adapt", help="Adaptations (dataset-driven, with backup/revert safety)")
    _add_logging_args(adapt_p)
    adapt_sub = adapt_p.add_subparsers(dest="adapt_cmd", required=True)

    adapt_backup_p = adapt_sub.add_parser("backup", help="Create a manual backup snapshot for an adaptation key")
    _add_logging_args(adapt_backup_p)
    adapt_backup_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 09)")
    adapt_backup_p.add_argument("--key", required=True, help="Dataset setting key")
    adapt_backup_p.add_argument("--notes", default=None, help="Optional notes")
    adapt_backup_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(adapt_backup_p)
    _add_connect_arg(adapt_backup_p)
    _add_can_id_mode_arg(adapt_backup_p)

    adapt_list_p = adapt_sub.add_parser("list", help="List available adaptation settings for an ECU")
    _add_logging_args(adapt_list_p)
    adapt_list_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 09)")
    adapt_list_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(adapt_list_p)
    _add_connect_arg(adapt_list_p)
    _add_can_id_mode_arg(adapt_list_p)

    adapt_read_p = adapt_sub.add_parser("read", help="Read an adaptation setting")
    _add_logging_args(adapt_read_p)
    adapt_read_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 09)")
    adapt_read_p.add_argument("--key", required=True, help="Dataset setting key")
    adapt_read_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(adapt_read_p)
    _add_connect_arg(adapt_read_p)
    _add_can_id_mode_arg(adapt_read_p)

    adapt_write_p = adapt_sub.add_parser("write", help="Write an adaptation setting (with backup)")
    _add_logging_args(adapt_write_p)
    adapt_write_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 09)")
    adapt_write_p.add_argument("--key", required=True, help="Dataset setting key")
    adapt_write_p.add_argument("--value", required=True, help="New value (format depends on kind)")
    adapt_write_p.add_argument("--mode", choices=["safe", "advanced", "unsafe"], default="safe")
    adapt_write_p.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    adapt_write_p.add_argument(
        "--unsafe-password-stdin",
        action="store_true",
        help="Read unsafe password from stdin (no echo). If not set, you will be prompted.",
    )
    adapt_write_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(adapt_write_p)
    _add_connect_arg(adapt_write_p)
    _add_can_id_mode_arg(adapt_write_p)

    adapt_raw_p = adapt_sub.add_parser("write-raw", help="Unsafe raw DID write (with backup)")
    _add_logging_args(adapt_raw_p)
    adapt_raw_p.add_argument("--ecu", required=True, help="ECU address as hex (e.g. 09)")
    adapt_raw_p.add_argument("--did", required=True, help="DID as hex (e.g. 1234)")
    adapt_raw_p.add_argument("--hex", dest="hex_payload", required=True, help="Raw bytes as hex (e.g. 01)")
    adapt_raw_p.add_argument("--mode", choices=["unsafe"], default="unsafe")
    adapt_raw_p.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    adapt_raw_p.add_argument(
        "--unsafe-password-stdin",
        action="store_true",
        help="Read unsafe password from stdin (no echo). If not set, you will be prompted.",
    )
    adapt_raw_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(adapt_raw_p)
    _add_connect_arg(adapt_raw_p)
    _add_can_id_mode_arg(adapt_raw_p)

    adapt_rev_p = adapt_sub.add_parser("revert", help="Revert a previous write using a backup id")
    _add_logging_args(adapt_rev_p)
    adapt_rev_p.add_argument("--backup-id", required=True, help="Backup id (e.g. 000001)")
    adapt_rev_p.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    adapt_rev_p.add_argument("--json", action="store_true", help="Output deterministic JSON (for tests)")
    _add_can_args(adapt_rev_p)
    _add_connect_arg(adapt_rev_p)
    _add_can_id_mode_arg(adapt_rev_p)

    args = parser.parse_args(argv)

    _apply_dir_overrides(args)

    # Ensure base dirs exist early (for unsafe password and backup store).
    ensure_dirs(load_dirs())

    # Logging (stderr/file). Keep command results on stdout.
    level_name: str | None = getattr(args, "log_level", None)
    if getattr(args, "trace", False):
        level = TRACE_LEVEL
    elif getattr(args, "verbose", False):
        level = logging.DEBUG
    else:
        level = parse_log_level(level_name)

    trace_id = uuid.uuid4().hex[:12]

    log_file = getattr(args, "log_file", None)
    runlog = None
    result_fh = None
    stdout_orig = sys.stdout
    try:
        if getattr(args, "log_dir", None):
            argv_for_meta = [parser.prog] + (list(argv) if argv is not None else sys.argv[1:])
            runlog = create_run_log_dir(str(args.log_dir), trace_id=trace_id, argv=argv_for_meta)
            if not log_file:
                log_file = str(runlog.log_path)
            result_fh = open(runlog.result_path, "w", encoding="utf-8")
            sys.stdout = TeeTextIO(sys.stdout, result_fh)

        setup_logging(
            level=level,
            log_format=str(getattr(args, "log_format", "pretty") or "pretty"),
            log_file=log_file,
            no_color=bool(getattr(args, "no_color", False)),
        )

        with trace_context(trace_id):
            log.debug("CLI start", extra={"cmd": getattr(args, "cmd", None), "trace_id": trace_id})
            _dispatch(args)
    finally:
        sys.stdout = stdout_orig
        if result_fh is not None:
            result_fh.flush()
            result_fh.close()


def _dispatch(args: argparse.Namespace) -> None:
    if args.cmd == "daemon":
        from autosvc.apps.daemon import main as daemon_main

        daemon_argv = ["--can", args.can, "--can-id-mode", args.can_id_mode, "--sock", args.sock]
        if getattr(args, "brand", None):
            daemon_argv.extend(["--brand", args.brand])
        # Forward logging flags when daemon is invoked via the umbrella CLI.
        daemon_argv.extend(_logging_argv_from_args(args))
        daemon_main(daemon_argv)
        return None

    if args.cmd == "tui":
        from autosvc.apps.tui import main as tui_main

        connect = getattr(args, "connect", None) or args.global_connect
        tui_args: list[str] = []
        if connect:
            tui_args.extend(["--connect", connect])
        if getattr(args, "can", None):
            tui_args.extend(["--can", args.can])
        if getattr(args, "can_id_mode", None):
            tui_args.extend(["--can-id-mode", args.can_id_mode])
        if getattr(args, "addressing", None):
            tui_args.extend(["--addressing", args.addressing])
        tui_args.extend(_logging_argv_from_args(args))
        tui_main(tui_args)
        return None

    if args.cmd == "unsafe" and args.unsafe_cmd == "set-password":
        from autosvc.unsafe import set_password_interactive

        set_password_interactive()
        _print_json({"ok": True})
        raise SystemExit(0)

    if args.cmd == "unsafe" and args.unsafe_cmd == "status":
        from autosvc.unsafe import is_password_configured

        _print_json({"ok": True, "configured": bool(is_password_configured())})
        raise SystemExit(0)

    if args.cmd == "backup" and args.backup_cmd == "did":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            _print_json({"ok": False, "error": "backup is not available in daemon mode"})
            raise SystemExit(1)
        response = _run_inprocess(
            args.can,
            can_id_mode=args.can_id_mode,
            op="backup_did",
            ecu=args.ecu,
            did=args.did,
            notes=args.notes,
            log_dir=getattr(args, "log_dir", None),
        )
        _print_json(response)
        raise SystemExit(0 if response.get("ok") else 1)

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

    if args.cmd == "adapt":
        connect = getattr(args, "connect", None) or args.global_connect
        if connect:
            _print_json({"ok": False, "error": "adaptations are not available in daemon mode"})
            raise SystemExit(1)

        if args.adapt_cmd == "list":
            response = _run_inprocess(
                args.can,
                can_id_mode=args.can_id_mode,
                op="adapt_list",
                ecu=args.ecu,
            )
            if args.json:
                _print_json(response)
            else:
                _print_adapt_list(response)
            raise SystemExit(0 if response.get("ok") else 1)

        if args.adapt_cmd == "read":
            response = _run_inprocess(
                args.can,
                can_id_mode=args.can_id_mode,
                op="adapt_read",
                ecu=args.ecu,
                key=args.key,
            )
            if args.json:
                _print_json(response)
            else:
                _print_adapt_read(response)
            raise SystemExit(0 if response.get("ok") else 1)

        if args.adapt_cmd == "write":
            if args.mode == "safe":
                _print_json({"ok": False, "error": "safe mode is read-only (use --mode advanced or --mode unsafe)"})
                raise SystemExit(1)

            unsafe_password = None
            if args.mode == "unsafe":
                unsafe_password = _get_unsafe_password(args)

            # advanced/unsafe require explicit confirmation token
            confirm_or_raise(
                f"About to write adaptation ECU={args.ecu} key={args.key} value={args.value} mode={args.mode}.",
                assume_yes=bool(args.yes),
                token="APPLY",
            )

            response = _run_inprocess(
                args.can,
                can_id_mode=args.can_id_mode,
                op="adapt_write",
                ecu=args.ecu,
                key=args.key,
                value=args.value,
                mode=args.mode,
                unsafe_password=unsafe_password,
                log_dir=getattr(args, "log_dir", None),
            )
            if args.json:
                _print_json(response)
            else:
                _print_adapt_write(response)
            raise SystemExit(0 if response.get("ok") else 1)

        if args.adapt_cmd == "write-raw":
            unsafe_password = _get_unsafe_password(args)
            confirm_or_raise(
                f"About to perform raw DID write ECU={args.ecu} DID={args.did} HEX={args.hex_payload}.",
                assume_yes=bool(args.yes),
                token="APPLY",
            )
            response = _run_inprocess(
                args.can,
                can_id_mode=args.can_id_mode,
                op="adapt_write_raw",
                ecu=args.ecu,
                did=args.did,
                hex_payload=args.hex_payload,
                mode=args.mode,
                unsafe_password=unsafe_password,
                log_dir=getattr(args, "log_dir", None),
            )
            if args.json:
                _print_json(response)
            else:
                _print_adapt_write(response)
            raise SystemExit(0 if response.get("ok") else 1)

        if args.adapt_cmd == "revert":
            confirm_or_raise(
                f"About to revert adaptation backup_id={args.backup_id}.",
                assume_yes=bool(args.yes),
                token="APPLY",
            )
            response = _run_inprocess(
                args.can,
                can_id_mode=args.can_id_mode,
                op="adapt_revert",
                backup_id=args.backup_id,
            )
            if args.json:
                _print_json(response)
            else:
                _print_adapt_write(response)
            raise SystemExit(0 if response.get("ok") else 1)

        if args.adapt_cmd == "backup":
            response = _run_inprocess(
                args.can,
                can_id_mode=args.can_id_mode,
                op="adapt_backup",
                ecu=args.ecu,
                key=args.key,
                notes=args.notes,
                log_dir=getattr(args, "log_dir", None),
            )
            _print_json(response) if args.json else _print_json(response)
            raise SystemExit(0 if response.get("ok") else 1)

        raise SystemExit("error: unknown adapt command")

    raise SystemExit("error: unknown command")


def _apply_dir_overrides(args: argparse.Namespace) -> None:
    # Apply as env vars so core stays CLI-agnostic.
    if getattr(args, "config_dir", None):
        os.environ["AUTOSVC_CONFIG_DIR"] = str(args.config_dir)
    if getattr(args, "cache_dir", None):
        os.environ["AUTOSVC_CACHE_DIR"] = str(args.cache_dir)
    if getattr(args, "data_dir", None):
        os.environ["AUTOSVC_DATA_DIR"] = str(args.data_dir)
    if getattr(args, "backups_dir", None):
        os.environ["AUTOSVC_BACKUPS_DIR"] = str(args.backups_dir)


def _get_unsafe_password(args: argparse.Namespace) -> str:
    if getattr(args, "unsafe_password_stdin", False):
        pw = (sys.stdin.readline() or "").rstrip("\n")
        if not pw:
            raise SystemExit("error: unsafe password is required on stdin")
        return pw
    from autosvc.unsafe import prompt_password

    return prompt_password()


def _logging_argv_from_args(args: argparse.Namespace) -> list[str]:
    out: list[str] = []
    if getattr(args, "trace", False):
        out.append("--trace")
    elif getattr(args, "verbose", False):
        out.append("--verbose")
    elif getattr(args, "log_level", None):
        out.extend(["--log-level", str(args.log_level)])
    if getattr(args, "log_file", None):
        out.extend(["--log-file", str(args.log_file)])
    if getattr(args, "log_dir", None):
        out.extend(["--log-dir", str(args.log_dir)])
    if getattr(args, "log_format", None):
        out.extend(["--log-format", str(args.log_format)])
    if getattr(args, "no_color", False):
        out.append("--no-color")
    return out


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


def _add_logging_args(parser: argparse.ArgumentParser) -> None:
    # Use SUPPRESS defaults so that root-level flags (placed before the subcommand)
    # are not overwritten by subparser defaults.
    parser.add_argument(
        "--log-level",
        choices=["error", "warning", "info", "debug", "trace"],
        default=argparse.SUPPRESS,
        help="Logging level (default: info)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Alias for --log-level=debug",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Alias for --log-level=trace",
    )
    parser.add_argument("--log-file", default=argparse.SUPPRESS, help="Optional log file path")
    parser.add_argument(
        "--log-dir",
        default=argparse.SUPPRESS,
        help="Optional directory to create a per-run log bundle (autosvc.log, result.json, metadata.json)",
    )
    parser.add_argument(
        "--log-format",
        choices=["pretty", "json"],
        default=argparse.SUPPRESS,
        help="Log output format (default: pretty)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable ANSI colors in pretty logs",
    )


def _add_dir_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config-dir", default=None, help="Override config dir (default: ~/.config/autosvc)")
    parser.add_argument("--cache-dir", default=None, help="Override cache dir (default: ~/.cache/autosvc)")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override datasets dir (default: package datasets).",
    )
    parser.add_argument(
        "--backups-dir",
        default=None,
        help="Override backups dir (default: <cache>/backups).",
    )


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
    key: str | None = None,
    value: str | None = None,
    mode: str | None = None,
    hex_payload: str | None = None,
    backup_id: str | None = None,
    with_freeze_frame: bool = False,
    addressing: str = "both",
    timeout_ms: int = 250,
    retries: int = 1,
    probe_session: bool = True,
    unsafe_password: str | None = None,
    notes: str | None = None,
    log_dir: str | None = None,
) -> dict[str, Any]:
    transport: SocketCanTransport | None = None
    try:
        transport = SocketCanTransport(channel=can_if, is_extended_id=(can_id_mode == "29bit"))
        # Resolve datasets_dir from env override (set by --data-dir), keep core CLI-agnostic.
        datasets_dir = os.getenv("AUTOSVC_DATA_DIR")
        service = DiagnosticService(
            transport,
            can_interface=can_if,
            can_id_mode=can_id_mode,
            datasets_dir=datasets_dir,
            log_dir=log_dir,
        )
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
        if op == "adapt_list":
            assert ecu is not None
            return {"ok": True, "ecu": str(ecu).upper(), "settings": service.list_adaptations(ecu)}
        if op == "adapt_read":
            assert ecu is not None
            assert key is not None
            return {"ok": True, "item": service.read_adaptation(ecu, key)}
        if op == "adapt_write":
            assert ecu is not None
            assert key is not None
            assert value is not None
            assert mode is not None
            return {
                "ok": True,
                "result": service.write_adaptation(ecu, key, value, mode=mode, unsafe_password=unsafe_password),
            }
        if op == "adapt_write_raw":
            assert ecu is not None
            assert did is not None
            assert hex_payload is not None
            assert mode is not None
            did_int = parse_did(did)
            return {
                "ok": True,
                "result": service.write_adaptation_raw(
                    ecu,
                    did_int,
                    hex_payload,
                    mode=mode,
                    unsafe_password=unsafe_password,
                ),
            }
        if op == "adapt_backup":
            assert ecu is not None
            assert key is not None
            return {"ok": True, "result": service.backup_adaptation(ecu, key, notes=notes)}
        if op == "backup_did":
            assert ecu is not None
            assert did is not None
            did_int = parse_did(did)
            return {"ok": True, "result": service.backup_did(ecu, did_int, notes=notes)}
        if op == "adapt_revert":
            assert backup_id is not None
            return {"ok": True, "result": service.revert_adaptation(backup_id)}
        return {"ok": False, "error": "invalid operation"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if transport is not None:
            transport.close()


def _print_adapt_list(resp: dict[str, Any]) -> None:
    if not resp.get("ok"):
        sys.stdout.write(f"error: {resp.get('error')}\n")
        return
    ecu = str(resp.get("ecu") or "")
    settings = resp.get("settings") or []
    sys.stdout.write(f"ECU {ecu} settings:\n")
    if not isinstance(settings, list) or not settings:
        sys.stdout.write("(none)\n")
        return
    for item in settings:
        if not isinstance(item, dict):
            continue
        sys.stdout.write(
            f"- {item.get('key')} ({item.get('kind')}, risk={item.get('risk')}, did={item.get('did')}): {item.get('label')}\n"
        )


def _print_adapt_read(resp: dict[str, Any]) -> None:
    if not resp.get("ok"):
        sys.stdout.write(f"error: {resp.get('error')}\n")
        return
    item = resp.get("item") or {}
    if not isinstance(item, dict):
        sys.stdout.write("error: invalid response\n")
        return
    sys.stdout.write(
        f"{item.get('ecu')} {item.get('ecu_name')} {item.get('key')} ({item.get('kind')}, did={item.get('did')}): {item.get('value')}\n"
    )


def _print_adapt_write(resp: dict[str, Any]) -> None:
    if not resp.get("ok"):
        sys.stdout.write(f"error: {resp.get('error')}\n")
        return
    result = resp.get("result") or {}
    if isinstance(result, dict) and result.get("backup_id"):
        sys.stdout.write(f"OK backup_id={result.get('backup_id')}\n")
    else:
        sys.stdout.write("OK\n")


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

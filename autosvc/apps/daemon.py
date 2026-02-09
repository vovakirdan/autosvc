from __future__ import annotations

import argparse
import logging
import sys
import uuid

from autosvc.core.service import DiagnosticService
from autosvc.runlog import create_run_log_dir
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.ipc.unix_server import JsonlUnixServer
from autosvc.logging import TRACE_LEVEL, parse_log_level, setup_logging


log = logging.getLogger(__name__)


def build_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["error", "warning", "info", "debug", "trace"],
        default=None,
        help="Logging level (default: info)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Alias for --log-level=debug")
    parser.add_argument("--trace", action="store_true", help="Alias for --log-level=trace")
    parser.add_argument("--log-file", default=None, help="Optional log file path")
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Optional directory to create a per-run log bundle (autosvc.log, metadata.json)",
    )
    parser.add_argument("--log-format", choices=["pretty", "json"], default="pretty")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in pretty logs")

    parser.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")
    parser.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")
    parser.add_argument("--sock", default="/tmp/autosvc.sock", help="Unix socket path")
    parser.add_argument("--brand", default=None, help="Optional brand registry (e.g. vag)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc daemon (JSONL over Unix socket)")
    build_parser(parser)
    args = parser.parse_args(argv)

    level_name: str | None = getattr(args, "log_level", None)
    if getattr(args, "trace", False):
        level = TRACE_LEVEL
    elif getattr(args, "verbose", False):
        level = logging.DEBUG
    else:
        level = parse_log_level(level_name)

    trace_id = uuid.uuid4().hex[:12]
    log_file = getattr(args, "log_file", None)
    if getattr(args, "log_dir", None) and not log_file:
        argv_for_meta = [parser.prog] + (list(argv) if argv is not None else sys.argv[1:])
        runlog = create_run_log_dir(str(args.log_dir), trace_id=trace_id, argv=argv_for_meta)
        log_file = str(runlog.log_path)

    setup_logging(
        level=level,
        log_format=str(getattr(args, "log_format", "pretty") or "pretty"),
        log_file=log_file,
        no_color=bool(getattr(args, "no_color", False)),
    )

    log.info(
        "Daemon starting",
        extra={"can_interface": args.can, "can_id_mode": args.can_id_mode, "sock": args.sock, "brand": args.brand},
    )

    transport = SocketCanTransport(channel=args.can, is_extended_id=(args.can_id_mode == "29bit"))
    service = DiagnosticService(
        transport,
        brand=args.brand,
        can_interface=args.can,
        can_id_mode=args.can_id_mode,
    )
    server = JsonlUnixServer(args.sock, service)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return None
    finally:
        server.close()
        transport.close()


if __name__ == "__main__":
    main()

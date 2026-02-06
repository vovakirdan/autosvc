from __future__ import annotations

import argparse

from autosvc.core.service import DiagnosticService
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.ipc.unix_server import JsonlUnixServer


def build_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. can0, vcan0)")
    parser.add_argument("--sock", default="/tmp/autosvc.sock", help="Unix socket path")
    parser.add_argument("--brand", default=None, help="Optional brand registry (e.g. vag)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc daemon (JSONL over Unix socket)")
    build_parser(parser)
    args = parser.parse_args(argv)

    transport = SocketCanTransport(channel=args.can)
    service = DiagnosticService(transport, brand=args.brand)
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


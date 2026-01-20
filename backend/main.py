from __future__ import annotations

import argparse

from backend.protocol.server import JsonlServer
from backend.transport.mock import MockTransport
from backend.transport.socketcan import SocketCanTransport
from backend.uds.client import UdsClient


def _build_transport(args: argparse.Namespace):
    if args.transport == "socketcan":
        return SocketCanTransport(channel=args.can_if)
    return MockTransport()


def main() -> None:
    parser = argparse.ArgumentParser(description="autosvc backend")
    parser.add_argument("--socket-path", default="/tmp/autosvc.sock")
    parser.add_argument("--transport", choices=["mock", "socketcan"], default="mock")
    parser.add_argument("--can-if", default="vcan0")
    args = parser.parse_args()

    transport = _build_transport(args)
    uds_client = UdsClient(transport)
    server = JsonlServer(args.socket_path, uds_client)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return None
    finally:
        server.close()
        transport.close()


if __name__ == "__main__":
    main()

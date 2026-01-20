from __future__ import annotations

import argparse
import json
import socket
from typing import Any, Dict

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Log, Static


class AutosvcApp(App):
    CSS = """
    Screen {
        align: center middle;
    }

    #panel {
        width: 80%;
        height: 90%;
        padding: 1;
        border: solid $accent;
    }

    #buttons {
        height: 3;
        content-align: center middle;
    }

    #title {
        content-align: center middle;
        height: 3;
    }
    """

    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self._socket_path = socket_path

    def compose(self) -> ComposeResult:
        yield Static("autosvc", id="title")
        with Vertical(id="panel"):
            yield Input(placeholder="ECU hex (e.g. 01)", id="ecu")
            with Horizontal(id="buttons"):
                yield Button("Scan ECUs", id="scan")
                yield Button("Read DTCs", id="read")
                yield Button("Clear DTCs", id="clear")
            yield Log(id="log")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ecu = self.query_one("#ecu", Input).value.strip().upper()
        if event.button.id == "scan":
            payload = {"cmd": "scan_ecus"}
        elif event.button.id == "read":
            if not ecu:
                self._log_error("ECU is required")
                return
            payload = {"cmd": "read_dtcs", "ecu": ecu}
        elif event.button.id == "clear":
            if not ecu:
                self._log_error("ECU is required")
                return
            payload = {"cmd": "clear_dtcs", "ecu": ecu}
        else:
            return
        self._send_and_render(payload)

    def _send_and_render(self, payload: Dict[str, Any]) -> None:
        try:
            response = self._send_request(payload)
        except Exception as exc:
            self._log_error(str(exc))
            return
        self._render_response(response)

    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(self._socket_path)
            sock.sendall(data)
            fileobj = sock.makefile("rb")
            with fileobj:
                line = fileobj.readline()
            if not line:
                raise RuntimeError("no response")
        return json.loads(line.decode("utf-8"))

    def _render_response(self, response: Dict[str, Any]) -> None:
        log = self.query_one("#log", Log)
        if not response.get("ok"):
            log.write(f"error: {response.get('error', 'unknown error')}")
            return
        if "ecus" in response:
            ecus = response.get("ecus") or []
            log.write("ecus: " + ", ".join(ecus))
            return
        if "dtcs" in response:
            dtcs = response.get("dtcs") or []
            if not dtcs:
                log.write("dtcs: none")
                return
            for item in dtcs:
                code = item.get("code", "")
                status = item.get("status", "unknown")
                log.write(f"{code} ({status})")
            return
        log.write("ok")

    def _log_error(self, message: str) -> None:
        log = self.query_one("#log", Log)
        log.write(f"error: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="autosvc TUI client")
    parser.add_argument("--socket-path", default="/tmp/autosvc.sock")
    args = parser.parse_args()
    AutosvcApp(socket_path=args.socket_path).run()


if __name__ == "__main__":
    main()

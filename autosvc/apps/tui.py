from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Protocol

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, ListItem, ListView, Static

from autosvc.core.service import DiagnosticService
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.ipc.unix_client import UnixJsonlClient


class AutosvcApi(Protocol):
    def scan_ecus(self) -> list[str]: ...
    def read_dtcs(self, ecu: str) -> list[dict[str, object]]: ...
    def clear_dtcs(self, ecu: str) -> None: ...


@dataclass(frozen=True)
class _AppConfig:
    title: str


class InProcessApi:
    def __init__(self, can_if: str) -> None:
        self._transport = SocketCanTransport(channel=can_if)
        self._service = DiagnosticService(self._transport)

    def close(self) -> None:
        self._transport.close()

    def scan_ecus(self) -> list[str]:
        return self._service.scan_ecus()

    def read_dtcs(self, ecu: str) -> list[dict[str, object]]:
        return self._service.read_dtcs(ecu)

    def clear_dtcs(self, ecu: str) -> None:
        self._service.clear_dtcs(ecu)


class IpcApi:
    def __init__(self, sock_path: str) -> None:
        self._client = UnixJsonlClient(sock_path)

    def scan_ecus(self) -> list[str]:
        resp = self._client.request({"cmd": "scan_ecus"})
        _raise_on_error(resp)
        return list(resp.get("ecus") or [])

    def read_dtcs(self, ecu: str) -> list[dict[str, object]]:
        resp = self._client.request({"cmd": "read_dtcs", "ecu": ecu})
        _raise_on_error(resp)
        return list(resp.get("dtcs") or [])

    def clear_dtcs(self, ecu: str) -> None:
        resp = self._client.request({"cmd": "clear_dtcs", "ecu": ecu})
        _raise_on_error(resp)


def _raise_on_error(resp: dict[str, Any]) -> None:
    if not resp.get("ok"):
        raise RuntimeError(str(resp.get("error") or "unknown error"))


class AutosvcTui(App[None]):
    CSS = """
    Screen {
        align: center middle;
    }

    #panel {
        width: 90%;
        height: 95%;
        padding: 1;
        border: solid $accent;
    }

    #title {
        content-align: center middle;
        height: 3;
    }

    #status {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, api: AutosvcApi, config: _AppConfig) -> None:
        super().__init__()
        self._api = api
        self._config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Footer()

    def on_mount(self) -> None:
        self.push_screen(EcuScanScreen(self._api, self._config))


class EcuScanScreen(Screen[None]):
    def __init__(self, api: AutosvcApi, config: _AppConfig) -> None:
        super().__init__()
        self._api = api
        self._config = config

    def compose(self) -> ComposeResult:
        yield Static(self._config.title, id="title")
        with Vertical(id="panel"):
            with Horizontal():
                yield Button("Scan", id="scan")
                yield Button("Quit", id="quit")
            yield Static("", id="status")
            yield ListView(id="ecu_list")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
            return
        if event.button.id == "scan":
            self._scan()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        ecu = str(event.item.data)
        self.app.push_screen(DtcScreen(self._api, ecu))

    def _scan(self) -> None:
        status = self.query_one("#status", Static)
        status.update("Scanning...")
        ecu_list = self.query_one("#ecu_list", ListView)
        ecu_list.clear()
        try:
            ecus = self._api.scan_ecus()
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        if not ecus:
            status.update("No ECUs found.")
            return
        status.update(f"Found {len(ecus)} ECU(s). Select one to view DTCs.")
        for ecu in ecus:
            item = ListItem(Static(ecu))
            item.data = ecu
            ecu_list.append(item)


class DtcScreen(Screen[None]):
    def __init__(self, api: AutosvcApi, ecu: str) -> None:
        super().__init__()
        self._api = api
        self._ecu = ecu

    def compose(self) -> ComposeResult:
        yield Static(f"ECU {self._ecu}", id="title")
        with Vertical(id="panel"):
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Refresh", id="refresh")
                yield Button("Clear DTCs", id="clear")
            yield Static("", id="status")
            table = DataTable(id="dtc_table")
            table.add_columns("Code", "Status", "Severity", "Description")
            yield table

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "refresh":
            self._refresh()
            return
        if event.button.id == "clear":
            self._clear()

    def _refresh(self) -> None:
        status = self.query_one("#status", Static)
        status.update("Reading DTCs...")
        table = self.query_one("#dtc_table", DataTable)
        table.clear()
        try:
            dtcs = self._api.read_dtcs(self._ecu)
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        if not dtcs:
            status.update("No DTCs.")
            return
        status.update(f"{len(dtcs)} DTC(s).")
        for item in dtcs:
            table.add_row(
                str(item.get("code", "")),
                str(item.get("status", "")),
                str(item.get("severity", "")),
                str(item.get("description", "")),
            )

    def _clear(self) -> None:
        status = self.query_one("#status", Static)
        status.update("Clearing DTCs...")
        try:
            self._api.clear_dtcs(self._ecu)
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        status.update("Cleared. Refreshing...")
        self._refresh()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc Textual TUI")
    parser.add_argument("--can", default=None, help="SocketCAN interface (in-process mode, e.g. vcan0)")
    parser.add_argument("--connect", default=None, help="Unix socket path (daemon mode)")
    args = parser.parse_args(argv)

    config = _AppConfig(title="autosvc")

    api: AutosvcApi
    inproc: InProcessApi | None = None
    try:
        if args.connect:
            api = IpcApi(args.connect)
        else:
            can_if = args.can or "vcan0"
            inproc = InProcessApi(can_if)
            api = inproc
        AutosvcTui(api, config).run()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    finally:
        if inproc is not None:
            inproc.close()


if __name__ == "__main__":
    main()

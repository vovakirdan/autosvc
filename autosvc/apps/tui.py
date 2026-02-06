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
from autosvc.core.vehicle.discovery import DiscoveryConfig
from autosvc.core.vehicle.topology import EcuNode, Topology, ids_for_ecu
from autosvc.ipc.unix_client import UnixJsonlClient


class AutosvcApi(Protocol):
    def scan_topology(self) -> Topology: ...
    def read_dtcs(self, ecu: str) -> list[dict[str, object]]: ...
    def clear_dtcs(self, ecu: str) -> None: ...
    def read_dids(self, ecu: str, dids: list[int]) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class _AppConfig:
    title: str


class InProcessApi:
    def __init__(self, can_if: str, *, can_id_mode: str, addressing: str) -> None:
        self._can_if = can_if
        self._can_id_mode = can_id_mode
        self._addressing = addressing
        self._transport = SocketCanTransport(channel=can_if, is_extended_id=(can_id_mode == "29bit"))
        self._service = DiagnosticService(self._transport, can_interface=can_if, can_id_mode=can_id_mode)

    def close(self) -> None:
        self._transport.close()

    def scan_topology(self) -> Topology:
        return self._service.scan_topology(
            DiscoveryConfig(
                addressing=self._addressing,
                can_id_mode=self._can_id_mode,
            )
        )

    def read_dtcs(self, ecu: str) -> list[dict[str, object]]:
        return self._service.read_dtcs(ecu)

    def clear_dtcs(self, ecu: str) -> None:
        self._service.clear_dtcs(ecu)

    def read_dids(self, ecu: str, dids: list[int]) -> list[dict[str, object]]:
        return self._service.read_dids(ecu, dids)


class IpcApi:
    def __init__(self, sock_path: str, *, can_id_mode: str, addressing: str) -> None:
        self._client = UnixJsonlClient(sock_path)
        self._can_id_mode = can_id_mode
        self._addressing = addressing

    def scan_topology(self) -> Topology:
        resp = self._client.request({"cmd": "scan_ecus"})
        _raise_on_error(resp)
        nodes_raw = resp.get("nodes")
        entries: list[tuple[str, str]] = []
        if isinstance(nodes_raw, list):
            for item in nodes_raw:
                if not isinstance(item, dict):
                    continue
                ecu = item.get("ecu")
                ecu_name = item.get("ecu_name")
                if isinstance(ecu, str):
                    entries.append((ecu.upper(), str(ecu_name) if isinstance(ecu_name, str) else "Unknown ECU"))
        if not entries:
            ecus = list(resp.get("ecus") or [])
            for ecu in sorted({str(e).upper() for e in ecus}):
                entries.append((ecu, "Unknown ECU"))

        nodes: list[EcuNode] = []
        for ecu, ecu_name in sorted(set(entries), key=lambda t: t[0]):
            tx_id, rx_id = ids_for_ecu(ecu, self._can_id_mode)
            nodes.append(
                EcuNode(
                    ecu=ecu,
                    ecu_name=ecu_name,
                    tx_id=tx_id,
                    rx_id=rx_id,
                    can_id_mode=self._can_id_mode,
                    uds_confirmed=True,
                    notes=["from:daemon"],
                )
            )
        return Topology(
            can_interface="daemon",
            can_id_mode=self._can_id_mode,
            addressing=self._addressing,
            nodes=nodes,
        )

    def read_dtcs(self, ecu: str) -> list[dict[str, object]]:
        resp = self._client.request({"cmd": "read_dtcs", "ecu": ecu})
        _raise_on_error(resp)
        return list(resp.get("dtcs") or [])

    def clear_dtcs(self, ecu: str) -> None:
        resp = self._client.request({"cmd": "clear_dtcs", "ecu": ecu})
        _raise_on_error(resp)

    def read_dids(self, ecu: str, dids: list[int]) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for did in dids:
            resp = self._client.request({"cmd": "read_did", "ecu": ecu, "did": f"{int(did) & 0xFFFF:04X}"})
            _raise_on_error(resp)
            item = resp.get("item")
            if isinstance(item, dict):
                out.append(item)
        return out


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
            topo = self._api.scan_topology()
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        if not topo.nodes:
            status.update("No ECUs found.")
            return
        status.update(f"Found {len(topo.nodes)} ECU(s). Select one to view DTCs.")
        for node in topo.nodes:
            label = (
                f"{node.ecu}  "
                f"{node.ecu_name}  "
                f"tx=0x{node.tx_id:X}  "
                f"rx=0x{node.rx_id:X}  "
                f"uds={'yes' if node.uds_confirmed else 'no'}"
            )
            item = ListItem(Static(label))
            item.data = node.ecu
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
                yield Button("Live", id="live")
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
            return
        if event.button.id == "live":
            self.app.push_screen(LiveScreen(self._api, self._ecu))

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


class LiveScreen(Screen[None]):
    _DIDS: list[int] = [0xF190, 0xF187, 0x1234]

    def __init__(self, api: AutosvcApi, ecu: str) -> None:
        super().__init__()
        self._api = api
        self._ecu = ecu
        self._tick = 0

    def compose(self) -> ComposeResult:
        yield Static(f"Live data (ECU {self._ecu})", id="title")
        with Vertical(id="panel"):
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Refresh", id="refresh")
            yield Static("", id="status")
            table = DataTable(id="live_table")
            table.add_columns("DID", "Name", "Value", "Unit")
            yield table

    def on_mount(self) -> None:
        self._refresh()
        # Poll in a simple tick loop. This is synchronous and may block briefly.
        self.set_interval(0.5, self._refresh)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "refresh":
            self._refresh()

    def _refresh(self) -> None:
        self._tick += 1
        status = self.query_one("#status", Static)
        table = self.query_one("#live_table", DataTable)
        status.update(f"Tick {self._tick}")
        try:
            items = self._api.read_dids(self._ecu, self._DIDS)
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        table.clear()
        for item in items:
            table.add_row(
                str(item.get("did", "")),
                str(item.get("name", "")),
                str(item.get("value", "")),
                str(item.get("unit", "")),
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc Textual TUI")
    parser.add_argument("--can", default=None, help="SocketCAN interface (in-process mode, e.g. vcan0)")
    parser.add_argument("--connect", default=None, help="Unix socket path (daemon mode)")
    parser.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")
    parser.add_argument("--addressing", choices=["functional", "physical", "both"], default="both")
    args = parser.parse_args(argv)

    config = _AppConfig(title="autosvc")

    api: AutosvcApi
    inproc: InProcessApi | None = None
    try:
        if args.connect:
            api = IpcApi(args.connect, can_id_mode=args.can_id_mode, addressing=args.addressing)
        else:
            can_if = args.can or "vcan0"
            inproc = InProcessApi(can_if, can_id_mode=args.can_id_mode, addressing=args.addressing)
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

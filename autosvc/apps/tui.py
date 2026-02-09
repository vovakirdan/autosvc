from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Any, Protocol

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, ListItem, ListView, Static

from autosvc.core.service import DiagnosticService
from autosvc.core.transport.socketcan import SocketCanTransport
from autosvc.core.vehicle.discovery import DiscoveryConfig
from autosvc.core.vehicle.topology import EcuNode, Topology, ids_for_ecu
from autosvc.ipc.unix_client import UnixJsonlClient
from autosvc.logging import TRACE_LEVEL, parse_log_level, setup_logging


log = logging.getLogger(__name__)


class AutosvcApi(Protocol):
    def scan_topology(self) -> Topology: ...
    def read_dtcs(self, ecu: str, *, with_freeze_frame: bool = False) -> list[dict[str, object]]: ...
    def clear_dtcs(self, ecu: str) -> None: ...
    def read_dids(self, ecu: str, dids: list[int]) -> list[dict[str, object]]: ...
    def list_adaptations(self, ecu: str) -> list[dict[str, object]]: ...
    def read_adaptation(self, ecu: str, key: str) -> dict[str, object]: ...
    def write_adaptation(self, ecu: str, key: str, value: str, *, mode: str) -> dict[str, object]: ...
    def revert_adaptation(self, backup_id: str) -> dict[str, object]: ...


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

    def read_dtcs(self, ecu: str, *, with_freeze_frame: bool = False) -> list[dict[str, object]]:
        return self._service.read_dtcs(ecu, with_freeze_frame=with_freeze_frame)

    def clear_dtcs(self, ecu: str) -> None:
        self._service.clear_dtcs(ecu)

    def read_dids(self, ecu: str, dids: list[int]) -> list[dict[str, object]]:
        return self._service.read_dids(ecu, dids)

    def list_adaptations(self, ecu: str) -> list[dict[str, object]]:
        return self._service.list_adaptations(ecu)

    def read_adaptation(self, ecu: str, key: str) -> dict[str, object]:
        return self._service.read_adaptation(ecu, key)

    def write_adaptation(self, ecu: str, key: str, value: str, *, mode: str) -> dict[str, object]:
        return self._service.write_adaptation(ecu, key, value, mode=mode)

    def revert_adaptation(self, backup_id: str) -> dict[str, object]:
        return self._service.revert_adaptation(backup_id)


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

    def read_dtcs(self, ecu: str, *, with_freeze_frame: bool = False) -> list[dict[str, object]]:
        # Freeze-frame is currently in-process only. Daemon protocol can be
        # extended later without changing the core API.
        _ = with_freeze_frame
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

    def list_adaptations(self, ecu: str) -> list[dict[str, object]]:
        raise RuntimeError("adaptations are not available in daemon mode")

    def read_adaptation(self, ecu: str, key: str) -> dict[str, object]:
        raise RuntimeError("adaptations are not available in daemon mode")

    def write_adaptation(self, ecu: str, key: str, value: str, *, mode: str) -> dict[str, object]:
        raise RuntimeError("adaptations are not available in daemon mode")

    def revert_adaptation(self, backup_id: str) -> dict[str, object]:
        raise RuntimeError("adaptations are not available in daemon mode")


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
        self._dtcs: list[dict[str, object]] = []

    def compose(self) -> ComposeResult:
        yield Static(f"ECU {self._ecu}", id="title")
        with Vertical(id="panel"):
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Refresh", id="refresh")
                yield Button("Clear DTCs", id="clear")
                yield Button("Live", id="live")
                yield Button("Adapt", id="adapt")
            yield Static("", id="status")
            table = DataTable(id="dtc_table")
            table.add_columns("Code", "Status", "Severity", "Description")
            yield table

    def on_mount(self) -> None:
        table = self.query_one("#dtc_table", DataTable)
        table.cursor_type = "row"
        self._refresh()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "dtc_table":
            return
        row = int(getattr(event, "cursor_row", -1))
        if row < 0 or row >= len(self._dtcs):
            return
        self.app.push_screen(DtcDetailScreen(self._ecu, self._dtcs[row]))

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
        if event.button.id == "adapt":
            self.app.push_screen(AdaptationsScreen(self._api, self._ecu))

    def _refresh(self) -> None:
        status = self.query_one("#status", Static)
        status.update("Reading DTCs...")
        table = self.query_one("#dtc_table", DataTable)
        table.clear()
        try:
            dtcs = self._api.read_dtcs(self._ecu, with_freeze_frame=True)
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        self._dtcs = list(dtcs)
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


class DtcDetailScreen(Screen[None]):
    def __init__(self, ecu: str, dtc: dict[str, object]) -> None:
        super().__init__()
        self._ecu = ecu
        self._dtc = dict(dtc)

    def compose(self) -> ComposeResult:
        code = str(self._dtc.get("code") or "")
        yield Static(f"DTC {code} (ECU {self._ecu})", id="title")
        with Vertical(id="panel"):
            with Horizontal():
                yield Button("Back", id="back")
            yield Static("", id="status")
            yield Static("", id="dtc_info")
            table = DataTable(id="ff_table")
            table.add_columns("DID", "Name", "Value", "Unit", "Raw")
            yield table

    def on_mount(self) -> None:
        info = self.query_one("#dtc_info", Static)
        code = str(self._dtc.get("code") or "")
        status = str(self._dtc.get("status") or "")
        severity = str(self._dtc.get("severity") or "")
        desc = str(self._dtc.get("description") or "")
        info.update(f"{code}  status={status}  severity={severity}\n{desc}")
        self._render_freeze_frame()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

    def _render_freeze_frame(self) -> None:
        status = self.query_one("#status", Static)
        table = self.query_one("#ff_table", DataTable)
        table.clear()
        ff = self._dtc.get("freeze_frame")
        if not isinstance(ff, dict):
            status.update("No freeze-frame data.")
            return
        record_id = ff.get("record_id")
        status.update(f"Freeze-frame record {record_id}")
        params = ff.get("parameters")
        if not isinstance(params, list) or not params:
            return
        for p in params:
            if not isinstance(p, dict):
                continue
            table.add_row(
                str(p.get("did") or ""),
                str(p.get("name") or ""),
                str(p.get("value") or ""),
                str(p.get("unit") or ""),
                str(p.get("raw") or ""),
            )


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


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Static("Confirm", id="title")
        with Vertical(id="panel"):
            yield Static(self._message, id="status")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Yes", id="yes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)


class AdaptationsScreen(Screen[None]):
    def __init__(self, api: AutosvcApi, ecu: str) -> None:
        super().__init__()
        self._api = api
        self._ecu = ecu
        self._settings: list[dict[str, object]] = []
        self._selected_key: str | None = None
        self._last_backup_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"Adaptations (ECU {self._ecu})", id="title")
        with Vertical(id="panel"):
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Refresh", id="refresh")
                yield Button("Apply", id="apply")
                yield Button("Revert", id="revert")
            yield Static("", id="status")
            table = DataTable(id="adapt_table")
            table.add_columns("Key", "Label", "Kind", "Risk", "DID")
            yield table
            yield Static("New value:")
            yield Input(placeholder="Enter value (e.g. true/false/1/0)", id="adapt_value")

    def on_mount(self) -> None:
        table = self.query_one("#adapt_table", DataTable)
        table.cursor_type = "row"
        self._refresh()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "adapt_table":
            return
        row = int(getattr(event, "cursor_row", -1))
        if row < 0 or row >= len(self._settings):
            return
        item = self._settings[row]
        key = str(item.get("key") or "")
        self._selected_key = key
        self._read_selected()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "refresh":
            self._refresh()
            return
        if event.button.id == "apply":
            self._apply()
            return
        if event.button.id == "revert":
            self._revert()

    def _refresh(self) -> None:
        status = self.query_one("#status", Static)
        status.update("Loading dataset settings...")
        table = self.query_one("#adapt_table", DataTable)
        table.clear()
        self._selected_key = None
        try:
            settings = self._api.list_adaptations(self._ecu)
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        self._settings = list(settings or [])
        if not self._settings:
            status.update("No adaptation settings for this ECU.")
            return
        status.update(f"{len(self._settings)} setting(s). Select one to read current value.")
        for s in self._settings:
            if not isinstance(s, dict):
                continue
            table.add_row(
                str(s.get("key") or ""),
                str(s.get("label") or ""),
                str(s.get("kind") or ""),
                str(s.get("risk") or ""),
                str(s.get("did") or ""),
            )

    def _read_selected(self) -> None:
        if not self._selected_key:
            return
        status = self.query_one("#status", Static)
        try:
            item = self._api.read_adaptation(self._ecu, self._selected_key)
        except Exception as exc:
            status.update(f"Error: {exc}")
            return
        if isinstance(item, dict):
            status.update(
                f"{item.get('key')} = {item.get('value')} (raw={item.get('raw')}, kind={item.get('kind')}, risk={item.get('risk')})"
            )

    def _apply(self) -> None:
        if not self._selected_key:
            self.query_one("#status", Static).update("Select a setting first.")
            return
        value = self.query_one("#adapt_value", Input).value

        def _after_confirm(ok: bool) -> None:
            if not ok:
                self.query_one("#status", Static).update("Cancelled.")
                return
            status = self.query_one("#status", Static)
            status.update("Writing...")
            try:
                result = self._api.write_adaptation(self._ecu, self._selected_key or "", value, mode="safe")
            except Exception as exc:
                status.update(f"Error: {exc}")
                return
            if isinstance(result, dict):
                backup_id = result.get("backup_id")
                self._last_backup_id = str(backup_id) if backup_id else None
                status.update(f"Wrote. backup_id={backup_id}")
                self._read_selected()

        self.app.push_screen(
            ConfirmScreen(f"Write {self._selected_key} = {value} (safe mode)?"),
            _after_confirm,
        )

    def _revert(self) -> None:
        if not self._last_backup_id:
            self.query_one("#status", Static).update("No backup id available in this session.")
            return

        backup_id = self._last_backup_id

        def _after_confirm(ok: bool) -> None:
            if not ok:
                self.query_one("#status", Static).update("Cancelled.")
                return
            status = self.query_one("#status", Static)
            status.update("Reverting...")
            try:
                result = self._api.revert_adaptation(backup_id)
            except Exception as exc:
                status.update(f"Error: {exc}")
                return
            status.update(f"Reverted backup_id={backup_id}")
            _ = result
            self._read_selected()

        self.app.push_screen(ConfirmScreen(f"Revert backup_id={backup_id}?"), _after_confirm)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc Textual TUI")
    parser.add_argument(
        "--log-level",
        choices=["error", "warning", "info", "debug", "trace"],
        default=None,
        help="Logging level (default: info)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Alias for --log-level=debug")
    parser.add_argument("--trace", action="store_true", help="Alias for --log-level=trace")
    parser.add_argument("--log-file", default=None, help="Optional log file path")
    parser.add_argument("--log-format", choices=["pretty", "json"], default="pretty")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in pretty logs")

    parser.add_argument("--can", default=None, help="SocketCAN interface (in-process mode, e.g. vcan0)")
    parser.add_argument("--connect", default=None, help="Unix socket path (daemon mode)")
    parser.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")
    parser.add_argument("--addressing", choices=["functional", "physical", "both"], default="both")
    args = parser.parse_args(argv)

    level_name: str | None = getattr(args, "log_level", None)
    if getattr(args, "trace", False):
        level = TRACE_LEVEL
    elif getattr(args, "verbose", False):
        level = logging.DEBUG
    else:
        level = parse_log_level(level_name)

    setup_logging(
        level=level,
        log_format=str(getattr(args, "log_format", "pretty") or "pretty"),
        log_file=getattr(args, "log_file", None),
        no_color=bool(getattr(args, "no_color", False)),
    )

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

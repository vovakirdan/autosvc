from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from autosvc.core.isotp.transport import IsoTpError, IsoTpTimeoutError, IsoTpTransport
from autosvc.core.transport.base import CanTransport
from autosvc.core.vehicle.topology import EcuNode, Topology, ids_for_ecu, infer_ecu_from_response_id


AddressingMode = Literal["functional", "physical", "both"]
CanIdMode = Literal["11bit", "29bit"]


@dataclass(frozen=True)
class DiscoveryConfig:
    addressing: AddressingMode = "both"
    can_id_mode: CanIdMode = "11bit"
    timeout_ms: int = 250
    retries: int = 1
    probe_session: bool = True
    functional_id_11: int = 0x7DF
    # Conventional UDS functional request ID for 29-bit normal fixed addressing (tester SA = 0xF1).
    # This matches the ISO-TP/UDS convention used by the built-in emulator.
    functional_id_29: int = 0x18DB33F1


@dataclass
class _NodeAcc:
    ecu: str
    tx_id: int
    rx_id: int
    can_id_mode: str
    uds_confirmed: bool = False
    notes: set[str] = field(default_factory=set)

    def to_node(self) -> EcuNode:
        return EcuNode(
            ecu=self.ecu,
            tx_id=self.tx_id,
            rx_id=self.rx_id,
            can_id_mode=self.can_id_mode,
            uds_confirmed=self.uds_confirmed,
            notes=sorted(self.notes),
        )


def scan_topology(transport: CanTransport, config: DiscoveryConfig, *, can_interface: str = "unknown") -> Topology:
    _validate_config(config)

    nodes: dict[str, _NodeAcc] = {}

    if config.addressing in {"functional", "both"}:
        _functional_scan(transport, config, nodes)

    if config.addressing in {"physical", "both"}:
        # Default physical scan range is intentionally small and deterministic.
        # If functional scan discovered ECUs outside this range, we also probe them.
        candidates: list[str] = []
        candidates.extend(_default_physical_candidates(config.can_id_mode))
        if config.addressing == "both":
            candidates.extend(sorted(nodes.keys()))
        _physical_scan(transport, config, nodes, candidates=sorted(set(candidates)))

    topo = Topology(
        can_interface=can_interface,
        can_id_mode=config.can_id_mode,
        addressing=config.addressing,
        nodes=[acc.to_node() for acc in nodes.values()],
    )
    topo.nodes.sort(key=lambda n: n.ecu)
    return topo


def _validate_config(config: DiscoveryConfig) -> None:
    if config.addressing not in {"functional", "physical", "both"}:
        raise ValueError("invalid addressing")
    if config.can_id_mode not in {"11bit", "29bit"}:
        raise ValueError("invalid can_id_mode")
    if int(config.timeout_ms) <= 0:
        raise ValueError("timeout_ms must be positive")
    if int(config.retries) < 0:
        raise ValueError("retries must be >= 0")


def _default_physical_candidates(can_id_mode: str) -> list[str]:
    # For 11-bit, default request IDs are 0x7E0..0x7E7 (ECUs 00..07).
    # For 29-bit, we reuse the same ECU address range (00..07) as a practical default.
    if can_id_mode not in {"11bit", "29bit"}:
        raise ValueError("invalid can_id_mode")
    return [f"{ecu:02X}" for ecu in range(0x00, 0x08)]


def _functional_scan(transport: CanTransport, config: DiscoveryConfig, nodes: dict[str, _NodeAcc]) -> None:
    func_id = int(config.functional_id_11) if config.can_id_mode == "11bit" else int(config.functional_id_29)
    payload = bytes([0x10, 0x01])
    frame = _isotp_single_frame(payload)

    _drain_rx(transport)
    for _ in range(int(config.retries) + 1):
        transport.send(func_id, frame)
        deadline = time.monotonic() + (int(config.timeout_ms) / 1000.0)
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            rx = transport.recv(remaining_ms)
            if rx is None:
                continue
            if not _mode_matches_id(rx.can_id, config.can_id_mode):
                continue
            ecu = infer_ecu_from_response_id(rx.can_id, config.can_id_mode)
            if ecu is None:
                continue
            uds_payload = _decode_isotp_single_frame(rx.data)
            uds_ok = uds_payload is not None and uds_payload[:2] == b"\x50\x01"
            tx_id, rx_id = ids_for_ecu(ecu, config.can_id_mode)
            acc = nodes.get(ecu)
            if acc is None:
                acc = _NodeAcc(ecu=ecu, tx_id=tx_id, rx_id=rx_id, can_id_mode=config.can_id_mode)
                nodes[ecu] = acc
            acc.notes.add("seen:functional")
            acc.uds_confirmed = bool(acc.uds_confirmed or uds_ok)


def _physical_scan(
    transport: CanTransport,
    config: DiscoveryConfig,
    nodes: dict[str, _NodeAcc],
    *,
    candidates: list[str],
) -> None:
    payload = bytes([0x10, 0x01])
    for ecu in candidates:
        tx_id, rx_id = ids_for_ecu(ecu, config.can_id_mode)
        uds_ok = False
        got_response = False

        for _ in range(int(config.retries) + 1):
            isotp = IsoTpTransport(transport, tx_id, rx_id, timeout_ms=int(config.timeout_ms))
            try:
                response = isotp.request(payload)
            except IsoTpTimeoutError:
                continue
            except IsoTpError:
                continue
            got_response = True
            uds_ok = response[:2] == b"\x50\x01"
            break

        if not got_response:
            continue
        if config.probe_session and not uds_ok:
            continue

        acc = nodes.get(ecu)
        if acc is None:
            acc = _NodeAcc(ecu=ecu, tx_id=tx_id, rx_id=rx_id, can_id_mode=config.can_id_mode)
            nodes[ecu] = acc
        acc.notes.add("seen:physical")
        acc.uds_confirmed = bool(acc.uds_confirmed or uds_ok)


def _drain_rx(transport: CanTransport, *, max_frames: int = 64) -> None:
    for _ in range(max_frames):
        frame = transport.recv(0)
        if frame is None:
            return None


def _mode_matches_id(can_id: int, can_id_mode: str) -> bool:
    if can_id_mode == "11bit":
        return 0 <= int(can_id) <= 0x7FF
    if can_id_mode == "29bit":
        return int(can_id) > 0x7FF
    return False


def _isotp_single_frame(payload: bytes) -> bytes:
    if len(payload) > 7:
        raise ValueError("payload too large for single-frame probe")
    pci = len(payload) & 0x0F
    data = bytes([pci]) + payload
    if len(data) < 8:
        data = data + (b"\x00" * (8 - len(data)))
    return data


def _decode_isotp_single_frame(data: bytes) -> bytes | None:
    if not data:
        return None
    frame_type = data[0] >> 4
    if frame_type != 0x0:
        return None
    length = data[0] & 0x0F
    if length > len(data) - 1:
        return None
    return data[1 : 1 + length]


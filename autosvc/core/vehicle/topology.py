from __future__ import annotations

from dataclasses import dataclass, field


_TESTER_SOURCE_ADDRESS_29 = 0xF1


@dataclass
class EcuNode:
    ecu: str  # "01" style
    tx_id: int  # physical request CAN id
    rx_id: int  # physical response CAN id
    can_id_mode: str  # "11bit"|"29bit"
    uds_confirmed: bool
    ecu_name: str = "Unknown ECU"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ecu": self.ecu,
            "ecu_name": self.ecu_name,
            "tx_id": int(self.tx_id),
            "rx_id": int(self.rx_id),
            "can_id_mode": self.can_id_mode,
            "uds_confirmed": bool(self.uds_confirmed),
            "notes": list(self.notes),
        }


@dataclass
class Topology:
    can_interface: str
    can_id_mode: str
    addressing: str
    nodes: list[EcuNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        nodes = sorted(self.nodes, key=lambda n: n.ecu)
        return {
            "can_interface": self.can_interface,
            "can_id_mode": self.can_id_mode,
            "addressing": self.addressing,
            "nodes": [n.to_dict() for n in nodes],
        }


def ids_for_ecu(ecu: str, can_id_mode: str) -> tuple[int, int]:
    ecu_int = int(ecu, 16)
    if ecu_int < 0 or ecu_int > 0xFF:
        raise ValueError("ecu out of range")
    if can_id_mode == "11bit":
        # 0x7E8 + ecu must remain within the 11-bit ID range (<= 0x7FF).
        if ecu_int > 0x17:
            raise ValueError("ecu out of range")
        return 0x7E0 + ecu_int, 0x7E8 + ecu_int
    if can_id_mode == "29bit":
        # Conventional UDS-on-CAN extended IDs (ISO-TP normal fixed addressing):
        #   request  = 0x18DA <target> <source>
        #   response = 0x18DA <source> <target>
        # With tester SA = 0xF1 and ECU "01":
        #   tx_id = 0x18DA01F1
        #   rx_id = 0x18DAF101
        tx_id = 0x18DA0000 | ((ecu_int & 0xFF) << 8) | (_TESTER_SOURCE_ADDRESS_29 & 0xFF)
        rx_id = 0x18DA0000 | ((_TESTER_SOURCE_ADDRESS_29 & 0xFF) << 8) | (ecu_int & 0xFF)
        return tx_id, rx_id
    raise ValueError("invalid can_id_mode")


def infer_ecu_from_response_id(can_id: int, can_id_mode: str) -> str | None:
    if can_id_mode == "11bit":
        # Typical physical response range for ECUs derived from 0x7E8.
        if 0x7E8 <= can_id <= 0x7FF:
            ecu_int = can_id - 0x7E8
            return f"{ecu_int:02X}"
        return None
    if can_id_mode == "29bit":
        # Response IDs follow: 0x18DAF1xx (see ids_for_ecu()).
        if (can_id & 0x1FFFFF00) == 0x18DAF100:
            ecu_int = can_id & 0xFF
            return f"{ecu_int:02X}"
        return None
    raise ValueError("invalid can_id_mode")

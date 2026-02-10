from __future__ import annotations

# ISO 14229-1 Negative Response Codes (subset).
# Keep this small and focused; add codes as needed.
NRC_NAMES: dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x78: "requestCorrectlyReceivedResponsePending",
}


def nrc_name(nrc: int) -> str | None:
    return NRC_NAMES.get(int(nrc) & 0xFF)

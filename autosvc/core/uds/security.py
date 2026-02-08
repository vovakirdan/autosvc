from __future__ import annotations


# UDS Negative Response Codes related to security. See ISO 14229-1.
SECURITY_RELATED_NRCS: set[int] = {
    0x33,  # securityAccessDenied
    0x35,  # invalidKey
    0x36,  # exceedNumberOfAttempts
    0x37,  # requiredTimeDelayNotExpired
}


def is_security_nrc(nrc: int) -> bool:
    return (int(nrc) & 0xFF) in SECURITY_RELATED_NRCS


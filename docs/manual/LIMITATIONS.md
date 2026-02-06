# Limitations / Non-Goals

This document is intentionally blunt. If you need these capabilities, do not assume `autosvc` can do them.

## Protocol / Vehicle Coverage

- No K-line / KWP2000 support (CAN/UDS only).
- Not all ECUs are UDS. Some will never answer UDS requests.
- Many vehicles have multiple CAN buses behind a gateway. You may be on the wrong bus even if you see traffic.
- 29-bit support is limited to a single convention. If your platform uses a different 29-bit addressing scheme, discovery and requests will fail.
- No CAN FD support.

## Diagnostic Coverage

- Service diagnostics only.
- No security access (`0x27`), no unlocking, no key learning.
- No flashing/programming.
- No coding/adaptations.
- No long/complex diagnostic sessions (coverage is intentionally minimal).
- Live data support is minimal and DID coverage is not comprehensive.

## Known Failure Modes

- Wrong bitrate: you see traffic but nothing answers UDS, or you see nothing at all.
- Wrong CAN ID mode: using `11bit` on a 29-bit vehicle (or the reverse).
- Gateway filtering: functional requests may be blocked; some ECUs may be invisible.
- Timing sensitivity: some ECUs need longer timeouts; others may reject frequent polling.
- Intermittent faults: clearing codes can hide problems temporarily.

## Not A Replacement For OEM Tools

`autosvc` is not a replacement for:

- ODIS / VCDS / OEM dealership tools
- tools that implement full brand-specific semantics, guided fault finding, and coding

Use `autosvc` as a focused service-diagnostics tool and a research/development platform.


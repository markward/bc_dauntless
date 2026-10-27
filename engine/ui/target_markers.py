"""Per-ship markers shown on target list rows (Quick Battle victory).

Keyed by the ship's object name (``GetName()``). Process-global; cleared on
mission swap, run teardown and between tests so nothing leaks.
"""
from __future__ import annotations

from typing import Dict, Optional

KINDS = frozenset({"protect", "target"})

_markers: Dict[str, str] = {}


def set_marker(ship_name: str, kind: str) -> None:
    if kind not in KINDS:
        raise ValueError("unknown marker kind: %r" % (kind,))
    _markers[ship_name] = kind


def clear_marker(ship_name: str) -> None:
    _markers.pop(ship_name, None)


def marker_for(ship_name: str) -> Optional[str]:
    return _markers.get(ship_name)


def clear() -> None:
    _markers.clear()

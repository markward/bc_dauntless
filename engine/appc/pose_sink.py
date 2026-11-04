"""Where a ship's articulated part poses go when they CHANGE (phase 3a).

`articulation` calls `notify(ship)` whenever `ship._articulation_poses` is
written (the sim tick's `tick_ship`, the SPV's forced-pose edges). The live
host installs a sink that pushes the poses to the ship's render instance as
node overrides, which the mesh trace reads; headless, no sink is set and
`notify` does nothing. Kept free of host and renderer imports, so the sim
side never reaches up into the host.
"""
from __future__ import annotations

from typing import Callable, Optional

_sink: Optional[Callable[[object], None]] = None


def set(fn: Optional[Callable[[object], None]]) -> None:  # noqa: A001
    """Install `fn(ship)` as the sink, or None to remove it."""
    global _sink
    _sink = fn


def notify(ship) -> None:
    """Hand `ship` to the sink. A no-op when unset; a raising sink is logged
    (dev mode) and swallowed, never raised into the tick."""
    fn = _sink
    if fn is None:
        return
    try:
        fn(ship)
    except Exception as exc:  # noqa: BLE001 - must never break the sim tick
        from engine import dev_mode
        dev_mode.log_swallowed("articulation pose sink", exc)


def reset() -> None:
    set(None)

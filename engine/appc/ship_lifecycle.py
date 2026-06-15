"""Pub/sub for ship lifecycle events.

Subscribers receive ``("added", ship)`` when a ShipClass is inserted into a
set via SetClass.AddObjectToSet, and ``("destroyed", ship)`` when
ShipClass.SetDead transitions False -> True. The hub also maintains a
``_live`` set so late subscribers can call ``snapshot()`` to bootstrap.

The hub is engine-side and UI-agnostic. Subscribers manage their own
lifetime via the unsubscribe handle returned by ``subscribe``.
``reset()`` clears ``_live`` for mission swap; subscribers persist.
"""
from __future__ import annotations
from typing import Callable

import engine.dev_mode as dev_mode

_Callback = Callable[[str, object], None]

_subscribers: list[_Callback] = []
_live: set = set()


def subscribe(cb: _Callback) -> Callable[[], None]:
    """Register a callback. Returns an idempotent unsubscribe handle."""
    _subscribers.append(cb)
    def unsubscribe() -> None:
        if cb in _subscribers:
            _subscribers.remove(cb)
    return unsubscribe


def publish_added(ship) -> None:
    _live.add(ship)
    _fanout("added", ship)


def publish_destroyed(ship) -> None:
    _live.discard(ship)
    _fanout("destroyed", ship)


def snapshot() -> tuple:
    """Currently-live ships, in arbitrary order."""
    return tuple(_live)


def reset() -> None:
    """Clear _live (for mission swap). Subscribers are not affected."""
    _live.clear()


def _fanout(event: str, ship) -> None:
    # Snapshot subscriber list — a callback may unsubscribe itself.
    for cb in list(_subscribers):
        try:
            cb(event, ship)
        except Exception as _e:
            dev_mode.log_swallowed("ship_lifecycle subscriber callback", _e)

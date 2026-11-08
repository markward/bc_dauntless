"""Collect and freeze the GC heap after every mission load; thaw on every
teardown (spec 2026-11-08-perf-tier1-design.md §2.5).

A gen-2 pass walks every tracked object the loaded mission built, which is a
21-27 ms hitch every 30-80 s. After a load, ``gc.collect(); gc.freeze()``
moves that heap into the permanent generation, so later passes walk only what
the mission allocates afterwards (~3 ms).

The pairing rule: every teardown calls ``thaw()`` BEFORE it tears the old
mission down. A frozen object is never collected, so a cycle the old mission
leaves behind would otherwise stay alive for good. ``thaw()`` also cancels a
pending request, so a load that a teardown interrupts never freezes.

Freezing happens only in ``service()``, which the host loop calls once per
frame at its end. Load paths only ``request()``: Quick Battle's End flags its
objects SetDeleteMe and the host removes them at the start of a later frame,
and sim_restore's rebuild (which requests) runs after BC's End.

Mid-mission, a load-time object that turns into CYCLIC garbage stays alive
until the next teardown thaws it (refcount frees still happen; objects made
after the freeze collect normally), so the growth is bounded by the load-time
heap. Its ``weakref.finalize`` callbacks (native-mirror frees) fire then.

Armed only by ``engine.host_loop.run()`` outside pytest: the suite never runs
frozen (docs/reference/architecture/test-suite-memory.md).
"""
from __future__ import annotations

import gc

from engine.core import frame_profiler

_armed = False
_due = False
_frozen = False   # this module froze the heap and has not thawed it


def arm() -> None:
    global _armed
    _armed = True


def disarm() -> None:
    global _armed
    _armed = False


def armed() -> bool:
    return _armed


def thaw() -> None:
    """Unfreeze before a teardown; always cancels a pending request. Also
    unfreezes a heap this module froze before it was disarmed, so the
    per-test reset's ``disarm(); thaw()`` never leaves the process frozen."""
    global _due, _frozen
    _due = False
    if _armed or _frozen:
        gc.unfreeze()
        _frozen = False


def request() -> None:
    """A load finished: freeze at the next frame boundary."""
    global _due
    _due = True


def service() -> bool:
    """At a frame boundary: collect and freeze if armed and requested.
    True when it froze."""
    global _due, _frozen
    if not (_armed and _due):
        return False
    with frame_profiler.scope("gc.freeze"):
        gc.collect()
        gc.freeze()
    _due = False
    _frozen = True
    return True

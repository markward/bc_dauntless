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
frame inside ``sim.session_sync``, right after the SetDeleteMe sweep
(``_process_object_deletions``); the ``gc.freeze`` profiler row therefore
sits under ``sim.session_sync``. Load paths only ``request()``, and a request
is frozen at the SECOND ``service()`` after it, never the first: the first
only marks it ready. Why: Quick Battle's End runs mid-frame (a CEF click
dispatched inside ``r.frame()``, or a timer in the sim ticks). BC flags the
battle SetDeleteMe and sim_restore requests while those ships are still in
their set. The next frame's sweep takes them out of the set, but
``session.ship_instances`` and ``slot_bindings`` hold them until that frame's
``sim.reconcile``. Servicing at that first sweep would freeze them alive.
One frame later both have run, and the collect reclaims them. Every source
then has a full sweep + reconcile between its request and the freeze:
- the dev swap (drained before session_sync) and Quick Battle's preload-done
  ``GenerateShips`` (fired in session_sync before the sweep) freeze on the
  next frame;
- ``mission_change`` (sim ticks), End / Restart (ticks or the CEF pump) and
  boot freeze one frame later still.
A new ``request()`` restarts the wait.

Mid-mission, a load-time object that turns into CYCLIC garbage stays alive
until the next teardown thaws it (refcount frees still happen; objects made
after the freeze collect normally), so the growth is bounded by the load-time
heap. Its ``weakref.finalize`` callbacks (native-mirror frees) fire then.
What relies on mid-mission cyclic collection: the transform-slot and
native-row finalizers (objects.py, native_combat.py) and the hum finalizer
(hum_allocator.py, now also covered by dirty marks). Before this change those
frees waited for a gen-2 pass (30-80 s); now they wait for the next teardown.

Armed only by ``engine.host_loop.run()`` outside pytest: the suite never runs
frozen (docs/reference/architecture/test-suite-memory.md).
"""
from __future__ import annotations

import gc

from engine.core import frame_profiler

_armed = False
_due = False      # a load requested a freeze
_ready = False    # ... and one service() has passed since that request
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
    global _due, _ready, _frozen
    _due = False
    _ready = False
    if _armed or _frozen:
        gc.unfreeze()
        _frozen = False


def request() -> None:
    """A load finished: freeze once a whole frame's sweep and reconcile
    have run (the second service() from now)."""
    global _due, _ready
    _due = True
    _ready = False


def service() -> bool:
    """Once per frame, after the SetDeleteMe sweep: collect and freeze if
    armed and a request has waited one service(). True when it froze."""
    global _due, _ready, _frozen
    if not (_armed and _due):
        return False
    if not _ready:
        _ready = True
        return False
    with frame_profiler.scope("gc.freeze"):
        gc.collect()
        gc.freeze()
    _due = False
    _ready = False
    _frozen = True
    return True

"""The subsystem stage, native (phase 6 A1; plan
docs/superpowers/plans/2026-11-05-phase6-b0-a1-subsystems.md, stage map
docs/superpowers/plans/2026-11-05-phase6-a1-subsystem-stage-map.md).

``engine.core.loop._update_ship_subsystems`` calls ``step_all(dt)`` while
``enabled()``: the switch (``DAUNTLESS_NATIVE_SUBSYSTEMS``, on unless
exactly ``"0"``, set by ``configure``, which ``native_combat.configure``
calls) and the mirror live (``native_combat._enabled``). Off, the stage is
the Python loop in loop.py, unchanged -- the bit-exact reference the
per-tick differential (tests/integration/test_native_subsystems_
differential.py) compares this driver against, until Task 8 deletes it.

THE DRIVER. The roster is ``iter_non_rock_ships``' own, one set at a time
(``ship_iter.iter_non_rock_ship_sets``: the sets as the stage begins, each
set's objects when the stage reaches that set), so a ship a handler adds to
a later set, or removes from it, is seen exactly as the Python loop sees
it. Each set's ships open one native session (``combat_subsys_begin``, the handles
the mirror registers them under: ``_nslot``), and the driver loops
``combat_subsys_next`` to DONE:

* ``RUN_PYTHON(ship, piece)``: that piece of that ship, exactly as the
  Python loop runs it -- the getter asked NOW (a handler may have detached
  the subsystem since the ship's last record), the call made only when it
  returns one: ``GetShieldSubsystem().Update(dt)``,
  ``GetPowerSubsystem().Update(dt)``, ``GetCloakingSubsystem().Update(dt)``,
  ``GetRepairSubsystem().Update(dt)``, ``articulation.tick_ship(ship, dt)``.
* ``EVENT(ship, kind, code, a, b)``: ``_EVENT_HANDLERS[kind](ship, code, a,
  b)`` posts the SDK event a native piece stopped for (ruling R3: stop and
  resume, never batched). No piece is native yet, so the table is empty:
  Tasks 3-5 fill it.

A ship whose mirror row is freed mid-walk while it lives on
(``native_combat._drop``) is NOT skipped: the Python stage still updates
it, so its remaining pieces come back as RUN_PYTHON and its row is never
read again (Review Focus 3; subsystem_step.h FREED ROWS). A ship with no
row is all Python.

In this task every piece is RUN_PYTHON, so the stage makes the Python loop's
calls, in its order, by construction.
"""
import os
import sys
from typing import Mapping

from engine.appc import articulation, native_combat, ship_iter
from engine.appc.ship_iter import iter_non_rock_ship_sets

try:
    import _dauntless_host as _h
except ImportError:     # pragma: no cover -- a build without the module
    _h = None


# ── The switch and the counts ────────────────────────────────────────────────

_switch = False
_counts = {"stages": 0, "sessions": 0, "run_python": 0, "events": 0,
           "patched_stages": 0}

#: The roster as the Python stage takes it, stock (taken at import): the
#: driver walks the sets itself (iter_non_rock_ship_sets), so a patched
#: iterator -- a test feeding the stage its own ships -- sends the whole
#: stage to the Python loop, which honours it (native_motion's _SURFACE
#: does the same for kernel M).
_STOCK_ROSTER = (ship_iter.iter_ships, ship_iter.iter_non_rock_ships,
                 ship_iter.iter_set_objects)


_SWITCH_ENV = "DAUNTLESS_NATIVE_SUBSYSTEMS"


def configure(environ: Mapping[str, str] = os.environ) -> None:
    """The switch from `environ`: DAUNTLESS_NATIVE_SUBSYSTEMS, on unless
    exactly "0". Called by native_combat.configure (the mirror's own
    configure, which every caller that makes the mirror live runs). A
    caller's own env dict (a test scene's ``{"DAUNTLESS_NATIVE_COMBAT":
    "1"}``) that does not name the switch falls back to the process
    environment, so a shell's ``DAUNTLESS_NATIVE_SUBSYSTEMS=0`` reaches
    every stage."""
    global _switch
    value = environ.get(_SWITCH_ENV)
    if value is None and environ is not os.environ:
        value = os.environ.get(_SWITCH_ENV)
    _switch = value != "0"


def enabled() -> bool:
    """The native stage runs: the switch is on, the mirror is live, and the
    roster is stock (_STOCK_ROSTER, and loop.py's own iter_non_rock_ships;
    else ``patched_stages`` counts the stage, which runs in Python)."""
    if not _switch or not native_combat._enabled or _h is None:
        return False
    if not _roster_is_stock():
        _counts["patched_stages"] += 1
        native_combat._log_once(
            ("subsystems-patched",),
            "native subsystems: the ship roster is patched; the subsystem "
            "stage runs in Python while it is")
        return False
    return True


def _roster_is_stock() -> bool:
    if (ship_iter.iter_ships is not _STOCK_ROSTER[0]
            or ship_iter.iter_non_rock_ships is not _STOCK_ROSTER[1]
            or ship_iter.iter_set_objects is not _STOCK_ROSTER[2]):
        return False
    loop = sys.modules.get("engine.core.loop")
    return loop is None or getattr(
        loop, "iter_non_rock_ships", None) is _STOCK_ROSTER[1]


def reset() -> None:
    """The switch off and the counts zeroed (native_combat.reset calls
    this)."""
    global _switch
    _switch = False
    reset_counts()


def reset_counts() -> None:
    for k in _counts:
        _counts[k] = 0


def counts() -> dict:
    return dict(_counts)


# ── The records ──────────────────────────────────────────────────────────────

def _kinds():
    types, pieces = _h.combat_subsys_kinds()
    return types, pieces


_TYPES, _PIECES = _kinds() if _h is not None and hasattr(
    _h, "combat_subsys_kinds") else ({}, {})
DONE = _TYPES.get("DONE", 0)
RUN_PYTHON = _TYPES.get("RUN_PYTHON", 1)
EVENT = _TYPES.get("EVENT", 2)
SHIELD = _PIECES.get("SHIELD", 0)
POWER = _PIECES.get("POWER", 1)
CLOAK = _PIECES.get("CLOAK", 2)
REPAIR = _PIECES.get("REPAIR", 3)
ARTICULATION = _PIECES.get("ARTICULATION", 4)

#: EVENT kind -> handler(ship, code, a, b), posting that record's SDK event.
#: Empty until a piece is native (Tasks 3-5).
_EVENT_HANDLERS: dict = {}


def _run_shield(ship, dt):
    ss = ship.GetShieldSubsystem()
    if ss is not None:
        ss.Update(dt)


def _run_power(ship, dt):
    ps = ship.GetPowerSubsystem()
    if ps is not None:
        ps.Update(dt)


def _run_cloak(ship, dt):
    cl = ship.GetCloakingSubsystem()
    if cl is not None:
        cl.Update(dt)


def _run_repair(ship, dt):
    rs = ship.GetRepairSubsystem()
    if rs is not None:
        rs.Update(dt)


def _run_articulation(ship, dt):
    articulation.tick_ship(ship, dt)


#: RUN_PYTHON piece -> the Python loop's own line for it (loop.py).
_RUN = {SHIELD: _run_shield, POWER: _run_power, CLOAK: _run_cloak,
        REPAIR: _run_repair, ARTICULATION: _run_articulation}


# ── The stage ────────────────────────────────────────────────────────────────

def _handle(ship) -> int:
    h = ship.__dict__.get("_nslot", -1)
    return h if type(h) is int else -1


def step_all(dt: float) -> None:
    """One subsystem stage, natively driven (module docstring)."""
    _counts["stages"] += 1
    for ships in iter_non_rock_ship_sets():
        _step_set(ships, dt)


def _step_set(ships, dt) -> None:
    session = _h.combat_subsys_begin([_handle(s) for s in ships], dt)
    _counts["sessions"] += 1
    nxt = _h.combat_subsys_next
    run = _RUN
    while True:
        rtype, pos, _ship_h, kind, code, a, b = nxt(session)
        if rtype == DONE:
            return
        ship = ships[pos]
        if rtype == RUN_PYTHON:
            _counts["run_python"] += 1
            run[kind](ship, dt)
        else:
            _counts["events"] += 1
            _EVENT_HANDLERS[kind](ship, code, a, b)

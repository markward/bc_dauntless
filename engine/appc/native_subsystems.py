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
* ``EVENT(ship, kind, code, a, b, sub)``: ``_EVENT_HANDLERS[kind](ship,
  code, a, b, sub, pins)`` posts the SDK event a native piece stopped for
  (ruling R3: stop and resume, never batched); `sub` is the Subsystem
  handle it is about, `pins` the session's handle -> object dict (an object
  an event named stays reachable for the rest of its piece, even if its
  row is dropped or its ship lets it go).

Each record's write log -- what the native piece wrote -- is applied into
the Python objects by ``combat_subsys_next`` before the record comes back
(subsystem_write_apply.h), so the Python a record runs sees it.

THE SHIELD PIECE (Task 3) is native: ``ShieldSubsystem.Update`` bit for bit
(subsystem_step.h THE SHIELD PIECE). A script that patches the methods it
stands in for is NOT honoured, and there is no per-ship check for one (spec
§3 "Mods and patches (Part A)": BC's per-tick update was internal C++ that
ignored such patches). ``python_pieces`` (a piece mask, 0 in production) is
the test-facing hook that hands every ship's piece to Python. The
watcher-crossing protocol (``SHIELD_WATCHER``, ``SHIELD_WATCHER_TAIL``) is
the one Task 4's battery watchers reuse.

Every piece but the shield is still RUN_PYTHON (Tasks 4-6).
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

#: The test-facing hook: a mask of (1 << piece) the native session hands to
#: Python for every ship (combat_subsys_begin's python_pieces). 0 in
#: production; tests set it (and reset() clears it).
python_pieces = 0

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
    global _switch, python_pieces
    _switch = False
    python_pieces = 0
    reset_counts()


def reset_counts() -> None:
    for k in _counts:
        _counts[k] = 0


def counts() -> dict:
    return dict(_counts)


# ── The records ──────────────────────────────────────────────────────────────

def _kinds():
    return _h.combat_subsys_kinds()


_TYPES, _PIECES, _EVENTS = _kinds() if _h is not None and hasattr(
    _h, "combat_subsys_kinds") else ({}, {}, {})
DONE = _TYPES.get("DONE", 0)
RUN_PYTHON = _TYPES.get("RUN_PYTHON", 1)
EVENT = _TYPES.get("EVENT", 2)
SHIELD = _PIECES.get("SHIELD", 0)
POWER = _PIECES.get("POWER", 1)
CLOAK = _PIECES.get("CLOAK", 2)
REPAIR = _PIECES.get("REPAIR", 3)
ARTICULATION = _PIECES.get("ARTICULATION", 4)
SHIELD_WATCHER = _EVENTS.get("SHIELD_WATCHER", 0)
SHIELD_WATCHER_TAIL = _EVENTS.get("SHIELD_WATCHER_TAIL", 1)

# ── The event handlers ───────────────────────────────────────────────────────

def _event_object(h, pins):
    """The object Subsystem row `h` names: pinned for the rest of the
    session (the record's row is live when it is returned)."""
    obj = pins.get(h)
    if obj is None:
        obj = native_combat._registry.get(h)
        if obj is None or obj.__dict__.get("_nslot") != h:
            raise RuntimeError("native subsystems: an EVENT names row %r, "
                               "which no live object holds" % (h,))
        pins[h] = obj
    return obj


def _shield_watcher(ship, code, a, b, h, pins) -> None:
    """SHIELD_WATCHER: the Python piece's own line for watcher `code` of
    generator `h`, with the value the native piece computed for it --
    ``self._shield_watchers[code]._update(value)``, which fires the checks
    it crosses and commits the value (pushing it)."""
    sub = _event_object(h, pins)
    sub._shield_watchers[code]._update(a)


def _shield_watcher_tail(ship, code, a, b, h, pins) -> None:
    """SHIELD_WATCHER_TAIL: the rest of the Python piece's watcher loop on
    generator `h`, from watcher `code` on, as Update's own lines run it."""
    sub = pins.get(h)
    if sub is None:
        raise RuntimeError(
            "native subsystems: SHIELD_WATCHER_TAIL for generator row %r, "
            "which no SHIELD_WATCHER of this session pinned" % (h,))
    for f in range(code, sub.NUM_SHIELDS):
        sub._shield_watchers[f]._update(sub.GetSingleShieldPercentage(f))
    sub._shield_watchers[sub.NUM_SHIELDS]._update(sub.GetShieldPercentage())


#: EVENT kind -> handler(ship, code, a, b, sub, pins), posting that
#: record's SDK event.
_EVENT_HANDLERS: dict = {SHIELD_WATCHER: _shield_watcher,
                         SHIELD_WATCHER_TAIL: _shield_watcher_tail}


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
    session = _h.combat_subsys_begin([_handle(s) for s in ships], dt,
                                     python_pieces)
    _counts["sessions"] += 1
    nxt = _h.combat_subsys_next
    run = _RUN
    registry = native_combat._registry
    pins: dict = {}
    while True:
        try:
            rtype, pos, _ship_h, kind, code, a, b, sub = nxt(session, registry)
        except BaseException:
            _resync(ships)
            raise
        if rtype == DONE:
            return
        ship = ships[pos]
        if rtype == RUN_PYTHON:
            _counts["run_python"] += 1
            run[kind](ship, dt)
        else:
            _counts["events"] += 1
            _EVENT_HANDLERS[kind](ship, code, a, b, sub, pins)


def _resync(ships) -> None:
    """A raise out of combat_subsys_next (a broken invariant: its write log
    could not be applied): every generator of `ships` pushed again from its
    Python object, so no row keeps a write Python never got."""
    nc = native_combat
    for ship in ships:
        sh = ship.__dict__.get("_shield_subsystem")
        if sh is None:
            continue
        h = sh.__dict__.get("_nslot")
        if h is None or nc._registry.get(h) is not sh:
            continue
        try:
            nc._push_all(sh, h)
        except Exception as e:      # noqa: BLE001 -- the raise in flight wins
            nc._log_once(("subsystems-resync", type(e)),
                         "native subsystems: a resync after a raise raised "
                         "%r" % (e,))

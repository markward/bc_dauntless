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
the one the battery watchers reuse.

THE POWER PIECE (Task 4) is native too: ``PowerSubsystem.Update`` with its
consumer pump, bit for bit (subsystem_step.h THE POWER PIECE), under the
same Part A rule. Its events: ``BREACH`` (the plant's ``_trigger_breach``,
after the native piece latched ``_breach_fired``), ``BATTERY_WATCHER`` (a
battery watcher's ``_update`` with the value it crossed to) and
``POWER_TAIL`` (the rest of Update in Python, on a plant the piece could
not finish). The power draw program (engine/appc/passive_power.py) is not
used here: every native run drops the plant's program, and the Python
path's next pump rebuilds one.

THE CLOAK AND REPAIR PIECES (Task 5) are native too:
``CloakingSubsystem.Update`` and ``RepairSubsystem.Update`` bit for bit
(subsystem_step.h THE CLOAK PIECE, THE REPAIR PIECE), under the same Part A
rule. The cloak's events: ``FORCE_DECLOAK`` (the cloak's own
``_force_decloak``, so its state change, log and event stay Python's) and
``CLOAK_DONE`` (``_fire`` of the completion event, after the native piece
wrote the state). The bay's: ``REPAIR_CANNOT`` (ET_REPAIR_CANNOT_BE_COMPLETED
mid-walk, after the native piece added the member to the notified set),
``REPAIR_DONE`` (Update's last loop, one item per record: the queue discard,
then ET_REPAIR_COMPLETED) and ``REPAIR_TAIL`` (the rest of Update in Python,
``_repair_walk`` or ``_repair_worked``, on a bay the piece could not
finish). The bay's condition writes are damage.h's set_condition, applied
by ``combat_subsys_next`` under ``native_combat._dmg_context()`` exactly as
SetCondition's native chain applies its own: the same writes, the same
effect-queue entries, held to the boundary. The repair piece's locals
(teams, points, the queue index, the worked and completed items) are read
back with ``combat_subsys_repair_state``.

Articulation is still RUN_PYTHON (Task 6).
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
#: EVENT records by kind name (event_counts()).
_event_counts: dict = {}

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
    _event_counts.clear()


def counts() -> dict:
    return dict(_counts)


def event_counts() -> dict:
    """EVENT records handled since the last reset, by kind name."""
    return dict(_event_counts)


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
BREACH = _EVENTS.get("BREACH", 2)
BATTERY_WATCHER = _EVENTS.get("BATTERY_WATCHER", 3)
POWER_TAIL = _EVENTS.get("POWER_TAIL", 4)
FORCE_DECLOAK = _EVENTS.get("FORCE_DECLOAK", 5)
CLOAK_DONE = _EVENTS.get("CLOAK_DONE", 6)
REPAIR_CANNOT = _EVENTS.get("REPAIR_CANNOT", 7)
REPAIR_DONE = _EVENTS.get("REPAIR_DONE", 8)
REPAIR_TAIL = _EVENTS.get("REPAIR_TAIL", 9)
_EVENT_NAMES = {v: k for k, v in _EVENTS.items()}

#: The pins key of the session a handler's record came from (pins are
#: otherwise keyed by row handle).
_SESSION = "session"

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


def _breach(ship, code, a, b, h, pins) -> None:
    """BREACH: the Python piece's own line after it latched _breach_fired
    (the native piece did): ``self._trigger_breach()``."""
    _event_object(h, pins)._trigger_breach()


def _battery_watcher(ship, code, a, b, h, pins) -> None:
    """BATTERY_WATCHER: battery watcher `code` (0 main, 1 backup) of plant
    `h`, with the value the native piece computed for it --
    ``self._main_battery_watcher._update(value)`` (or the backup's)."""
    plant = _event_object(h, pins)
    w = (plant._main_battery_watcher if code == 0
         else plant._backup_battery_watcher)
    w._update(a)


def _power_tail(ship, code, a, b, h, pins) -> None:
    """POWER_TAIL: the rest of plant `h`'s Update, in Python, on that same
    plant: code 0 everything after the breach (``_update_flow(dt)``, dt in
    `b`), code 1 the backup watcher's line (the backup limit in `a`, as
    Update read it before the main watcher)."""
    plant = _event_object(h, pins)
    if code == 0:
        plant._update_flow(b)
    else:
        plant._backup_battery_watcher._update(
            plant._backup_battery_power / a if a > 0.0 else 0.0)


def _force_decloak(ship, code, a, b, h, pins) -> None:
    """FORCE_DECLOAK: the Python piece's ``self._force_decloak()`` (the
    native piece wrote nothing: the state change, the dev log and
    ET_DECLOAK_COMPLETED are all that method's)."""
    _event_object(h, pins)._force_decloak()


def _cloak_done(ship, code, a, b, h, pins) -> None:
    """CLOAK_DONE: the completion event after the native piece snapped the
    state and reset the clock -- ``self._fire("ET_CLOAK_COMPLETED")`` (code
    1) or ``"ET_DECLOAK_COMPLETED"`` (code 0)."""
    _event_object(h, pins)._fire(
        "ET_CLOAK_COMPLETED" if code == 1 else "ET_DECLOAK_COMPLETED")


def _repair_state(pins):
    return _h.combat_subsys_repair_state(pins[_SESSION])


def _repair_cannot(ship, code, a, b, h, pins) -> None:
    """REPAIR_CANNOT: bay `code`'s ET_REPAIR_CANNOT_BE_COMPLETED for member
    `h`, mid-walk (the native piece already added it to the notified set).
    The bay and the items worked so far are pinned first: a handler may
    drop their rows, and a REPAIR_TAIL then still names them."""
    bay = _event_object(code, pins)
    sub = _event_object(h, pins)
    for w in _repair_state(pins)[3]:
        _event_object(w, pins)
    bay._fire_repair_event("ET_REPAIR_CANNOT_BE_COMPLETED", sub)


def _repair_done(ship, code, a, b, h, pins) -> None:
    """REPAIR_DONE: one turn of Update's last loop for completed item `h`
    of bay `code` -- ``self._queue.discard(sub)`` then
    ET_REPAIR_COMPLETED. The first (a == 0) pins every completed item: a
    handler may drop a later one's row."""
    bay = _event_object(code, pins)
    if a == 0.0:
        for c in _repair_state(pins)[4]:
            _event_object(c, pins)
    sub = _event_object(h, pins)
    bay._queue.discard(sub)
    bay._fire_repair_event("ET_REPAIR_COMPLETED", sub)


def _repair_tail(ship, code, a, b, h, pins) -> None:
    """REPAIR_TAIL: the rest of bay `code`'s Update, in Python, with the
    native piece's locals: a 0 the walk from its queue index
    (``_repair_walk``), a 1 the worked items' repair (``_repair_worked``);
    dt in `b`."""
    bay = _event_object(code, pins)
    teams, points, index, worked, _completed = _repair_state(pins)
    items = [_event_object(w, pins) for w in worked]
    if a == 0.0:
        bay._repair_walk(b, teams, points, index, items)
    else:
        bay._repair_worked(b, points, items)


#: EVENT kind -> handler(ship, code, a, b, sub, pins), posting that
#: record's SDK event.
_EVENT_HANDLERS: dict = {SHIELD_WATCHER: _shield_watcher,
                         SHIELD_WATCHER_TAIL: _shield_watcher_tail,
                         BREACH: _breach, BATTERY_WATCHER: _battery_watcher,
                         POWER_TAIL: _power_tail,
                         FORCE_DECLOAK: _force_decloak,
                         CLOAK_DONE: _cloak_done,
                         REPAIR_CANNOT: _repair_cannot,
                         REPAIR_DONE: _repair_done,
                         REPAIR_TAIL: _repair_tail}


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
    dmg_context = native_combat._dmg_context
    pins: dict = {_SESSION: session}
    while True:
        try:
            rtype, pos, _ship_h, kind, code, a, b, sub = nxt(
                session, registry, dmg_context())
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
            name = _EVENT_NAMES.get(kind, kind)
            _event_counts[name] = _event_counts.get(name, 0) + 1
            _EVENT_HANDLERS[kind](ship, code, a, b, sub, pins)


def _resync(ships) -> None:
    """A raise out of combat_subsys_next (a broken invariant: its write log
    could not be applied): every row a native piece of `ships` writes -- the
    generator, the plant and the plant's consumers (the cloak and the bay
    among them), the bay's queued items -- pushed again from its Python
    object, so no row keeps a write Python never got."""
    nc = native_combat
    for ship in ships:
        d = ship.__dict__
        objs = [d.get("_shield_subsystem"), d.get("_power_subsystem"),
                d.get("_cloaking_subsystem"), d.get("_repair_subsystem")]
        objs += list(d.get("_powered_consumers") or ())
        bay = d.get("_repair_subsystem")
        if bay is not None:
            objs += list(getattr(bay, "__dict__", {}).get("_queue") or ())
        for sub in objs:
            if sub is None:
                continue
            h = getattr(sub, "__dict__", {}).get("_nslot")
            if h is None or nc._registry.get(h) is not sub:
                continue
            try:
                nc._push_all(sub, h)
            except Exception as e:  # noqa: BLE001 -- the raise in flight wins
                nc._log_once(("subsystems-resync", type(e)),
                             "native subsystems: a resync after a raise "
                             "raised %r" % (e,))

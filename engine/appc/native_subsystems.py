"""The subsystem stage, native (phase 6 A1; plan
docs/superpowers/plans/2026-11-05-phase6-b0-a1-subsystems.md, stage map
docs/superpowers/plans/2026-11-05-phase6-a1-subsystem-stage-map.md).

``engine.core.loop._update_ship_subsystems`` calls ``step_all(dt)``: the
only subsystem stage there is (phase 6 A1 Task 8 deleted the Python one,
ruling R2, and its switch). It needs the live mirror and the native module,
and raises without them (as fire control does, M10); it walks the sets
itself, so a caller that patches the roster iterators to feed it its own
ships gets a RuntimeError, not a stage that silently ignores the patch.

THE DRIVER. The roster is ``iter_non_rock_ships``' own, one set at a time
(``ship_iter.iter_non_rock_ship_sets``: the sets as the stage begins, each
set's objects when the stage reaches that set), so a ship a handler adds to
a later set, or removes from it, is seen exactly as the Python loop sees
it. Each set's ships open one native session (``combat_subsys_begin``, the handles
the mirror registers them under: ``_nslot``), and the driver loops
``combat_subsys_next`` to DONE:

* ``RUN_PYTHON(ship, ARTICULATION)``: ``articulation.tick_ship(ship, dt)``,
  the one piece whose Python is kept. The other four pieces are native only
  (phase 6 Task 8): a RUN_PYTHON naming one is a protocol error. A piece
  the mirror cannot run is SKIPPED instead (subsystem_step.h THE SKIPS):
  DONE's code says how many; each (piece, reason) is logged once
  (``_log_once``, as fire control's no-fire is) and counted natively
  (``skip_counts()``), and under DAUNTLESS_NATIVE_AUDIT=1 each is an audit
  failure. The goldens hold every count at 0.
* ``EVENT(ship, kind, code, a, b, sub)``: ``_EVENT_HANDLERS[kind](ship,
  code, a, b, sub, pins)`` posts the SDK event a native piece stopped for
  (ruling R3: stop and resume, never batched); `sub` is the Subsystem
  handle it is about, `pins` the session's handle -> object dict (an object
  an event named stays reachable for the rest of its piece, even if its
  row is dropped or its ship lets it go).

Each record's write log -- what the native piece wrote -- is applied into
the Python objects by ``combat_subsys_next`` before the record comes back
(subsystem_write_apply.h), so the Python a record runs sees it.

THE SHIELD PIECE (Task 3): the generator's regen (subsystem_step.h THE
SHIELD PIECE; the deleted ShieldSubsystem.Update's, bit for bit, as the
goldens pin). A script that patches the methods it
stands in for is NOT honoured, and there is no per-ship check for one (spec
§3 "Mods and patches (Part A)": BC's per-tick update was internal C++ that
ignored such patches). The
watcher-crossing protocol (``SHIELD_WATCHER``, ``SHIELD_WATCHER_TAIL``) is
the one the battery watchers reuse.

THE POWER PIECE (Task 4): the plant's tick with its consumer pump
(subsystem_step.h THE POWER PIECE), under the same Part A rule. Its events: ``BREACH`` (the plant's ``_trigger_breach``,
after the native piece latched ``_breach_fired``), ``BATTERY_WATCHER`` (a
battery watcher's ``_update`` with the value it crossed to) and
``POWER_TAIL`` (the backup watcher's line, on a plant whose watchers a
handler of the main one's crossing made unreadable).

THE CLOAK AND REPAIR PIECES (Task 5): the cloak's transition and the bay's
repair tick (subsystem_step.h THE CLOAK PIECE, THE REPAIR PIECE), under the
same Part A rule. The cloak's events: ``FORCE_DECLOAK`` (the cloak's own
``_force_decloak``, so its state change, log and event stay Python's) and
``CLOAK_DONE`` (``_fire`` of the completion event, after the native piece
wrote the state). The bay's: ``REPAIR_CANNOT`` (ET_REPAIR_CANNOT_BE_COMPLETED
mid-walk, after the native piece added the member to the notified set),
``REPAIR_DONE`` (one completed item per record: the queue discard, then
ET_REPAIR_COMPLETED) and ``REPAIR_SET`` (one worked item the native
condition chain cannot repair, repaired here through the SDK's own
``Repair``, ruling R8-3). The bay's condition writes are damage.h's
set_condition, applied by ``combat_subsys_next`` under ``native_combat._dmg_context()`` exactly as
SetCondition's native chain applies its own: the same writes, the same
effect-queue entries, held to the boundary. The repair piece's locals
(teams, points, the queue index, the worked and completed items) are read
back with ``combat_subsys_repair_state``.

Articulation is RUN_PYTHON for rigged ships (Task 6 skips rigless ones
natively).
"""
import sys

from engine.appc import articulation, native_combat, ship_iter
from engine.appc.ship_iter import iter_non_rock_ship_sets

try:
    import _dauntless_host as _h
except ImportError:     # pragma: no cover -- a build without the module
    _h = None


# ── The counts ───────────────────────────────────────────────────────────────

_counts = {"stages": 0, "sessions": 0, "run_python": 0, "events": 0}
#: EVENT records by kind name (event_counts()).
_event_counts: dict = {}

#: The roster as the game takes it, stock (taken at import). The driver
#: walks the sets itself (iter_non_rock_ship_sets), so a patched iterator --
#: a test feeding the stage its own ships -- would be silently ignored: the
#: stage raises instead (ruling R8-5, A4). Feed a test's own ships through
#: tests/helpers/subsystem_stage.py (tick_subsystems).
_STOCK_ROSTER = (ship_iter.iter_ships, ship_iter.iter_non_rock_ships,
                 ship_iter.iter_set_objects)


def _roster_is_stock() -> bool:
    if (ship_iter.iter_ships is not _STOCK_ROSTER[0]
            or ship_iter.iter_non_rock_ships is not _STOCK_ROSTER[1]
            or ship_iter.iter_set_objects is not _STOCK_ROSTER[2]):
        return False
    loop = sys.modules.get("engine.core.loop")
    patched = getattr(loop, "iter_non_rock_ships", None) if loop else None
    return patched is None or patched is _STOCK_ROSTER[1]


def reset() -> None:
    """The counts zeroed, the native skip counts too (native_combat.reset
    calls this)."""
    reset_counts()
    if _h is not None and hasattr(_h, "combat_subsys_skip_counts_reset"):
        _h.combat_subsys_skip_counts_reset()
    if _h is not None and hasattr(_h, "combat_subsys_write_stats_reset"):
        _h.combat_subsys_write_stats_reset()


def reset_counts() -> None:
    for k in _counts:
        _counts[k] = 0
    _event_counts.clear()


def counts() -> dict:
    return dict(_counts)


def event_counts() -> dict:
    """EVENT records handled since the last reset, by kind name."""
    return dict(_event_counts)


def skip_counts() -> dict:
    """THE SKIPS since the last reset (subsystem_step.h), counted natively:
    {(piece name, reason name): count}, the non-zero ones."""
    return dict(_h.combat_subsys_skip_counts())


def write_stats() -> dict:
    """{"logged": n, "identical": n} since the last reset: the writes the
    stage logged for the applier, and the ones it skipped because the mirror
    (so Python) already held the value bit for bit (subsystem_step.cc)."""
    return dict(_h.combat_subsys_write_stats())


# ── The records ──────────────────────────────────────────────────────────────

def _kinds():
    return _h.combat_subsys_kinds()


_TYPES, _PIECES, _EVENTS, _SKIPS = _kinds() if _h is not None and hasattr(
    _h, "combat_subsys_kinds") else ({}, {}, {}, {})
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
REPAIR_SET = _EVENTS.get("REPAIR_SET", 9)
_EVENT_NAMES = {v: k for k, v in _EVENTS.items()}
_PIECE_NAMES = {v: k for k, v in _PIECES.items()}
_SKIP_NAMES = {v: k for k, v in _SKIPS.items()}
#: What each skip reason means, for its one log line.
_SKIP_TEXT = {
    "NO_ROW": "a ship the mirror has no row for -- the freeze persists for "
              "that ship: it is skipped every stage until it has a row",
    "LOST_ROW": "a ship whose row was dropped mid-stage -- the freeze "
                "persists for that ship: it has no row from now on",
    "REF": "a subsystem the mirror cannot name (unregistered, dropped, or "
           "of another kind)",
    "SHIELD_UNREADY": "a shield generator whose faces or watchers the "
                      "mirror cannot read",
    "OFFLINE": "an offline or condition question the mirror cannot answer",
    "PROPERTY": "a property the mirror cannot read",
    "BATTERY_WATCH": "battery watchers the mirror cannot read",
    "PARENT_SHIP": "a power plant whose parent ship is not a ShipClass row",
    "CONSUMER": "a power consumer the pump cannot run (that consumer is "
                "passed over; the plant still runs)",
    "QUEUE_MEMBER": "a repair-queue entry the mirror cannot name (that "
                    "member is passed over)",
    "BAY_GONE": "a repair bay whose row was dropped mid-stage",
    "POST_BREACH_UNREADY": "a power plant its BREACH handler left "
                           "unreadable (the rest of its tick)",
}

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
    """POWER_TAIL (code 1): plant `h`'s backup watcher line, in Python, the
    backup limit in `a` as the piece read it before the main watcher."""
    if code != 1:
        raise RuntimeError("native subsystems: POWER_TAIL code %r (only "
                           "the backup watcher's line, code 1, exists)"
                           % (code,))
    plant = _event_object(h, pins)
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
    drop their rows, and a REPAIR_SET then still names them."""
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


def _repair_set(ship, code, a, b, h, pins) -> None:
    """REPAIR_SET: worked item `h` of bay `code`, which the native condition
    chain could not repair (ruling R8-3): that one item's lines of the
    repair tick, through the SDK-facing surface -- its complexity, ``Repair
    (per_item / complexity)`` (SetCondition of min(max, condition + gain)),
    then the completion test, reported back so the item joins the
    completions in order. per_item in `a`. The bay and every worked item
    are pinned first: a handler may drop a later item's row."""
    _event_object(code, pins)
    for w in _repair_state(pins)[3]:
        _event_object(w, pins)
    sub = _event_object(h, pins)
    complexity = sub.GetRepairComplexity()
    if complexity <= 0.0:
        complexity = 1.0
    sub.Repair(a / complexity)
    if sub.GetCondition() >= sub.GetMaxCondition():
        _h.combat_subsys_repair_complete(pins[_SESSION], h)


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
                         REPAIR_SET: _repair_set}


# ── The stage ────────────────────────────────────────────────────────────────

def _handle(ship) -> int:
    h = ship.__dict__.get("_nslot", -1)
    return h if type(h) is int else -1


def step_all(dt: float) -> None:
    """One subsystem stage, natively driven (module docstring). Raises
    RuntimeError without the native module or the live mirror, or with a
    patched roster."""
    if _h is None:
        raise RuntimeError(
            "native subsystems: the _dauntless_host module did not import; "
            "the subsystem stage is native only -- build it "
            "(cmake --build build -j)")
    if not native_combat._enabled:
        raise RuntimeError(
            "native subsystems: the native mirror is not live "
            "(native_combat.configure() first); the subsystem stage is "
            "native only")
    if not _roster_is_stock():
        raise RuntimeError(
            "native subsystems: the ship roster (ship_iter.iter_ships / "
            "iter_non_rock_ships / iter_set_objects) is patched; the native "
            "stage walks the sets itself and would ignore the patch -- tick "
            "a test's own ships with tests/helpers/subsystem_stage.py")
    _counts["stages"] += 1
    for ships in iter_non_rock_ship_sets():
        _step_set(ships, dt)


def _step_set(ships, dt) -> None:
    session = _h.combat_subsys_begin([_handle(s) for s in ships], dt)
    _counts["sessions"] += 1
    nxt = _h.combat_subsys_next
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
            if code:
                _skipped(session, ships)
            return
        ship = ships[pos]
        if rtype == RUN_PYTHON:
            if kind != ARTICULATION:
                raise RuntimeError(
                    "native subsystems: a RUN_PYTHON for piece %r -- only "
                    "ARTICULATION has a Python copy (stale build?)"
                    % (_PIECE_NAMES.get(kind, kind),))
            _counts["run_python"] += 1
            articulation.tick_ship(ship, dt)
        else:
            _counts["events"] += 1
            name = _EVENT_NAMES.get(kind, kind)
            _event_counts[name] = _event_counts.get(name, 0) + 1
            _EVENT_HANDLERS[kind](ship, code, a, b, sub, pins)


def _skipped(session, ships) -> None:
    """The session's skips (DONE's code): each (piece, reason) logged once,
    and, under the audit, recorded as a failure (subsystem_step.h THE
    SKIPS; the native counts are skip_counts())."""
    audit = native_combat.audit_enabled()
    for pos, piece, why, _sub in _h.combat_subsys_skips(session):
        pname = _PIECE_NAMES.get(piece, piece)
        wname = _SKIP_NAMES.get(why, why)
        native_combat._log_once(
            ("subsystems-skip", pname, wname),
            "native subsystems: %s skipped for %s (%s) -- not run "
            "(skip %s)" % (pname, type(ships[pos]).__name__,
                           _SKIP_TEXT.get(wname, wname), wname))
        if audit:
            native_combat._failures.append(
                ("subsystem stage", "skip %s %s" % (pname, wname)))


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

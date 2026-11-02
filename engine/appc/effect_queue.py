"""The combat effect queue: weapon events and weapon sounds, and what a
condition write or a hit reports (THE DAMAGE KINDS below), delivered at the
tick boundary.

Spec docs/superpowers/specs/2026-11-02-combat-fire-events-design.md §4.1-4.2
(roadmap decisions 6, 9, 13). The combat step must not check in with Python
mid-step, so the effects that only report or present -- a weapon's fire
sound and loop stop, its ET_WEAPON_FIRED, a tube's cannot-fire, launch,
ammo and reload events, a charge watcher's crossings -- go into ONE ordered
queue (native/src/host/combat_effect_queue.h) and are delivered here, in
emission order, when the deferral scope closes.

THE SCOPE. ``host_loop`` opens it around each sim tick's ``sim.weapons`` and
``sim.combat``, only with native combat on (``host_loop._combat_effect_scope``);
switch off it is never open and every weapon-kind producer acts at once,
as before. While it is open every producer below appends instead of acting,
Python ones included (E4: no split path per kind). Nestable: only the
outermost exit flushes, and it flushes even when the tick raised (what was
produced was produced). Outside it a weapon-kind producer acts at once; the
damage kinds always append (THE DAMAGE KINDS).

THE PRODUCERS (each ``if effect_queue.deferring(): post(...)``, else today's
code; weapon_subsystems / float_range_watcher):
  FIRE_SOUND(bank)            _EnergyWeaponFireMixin._fire_effect's edge
  LOOP_STOP(bank)             _EnergyWeaponFireMixin.StopFiring of a firing
                              bank (its loop handle may not exist yet: a
                              FIRE_SOUND queued this tick)
  WEAPON_FIRED(weapon, target)  _post_weapon_fired
  WEAPON_FIRE_FAILED(tube)    TorpedoTube._broadcast_weapon_fire_failed
  TORPEDO_FIRED(tube, torp)   TorpedoTube._broadcast_torpedo_fired
  AMMO_CONSUMED(tube)         TorpedoTube._broadcast_ammo_consumed_if_player
  TORPEDO_RELOAD(tube)        TorpedoTube._broadcast_reload
  WATCH(watcher, old, new)    FloatRangeWatcher._update of a weapon's charge
                              watcher with checks: the value is committed at
                              once; delivery fires the checks crossed
                              between old and new, as registered THEN (E3)
A kernel appends the same kinds natively, naming objects by mirror handle
(-1 None); its WATCH names the WEAPON, whose charge watcher it means. And
one kind only a kernel appends (spec 2026-11-02-combat-launch-deferral
§4.1):
  SPAWN(launcher, kind, ship, set, module, target, position xyz, has
        velocity, velocity xyz, has offset, offset xyz, baked xyz, drf,
        damage scale, fired at)
                              a launch, its fire-time values read when it
                              was decided: K1's (k1_fire_control.h,
                              LAUNCHES AT THE BOUNDARY: a tube's, a dumb
                              fire, a cannon's) or Python's own
                              while this queue defers (E4 for launches,
                              rulings L5-L6: weapon_subsystems._defer_spawn,
                              a tube's or a cannon's, whatever its module's
                              Create does). Delivery builds the torpedo from
                              that record (weapon_subsystems.spawn_launch:
                              Create, register -- ET_TORPEDO_ENTERED_SET, so
                              ruling L2 moves it to the boundary -- and the
                              launch sound), then a tube's ET_TORPEDO_FIRED,
                              or a cannon's damage scale and its
                              ET_WEAPON_FIRED at `fired at` (M4: once the
                              bolt exists). A kernel's kind and flags are
                              numbers; its module (the one its launch
                              resolved), launcher, ship, set, target and
                              `fired at` are the objects themselves, held
                              from fire time, so one freed or swapped
                              before the boundary is still the torpedo's
                              (the bindings, K1Held, k1_append_spawn), as
                              is a kernel WEAPON_FIRED's weapon and target
                              and an AMMO_CONSUMED's tube: a launch whose
                              writes applied never loses its events.

THE DAMAGE KINDS (spec 2026-11-02-native-damage-design.md M2, M5, §4.3;
controller rulings R7-R9). What a condition write and a hit REPORT, in
today's synchronous order minus nesting -- per write (subsystems.
ShipSubsystem._set_condition): COND_WATCH (combined watcher, then condition
watcher), SUBSYS_EVENT, REPAIR_ADD, ZERO_CROSS; per hit (combat._apply_hit):
each write's, then HIT_PRESENT, then WEAPON_HIT:
  COND_WATCH(subsystem, which, old, new)
                              a subsystem's condition watcher WITH checks:
                              committed at once, its crossings fired at
                              delivery as registered then (E3)
  SUBSYS_EVENT(subsystem, which)  ET_SUBSYSTEM_DESTROYED (and its internal
                              blast) / _DISABLED / _OPERATIONAL
  REPAIR_ADD(subsystem)       a write left it below max: AddToRepairList
  ZERO_CROSS(ship, subsystem, crossed, killer)
                              the death check (death_check._check): the
                              invincibility read at delivery, then the
                              breach / hull cascade and the death. Also
                              the destroyed-plant trigger's (R9)
  SPLASH(ship)                appended by ship_death.begin after its
                              ET_OBJECT_EXPLODING: the death splash
  HIT_PRESENT(*HIT_PRESENT_FIELDS)  hit_feedback.present (dispatch, F7
                              severance included)
  WEAPON_HIT(*WEAPON_HIT_FIELDS)    combat.post_weapon_hit
Unlike the weapon kinds they are queued in BOTH switch states (``emit``),
and outside the tick scope they are HELD for the next BOUNDARY
(``boundary()``: each tick's combat flush, the host's frame-end drain, a
host-less GameLoop tick's end), never delivered at the end of the call: a
script that zeroes a hull and only then makes the ship invincible (E3M5's
KillGonDev) must not see it die in between. A native session's end is not
a boundary: its flush delivers its own entries (F3) and puts the held
damage kinds back, in order. Entries a delivery appends (a splash's hits, a
handler's write) are delivered in the same flush.

DELIVERY (``flush``). The queue is taken whole and each entry performed in
order with the scope closed -- so a delivered event's handler, and anything
it produces, acts at once -- by the producer's own method (deferring() is
False while the queue drains). A kernel entry naming an object freed or
unregistered by the time its batch is taken is skipped and counted
("skipped_gone"); a row DROPPED while its object lives (native_combat._drop:
a value the mirror cannot hold) is not gone -- _drop first rebinds the
entries still queued naming it to the object (combat_effect_rebind), and a
batch being delivered had its handles resolved when it was taken (_drain),
so either way they are delivered. Two consequences of delivering
later than the reference acted:
  * A LOOP_STOP whose bank is gone by delivery (skipped_gone) stops
    nothing: the queue holds the bank, never its loop handle, so that loop
    would play on. Not reachable today: the host loop's tick list
    (`_ships_this_tick`) holds every ship, and through it its banks, alive
    across the flush, and a bank whose row was dropped is rebound, not
    skipped. Hold the handle in the entry if that ever changes.
  * A kernel WATCH names the weapon; it is delivered to the charge watcher
    the weapon holds AT DELIVERY (`weapon._charge_watcher`): a watcher
    swapped in between gets the crossing, the one swapped out does not.
An entry whose
delivery raises does not stop the rest (decision 13): in play it is logged
and delivery carries on; under tests and ``--developer`` the flush delivers
the rest, then re-raises the first error with each later one noted on it.
When the tick itself raised, the scope re-raises the tick's error with the
delivery errors noted on it instead. A delivery that calls reset() (a
mission swap) ends the drain: the rest of its batch is dropped with the
queue, never delivered into the next mission.

A NATIVE SESSION OUTSIDE THE SCOPE (an AI's StartFiring running a K1 system
session from gl.ai, or one a delivered event's handler started) opens its
own deferral, ``session()`` (ruling F3): while it runs EVERY producer
appends -- its kernel's entries and the Python of its records alike (a tube
launch, an asked Fire, a handler stopping a bank) -- so the session keeps
one emission order, and a bank it lit natively and Python stopped in it
plays, then stops, its loop (Python acting at once there would stop a loop
not yet started, which then plays forever). It counts even inside a
delivery, where nothing else defers. When it ends it delivers what it
appended (``session_ended()``). Inside a delivery that flush is nested: the
outer drain already took its batch whole, so the nested one delivers only
the session's entries, there and then -- before the rest of the outer
batch -- and its errors join the outermost flush's (decision 13 is applied
once, there). A session begun while something already defers (the tick's
scope, an enclosing session) opens nothing: that one delivers. The cost
(spec ruling E1): a weapon event a K1 session produces outside the tick
never reaches its handlers mid-walk, only at the session's end.
"""
import contextlib
import logging
import sys

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_logger = logging.getLogger(__name__)

#: The kinds, in combat_effect_queue.h's order (combat_effect_kinds()).
KIND_NAMES = ("FIRE_SOUND", "LOOP_STOP", "WEAPON_FIRED", "WEAPON_FIRE_FAILED",
              "TORPEDO_FIRED", "AMMO_CONSUMED", "TORPEDO_RELOAD", "WATCH",
              "SPAWN",
              # The damage kinds (THE DAMAGE KINDS above).
              "COND_WATCH", "SUBSYS_EVENT", "REPAIR_ADD", "ZERO_CROSS",
              "SPLASH", "HIT_PRESENT", "WEAPON_HIT")
(FIRE_SOUND, LOOP_STOP, WEAPON_FIRED, WEAPON_FIRE_FAILED, TORPEDO_FIRED,
 AMMO_CONSUMED, TORPEDO_RELOAD, WATCH, SPAWN,
 COND_WATCH, SUBSYS_EVENT, REPAIR_ADD, ZERO_CROSS, SPLASH, HIT_PRESENT,
 WEAPON_HIT) = range(len(KIND_NAMES))
DAMAGE_KINDS = frozenset((COND_WATCH, SUBSYS_EVENT, REPAIR_ADD, ZERO_CROSS,
                          SPLASH, HIT_PRESENT, WEAPON_HIT))

#: COND_WATCH's `which`: the subsystem's GetConditionWatcher or its
#: GetCombinedPercentageWatcher.
WATCH_CONDITION, WATCH_COMBINED = 0, 1
#: SUBSYS_EVENT's `which`: the event the threshold state machine posts.
SUBSYS_DESTROYED, SUBSYS_DISABLED, SUBSYS_OPERATIONAL = 0, 1, 2
#: HIT_PRESENT's operands: hit_feedback.dispatch's keyword arguments.
HIT_PRESENT_FIELDS = (
    "ship", "source", "point", "normal", "damage", "subsystem",
    "absorbed_shields", "absorbed_subsystem", "absorbed_hull",
    "sub_transition", "ship_instances", "weapon_type", "radius",
    "persist_decal", "allow_structural_wear", "shield_point", "tangent",
    "decal_radius", "decal_dent", "single_impact", "shield_radius")
#: WEAPON_HIT's operands: the WeaponHitEvent combat.apply_hit posts.
WEAPON_HIT_FIELDS = (
    "ship", "source", "damage", "hit_point", "normal", "radius",
    "subsystem", "weapon_type", "is_hull_hit")

_depth = 0              # open scopes
_sessions = 0           # open native-session deferrals (session())
_draining = False       # a flush is delivering: producers act at once
_boundary = True        # the delivering flush is a boundary (not a session's)
_held: list = []        # damage entries a session's flush set aside
_errors: list = []      # (kind, exception) of the outermost flush
_epoch = 0              # bumped by reset(): a scope opened before it is gone
_counts = {"delivered": 0, "skipped_gone": 0, "failed": 0, "damage": 0}


def deferring() -> bool:
    """Whether a producer must append (post) rather than act: inside an
    open native session (even mid-delivery), or the scope while it is not
    draining."""
    return _sessions > 0 or (_depth > 0 and not _draining)


@contextlib.contextmanager
def scope(profile=None):
    """Open the deferral scope; the outermost exit flushes. A scope a
    reset() closed exits doing nothing. `profile`: a frame-profiler row the
    exit's flush is timed under (host_loop: "sim.effects"), None for no
    timing."""
    global _depth
    epoch = _epoch
    _depth += 1
    try:
        yield
    except BaseException as body:
        if _close(epoch):
            # The tick raised: what it produced is still delivered, and a
            # delivery error rides on the tick's own, never replaces it.
            try:
                _exit_flush(profile)
            except Exception as x:
                body.add_note("combat effect queue: the flush at the scope's "
                              "exit raised %s: %s" % (type(x).__name__, x))
                for note in getattr(x, "__notes__", ()):
                    body.add_note(note)
        raise
    else:
        if _close(epoch):
            _exit_flush(profile)


def _exit_flush(profile) -> None:
    if profile is None:
        flush()
        return
    from engine.core import frame_profiler
    with frame_profiler.scope(profile):
        flush()


def _close(epoch) -> bool:
    """Leave a scope opened at `epoch`; True when it was the outermost (a
    scope a reset() closed is already gone: False)."""
    global _depth
    if epoch != _epoch:
        return False
    _depth -= 1
    return _depth == 0


@contextlib.contextmanager
def session():
    """A native session's own deferral (see the module docstring, A NATIVE
    SESSION OUTSIDE THE SCOPE): opened only when nothing defers; its exit
    delivers what was appended in it (session_ended), even when its body
    raised -- an abandoned kernel session's entries stand for effects that
    already happened (ruling F5) -- with a delivery error then noted on
    the body's own. A session a reset() closed exits doing nothing."""
    global _sessions
    if deferring():
        yield                   # the enclosing scope or session delivers
        return
    epoch = _epoch
    _sessions += 1
    try:
        yield
    except BaseException as body:
        if _end_session(epoch):
            try:
                session_ended()
            except Exception as x:
                body.add_note("combat effect queue: the delivery at the "
                              "session's end raised %s: %s"
                              % (type(x).__name__, x))
                for note in getattr(x, "__notes__", ()):
                    body.add_note(note)
        raise
    else:
        if _end_session(epoch):
            session_ended()


def _end_session(epoch) -> bool:
    """Leave a session opened at `epoch`; False when a reset() closed it
    already."""
    global _sessions
    if epoch != _epoch:
        return False
    _sessions -= 1
    return True


def session_ended() -> None:
    """A native session (a kernel run of Tasks 3-4) has ended: deliver what
    it appended, now, unless something still defers (the tick's scope or an
    enclosing session then delivers it). Safe anywhere, inside a delivery
    included (see the module docstring); session() calls it."""
    if not deferring():
        flush(boundary=False)


def boundary() -> None:
    """THE TICK BOUNDARY (native damage, rulings M5, R8): deliver every
    queued entry, the damage kinds held since the last boundary included,
    unless something still defers (the tick's scope then delivers at its
    exit, which is the boundary). host_loop calls it after each tick's
    combat step (_combat_tick_boundary, both switch states) and once more
    after the frame's post-step pass (radiation, collisions, scenery,
    hull_breakup); a GameLoop the host does not drive, at the end of its
    tick. Inside a delivery: what is queued now is delivered there."""
    if not deferring():
        flush()


def emit(kind: int, *operands) -> None:
    """A damage kind's producer (see THE DAMAGE KINDS): append, in both
    switch states, wherever it runs -- in the scope, outside it (held for
    the next boundary) or during a delivery (delivered in the same flush).
    Without the native module there is no queue: deliver at once."""
    if _h is None:
        _DELIVER[kind](*operands)
        return
    _h.combat_effect_post(kind, *operands)


def check_acting_directly(what: str) -> None:
    """For a producer that posts a queued kind directly, by design only
    where nothing defers (TorpedoSystem._post_cant_fire: ET_CANT_FIRE is
    ET_WEAPON_FIRE_FAILED): under tests and --developer, raise if it runs
    while the queue defers -- one kind on two paths (ruling E4). In play,
    nothing."""
    if deferring() and _strict():
        raise AssertionError(
            "combat effect queue: %s posted directly while deferring" % what)


def post(kind: int, *operands) -> None:
    """Append Python's entry (the caller checked deferring())."""
    _h.combat_effect_post(kind, *operands)


def counts() -> dict:
    """Since the last reset(): entries delivered (failed ones included),
    kernel entries skipped because an object they name was gone, deliveries
    that raised, and -- of those delivered -- the damage kinds."""
    return dict(_counts)


def reset() -> None:
    """native_combat.reset(): drop every queued entry undelivered, close
    any scope or session left open, zero the counts."""
    global _depth, _sessions, _draining, _epoch, _boundary
    _depth = 0
    _sessions = 0
    _draining = False
    _boundary = True
    del _held[:]
    _epoch += 1
    for k in _counts:
        _counts[k] = 0
    if _h is not None and hasattr(_h, "combat_effect_clear"):
        _h.combat_effect_clear()


def _strict(modules=None) -> bool:
    """Decision 13's loud mode: under tests (pytest imported, as
    host_loop._boot_notice_wanted asks) or with --developer."""
    from engine import dev_mode
    if modules is None:
        modules = sys.modules
    return "pytest" in modules or dev_mode.is_enabled()


def flush(boundary: bool = True) -> None:
    """Deliver every queued entry, in order (see the module docstring).
    Inside a delivery (nested): deliver what is queued now -- appended
    since the outer drain took its batch -- and leave the errors to it.
    `boundary` False (a native session's end, session_ended): the damage
    kinds are set aside and put back, in order, for the next boundary
    (ruling R8); everything else is delivered."""
    global _draining, _errors, _boundary
    if _draining:
        _drain()
        return
    _draining = True
    _boundary = boundary
    _errors = []
    epoch = _epoch
    try:
        _drain()
    finally:
        _draining = False
        _boundary = True
        errors, _errors = _errors, []
        held = list(_held)
        del _held[:]
        if epoch == _epoch:
            for kind, ops in held:
                _h.combat_effect_post(kind, *ops)
    if not errors:
        return
    if not _strict():
        for kind, x in errors:
            _logger.error("combat effect queue: %s delivery raised %r",
                          KIND_NAMES[kind], x, exc_info=x)
        return
    first = errors[0][1]
    for kind, x in errors[1:]:
        first.add_note("combat effect queue: a later %s delivery raised "
                       "%s: %s" % (KIND_NAMES[kind], type(x).__name__, x))
    raise first


def _drain() -> None:
    """Take and deliver until the queue is empty; errors into _errors. A
    batch's kernel handles are resolved as it is taken, before any of its
    entries is delivered: a delivery that drops a row (native_combat._drop)
    cannot rebind entries that already left the queue, so a later entry of
    the same batch naming that row must hold its object already. A delivery
    that resets the queue (reset(): a mission swap) ends the drain: the rest
    of the batch is the old mission's, and is dropped like the queue."""
    epoch = _epoch
    while True:
        entries = _h.combat_effect_take()
        if not entries:
            break
        batch = [(kind, _resolve(ops) if native else ops)
                 for kind, native, ops in entries]
        for kind, ops in batch:
            if _epoch != epoch:
                return
            if ops is None:
                _counts["skipped_gone"] += 1
                continue
            if not _boundary and kind in DAMAGE_KINDS:
                _held.append((kind, ops))   # for the next boundary (R8)
                continue
            _counts["delivered"] += 1
            if kind in DAMAGE_KINDS:
                _counts["damage"] += 1
            try:
                _DELIVER[kind](*ops)
            except Exception as x:
                _counts["failed"] += 1
                _errors.append((kind, x))


def _resolve(ops):
    """A kernel entry's operands: a handle -> its object (-1 None), a
    number kept. None when a handle names no live registered object."""
    from engine.appc import native_combat
    out = []
    for v in ops:
        if type(v) is int:
            if v == native_combat.REF_NONE:
                v = None
            else:
                o = native_combat._registry.get(v)
                if o is None or o.__dict__.get("_nslot") != v:
                    return None
                v = o
        out.append(v)
    return out


# ── Delivery: each kind's producer, acting now ───────────────────────────────

def _fire_sound(bank):
    bank._play_fire_sfx()


def _loop_stop(bank):
    bank._stop_loop_sound()


def _weapon_fired(weapon, target):
    from engine.appc.weapon_subsystems import _post_weapon_fired
    _post_weapon_fired(weapon, target)


def _weapon_fire_failed(tube):
    tube._broadcast_weapon_fire_failed()


def _torpedo_fired(tube, torp):
    tube._broadcast_torpedo_fired(torp)


def _ammo_consumed(tube):
    tube._broadcast_ammo_consumed_if_player()


def _torpedo_reload(tube):
    tube._broadcast_reload()


def _watch(watcher, old, new):
    from engine.appc.float_range_watcher import FloatRangeWatcher
    if not isinstance(watcher, FloatRangeWatcher):
        # A kernel's names the weapon: its watcher as of NOW (see DELIVERY).
        watcher = watcher._charge_watcher
    watcher._fire_crossed(old, new)


def _spawn(launcher, kind, ship, kset, module, target, *record):
    from engine.appc.weapon_subsystems import spawn_launch
    spawn_launch(launcher, kind, ship, kset, module, target, record)


def _cond_watch(subsystem, which, old, new):
    # The watcher the subsystem holds NOW, against its checks as registered
    # now (ruling E3, as a kernel's WATCH).
    watcher = (subsystem._condition_watcher if which == WATCH_CONDITION
               else subsystem._combined_watcher)
    if watcher is not None:
        watcher._fire_crossed(old, new)


def _subsys_event(subsystem, which):
    subsystem._deliver_threshold_event(which)


def _repair_add(subsystem):
    subsystem._auto_enqueue_for_repair()


def _zero_cross(ship, subsystem, crossed, killer):
    from engine.appc import death_check
    death_check._check(ship, subsystem, bool(crossed), killer)


def _splash(ship):
    from engine.appc import ship_death
    ship_death.deliver_splash(ship)


def _hit_present(*ops):
    from engine.appc import hit_feedback
    hit_feedback.present(**dict(zip(HIT_PRESENT_FIELDS, ops)))


def _weapon_hit(*ops):
    from engine.appc import combat
    combat.post_weapon_hit(**dict(zip(WEAPON_HIT_FIELDS, ops)))


_DELIVER = (_fire_sound, _loop_stop, _weapon_fired, _weapon_fire_failed,
            _torpedo_fired, _ammo_consumed, _torpedo_reload, _watch, _spawn,
            _cond_watch, _subsys_event, _repair_add, _zero_cross, _splash,
            _hit_present, _weapon_hit)

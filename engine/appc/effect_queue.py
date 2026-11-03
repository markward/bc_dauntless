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
  FIRE_SOUND(bank)            a beam's fire edge (only K1 appends it now:
                              fire control native only)
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
        velocity, velocity xyz, has offset, offset xyz, drf, damage
        scale, fired at)
                              a launch, its fire-time values read when it
                              was decided: K1's (k1_fire_control.h,
                              LAUNCHES AT THE BOUNDARY: a tube's, a dumb
                              fire, a cannon's; whatever its module's
                              Create does, rulings L5-L6). Delivery builds the torpedo from
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
And the tractor's two events (fire control native only, ruling R8; spec
2026-11-03-fire-control-native-only §4.4):
  TRACTOR_STARTED(system, ship)  ET_TRACTOR_BEAM_STARTED_FIRING
  TRACTOR_STOPPED(system, ship)  ET_TRACTOR_BEAM_STOPPED_FIRING
                              a tractor system's firing edge, source the
                              system, destination its ship: K1's (its
                              tractor walk, k1_fire_control.h) or Python's
                              (TractorBeamSystem.StopFiring's
                              _sync_firing_event). They are ALWAYS appended
                              (``emit``), never acted on at once: outside the
                              tick scope one waits for the next flush (a
                              session's end delivers it, as any weapon kind)
                              or boundary, and one a delivered handler
                              produces is delivered later in the same flush,
                              never nested inside the event that caused it.
                              So a STARTED handler's StopFiring (E8M2's OD1)
                              lands after the tick's tractor force (decision
                              9).

THE DAMAGE KINDS (spec 2026-11-02-native-damage-design.md M2, M5, §4.3;
controller rulings R7-R9, I1-I4). What a condition write and a hit REPORT,
in today's synchronous order minus nesting -- per write (subsystems.
ShipSubsystem._set_condition): COND_WATCH (combined watcher, then condition
watcher), SUBSYS_EVENT, REPAIR_ADD, ZERO_CROSS; per hit (combat._apply_hit):
each write's, then HIT_PRESENT, then WEAPON_HIT:
  COND_WATCH(subsystem, which, old, new)
                              a subsystem's condition watcher WITH checks:
                              committed at once, its crossings fired at
                              delivery as registered then (E3)
  SUBSYS_EVENT(subsystem, which)  ET_SUBSYSTEM_DESTROYED (and its internal
                              blast) / _DISABLED / _OPERATIONAL
  REPAIR_ADD(subsystem)       a write left it below max while it is not in
                              its bay's queue (I3): AddToRepairList
  ZERO_CROSS(ship, subsystem, crossed, killer)
                              the death check (death_check._check): the
                              invincibility and the condition read at
                              delivery (I1), then the breach / hull
                              cascade and the death. Also the
                              destroyed-plant trigger's (R9)
  SPLASH(ship)                appended by ship_death.begin after its
                              ET_OBJECT_EXPLODING: the death splash
  HIT_PRESENT(*HIT_PRESENT_FIELDS)  hit_feedback.present (dispatch, F7
                              severance included)
  WEAPON_HIT(*WEAPON_HIT_FIELDS)    combat.post_weapon_hit
THEIR ENTRIES ARE A FROZEN CONTRACT (I4) the native arm reproduces: one
layout per kind (OPERANDS, the C++ effect_kind_operands), one letter per
operand -- R an object reference (a kernel's mirror handle, -1 None; the
entry's SUBJECT is one), H an object the entry holds (a hit's source, a
death's killer), D a float, I an int code (the named constants below,
combat_effect_codes), B a bool -- with exactly those Python types in BOTH
arms once taken, so the two compare without normalising. HIT_PRESENT
spells its points as xyz with presence flags, its weapon type as a code,
carries no instances map (delivery looks it up: hit_feedback.
delivery_instances) and flags its shield point standing for the hit point
itself (DM H14), so delivery rebuilds that alias (hit_present_operands /
_hit_present are the encoding's two halves). ONE GONE-OBJECT RULE (I4):
an entry whose subject -- its ship, or for COND_WATCH / SUBSYS_EVENT /
REPAIR_ADD its subsystem's ship -- has left the world (objects.
broadcast_object_deleted: DeleteObjectFromSet, a death's linger end, the
SetDeleteMe sweep) by its delivery is skipped and counted "skipped_gone",
whichever arm emitted it; a kernel's whose subject's row was freed is
skipped the same way.
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


class _PyQueue:
    """The queue without the native module (task review M4): the binding's
    four calls over a Python list, so the hold-and-boundary rules -- and
    with them KillGonDev's survival and R2's order -- are the same with or
    without it. Python entries only (nothing native runs without it)."""

    def __init__(self):
        self._entries = []

    def combat_effect_post(self, kind, *ops):
        self._entries.append((kind, False, ops))

    def combat_effect_take(self):
        out, self._entries = self._entries, []
        return out

    def combat_effect_clear(self):
        del self._entries[:]

    def combat_effect_size(self):
        return len(self._entries)


#: The queue: the native one (combat_effect_queue.h) when built.
_q = (_h if _h is not None and hasattr(_h, "combat_effect_take")
      else _PyQueue())

#: The kinds, in combat_effect_queue.h's order (combat_effect_kinds()).
KIND_NAMES = ("FIRE_SOUND", "LOOP_STOP", "WEAPON_FIRED", "WEAPON_FIRE_FAILED",
              "TORPEDO_FIRED", "AMMO_CONSUMED", "TORPEDO_RELOAD", "WATCH",
              "SPAWN", "TRACTOR_STARTED", "TRACTOR_STOPPED",
              # The damage kinds (THE DAMAGE KINDS above).
              "COND_WATCH", "SUBSYS_EVENT", "REPAIR_ADD", "ZERO_CROSS",
              "SPLASH", "HIT_PRESENT", "WEAPON_HIT")
(FIRE_SOUND, LOOP_STOP, WEAPON_FIRED, WEAPON_FIRE_FAILED, TORPEDO_FIRED,
 AMMO_CONSUMED, TORPEDO_RELOAD, WATCH, SPAWN, TRACTOR_STARTED, TRACTOR_STOPPED,
 COND_WATCH, SUBSYS_EVENT, REPAIR_ADD, ZERO_CROSS, SPLASH, HIT_PRESENT,
 WEAPON_HIT) = range(len(KIND_NAMES))
DAMAGE_KINDS = frozenset((COND_WATCH, SUBSYS_EVENT, REPAIR_ADD, ZERO_CROSS,
                          SPLASH, HIT_PRESENT, WEAPON_HIT))

# ── The damage kinds' code operands (combat_effect_queue.h's enums, by the
# same names: combat_effect_codes) ──
#: COND_WATCH's `which`: the subsystem's GetConditionWatcher or its
#: GetCombinedPercentageWatcher.
WATCH_CONDITION, WATCH_COMBINED = 0, 1
#: SUBSYS_EVENT's `which`: the event the threshold state machine posts.
SUBSYS_DESTROYED, SUBSYS_DISABLED, SUBSYS_OPERATIONAL = 0, 1, 2
#: HIT_PRESENT's sub_transition: the primary subsystem's worst new state
#: (combat._diff_state's None / "disabled" / "destroyed").
TRANSITION_NONE, TRANSITION_DISABLED, TRANSITION_DESTROYED = 0, 1, 2
#: HIT_PRESENT's weapon_type: apply_hit's weapon_type string.
(HIT_WEAPON_NONE, HIT_WEAPON_PHASER, HIT_WEAPON_TORPEDO, HIT_WEAPON_TRACTOR,
 HIT_WEAPON_COLLISION) = range(5)
#: WEAPON_HIT's weapon_type: the WeaponHitEvent id (events.WeaponHitEvent).
(WEAPON_HIT_NON_WEAPON, WEAPON_HIT_PHASER, WEAPON_HIT_TORPEDO,
 WEAPON_HIT_TRACTOR_BEAM) = (-1, 0, 1, 2)
CODE_NAMES = (
    "WATCH_CONDITION", "WATCH_COMBINED",
    "SUBSYS_DESTROYED", "SUBSYS_DISABLED", "SUBSYS_OPERATIONAL",
    "TRANSITION_NONE", "TRANSITION_DISABLED", "TRANSITION_DESTROYED",
    "HIT_WEAPON_NONE", "HIT_WEAPON_PHASER", "HIT_WEAPON_TORPEDO",
    "HIT_WEAPON_TRACTOR", "HIT_WEAPON_COLLISION",
    "WEAPON_HIT_NON_WEAPON", "WEAPON_HIT_PHASER", "WEAPON_HIT_TORPEDO",
    "WEAPON_HIT_TRACTOR_BEAM")
_TRANSITIONS = (None, "disabled", "destroyed")
_TRANSITION_CODES = {t: i for i, t in enumerate(_TRANSITIONS)}
_HIT_WEAPONS = (None, "phaser", "torpedo", "tractor", "collision")
_HIT_WEAPON_CODES = {w: i for i, w in enumerate(_HIT_WEAPONS)}

#: HIT_PRESENT's operands, in order: hit_feedback.dispatch's inputs, points
#: spelled as xyz behind a presence flag (hit_present_operands).
HIT_PRESENT_FIELDS = (
    "ship", "source", "has_instances",
    "point_x", "point_y", "point_z",
    "has_normal", "normal_x", "normal_y", "normal_z",
    "damage", "subsystem",
    "absorbed_shields", "absorbed_subsystem", "absorbed_hull",
    "sub_transition", "weapon_type", "radius",
    "persist_decal", "allow_structural_wear",
    "has_shield_point", "shield_point_is_point",
    "shield_point_x", "shield_point_y", "shield_point_z",
    "has_tangent", "tangent_x", "tangent_y", "tangent_z",
    "has_decal_radius", "decal_radius", "decal_dent", "single_impact",
    "has_shield_radius", "shield_radius")
#: WEAPON_HIT's operands, in order: the WeaponHitEvent combat.apply_hit
#: posts (weapon_hit_operands).
WEAPON_HIT_FIELDS = (
    "ship", "source", "damage", "hit_x", "hit_y", "hit_z",
    "has_normal", "normal_x", "normal_y", "normal_z", "radius",
    "subsystem", "weapon_type", "is_hull_hit")

#: Each damage kind's frozen layout (combat_effect_queue.h
#: effect_kind_operands; see THE DAMAGE KINDS): R a reference (handle), H a
#: held object, D float, I int, B bool.
OPERANDS = {
    COND_WATCH: "RIDD",
    SUBSYS_EVENT: "RI",
    REPAIR_ADD: "R",
    ZERO_CROSS: "RRBH",
    SPLASH: "R",
    HIT_PRESENT: "RHBDDDBDDDDRDDDIIDBBBBDDDBDDDBDDBBD",
    WEAPON_HIT: "RHDDDDBDDDDRIB",
}

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
    """A damage kind's producer (see THE DAMAGE KINDS), or a tractor
    event's: append, in both switch states, wherever it runs -- in the
    scope, outside it (held for the next flush) or during a delivery
    (delivered in the same flush). A damage kind's operands fit its layout
    (OPERANDS), Python types exact."""
    _q.combat_effect_post(kind, *operands)


def _xyz(p):
    return (0.0, 0.0, 0.0) if p is None else (float(p.x), float(p.y),
                                               float(p.z))


def hit_present_operands(*, ship, source, point, normal, damage, subsystem,
                         absorbed_shields, absorbed_subsystem, absorbed_hull,
                         sub_transition, has_instances, weapon_type, radius,
                         persist_decal, allow_structural_wear, shield_point,
                         tangent, decal_radius, decal_dent, single_impact,
                         shield_radius) -> tuple:
    """HIT_PRESENT's operands (HIT_PRESENT_FIELDS) from dispatch's inputs:
    the encoding _hit_present decodes. `has_instances`: the hit was given an
    instances map (delivery uses delivery_instances, not a carried one). A
    weapon type with no code is HIT_WEAPON_NONE: dispatch only ever compares
    it with "phaser", "torpedo" and "collision", so any other string acts as
    None does (as WEAPON_HIT's id makes it NON_WEAPON)."""
    weapon = _HIT_WEAPON_CODES.get(weapon_type, HIT_WEAPON_NONE)
    return ((ship, source, bool(has_instances)) + _xyz(point)
            + (normal is not None,) + _xyz(normal)
            + (float(damage), subsystem, float(absorbed_shields),
               float(absorbed_subsystem), float(absorbed_hull),
               _TRANSITION_CODES[sub_transition], weapon, float(radius),
               bool(persist_decal), bool(allow_structural_wear),
               shield_point is not None,
               shield_point is not None and shield_point is point)
            + _xyz(shield_point)
            + (tangent is not None,) + _xyz(tangent)
            + (decal_radius is not None,
               0.0 if decal_radius is None else float(decal_radius),
               float(decal_dent), bool(single_impact),
               shield_radius is not None,
               0.0 if shield_radius is None else float(shield_radius)))


def weapon_hit_operands(*, ship, source, damage, hit_point, normal, radius,
                        subsystem, weapon_type, is_hull_hit) -> tuple:
    """WEAPON_HIT's operands (WEAPON_HIT_FIELDS): the encoding _weapon_hit
    decodes. `weapon_type` is the WeaponHitEvent id (WEAPON_HIT_*)."""
    return ((ship, source, float(damage)) + _xyz(hit_point)
            + (normal is not None,) + _xyz(normal)
            + (float(radius), subsystem, int(weapon_type), bool(is_hull_hit)))


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
    _q.combat_effect_post(kind, *operands)


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
    _q.combat_effect_clear()


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
                _q.combat_effect_post(kind, *ops)
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
        entries = _q.combat_effect_take()
        if not entries:
            break
        batch = [(kind, _resolve(kind, ops) if native else ops)
                 for kind, native, ops in entries]
        for kind, ops in batch:
            if _epoch != epoch:
                return
            if ops is None:
                _counts["skipped_gone"] += 1
                continue
            if kind >= COND_WATCH:      # a damage kind (they come last)
                if not _boundary:
                    _held.append((kind, ops))   # for the next boundary (R8)
                    continue
                if _subject_gone(kind, ops):
                    _counts["skipped_gone"] += 1    # the gone rule (I4)
                    continue
                _counts["damage"] += 1
            _counts["delivered"] += 1
            try:
                _DELIVER[kind](*ops)
            except Exception as x:
                _counts["failed"] += 1
                _errors.append((kind, x))


def _resolve(kind, ops):
    """A kernel entry's operands: a handle -> its object (-1 None), a
    number kept. None when a handle names no live registered object. A
    damage kind's by its layout (OPERANDS): only an R operand is a handle
    (an I is an int code); an H is held, an int there only -1 (None)."""
    from engine.appc import native_combat
    layout = OPERANDS.get(kind)
    out = []
    for i, v in enumerate(ops):
        if type(v) is int and (layout is None or layout[i] in "RH"):
            if v == native_combat.REF_NONE or layout is not None and \
                    layout[i] == "H":
                v = None
            else:
                o = native_combat._registry.get(v)
                if o is None or o.__dict__.get("_nslot") != v:
                    return None
                v = o
        out.append(v)
    return out


def _subject_gone(kind, ops) -> bool:
    """THE GONE-OBJECT RULE (I4): the entry's subject -- its ship, or a
    subsystem's ship for the per-subsystem kinds -- has left the world
    (objects.broadcast_object_deleted) by its delivery."""
    subject = ops[0]
    if kind <= REPAIR_ADD and subject is not None:
        # COND_WATCH, SUBSYS_EVENT, REPAIR_ADD name a subsystem.
        owning = getattr(type(subject), "_owning_ship", None)
        subject = owning(subject) if owning is not None else None
    d = getattr(subject, "__dict__", None)
    return d is not None and d.get("_deleted", False) is True


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


def _tractor_event(event_type, system, ship):
    """ET_TRACTOR_BEAM_*: no payload, source the system, destination the
    ship (Bridge/PowerDisplay.py:1013 and Conditions/
    ConditionFiringTractorBeam.py:26-27 filter on it; both re-read the live
    state themselves)."""
    import App
    evt = App.TGEvent_Create()
    evt.SetEventType(event_type)
    evt.SetSource(system)
    evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)


def _tractor_started(system, ship):
    import App
    _tractor_event(App.ET_TRACTOR_BEAM_STARTED_FIRING, system, ship)


def _tractor_stopped(system, ship):
    import App
    _tractor_event(App.ET_TRACTOR_BEAM_STOPPED_FIRING, system, ship)


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


def _point(has, x, y, z):
    if not has:
        return None
    from engine.appc.math import TGPoint3
    return TGPoint3(x, y, z)


def _hit_present(ship, source, has_instances, px, py, pz, has_normal,
                 nx, ny, nz, damage, subsystem, absorbed_shields,
                 absorbed_subsystem, absorbed_hull, transition, weapon,
                 radius, persist_decal, allow_structural_wear,
                 has_shield_point, shield_point_is_point, sx, sy, sz,
                 has_tangent, tx, ty, tz, has_decal_radius, decal_radius,
                 decal_dent, single_impact, has_shield_radius, shield_radius):
    # hit_present_operands' inverse: the points rebuilt, the shield point
    # the hit point itself when it was (DM H14), the instances map the one
    # in force now.
    from engine.appc import hit_feedback
    point = _point(True, px, py, pz)
    hit_feedback.present(
        ship=ship, source=source, point=point,
        normal=_point(has_normal, nx, ny, nz), damage=damage,
        subsystem=subsystem, absorbed_shields=absorbed_shields,
        absorbed_subsystem=absorbed_subsystem, absorbed_hull=absorbed_hull,
        sub_transition=_TRANSITIONS[transition],
        ship_instances=(hit_feedback.delivery_instances() if has_instances
                        else None),
        weapon_type=_HIT_WEAPONS[weapon], radius=radius,
        persist_decal=persist_decal,
        allow_structural_wear=allow_structural_wear,
        shield_point=(point if shield_point_is_point
                      else _point(has_shield_point, sx, sy, sz)),
        tangent=_point(has_tangent, tx, ty, tz),
        decal_radius=decal_radius if has_decal_radius else None,
        decal_dent=decal_dent, single_impact=single_impact,
        shield_radius=shield_radius if has_shield_radius else None)


def _weapon_hit(ship, source, damage, hx, hy, hz, has_normal, nx, ny, nz,
                radius, subsystem, weapon_type, is_hull_hit):
    from engine.appc import combat
    combat.post_weapon_hit(
        ship=ship, source=source, damage=damage,
        hit_point=_point(True, hx, hy, hz),
        normal=_point(has_normal, nx, ny, nz), radius=radius,
        subsystem=subsystem, weapon_type=weapon_type,
        is_hull_hit=is_hull_hit)


_DELIVER = (_fire_sound, _loop_stop, _weapon_fired, _weapon_fire_failed,
            _torpedo_fired, _ammo_consumed, _torpedo_reload, _watch, _spawn,
            _tractor_started, _tractor_stopped, _cond_watch, _subsys_event,
            _repair_add, _zero_cross, _splash, _hit_present, _weapon_hit)

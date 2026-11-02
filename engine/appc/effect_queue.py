"""The combat effect queue: weapon events and weapon sounds, delivered at the
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
switch off it is never open and every producer acts at once, as before.
While it is open every producer below appends instead of acting, Python
ones included (E4: no split path per kind). Nestable: only the outermost
exit flushes, and it flushes even when the tick raised (what was produced
was produced). Outside it a producer acts at once.

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
(-1 None); its WATCH names the WEAPON, whose charge watcher it means.

DELIVERY (``flush``). The queue is taken whole and each entry performed in
order with the scope closed -- so a delivered event's handler, and anything
it produces, acts at once -- by the producer's own method (deferring() is
False while the queue drains). A kernel entry naming an object freed or
unregistered by the time its batch is taken is skipped and counted
("skipped_gone"); a row DROPPED while its object lives (native_combat._drop:
a value the mirror cannot hold) is not gone -- _drop first rebinds the
entries still queued naming it to the object (combat_effect_rebind), and a
batch being delivered had its handles resolved when it was taken (_drain),
so either way they are delivered. An entry whose
delivery raises does not stop the rest (decision 13): in play it is logged
and delivery carries on; under tests and ``--developer`` the flush delivers
the rest, then re-raises the first error with each later one noted on it.
When the tick itself raised, the scope re-raises the tick's error with the
delivery errors noted on it instead.

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
              "TORPEDO_FIRED", "AMMO_CONSUMED", "TORPEDO_RELOAD", "WATCH")
(FIRE_SOUND, LOOP_STOP, WEAPON_FIRED, WEAPON_FIRE_FAILED, TORPEDO_FIRED,
 AMMO_CONSUMED, TORPEDO_RELOAD, WATCH) = range(len(KIND_NAMES))

_depth = 0              # open scopes
_sessions = 0           # open native-session deferrals (session())
_draining = False       # a flush is delivering: producers act at once
_errors: list = []      # (kind, exception) of the outermost flush
_epoch = 0              # bumped by reset(): a scope opened before it is gone
_counts = {"delivered": 0, "skipped_gone": 0, "failed": 0}


def deferring() -> bool:
    """Whether a producer must append (post) rather than act: inside an
    open native session (even mid-delivery), or the scope while it is not
    draining."""
    return _sessions > 0 or (_depth > 0 and not _draining)


@contextlib.contextmanager
def scope():
    """Open the deferral scope; the outermost exit flushes. A scope a
    reset() closed exits doing nothing."""
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
                flush()
            except Exception as x:
                body.add_note("combat effect queue: the flush at the scope's "
                              "exit raised %s: %s" % (type(x).__name__, x))
                for note in getattr(x, "__notes__", ()):
                    body.add_note(note)
        raise
    else:
        if _close(epoch):
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
        flush()


def post(kind: int, *operands) -> None:
    """Append Python's entry (the caller checked deferring())."""
    _h.combat_effect_post(kind, *operands)


def counts() -> dict:
    """Since the last reset(): entries delivered (failed ones included),
    kernel entries skipped because an object they name was gone, and
    deliveries that raised."""
    return dict(_counts)


def reset() -> None:
    """native_combat.reset(): drop every queued entry undelivered, close
    any scope or session left open, zero the counts."""
    global _depth, _sessions, _draining, _epoch
    _depth = 0
    _sessions = 0
    _draining = False
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


def flush() -> None:
    """Deliver every queued entry, in order (see the module docstring).
    Inside a delivery (nested): deliver what is queued now -- appended
    since the outer drain took its batch -- and leave the errors to it."""
    global _draining, _errors
    if _draining:
        _drain()
        return
    _draining = True
    _errors = []
    try:
        _drain()
    finally:
        _draining = False
        errors, _errors = _errors, []
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
    the same batch naming that row must hold its object already."""
    while True:
        entries = _h.combat_effect_take()
        if not entries:
            break
        batch = [(kind, _resolve(ops) if native else ops)
                 for kind, native, ops in entries]
        for kind, ops in batch:
            if ops is None:
                _counts["skipped_gone"] += 1
                continue
            _counts["delivered"] += 1
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
        watcher = watcher._charge_watcher       # a kernel's: the weapon
    watcher._fire_crossed(old, new)


_DELIVER = (_fire_sound, _loop_stop, _weapon_fired, _weapon_fire_failed,
            _torpedo_fired, _ammo_consumed, _torpedo_reload, _watch)

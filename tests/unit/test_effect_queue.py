"""The combat effect queue (spec docs/superpowers/specs/2026-11-02-combat-
fire-events-design.md §4.1-4.2; plan 2026-11-02-combat-fire-events.md Task 2).

One ordered queue for weapon events and weapon sounds: kernels append mirror
handles, Python appends object references, and engine/appc/effect_queue.py
delivers every entry in emission order when the deferral scope closes (the
tick boundary). Outside the scope every producer acts at once; host_loop
opens the scope only with native combat on.
"""
import gc
import logging

import pytest

import App
from tests.helpers import host_frame_source

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_effect_take"),
    reason="combat effect queue bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import effect_queue as eq  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.actions import TGObjPtrEvent  # noqa: E402
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _clean():
    nc.reset()
    yield
    nc.reset()


@pytest.fixture
def calls(monkeypatch):
    """Every bank sound delivered, as (what, bank name), in order."""
    log = []
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                        lambda self: log.append(("play", self.GetName())))
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_stop_loop_sound",
                        lambda self: log.append(("stop", self.GetName())))
    return log


@pytest.fixture
def events(monkeypatch):
    """Every AddEvent, as (type, source, destination, object pointer)."""
    log = []
    orig = App.g_kEventManager.AddEvent

    def add_event(evt, _orig=orig):
        ptr = (evt.GetObjPtr() if isinstance(evt, TGObjPtrEvent)
               else None)
        log.append((evt.GetEventType(), evt.GetSource(),
                    evt.GetDestination(), ptr))
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)
    return log


def _bank(name):
    return ws.PhaserBank(name)


def _post_native(kind, *ops):
    _h.combat_effect_post_native(kind, *ops)


# ── The kinds ────────────────────────────────────────────────────────────────

def test_kinds_match_the_native_queue():
    """Python's kind numbers are the binding's, name for name."""
    native = _h.combat_effect_kinds()
    assert native == {name: getattr(eq, name) for name in eq.KIND_NAMES}
    # 9 weapon kinds, the 2 tractor events (fire control native only, R8),
    # 7 damage kinds.
    assert len(eq.KIND_NAMES) == 18


# ── Order ────────────────────────────────────────────────────────────────────

def test_order_across_native_and_python_appends(calls):
    """Python and kernel appends share ONE emission order."""
    a, b, c = _bank("A"), _bank("B"), _bank("C")
    with eq.scope():
        eq.post(eq.FIRE_SOUND, a)
        _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
        eq.post(eq.LOOP_STOP, a)
        _post_native(eq.LOOP_STOP, b.__dict__["_nslot"])
        eq.post(eq.FIRE_SOUND, c)
        assert calls == []
    assert calls == [("play", "A"), ("play", "B"), ("stop", "A"),
                     ("stop", "B"), ("play", "C")]
    assert eq.counts() == {"delivered": 5, "skipped_gone": 0,
                           "failed": 0, "damage": 0}
    assert _h.combat_effect_take() == []


def test_native_minus_one_handle_is_none(events):
    """A kernel's -1 operand is None (a dumbfire's target)."""
    bank = _bank("A")
    with eq.scope():
        _post_native(eq.WEAPON_FIRED, bank.__dict__["_nslot"], -1)
    assert [(e[0], e[1], e[3]) for e in events] == [
        (App.ET_WEAPON_FIRED, bank, None)]


# ── The scope ────────────────────────────────────────────────────────────────

def test_outside_the_scope_producers_act_at_once(events):
    bank, target = _bank("A"), _bank("T")
    assert not eq.deferring()
    ws._post_weapon_fired(bank, target)
    assert [(e[0], e[1], e[3]) for e in events] == [
        (App.ET_WEAPON_FIRED, bank, target)]
    assert _h.combat_effect_take() == []


def test_inside_the_scope_producers_append(events):
    bank, target = _bank("A"), _bank("T")
    with eq.scope():
        assert eq.deferring()
        ws._post_weapon_fired(bank, target)
        assert events == []
    assert not eq.deferring()
    assert [(e[0], e[1], e[3]) for e in events] == [
        (App.ET_WEAPON_FIRED, bank, target)]


def test_nested_scope_flushes_once_at_the_outermost_exit(calls):
    a = _bank("A")
    with eq.scope():
        with eq.scope():
            eq.post(eq.FIRE_SOUND, a)
        assert calls == []
        assert eq.deferring()
    assert calls == [("play", "A")]


def test_scope_flushes_when_its_body_raises(calls):
    a = _bank("A")
    with pytest.raises(KeyError):
        with eq.scope():
            eq.post(eq.FIRE_SOUND, a)
            raise KeyError("boom")
    assert calls == [("play", "A")]
    assert not eq.deferring()


def test_delivery_acts_at_once(monkeypatch, events):
    """A handler run by a delivered entry produces at once: the scope is
    closed while the queue drains."""
    bank, target = _bank("A"), _bank("T")
    seen = []

    def play(self):
        seen.append(eq.deferring())
        ws._post_weapon_fired(self, target)
        seen.append(len(events))
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)
    with eq.scope():
        eq.post(eq.FIRE_SOUND, bank)
    assert seen == [False, 1]


def test_switch_off_never_opens_the_scope():
    """host_loop's tick scope is the queue's only with native combat on."""
    assert not nc.enabled()
    with host_loop._combat_effect_scope():
        assert not eq.deferring()
    nc.configure(ON)
    assert nc.enabled()
    with host_loop._combat_effect_scope():
        assert eq.deferring()
    assert not eq.deferring()


@pytest.fixture
def profiler():
    from engine.core import frame_profiler as fp
    fp.set_enabled(False, native=False)
    fp.reset()
    fp.set_enabled(True, native=False)
    yield fp
    fp.set_enabled(False, native=False)
    fp.reset()


def test_the_tick_flush_is_its_own_profiler_row(monkeypatch, profiler):
    """The delivery at the tick scope's close is timed as "sim.effects",
    under the row the scope sits in; with the switch off there is no such
    row (the scope is never opened)."""
    fp = profiler
    stack = []
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                        lambda self: stack.append(list(fp._scope_stack)))
    for native in (False, True):
        if native:
            nc.configure(ON)
        fp.begin_frame()
        with fp.scope("sim"):
            with host_loop._combat_effect_scope():
                _beam_edge(_bank("A"), _bank("T"))
        fp.end_frame()
        if not native:
            assert "sim.effects" not in fp.calls(), fp.calls()
            assert stack == [["sim"]]           # played at once, in "sim"
            stack.clear()
    assert fp.parents()["sim.effects"] == "sim"
    assert fp.calls()["sim.effects"] == 1
    assert stack == [["sim", "sim.effects"]]


def test_host_loop_tick_runs_weapons_and_combat_inside_the_scope():
    """The sim tick opens the scope around sim.weapons and sim.combat."""
    src = host_frame_source.run_source()
    at = src.index("with _combat_effect_scope():")
    assert src.index('"sim.weapons"') > at
    assert src.index('"sim.combat"') > at


# ── Freed objects ────────────────────────────────────────────────────────────

def _free(obj):
    """Let `obj` go: the id registry holds every TGObject strongly."""
    from engine.core import ids
    ids.unregister(obj.GetObjID())


def test_freed_or_unregistered_handle_is_skipped_and_counted(calls):
    """A kernel entry naming an object freed, or whose handle was
    unregistered behind the registry's back, since it was queued is
    skipped and counted; the rest are delivered."""
    a, gone, stale = _bank("A"), _bank("Gone"), _bank("Stale")
    with eq.scope():
        _post_native(eq.FIRE_SOUND, gone.__dict__["_nslot"])
        _post_native(eq.FIRE_SOUND, stale.__dict__["_nslot"])
        eq.post(eq.FIRE_SOUND, a)
        _free(gone)
        del gone
        gc.collect()
        h = stale.__dict__.pop("_nslot")
        nc.unregister_handle(h)
    assert calls == [("play", "A")]
    assert eq.counts() == {"delivered": 1, "skipped_gone": 2,
                           "failed": 0, "damage": 0}


def test_a_dropped_rows_entries_are_still_delivered(calls, events):
    """Task 3 review, Minor 3: an object whose row is DROPPED while kernel
    entries naming it wait (native_combat._drop: a value the mirror cannot
    hold) is still Python's live object, and the Python reference posts its
    events: _drop rebinds those operands to the object before it frees the
    row, so each entry is delivered, in its place. A WATCH's numbers and an
    entry's other handles are kept."""
    a, dropped = _bank("A"), _bank("Dropped")
    tube = ws.TorpedoTube("T")
    h = dropped.__dict__["_nslot"]
    with eq.scope():
        _post_native(eq.FIRE_SOUND, h)
        eq.post(eq.FIRE_SOUND, a)
        _post_native(eq.TORPEDO_RELOAD, tube.__dict__["_nslot"])
        _post_native(eq.LOOP_STOP, h)
        nc._drop(dropped)
        nc._drop(tube)
        assert "_nslot" not in dropped.__dict__
    assert calls == [("play", "Dropped"), ("play", "A"), ("stop", "Dropped")]
    assert [e[0] for e in events] == [App.ET_TORPEDO_RELOAD]
    assert events[0][2] is tube
    assert eq.counts() == {"delivered": 4, "skipped_gone": 0,
                           "failed": 0, "damage": 0}
    assert _h.combat_effect_size() == 0


def test_a_row_dropped_by_a_delivery_keeps_its_later_entries(monkeypatch):
    """Review minor 2: a delivered entry's handler drops another row
    (native_combat._drop) whose kernel entry comes LATER in the same batch.
    The batch left the queue before its first delivery (so _drop's rebind
    cannot reach it): its handles are resolved as it is taken, before any
    entry is delivered, and the later entry is still delivered."""
    log = []
    a, b = _bank("A"), _bank("B")

    def play(bank):
        log.append(("play", bank.GetName()))
        if bank is a:
            nc._drop(b)
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)
    with eq.scope():
        eq.post(eq.FIRE_SOUND, a)
        _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
    assert "_nslot" not in b.__dict__
    assert log == [("play", "A"), ("play", "B")]
    assert eq.counts() == {"delivered": 2, "skipped_gone": 0,
                           "failed": 0, "damage": 0}


def test_a_reset_by_a_delivery_stops_its_batch(monkeypatch):
    """Final review 2: a delivered entry's handler resets the queue (a
    mission swap's native_combat.reset). The rest of the batch that entry
    was taken with is the old mission's: not delivered (a SPAWN in it would
    register an old-mission torpedo in the new one), Python's and kernel's
    entries alike."""
    log = []
    a, b, c = _bank("A"), _bank("B"), _bank("C")

    def play(bank):
        log.append(("play", bank.GetName()))
        if bank is a:
            eq.reset()
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)
    with eq.scope():
        eq.post(eq.FIRE_SOUND, a)
        _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
        eq.post(eq.FIRE_SOUND, c)
    assert log == [("play", "A")]
    assert not eq.deferring() and _h.combat_effect_take() == []


def test_python_reference_keeps_its_object_alive(calls):
    with eq.scope():
        eq.post(eq.FIRE_SOUND, _bank("Held"))
        gc.collect()
    assert calls == [("play", "Held")]


def test_drop_without_the_rebind_binding_does_not_raise(monkeypatch):
    """A stale .so with no combat_effect_rebind: dropping a row (switch
    off) still works."""
    import types
    bank = _bank("A")
    stale = types.SimpleNamespace(combat_unregister=_h.combat_unregister)
    monkeypatch.setattr(nc, "_h", stale)
    nc._drop(bank)
    assert "_nslot" not in bank.__dict__


# ── Decision 13 ──────────────────────────────────────────────────────────────

class _Boom(Exception):
    pass


def _failing(monkeypatch, log, bad=("B", "C")):
    def play(self):
        if self.GetName() in bad:
            raise _Boom("bank " + self.GetName())
        log.append(self.GetName())
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)


def test_play_logs_a_failing_entry_and_carries_on(monkeypatch, caplog):
    log = []
    _failing(monkeypatch, log)
    monkeypatch.setattr(eq, "_strict", lambda: False)
    with caplog.at_level(logging.ERROR, logger=eq.__name__):
        with eq.scope():
            for name in "ABCD":
                eq.post(eq.FIRE_SOUND, _bank(name))
    assert log == ["A", "D"]
    assert eq.counts() == {"delivered": 4, "skipped_gone": 0,
                           "failed": 2, "damage": 0}
    msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(msgs) == 2 and "FIRE_SOUND" in msgs[0].getMessage()
    assert _h.combat_effect_take() == []


def test_strict_delivers_the_rest_then_raises_the_first(monkeypatch):
    log = []
    _failing(monkeypatch, log)
    monkeypatch.setattr(eq, "_strict", lambda: True)
    with pytest.raises(_Boom) as info:
        with eq.scope():
            for name in "ABCD":
                eq.post(eq.FIRE_SOUND, _bank(name))
    assert log == ["A", "D"]
    assert str(info.value) == "bank B"
    notes = getattr(info.value, "__notes__", [])
    assert len(notes) == 1 and "bank C" in notes[0], notes
    assert eq.counts()["failed"] == 2
    assert _h.combat_effect_take() == []
    assert not eq.deferring()


def test_strict_under_pytest_or_developer(monkeypatch):
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    assert eq._strict(modules={"pytest": object()})
    assert not eq._strict(modules={})
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    assert eq._strict(modules={})


# ── A native session ends (Task 3's hook) ───────────────────────────────────

def _session(appends, monkeypatch, log):
    """Bank A's sound delivery runs a 'native session': it appends kernel
    entries (the test binding) and ends with session_ended()."""
    def play(self):
        log.append(("play", self.GetName()))
        if self.GetName() == "A":
            for h in appends:
                _post_native(eq.FIRE_SOUND, h)
            eq.session_ended()
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)


def test_a_session_started_by_a_delivery_delivers_at_its_end(monkeypatch):
    """A handler (A's delivery) starts a native session appending B: B is
    delivered when that session ends, inside the handler -- before C, as
    the Python reference's producers would have acted -- not after the
    outer batch."""
    log = []
    a, b, c = _bank("A"), _bank("B"), _bank("C")
    _session([b.__dict__["_nslot"]], monkeypatch, log)
    with eq.scope():
        eq.post(eq.FIRE_SOUND, a)
        eq.post(eq.FIRE_SOUND, c)
    assert log == [("play", "A"), ("play", "B"), ("play", "C")]
    assert _h.combat_effect_take() == []


def test_a_nested_session_error_is_raised_by_the_outermost_flush(
        monkeypatch):
    """Decision 13 is applied once, at the outermost flush: a failing entry
    of the nested session's does not stop C, and is raised after it."""
    log = []
    a, b, c = _bank("A"), _bank("B"), _bank("C")
    _session([b.__dict__["_nslot"]], monkeypatch, log)
    play = ws._EnergyWeaponFireMixin._play_fire_sfx

    def failing(self):
        if self.GetName() == "B":
            raise _Boom("nested")
        play(self)
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", failing)
    monkeypatch.setattr(eq, "_strict", lambda: True)
    with pytest.raises(_Boom, match="nested"):
        with eq.scope():
            eq.post(eq.FIRE_SOUND, a)
            eq.post(eq.FIRE_SOUND, c)
    assert log == [("play", "A"), ("play", "C")]
    assert eq.counts()["failed"] == 1


def test_session_ended_inside_the_scope_waits_for_the_boundary(calls):
    b = _bank("B")
    with eq.scope():
        _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
        eq.session_ended()
        assert calls == []
    assert calls == [("play", "B")]


def test_session_ended_outside_the_scope_delivers_now(calls):
    b = _bank("B")
    _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
    eq.session_ended()
    assert calls == [("play", "B")]


# ── A native session's own deferral (ruling F3) ─────────────────────────────
# A K1 session that begins while nothing defers (an AI's StartFiring from
# gl.ai, one a delivery's handler starts) opens its own deferral: every
# producer appends while it runs, native and Python alike, and its end
# delivers -- one emission order per session, no loop stopped before it
# plays.

def test_a_session_defers_every_producer_until_it_ends(calls, events):
    a, b, t = _bank("A"), _bank("B"), _bank("T")
    assert not eq.deferring()
    with eq.session():
        assert eq.deferring()
        _post_native(eq.FIRE_SOUND, a.__dict__["_nslot"])
        b._firing = True
        b.StopFiring()                      # a Python producer: queued
        ws._post_weapon_fired(b, t)
        assert calls == [] and events == []
    assert not eq.deferring()
    assert calls == [("play", "A"), ("stop", "B")]
    assert [(e[0], e[1], e[3]) for e in events] == [
        (App.ET_WEAPON_FIRED, b, t)]
    assert _h.combat_effect_take() == []


def test_a_session_inside_the_scope_leaves_delivery_to_the_boundary(calls):
    a = _bank("A")
    with eq.scope():
        with eq.session():
            _post_native(eq.FIRE_SOUND, a.__dict__["_nslot"])
        assert calls == [] and eq.deferring()
    assert calls == [("play", "A")]


def test_a_session_inside_a_session_delivers_at_the_outer_end(calls):
    a, b = _bank("A"), _bank("B")
    with eq.session():
        _post_native(eq.FIRE_SOUND, a.__dict__["_nslot"])
        with eq.session():
            _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
        assert calls == []
    assert calls == [("play", "A"), ("play", "B")]


def test_a_session_started_by_a_delivery_defers_then_delivers_nested(
        monkeypatch):
    """Inside a delivery nothing defers (the drain acts at once), so a
    session a handler starts opens its own deferral: its native AND Python
    entries wait for its end, then are delivered there, nested -- before C,
    in emission order."""
    log = []
    a, b, c, d = _bank("A"), _bank("B"), _bank("C"), _bank("D")

    def play(self):
        log.append(("play", self.GetName(), eq.deferring()))
        if self.GetName() == "A":
            with eq.session():
                assert eq.deferring()
                _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
                eq.post(eq.FIRE_SOUND, d)       # Python: queued too
                assert len(log) == 1        # nothing delivered mid-session
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)
    with eq.scope():
        eq.post(eq.FIRE_SOUND, a)
        eq.post(eq.FIRE_SOUND, c)
    assert log == [("play", "A", False), ("play", "B", False),
                   ("play", "D", False), ("play", "C", False)]
    assert _h.combat_effect_take() == []


def test_a_raising_session_still_delivers_and_keeps_its_error(calls):
    a = _bank("A")
    with pytest.raises(KeyError):
        with eq.session():
            _post_native(eq.FIRE_SOUND, a.__dict__["_nslot"])
            raise KeyError("session")
    assert calls == [("play", "A")]
    assert not eq.deferring()


def test_reset_closes_an_open_session(calls):
    with eq.session():
        _post_native(eq.FIRE_SOUND, _bank("A").__dict__["_nslot"])
        nc.reset()
        assert not eq.deferring()
    assert calls == []
    assert not eq.deferring()


# ── The tick raised ──────────────────────────────────────────────────────────

def test_a_raising_tick_keeps_its_error_and_notes_the_delivery_errors(
        monkeypatch):
    log = []
    _failing(monkeypatch, log, bad=("B", "C"))
    monkeypatch.setattr(eq, "_strict", lambda: True)
    with pytest.raises(KeyError) as info:
        with eq.scope():
            for name in "ABCD":
                eq.post(eq.FIRE_SOUND, _bank(name))
            raise KeyError("tick")
    assert log == ["A", "D"]
    notes = info.value.__notes__
    assert len(notes) == 2, notes
    assert "_Boom: bank B" in notes[0] and "bank C" in notes[1], notes


# ── Dropping entries ─────────────────────────────────────────────────────────
# Only native_combat.reset() drops queued entries (combat_effect_clear): an
# abandoned kernel session no longer does (ruling F5), so the queue has no
# mark / truncate.

def test_clear_releases_the_dropped_references():
    import weakref
    bank = _bank("Dropped")
    _free(bank)
    ref = weakref.ref(bank)
    eq.post(eq.FIRE_SOUND, bank)
    del bank
    gc.collect()
    assert ref() is not None            # the queue holds it
    _h.combat_effect_clear()
    gc.collect()
    assert ref() is None


def test_reset_clears_the_queue_and_the_scope(calls):
    """native_combat.reset() drops what is queued, undelivered, and closes
    the scope; the scope it closed exits doing nothing."""
    with eq.scope():
        eq.post(eq.FIRE_SOUND, _bank("A"))
        nc.reset()
        assert not eq.deferring()
        assert _h.combat_effect_take() == []
        assert eq.counts() == {"delivered": 0, "skipped_gone": 0,
                               "failed": 0, "damage": 0}
        with eq.scope():                    # a fresh one opens and flushes
            eq.post(eq.FIRE_SOUND, _bank("B"))
        assert calls == [("play", "B")]
    assert not eq.deferring() and eq._depth == 0
    with eq.scope():
        assert eq.deferring()
    assert calls == [("play", "B")]


# ── The producers ────────────────────────────────────────────────────────────

def _deferred(fn, *args):
    """Run fn inside a scope; return (entries queued before the flush)."""
    with eq.scope():
        fn(*args)
        taken = _h.combat_effect_take()
        for kind, native, ops in taken:      # put them back, as they were
            assert not native
            eq.post(kind, *ops)
    return [(k, ops) for k, _n, ops in taken]


def _beam_edge(bank, target):
    """A beam's was-not-firing edge as its producer makes it -- the K1
    kernel since fire control went native only (M3; k1_fire_control.h, THE
    EFFECT QUEUE): its writes, then its fire sound, queued while the queue
    defers, played at once otherwise (the deleted Python _fire_effect's
    order). These tests are the queue's; the kernel's edge is
    K1Native.BeamEdgeIsLoggedWritesAndEntries."""
    bank._firing = True
    bank._target = target
    if eq.deferring():
        eq.post(eq.FIRE_SOUND, bank)
    else:
        bank._play_fire_sfx()
    return True


def test_fire_sound_is_queued_on_the_edge(calls):
    bank, target = _bank("A"), _bank("T")
    q = _deferred(_beam_edge, bank, target)
    assert q == [(eq.FIRE_SOUND, (bank,))]
    assert calls == [("play", "A")]
    assert bank._firing is True and bank._target is target


def test_loop_stop_is_queued_for_a_firing_bank_without_a_handle_yet(calls):
    """Review Focus 1: fired and stopped in one tick -- the loop handle
    does not exist yet when StopFiring runs, so the stop must still be
    queued, and delivery plays then stops."""
    bank, target = _bank("A"), _bank("T")
    with eq.scope():
        _beam_edge(bank, target)
        bank.StopFiring()
        assert bank._firing is False and calls == []
    assert calls == [("play", "A"), ("stop", "A")]


def test_loop_stop_skipped_for_a_bank_not_firing(calls):
    bank = _bank("A")
    assert _deferred(bank.StopFiring) == []


def test_stop_loop_sound_stops_and_clears_the_handle():
    stopped = []

    class Handle:
        def Stop(self):
            stopped.append(1)
    bank = _bank("A")
    bank._loop_handle = Handle()
    bank._stop_loop_sound()
    assert stopped == [1] and bank._loop_handle is None
    bank._stop_loop_sound()                 # no handle: nothing
    assert stopped == [1]


def test_stop_firing_outside_the_scope_stops_at_once():
    stopped = []

    class Handle:
        def Stop(self):
            stopped.append(1)
    bank = _bank("A")
    bank._firing = True
    bank._loop_handle = Handle()
    bank.StopFiring()
    assert stopped == [1] and bank._loop_handle is None


def test_stopping_a_loop_that_played_before_the_scope_stops_it_once():
    stopped = []

    class Handle:
        def Stop(self):
            stopped.append(eq._draining)
    bank = _bank("A")
    bank._firing = True
    bank._loop_handle = Handle()
    with eq.scope():
        bank.StopFiring()
        assert stopped == [] and bank._firing is False
    assert stopped == [True] and bank._loop_handle is None


def test_tube_producers_are_queued(events, monkeypatch):
    tube, torp = ws.TorpedoTube("Tube"), ws.PhaserBank("Torp")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: None)
    assert _deferred(tube._broadcast_weapon_fire_failed) == [
        (eq.WEAPON_FIRE_FAILED, (tube,))]
    assert _deferred(tube._broadcast_torpedo_fired, torp) == [
        (eq.TORPEDO_FIRED, (tube, torp))]
    assert _deferred(tube._broadcast_ammo_consumed_if_player) == [
        (eq.AMMO_CONSUMED, (tube,))]
    assert _deferred(tube._broadcast_reload) == [
        (eq.TORPEDO_RELOAD, (tube,))]
    assert [e[0] for e in events] == [
        App.ET_WEAPON_FIRE_FAILED, App.ET_TORPEDO_FIRED,
        App.ET_TORPEDO_RELOAD]          # no player: no ammo event
    assert events[1][1] is torp and events[1][2] is tube


def test_ammo_consumed_reads_the_player_gate_at_delivery(events,
                                                         monkeypatch):
    """The gate (is the firing ship the player?) is read when the entry is
    delivered, not when it is queued."""
    tube, ship = ws.TorpedoTube("Tube"), _bank("Ship")
    monkeypatch.setattr(tube, "_climb_to_ship", lambda: ship, raising=False)
    player = [None]
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player[0])
    with eq.scope():
        tube._broadcast_ammo_consumed_if_player()   # not the player yet
        player[0] = ship
    assert [(e[0], e[1], e[2]) for e in events] == [
        (App.ET_TORPEDO_AMMO_CONSUMED, tube, ship)]
    events.clear()
    with eq.scope():
        tube._broadcast_ammo_consumed_if_player()   # the player now...
        player[0] = None                            # ...not at delivery
    assert events == []


def test_cant_fire_posted_while_deferring_raises_when_strict(events,
                                                            monkeypatch):
    """ET_CANT_FIRE is ET_WEAPON_FIRE_FAILED, posted directly by design
    (StartFiring, outside any deferral): an in-scope post raises under
    tests / --developer, posts in play, and posts outside as before."""
    system = ws.TorpedoSystem("Torps")
    system._post_cant_fire()
    assert [e[0] for e in events] == [App.ET_CANT_FIRE]
    with pytest.raises(AssertionError, match="ET_CANT_FIRE"):
        with eq.scope():
            system._post_cant_fire()
    monkeypatch.setattr(eq, "_strict", lambda: False)
    with eq.scope():
        system._post_cant_fire()
    assert [e[0] for e in events] == [App.ET_CANT_FIRE] * 2


def test_tube_producers_act_at_once_outside(events):
    tube = ws.TorpedoTube("Tube")
    tube._broadcast_weapon_fire_failed()
    tube._broadcast_reload()
    assert [e[0] for e in events] == [App.ET_WEAPON_FIRE_FAILED,
                                      App.ET_TORPEDO_RELOAD]


# ── The charge watcher ───────────────────────────────────────────────────────

def _watched(owner=True):
    fired = []

    class Evt:
        def SetFloat(self, v):
            self.v = v

    class Mgr:
        def AddEvent(self, evt):
            fired.append((evt.name, evt.v))

    w = FloatRangeWatcher(1.0, event_manager=Mgr(),
                          owner=ws.PulseWeapon("P") if owner else None)
    return w, fired, Evt


def _check(w, Evt, name, threshold, direction):
    e = Evt()
    e.name = name
    return w.AddRangeCheck(threshold, direction, e)


def test_watcher_commits_at_once_and_fires_at_delivery():
    w, fired, Evt = _watched()
    _check(w, Evt, "below", 0.5, FloatRangeWatcher.FRW_BELOW)
    with eq.scope():
        w._update(0.25)
        assert w.GetWatchedVariable() == 0.25
        assert fired == []
        taken = _h.combat_effect_take()
        assert [(k, ops) for k, _n, ops in taken] == [
            (eq.WATCH, (w, 1.0, 0.25))]
        eq.post(eq.WATCH, w, 1.0, 0.25)
    assert fired == [("below", 0.25)]


def test_watcher_delivery_uses_the_checks_registered_at_delivery():
    w, fired, Evt = _watched()
    gone = _check(w, Evt, "gone", 0.5, FloatRangeWatcher.FRW_BELOW)
    with eq.scope():
        w._update(0.25)
        w.RemoveRangeCheck(gone)
        _check(w, Evt, "added", 0.75, FloatRangeWatcher.FRW_BELOW)
    assert fired == [("added", 0.25)]


def test_watcher_without_checks_queues_nothing():
    w, fired, Evt = _watched()
    with eq.scope():
        w._update(0.25)
        assert _h.combat_effect_take() == []
    assert w.GetWatchedVariable() == 0.25


def test_unowned_watcher_acts_at_once():
    """Only a weapon's charge watcher is queued (§4.2 WATCH); a shield,
    condition or battery watcher fires where it is pushed, as today."""
    w, fired, Evt = _watched(owner=False)
    _check(w, Evt, "below", 0.5, FloatRangeWatcher.FRW_BELOW)
    with eq.scope():
        w._update(0.25)
        assert fired == [("below", 0.25)]
        assert _h.combat_effect_take() == []


def test_two_crossings_in_one_tick_fire_in_order():
    """1.0 -> 0.25 -> 0.9 inside one scope: below@0.25, then above@0.9."""
    w, fired, Evt = _watched()
    _check(w, Evt, "below", 0.5, FloatRangeWatcher.FRW_BELOW)
    _check(w, Evt, "above", 0.5, FloatRangeWatcher.FRW_ABOVE)
    with eq.scope():
        w._update(0.25)
        w._update(0.9)
        assert fired == [] and w.GetWatchedVariable() == 0.9
    assert fired == [("below", 0.25), ("above", 0.9)]


def test_native_watch_names_the_weapon(monkeypatch):
    """A kernel's WATCH carries the weapon's handle: delivery fires its
    charge watcher's checks crossed between the two values."""
    fired = []

    class Evt:
        def SetFloat(self, v):
            self.v = v
    cannon = ws.PulseWeapon("P")
    watcher = cannon.GetChargeWatcher()

    class Mgr:
        def AddEvent(self, evt):
            fired.append(evt.v)
    watcher._event_manager = Mgr()
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_ABOVE, Evt())
    with eq.scope():
        _post_native(eq.WATCH, cannon.__dict__["_nslot"], 0.25, 0.75)
    assert fired == [0.75]


# ── SPAWN: a launch's spawn at the boundary (spec 2026-11-02-combat-launch-
# deferral §4.1) ─────────────────────────────────────────────────────────────

def _spawn_scene():
    """A ship in a set with a tube, its ammo type naming the stock photon,
    and a target: the objects a kernel SPAWN names."""
    from engine.appc.math import TGPoint3  # noqa: F401
    kset = App.SetClass_Create()
    App.g_kSetManager.AddSet(kset, "eq_spawn")
    ship = App.ShipClass_Create("Launcher")
    target = App.ShipClass_Create("Target")
    kset.AddObjectToSet(ship, "Launcher")
    kset.AddObjectToSet(target, "Target")
    tube = ws.TorpedoTube("Tube")
    ammo = ws.TorpedoAmmoType("Photon", script="Tactical.Projectiles."
                              "PhotonTorpedo")
    return kset, ship, target, tube, ammo


def _h_of(obj):
    return obj.__dict__["_nslot"]


def _module(name):
    """A stock projectile module: a SPAWN carries the module itself (the one
    its launch resolved, held from fire time)."""
    import importlib
    return importlib.import_module("Tactical.Projectiles." + name)


def _photon():
    return _module("PhotonTorpedo")


def test_spawn_builds_the_torpedo_from_its_record(events):
    """SPAWN(tube, kind, ship, set, ammo, target, position, velocity,
    offset, drf): the delivery builds the torpedo through the shared
    spawn path with the RECORD's values (none read live), registers it
    (ET_TORPEDO_ENTERED_SET) and then posts its ET_TORPEDO_FIRED."""
    from engine.appc import projectiles
    kset, ship, target, tube, ammo = _spawn_scene()
    events.clear()                  # the scene's own set entries
    try:
        before = list(projectiles._active)
        with eq.scope():
            _post_native(eq.SPAWN, _h_of(tube), 0.0, _h_of(ship),
                         _h_of(kset), _photon(), _h_of(target),
                         1.0, 2.0, 3.0, 1.0, 4.0, 5.0, 6.0,
                         1.0, 0.125, -0.25, 0.5, 0.25, 1.0, -1)
            assert events == []
        new = [t for t in projectiles._active if t not in before]
        assert len(new) == 1
        torp = new[0]
        p = torp.GetTranslate()
        assert (p.x, p.y, p.z) == (1.0, 2.0, 3.0)
        v = torp._velocity
        assert (v.x, v.y, v.z) == (4.0, 5.0, 6.0)
        assert torp._source_ship is ship
        assert torp._target_ship is target
        o = torp._target_offset
        assert (o.x, o.y, o.z) == (0.125, -0.25, 0.5)
        assert torp._damage_radius_factor == 0.25   # the launcher's override
        assert torp._damage == 500.0                 # PhotonTorpedo.Create
        assert torp.GetContainingSet() is kset
        assert [(e[0], e[1], e[2]) for e in events] == [
            (App.ET_TORPEDO_ENTERED_SET, torp, torp),
            (App.ET_TORPEDO_FIRED, torp, tube)]
        assert eq.counts() == {"delivered": 1, "skipped_gone": 0,
                               "failed": 0, "damage": 0}
    finally:
        for t in list(projectiles._active):
            if t not in before:
                projectiles.expire(t)
        App.g_kSetManager.DeleteSet("eq_spawn")


def test_spawn_without_velocity_offset_or_override(events):
    """No velocity (the direction had no length), no offset (a target only)
    and no launcher override: the torpedo keeps its own defaults there, as
    _spawn_projectile leaves them."""
    from engine.appc import projectiles
    kset, ship, target, tube, ammo = _spawn_scene()
    try:
        before = list(projectiles._active)
        with eq.scope():
            _post_native(eq.SPAWN, _h_of(tube), 2.0, _h_of(ship),
                         _h_of(kset), _photon(), -1,
                         1.0, 2.0, 3.0, 0.0, 9.0, 9.0, 9.0,
                         0.0, 9.0, 9.0, 9.0, 0.0, 1.0, -1)
        (torp,) = [t for t in projectiles._active if t not in before]
        v = torp._velocity
        assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
        assert torp._target_ship is None
        assert torp._target_offset is None
        assert torp._damage_radius_factor == 0.13   # PhotonTorpedo.Create
    finally:
        for t in list(projectiles._active):
            if t not in before:
                projectiles.expire(t)
        App.g_kSetManager.DeleteSet("eq_spawn")


def test_pulse_spawn_scales_its_bolt_then_reports_the_shot(events,
                                                          monkeypatch):
    """A pulse's SPAWN (ruling L5): the bolt is built and registered (its
    ET_TORPEDO_ENTERED_SET handlers see the module's damage), THEN scaled
    by the fire-time power setting's GetDamageScale, as PulseWeapon's
    effect does; then the shot's ET_WEAPON_FIRED at the target it used,
    now that the bolt exists (M4). No ET_TORPEDO_FIRED: tubes only."""
    from engine.appc import projectiles
    kset, ship, target, cannon, ammo = _spawn_scene()
    seen = []
    orig = App.g_kEventManager.AddEvent

    def add(evt, _orig=orig):
        if evt.GetEventType() == App.ET_TORPEDO_ENTERED_SET:
            seen.append(evt.GetDestination()._damage)
        return _orig(evt)
    events.clear()
    try:
        before = list(projectiles._active)
        monkeypatch.setattr(App.g_kEventManager, "AddEvent", add)
        with eq.scope():
            _post_native(eq.SPAWN, _h_of(cannon), 1.0, _h_of(ship),
                         _h_of(kset), _module("Disruptor"), -1,
                         1.0, 2.0, 3.0, 1.0, 4.0, 5.0, 6.0,
                         0.0, 0.0, 0.0, 0.0, 0.0, 1.5, _h_of(target))
        (bolt,) = [t for t in projectiles._active if t not in before]
        import Tactical.Projectiles.Disruptor as mod
        assert seen == [float(mod.GetDamage())]
        assert bolt._damage == float(mod.GetDamage()) * 1.5
        assert bolt._is_disruptor
        assert [(e[0], e[1], e[3]) for e in events] == [
            (App.ET_TORPEDO_ENTERED_SET, bolt, None),
            (App.ET_WEAPON_FIRED, cannon, target)]
    finally:
        for t in list(projectiles._active):
            if t not in before:
                projectiles.expire(t)
        App.g_kSetManager.DeleteSet("eq_spawn")

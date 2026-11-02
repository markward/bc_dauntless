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
        ptr = evt.GetObjPtr() if hasattr(evt, "GetObjPtr") else None
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
    assert len(eq.KIND_NAMES) == 8


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
    assert eq.counts() == {"delivered": 5, "skipped_gone": 0, "failed": 0}
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


def test_host_loop_tick_runs_weapons_and_combat_inside_the_scope():
    """The sim tick opens the scope around sim.weapons and sim.combat."""
    import inspect
    src = inspect.getsource(host_loop.run)
    at = src.index("with _combat_effect_scope():")
    assert src.index('"sim.weapons"') > at
    assert src.index('"sim.combat"') > at


# ── Freed objects ────────────────────────────────────────────────────────────

def _free(obj):
    """Let `obj` go: the id registry holds every TGObject strongly."""
    from engine.core import ids
    ids.unregister(obj.GetObjID())


def test_freed_or_unregistered_handle_is_skipped_and_counted(calls):
    """A kernel entry naming an object freed, or unregistered (its row
    dropped), since it was queued is skipped and counted; the rest are
    delivered."""
    a, gone, dropped = _bank("A"), _bank("Gone"), _bank("Dropped")
    with eq.scope():
        _post_native(eq.FIRE_SOUND, gone.__dict__["_nslot"])
        _post_native(eq.FIRE_SOUND, dropped.__dict__["_nslot"])
        eq.post(eq.FIRE_SOUND, a)
        _free(gone)
        del gone
        gc.collect()
        nc._drop(dropped)
    assert calls == [("play", "A")]
    assert eq.counts() == {"delivered": 1, "skipped_gone": 2, "failed": 0}


def test_python_reference_keeps_its_object_alive(calls):
    with eq.scope():
        eq.post(eq.FIRE_SOUND, _bank("Held"))
        gc.collect()
    assert calls == [("play", "Held")]


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
    assert eq.counts() == {"delivered": 4, "skipped_gone": 0, "failed": 2}
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


# ── A kernel's abandon ───────────────────────────────────────────────────────

def test_truncate_drops_only_later_entries(calls):
    a, b, c = _bank("A"), _bank("B"), _bank("C")
    with eq.scope():
        eq.post(eq.FIRE_SOUND, a)
        m = _h.combat_effect_mark()
        _post_native(eq.FIRE_SOUND, b.__dict__["_nslot"])
        eq.post(eq.FIRE_SOUND, c)
        _h.combat_effect_truncate(*m)
    assert calls == [("play", "A")]


def test_a_mark_made_stale_by_a_take_truncates_nothing(calls):
    """A session's mark, then a flush delivering its entries (take), then
    later entries: the abandon must not drop those (counted instead)."""
    _h.combat_effect_reset_counts()
    a, b = _bank("A"), _bank("B")
    m = _h.combat_effect_mark()
    _post_native(eq.FIRE_SOUND, a.__dict__["_nslot"])
    eq.flush()
    with eq.scope():
        eq.post(eq.FIRE_SOUND, b)
        _h.combat_effect_truncate(*m)
    assert calls == [("play", "A"), ("play", "B")]
    assert _h.combat_effect_counts() == {"stale_truncates": 1}


def test_truncate_releases_the_dropped_references():
    import weakref
    bank = _bank("Dropped")
    _free(bank)
    ref = weakref.ref(bank)
    m = _h.combat_effect_mark()
    eq.post(eq.FIRE_SOUND, bank)
    del bank
    gc.collect()
    assert ref() is not None            # the queue holds it
    _h.combat_effect_truncate(*m)
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
                               "failed": 0}
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


def test_fire_sound_is_queued_on_the_edge(calls):
    bank, target = _bank("A"), _bank("T")
    q = _deferred(ws._EnergyWeaponFireMixin._fire_effect, bank, target, None,
                  (False,))
    assert q == [(eq.FIRE_SOUND, (bank,))]
    assert calls == [("play", "A")]
    assert bank._firing is True and bank._target is target


def test_loop_stop_is_queued_for_a_firing_bank_without_a_handle_yet(calls):
    """Review Focus 1: fired and stopped in one tick -- the loop handle
    does not exist yet when StopFiring runs, so the stop must still be
    queued, and delivery plays then stops."""
    bank, target = _bank("A"), _bank("T")
    with eq.scope():
        ws._EnergyWeaponFireMixin._fire_effect(bank, target, None, (False,))
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

"""The native shield piece (phase 6 A1, Task 3; subsystem_step.h THE SHIELD
PIECE): the shield generator's per-tick regen, native only since Task 8
(there is no Python copy), its watcher crossings handed back to Python as
EVENT records. The goldens pin it bit for bit; these pin the pieces of the
contract one at a time.
"""
import random

import App
import pytest

from engine.appc import native_combat as nc
from engine.appc import native_subsystems, subsystems
from engine.appc.ship_iter import iter_non_rock_ships
from engine.core import loop as game_loop
from tests.helpers import bc_assets, headless_mission

CHARGE_TICK = 31        # `a = a + 1/60` first reaches 0.5 on tick 31


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()


def _world(mp):
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    ships = list(iter_non_rock_ships())
    assert len(ships) == 3
    return ships


def _tick(n=1):
    for _ in range(n):
        App.g_kTimerManager._time += game_loop.TICK_DELTA
        game_loop._update_ship_subsystems()


def _faces(ship):
    return [float(x).hex() for x in ship.GetShields()._current_shields]


def _no_skips():
    """Every piece ran: none was skipped (subsystem_step.h THE SKIPS)."""
    assert native_subsystems.skip_counts() == {}


def test_sdk_set_charge_per_second_reaches_the_native_step():
    """Review Focus 2: an SDK ``SetShieldChargePerSecond`` on the generator
    mid-run is what the next native charge uses -- the in-place write
    pushes the rates."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        native_subsystems.reset_counts()
        target = ships[1].GetShields()
        for f in range(6):
            target.SetCurShields(f, target.GetMaxShields(f) * 0.25)
        base = target.GetMaxShields(2) * 0.25
        _tick(10)
        # The SDK's own call (App.ShieldClass is ShieldSubsystem).
        App.ShieldClass.SetShieldChargePerSecond(target, 2, 40.0)
        target.SetShieldChargePerSecond(4, 0.0)
        _tick(CHARGE_TICK - 10)
        counts = native_subsystems.counts()
    # The new rates are the ones that charged: face 2 at 40/s, face 4 not
    # at all, over the 0.5 s carry.
    accum = 0.0
    for _ in range(CHARGE_TICK):
        accum = accum + game_loop.TICK_DELTA
    want2 = min(base + 40.0 * accum, target.GetMaxShields(2))
    assert target.GetCurrentShields(2) == want2
    assert target.GetCurrentShields(4) == target.GetMaxShields(4) * 0.25
    assert counts["stages"] == CHARGE_TICK
    _no_skips()


def test_a_crossing_fires_mid_stage_through_the_watchers_own_update():
    """A range check the regen crosses: the native piece stops at that
    watcher, Python's `_update` fires the SDK event with the value the
    piece computed, and the walk resumes after it: when watcher 1 fires,
    watcher 0 already holds its new value and 2..6 their old ones."""
    def run():
        fired = []
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp)
            native_subsystems.reset_counts()
            shields = ships[0].GetShields()
            for f in range(6):
                shields.SetCurShields(f, shields.GetMaxShields(f) * 0.4999)
            mgr = App.g_kEventManager
            orig = mgr.AddEvent

            def add_event(evt, _orig=orig):
                if evt.GetEventType() == et:
                    fired.append((evt.GetFloat().hex(),
                                  [w._value.hex()
                                   for w in shields._shield_watchers]))
                return _orig(evt)

            et = App.Game_GetNextEventType()
            mp.setattr(mgr, "AddEvent", add_event)
            for face in (1, 6):
                evt = App.TGFloatEvent_Create()
                evt.SetEventType(et)
                evt.SetSource(shields)
                shields.GetShieldWatcher(face).AddRangeCheck(
                    0.5, App.FloatRangeWatcher.FRW_ABOVE, evt)
            before = [w._value.hex() for w in shields._shield_watchers]
            _tick(CHARGE_TICK)
            values = [w._value.hex() for w in shields._shield_watchers]
            return fired, before, values, native_subsystems.counts()

    fired, before, values, counts = run()
    assert len(fired) == 2, fired
    # Watcher 1 fires with the value it then commits; watcher 0 holds its
    # new value, 2..6 their old ones (the walk stopped at 1).
    value, snapshot = fired[0]
    assert value == values[1]
    assert snapshot[0] == values[0]
    assert snapshot[2:] == before[2:]
    # Watcher 6 (the combined one) fires after all six faces committed.
    value6, snapshot6 = fired[1]
    assert value6 == values[6] and snapshot6[:6] == values[:6]
    assert counts["events"] == 2, counts
    _no_skips()


def test_a_patched_method_is_not_honoured():
    """Spec §3 "Mods and patches (Part A)": BC's per-tick update was
    internal C++ that ignored a script's patch of an App method, and so is
    the native stage -- a patched `_is_offline` is never called by it."""
    with pytest.MonkeyPatch.context() as mp:
        _world(mp)
        calls = []
        mp.setattr(subsystems, "_is_offline",
                   lambda sub: calls.append(("offline", sub)) or True)
        native_subsystems.reset_counts()
        _tick(CHARGE_TICK)
    assert calls == []
    _no_skips()


def test_the_mirror_agrees_after_native_charges():
    """The mirror audit (native_combat.audit_mirror) after native charges,
    a crossing and SDK writes: every shield field and the watcher state
    match their Python objects."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        shields = ships[0].GetShields()
        evt = App.TGFloatEvent_Create()
        evt.SetEventType(App.Game_GetNextEventType())
        evt.SetSource(shields)
        shields.GetShieldWatcher(0).AddRangeCheck(
            0.5, App.FloatRangeWatcher.FRW_BOTH, evt)
        shields.SetCurShields(0, shields.GetMaxShields(0) * 0.49)
        _tick(CHARGE_TICK + 5)
        ships[1].GetShields().SetShieldChargePerSecond(3, 1.5)
        _tick(40)
        nc._failures.clear()
        nc.audit_mirror()
        bad = [f for f in nc.audit_failures()
               if f[0] == "ShieldSubsystem"]
    assert bad == []

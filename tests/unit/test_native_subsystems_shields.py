"""The native shield piece (phase 6 A1, Task 3; subsystem_step.h THE SHIELD
PIECE): ``ShieldSubsystem.Update`` run natively by the subsystem stage, bit
for bit, its watcher crossings handed back to Python as EVENT records.

The per-tick state differential against the Python stage is
tests/integration/test_native_subsystems_differential.py; these pin the
pieces of the contract one at a time.
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


def _world(mp, native):
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1",
                  "DAUNTLESS_NATIVE_SUBSYSTEMS": "1" if native else "0"})
    assert native_subsystems.enabled() is native
    ships = list(iter_non_rock_ships())
    assert len(ships) == 3
    return ships


def _tick(n=1):
    for _ in range(n):
        App.g_kTimerManager._time += game_loop.TICK_DELTA
        game_loop._update_ship_subsystems()


def _faces(ship):
    return [float(x).hex() for x in ship.GetShields()._current_shields]


def _shield_records_python(counts, ships, stages):
    """How many SHIELD pieces ran as RUN_PYTHON records: cloak, repair and
    articulation are always RUN_PYTHON (Tasks 5-6), one record each per
    ship; power is native too (Task 4)."""
    return counts["run_python"] - 3 * ships * stages


def test_sdk_set_charge_per_second_reaches_the_native_step():
    """Review Focus 2: an SDK ``SetShieldChargePerSecond`` on the generator
    mid-run is what the next native charge uses -- the in-place write
    pushes the rates -- bit for bit what the Python stage does."""
    def run(native):
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
            native_subsystems.reset_counts()
            target = ships[1].GetShields()
            for f in range(6):
                target.SetCurShields(f, target.GetMaxShields(f) * 0.25)
            _tick(10)
            # The SDK's own call (App.ShieldClass is ShieldSubsystem).
            App.ShieldClass.SetShieldChargePerSecond(target, 2, 40.0)
            target.SetShieldChargePerSecond(4, 0.0)
            _tick(CHARGE_TICK - 10)
            counts = native_subsystems.counts()
            return ([_faces(s) for s in ships],
                    target.GetMaxShields(2) * 0.25, target, counts)

    py_faces, base, _t, _c = run(False)
    na_faces, _base, target, counts = run(True)
    assert na_faces == py_faces
    # The new rates are the ones that charged: face 2 at 40/s, face 4 not
    # at all, over the 0.5 s carry.
    accum = 0.0
    for _ in range(CHARGE_TICK):
        accum = accum + game_loop.TICK_DELTA
    want2 = min(base + 40.0 * accum, target.GetMaxShields(2))
    assert target.GetCurrentShields(2) == want2
    assert target.GetCurrentShields(4) == target.GetMaxShields(4) * 0.25
    # ... and the native piece did it: no shield piece came back to Python.
    assert counts["stages"] == CHARGE_TICK
    assert _shield_records_python(counts, 3, CHARGE_TICK) == 0, counts


def test_a_crossing_fires_mid_stage_through_the_watchers_own_update():
    """A range check the regen crosses: the native piece stops at that
    watcher, Python's `_update` fires the SDK event with the value the
    Python piece would have computed, and the walk resumes after it."""
    def run(native):
        fired = []
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
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
            _tick(CHARGE_TICK)
            values = [w._value.hex() for w in shields._shield_watchers]
            return fired, values, native_subsystems.counts()

    py_fired, py_values, _ = run(False)
    na_fired, na_values, counts = run(True)
    assert len(py_fired) == 2, py_fired
    # Same value, same moment: when watcher 1 fires, watcher 0 holds its
    # new value and 1..6 their old ones, in both stages.
    assert na_fired == py_fired
    assert na_values == py_values
    assert counts["events"] == 2, counts


def test_python_pieces_hands_every_shield_piece_to_python():
    """The test-facing hook: with SHIELD in ``python_pieces`` every ship's
    shield piece comes back as a RUN_PYTHON record (ShieldSubsystem.Update
    runs), and the state is bit for bit the native piece's."""
    def run(hook):
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, True)
            mp.setattr(native_subsystems, "python_pieces",
                       (1 << native_subsystems.SHIELD) if hook else 0)
            native_subsystems.reset_counts()
            for f in range(6):
                ships[0].GetShields().SetCurShields(f, 100.0)
            _tick(CHARGE_TICK + 31)
            return ([_faces(s) for s in ships],
                    [s.GetShields()._charge_accum.hex() for s in ships],
                    native_subsystems.counts())

    na_faces, na_accum, na_counts = run(False)
    py_faces, py_accum, py_counts = run(True)
    ticks = CHARGE_TICK + 31
    assert _shield_records_python(na_counts, 3, ticks) == 0, na_counts
    assert _shield_records_python(py_counts, 3, ticks) == 3 * ticks
    assert (py_faces, py_accum) == (na_faces, na_accum)


def test_a_patched_method_is_not_honoured():
    """Spec §3 "Mods and patches (Part A)": BC's per-tick update was
    internal C++ that ignored a script's patch of an App method, and so is
    the native piece -- a patched `_is_offline` or Update is never called
    by the stage."""
    with pytest.MonkeyPatch.context() as mp:
        _world(mp, True)
        calls = []
        mp.setattr(subsystems, "_is_offline",
                   lambda sub: calls.append(("offline", sub)) or True)
        mp.setattr(subsystems.ShieldSubsystem, "Update",
                   lambda self, dt: calls.append(("update", self)))
        native_subsystems.reset_counts()
        _tick(CHARGE_TICK)
        counts = native_subsystems.counts()
    # The power plant's Python Update still asks _is_offline; no shield
    # generator is ever asked, and no Update was called.
    from engine.appc.subsystems import ShieldSubsystem
    assert [c for c in calls if c[0] == "update"
            or isinstance(c[1], ShieldSubsystem)] == []
    assert _shield_records_python(counts, 3, CHARGE_TICK) == 0, counts


def test_the_mirror_agrees_after_native_charges():
    """The mirror audit (native_combat.audit_mirror) after native charges,
    a crossing and SDK writes: every shield field and the watcher state
    match their Python objects."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp, True)
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

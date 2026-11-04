"""Kernel M driving the motion stage against the Python stage, on random
scripted ships (native motion phase 2, Task 5).

40 seeds x 180 ticks: 10 asset-free ships in one set -- nine with an impulse
engine of 3 pods (as test_impulse_degradation_motion._galaxy) and one bare
ship (no engine). Every tick a few random beats hit random ships: SetSpeed
in both frames (negative, above the cap, one NaN per seed),
SetTargetAngularVelocityDirect, CompleteStop, `_speed_setpoint = None`, a pod's
SetCondition and SetDisabledPercentage, the engine's TurnOff / TurnOn and
SetPowerPercentageWanted, SetStatic, SetStationary, SetVelocity and
SetAngularVelocity in both spaces, a pod's and the engine's `_radiation_out`,
SetDying, and the current player moved between ships. Ships sit both near the
origin (where a mis-ordered product in the translate survives the add) and
thousands of GU out; rates are large and small, and the stage's dt is long or
short, tick by tick, all in the same scene.

Each seed runs fresh with the switch on, then off; the per-tick
golden_fight._pose_rows + motion_fight.motion_rows must be equal, and the
native arm hands no row to Python.
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import native_motion as nm  # noqa: E402
from engine.appc import ship_motion  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass, ShipClass_Create  # noqa: E402
from engine.appc.subsystems import ShipSubsystem  # noqa: E402
from engine.core.game import _set_current_game  # noqa: E402
from tests.helpers import golden_fight, motion_fight  # noqa: E402

SEEDS = range(20261104, 20261104 + 40)
TICKS = 180
SHIPS = 10
MODEL, WORLD = 0, 1
POD_MAX_CONDITION = 2600.0
#: The stage's dt, drawn per tick: the loop's own, a long hitch, tiny.
DTS = (1.0 / 60.0, 1.0 / 60.0, 1.0 / 60.0, 1.0 / 30.0, 0.25, 0.7,
       1.0 / 240.0)


@pytest.fixture(autouse=True)
def _clean():
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    nc.reset()
    nc.configure({})
    yield
    App.g_kSetManager._sets.clear()
    nc.reset()
    _set_current_game(None)


def _galaxy(name):
    ship = ShipClass_Create(name)
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    for i in range(3):
        pod = ShipSubsystem("pod%d" % i)
        pod.SetMaxCondition(POD_MAX_CONDITION)
        ies.AddChildSubsystem(pod)
    return ship


def _vec(rng, scale):
    return TGPoint3(rng.uniform(-scale, scale), rng.uniform(-scale, scale),
                    rng.uniform(-scale, scale))


def _position(rng, i):
    """Half the ships near the origin, half thousands of GU out."""
    if i % 2 == 0:
        return _vec(rng, 0.05)
    return _vec(rng, 6000.0)


def _build(rng):
    pSet = App.SetClass_Create()
    pSet.SetName("Diff")
    App.g_kSetManager._sets["Diff"] = pSet
    ships = []
    for i in range(SHIPS):
        name = "D%d" % i
        if i == SHIPS - 1:
            ship = ShipClass()
            ship.SetName(name)
        else:
            ship = _galaxy(name)
        p = _position(rng, i)
        ship.SetTranslateXYZ(p.x, p.y, p.z)
        R = TGMatrix3()
        R.MakeRotation(rng.uniform(-3.0, 3.0), _unit(rng))
        ship.SetMatrixRotation(R)
        pSet.AddObjectToSet(ship, name)
        ships.append(ship)
    App.Game_SetCurrentPlayer(ships[rng.randrange(SHIPS)])
    return ships


def _unit(rng):
    v = _vec(rng, 1.0)
    v.Unitize()
    return v


def _speed(rng, nan_left):
    r = rng.random()
    if nan_left[0] and r < 0.01:
        nan_left[0] = False
        return float("nan")
    if r < 0.2:
        return rng.uniform(-8.0, 0.0)           # reverse, past the cap too
    if r < 0.35:
        return rng.uniform(6.3, 40.0)           # above the cap
    if r < 0.4:
        return 0.0
    return rng.uniform(0.0, 6.3)


def _rate(rng):
    """Small or large: a large one under a long dt spins far."""
    return _vec(rng, rng.choice((0.02, 0.3, 3.0)))


def _pods(ship):
    ies = ship.GetImpulseEngineSubsystem()
    if ies is None:
        return []
    return [ies.GetChildSubsystem(i)
            for i in range(ies.GetNumChildSubsystems())]


def _beat(rng, ships, nan_left):
    ship = rng.choice(ships)
    ies = ship.GetImpulseEngineSubsystem()
    pods = _pods(ship)
    op = rng.randrange(19)
    if op in (0, 1, 2):
        ship.SetSpeed(_speed(rng, nan_left), _vec(rng, 2.0),
                      rng.choice((MODEL, WORLD)))
    elif op in (3, 4):
        ship.SetTargetAngularVelocityDirect(_rate(rng))
    elif op == 5:
        ship.CompleteStop()
    elif op == 6:
        ship._speed_setpoint = None
    elif op == 7 and pods:
        pod = rng.choice(pods)
        pod.SetCondition(rng.choice((0.0, POD_MAX_CONDITION,
                                     rng.uniform(0.0, POD_MAX_CONDITION))))
    elif op == 8 and pods:
        rng.choice(pods).SetDisabledPercentage(rng.uniform(0.0, 1.0))
    elif op == 9 and ies is not None:
        if rng.random() < 0.5:
            ies.TurnOff()
        else:
            ies.TurnOn()
    elif op == 10 and ies is not None:
        ies.SetPowerPercentageWanted(rng.uniform(0.0, 1.25))
    elif op == 11:
        ship.SetStatic(1 if rng.random() < 0.3 else 0)
    elif op == 12:
        ship.SetStationary(1 if rng.random() < 0.3 else 0)
    elif op == 13:
        ship.SetVelocity(_vec(rng, rng.choice((0.1, 5.0, 60.0))))
    elif op == 14:
        ship.SetAngularVelocity(_rate(rng), rng.choice((MODEL, WORLD)))
    elif op == 15 and pods:
        rng.choice(pods)._radiation_out = rng.random() < 0.5
    elif op == 16 and ies is not None:
        ies._radiation_out = rng.random() < 0.3
    elif op == 17:
        ship.SetDying(1 if rng.random() < 0.2 else 0)
    elif op == 18:
        App.Game_SetCurrentPlayer(rng.choice(ships))


def _run(seed, env):
    App.g_kSetManager._sets.clear()
    _set_current_game(None)
    rng = random.Random(seed)
    ships = _build(rng)
    nm.reset()
    nm.configure(env)
    nan_left = [True]
    rows = []
    for _t in range(TICKS):
        for _ in range(rng.randrange(4)):
            _beat(rng, ships, nan_left)
        ship_motion.tick_all_ship_motion(rng.choice(DTS))
        rows.append(golden_fight._pose_rows(ships)
                    + motion_fight.motion_rows(ships))
    return rows, nm.counts()


def _first_difference(a, b):
    for t, (x, y) in enumerate(zip(a, b)):
        if x != y:
            for i, (r, s) in enumerate(zip(x, y)):
                if r != s:
                    return t, r, s
    return None


def test_native_equals_python_on_random_scripted_ships():
    totals = {"native_calls": 0, "warp_rows": 0}
    for seed in SEEDS:
        native, counts = _run(seed, {})
        python, p_counts = _run(seed, {"DAUNTLESS_NATIVE_MOTION": "0"})
        assert p_counts["native_calls"] == 0
        assert native == python, (seed, _first_difference(native, python))
        assert counts["python_rows"] == {}, (seed, counts)
        assert counts["patched_stages"] == 0, (seed, counts)
        assert counts["native_calls"] == TICKS, (seed, counts)
        nc.audit_mirror()
        assert nc.audit_failures() == [], seed
        for k in totals:
            totals[k] += counts[k]
    print("differential:", len(SEEDS), "seeds x", TICKS, "ticks x", SHIPS,
          "ships;", totals)

"""Native impulse_fractions (impulse.cc) against the Python fused walk.

The C++ is a line-for-line port of ``subsystems.impulse_fractions``; every
float compares by ``.hex()``, never a tolerance. Real engine objects are
built through their real setters so the mirror sees every change as it would
in play.
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_impulse_fractions"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import subsystems  # noqa: E402
from engine.appc.properties import SensorProperty  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    ImpulseEngineSubsystem, ShipSubsystem, impulse_fractions,
    impulse_online_fraction)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    nc.configure({})
    assert nc.enabled()
    yield
    nc.reset()


def _slot(obj):
    return obj.__dict__["_nslot"]


def _hexes(pair):
    return tuple(float(v).hex() for v in pair)


def _pod(ies, cond, mx, dis, destroyed=False, prop_max=None):
    pod = ShipSubsystem("Pod")
    pod._max_condition = mx
    pod._condition = cond
    pod._disabled_percentage = dis
    pod._destroyed = destroyed
    if prop_max is not None:
        prop = SensorProperty("Pod")
        prop.SetMaxCondition(prop_max)
        pod.SetProperty(prop)
    ies.AddChildSubsystem(pod)
    return pod


def _engine(rng):
    ship = App.ShipClass_Create("Galaxy")
    ies = ImpulseEngineSubsystem("Impulse")
    ship.SetImpulseEngineSubsystem(ies)
    ies._max_condition = rng.choice([0.0, 100.0, 250.0])
    ies._condition = rng.choice([0.0, ies._max_condition,
                                 ies._max_condition * 0.3])
    ies._disabled_percentage = rng.choice([0.0, 0.25, 0.5])
    ies._destroyed = rng.random() < 0.1
    if rng.random() < 0.5:
        ies.TurnOn()
    else:
        ies.TurnOff()
    ies.SetPowerPercentageWanted(rng.choice(
        [0.0, 0.3, 0.5, 1.0, 1.25, rng.random() * 1.25]))
    ies._radiation_out = rng.random() < 0.1
    for _ in range(rng.randrange(0, 5)):
        mx = rng.choice([0.0, 100.0, 300.0])
        _pod(ies, rng.choice([0.0, mx, mx * rng.random(), mx * 0.7]), mx,
             rng.choice([0.0, 0.25, 0.5, 0.75]),
             destroyed=rng.random() < 0.1,
             prop_max=rng.choice([None, None, 0.0, 150.0, 400.0]))
    r = rng.random()
    if r < 0.1:
        ship._dying = True
    elif r < 0.2:
        ship._dead = True
    return ship, ies


def test_native_matches_the_fused_walk_on_random_engines():
    rng = random.Random(20261104)
    for case in range(500):
        ship, ies = _engine(rng)
        want = _hexes(impulse_fractions(ies))
        got = _hexes(_h.combat_impulse_fractions(_slot(ies)))
        assert got == want, "case %d" % case


def test_no_ies_is_one_one():
    assert _hexes(_h.combat_impulse_fractions(-1)) == _hexes((1.0, 1.0))


def test_pod_radiation_out_follows_the_fused_walk():
    """The latent gap, pinned. A pod with ``_radiation_out`` True counts as
    online in the FUSED walk (past ``_is_offline(ies)`` the ship is known
    good, and only IsDisabled/IsDestroyed are asked of a pod), while the
    separate ``impulse_online_fraction`` runs the full ``_is_offline(pod)``
    and counts it offline. The difference is deliberate today
    (open-questions-by-reading Q1): native must reproduce the fused walk,
    not the separate one, because the fused walk is what motion runs."""
    ship = App.ShipClass_Create("Galaxy")
    ies = ImpulseEngineSubsystem("Impulse")
    ship.SetImpulseEngineSubsystem(ies)
    a = _pod(ies, 100.0, 100.0, 0.25)
    _pod(ies, 100.0, 100.0, 0.25)
    a._radiation_out = True
    fused = impulse_fractions(ies)
    assert fused[0] != impulse_online_fraction(ies)
    assert _hexes(_h.combat_impulse_fractions(_slot(ies))) == _hexes(fused)


def test_unrepresentable_child_raises():
    ship = App.ShipClass_Create("Galaxy")
    ies = ImpulseEngineSubsystem("Impulse")
    ship.SetImpulseEngineSubsystem(ies)
    class _Alien:                       # the mirror cannot name it (-2)
        pass
    ies.AddChildSubsystem(_Alien())
    with pytest.raises(ValueError):
        _h.combat_impulse_fractions(_slot(ies))

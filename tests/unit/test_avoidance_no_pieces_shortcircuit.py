"""Two small correctness/cost properties of the avoidance scan.

1. In the NO-PIECES case — which `docs/engine/avoidance-duplication.md` measures
   as 100% of live ships, since the mission loader never caches hull bounds —
   the whole-body convergence gate and the per-piece loop were evaluating
   `_need_to_avoid` with *identical* arguments: `gate_r` is only raised above
   `GetRadius()` for a piece-bearing obstacle, so for a piece-less one the
   second call re-derives the first call's answer.

2. `reset_avoidance_state()` must drop the per-tick obstacle snapshot. It is
   keyed by `id(pSet)`, and CPython reuses addresses, so a snapshot that
   outlives its set can be handed to a *different* set that happens to land on
   the same id.
"""
import importlib
import sys

import pytest
import App
from engine.appc import collision_avoidance as ca
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem


def _load_galaxy(ship):
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    ca.reset_avoidance_state()
    yield
    App.g_kSetManager._sets.clear()
    ca.reset_avoidance_state()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def _scene():
    """One AI ship flying +Y at a stationary obstacle dead ahead.

    Neither body has cached hull bounds, so both take the single-sphere path —
    which is the live configuration.
    """
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass_Create("Galaxy")
    _load_galaxy(ship)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship.SetRadius(20.0)
    ship.SetAI(object())
    pSet.AddObjectToSet(ship, "Ship")
    ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                    PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    # The scan predicts from the CURRENT velocity, and nothing has integrated
    # yet — a ship at rest converges on nothing, so seed the closing speed
    # rather than tick motion (which would also move the scene under us).
    ship.SetVelocity(TGPoint3(0.0, 30.0, 0.0))

    obstacle = ShipClass_Create("Obstacle")
    h = HullSubsystem("Hull")
    h.SetMaxCondition(1e9)
    obstacle._hull = h
    obstacle.SetWorldLocation(TGPoint3(0, 150, 0))
    obstacle.SetRadius(20.0)
    pSet.AddObjectToSet(obstacle, "Obstacle")
    return pSet, ship, obstacle


def test_a_piece_less_obstacle_is_not_re_tested_after_the_gate(monkeypatch):
    from engine.appc import hull_bounds as hb
    pSet, ship, obstacle = _scene()
    assert not hb.has_hull_bounds(obstacle), "fixture drifted: obstacle has pieces"

    calls = []
    real = ca._need_to_avoid
    monkeypatch.setattr(ca, "_need_to_avoid",
                        lambda *a, **k: (calls.append(a), real(*a, **k))[1])

    ca.invalidate_obstacle_snapshot()
    heading, speed = ca._test_course_override(ship)

    assert heading is not None, (
        "fixture drifted: the obstacle is no longer avoided, so this proves "
        "nothing about the short-circuit")
    assert calls == [], (
        "the piece-less path re-ran _need_to_avoid with the arguments the "
        "convergence gate had already answered (%d times)" % len(calls))


def test_the_short_circuit_did_not_change_which_obstacles_are_avoided():
    """A piece-less obstacle the gate REJECTS must still be rejected — the
    short-circuit lives after the gate, so it may not resurrect one."""
    pSet, ship, obstacle = _scene()
    # Move it far off the flight path: outside the check radius entirely.
    obstacle.SetWorldLocation(TGPoint3(5000.0, 0.0, 0.0))
    ca.invalidate_obstacle_snapshot()
    heading, speed = ca._test_course_override(ship)
    assert heading is None
    assert speed is None


def test_reset_avoidance_state_drops_the_obstacle_snapshot():
    """`_snapshot_by_set` is keyed by `id(pSet)` and outlives a mission swap
    until the next tick invalidates it. A freed set's id can be reused, so a
    stale entry is not merely stale — it can be handed to a different set."""
    pSet, ship, obstacle = _scene()
    ca.invalidate_obstacle_snapshot()
    assert ca.obstacle_snapshot(pSet), "fixture drifted: empty snapshot"
    assert ca._snapshot_by_set, "fixture drifted: snapshot was not cached"

    ca.reset_avoidance_state()
    assert ca._snapshot_by_set == {}
    assert ca._snapshot_stamp is None

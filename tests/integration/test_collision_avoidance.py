"""Collision avoidance (B): an AI ship on a collision course with another
body must take evasive steering and never overlap it.

Reimplements the original Appc autopilot's obstacle avoidance, which the
SDK movement scripts relied on (they only command a heading + impulse).
Applies to all AI ships at all times, independent of difficulty.
"""
import importlib
import sys

import pytest
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.math import TGPoint3
from engine.appc.subsystems import HullSubsystem
from engine.appc.ship_motion import tick_all_ship_motion
from engine.appc.collision_avoidance import tick_collision_avoidance
from engine.appc.objects import PhysicsObjectClass


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
    yield
    App.g_kSetManager._sets.clear()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def _make_obstacle(pSet, x, y, z, name, radius=20.0):
    obs = ShipClass_Create(name)
    h = HullSubsystem("Hull"); h.SetMaxCondition(1e9)
    obs._hull = h
    obs.SetWorldLocation(TGPoint3(x, y, z))
    obs.SetRadius(radius)
    pSet.AddObjectToSet(obs, name)
    return obs


def test_ai_ship_avoids_stationary_obstacle_ahead():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetRadius(20.0)
    attacker.SetAI(object())            # marks it AI-controlled
    pSet.AddObjectToSet(attacker, "Attacker")

    # Stationary obstacle directly ahead on the +Y flight path.
    obstacle = _make_obstacle(pSet, 0, 150, 0, "Obstacle", radius=20.0)
    sum_r = attacker.GetRadius() + obstacle.GetRadius()

    # Command full-ahead toward +Y (model forward).
    attacker.SetImpulse(1.0, TGPoint3(0, 1, 0),
                        PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    closest = 1e18
    for _ in range(2400):               # 40 s @ 60 Hz
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)
        d = (obstacle.GetWorldLocation() - attacker.GetWorldLocation()).Length()
        closest = min(closest, d)

    assert closest > sum_r, (
        f"AI ship overlapped the obstacle: closest={closest:.1f} GU, "
        f"sum_radii={sum_r:.1f} GU"
    )


def test_ai_ship_avoids_ship_charging_head_on():
    """User's explicit scenario: another ship heading straight at them.
    The closing ship is advanced manually so the head-on closing speed is
    higher than a stationary obstacle; the AI ship must still steer clear."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetRadius(20.0)
    attacker.SetAI(object())
    pSet.AddObjectToSet(attacker, "Attacker")
    attacker.SetImpulse(1.0, TGPoint3(0, 1, 0),
                        PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    charger = _make_obstacle(pSet, 0, 260, 0, "Charger", radius=20.0)
    charger_speed = 5.0  # GU/s straight down the -Y axis toward attacker
    charger.SetVelocity(TGPoint3(0, -charger_speed, 0))
    sum_r = attacker.GetRadius() + charger.GetRadius()

    closest = 1e18
    dt = 1.0 / 60.0
    for _ in range(2400):
        # Charger flies straight at the attacker on rails.
        p = charger.GetWorldLocation()
        charger.SetWorldLocation(TGPoint3(p.x, p.y - charger_speed * dt, p.z))
        charger.SetVelocity(TGPoint3(0, -charger_speed, 0))
        tick_collision_avoidance()
        tick_all_ship_motion(dt)
        d = (charger.GetWorldLocation() - attacker.GetWorldLocation()).Length()
        closest = min(closest, d)

    assert closest > sum_r, (
        f"AI ship failed to dodge the charging ship: closest={closest:.1f} GU, "
        f"sum_radii={sum_r:.1f} GU"
    )


def test_stationary_ai_ship_thrusts_clear_of_charging_ship():
    """Regression: a parked AI ship (no forward impulse commanded) charged
    by another ship must ENGAGE ENGINES and move clear, not just pivot in
    place. Avoidance has to command thrust itself — it can't rely on a
    pre-existing speed setpoint, which in combat is often ~0."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetRadius(20.0)
    attacker.SetAI(object())
    pSet.AddObjectToSet(attacker, "Attacker")
    # NOTE: deliberately no SetImpulse — the ship starts dead in space.

    charger = _make_obstacle(pSet, 0, 160, 0, "Charger", radius=20.0)
    charger_speed = 8.0
    sum_r = attacker.GetRadius() + charger.GetRadius()

    start = attacker.GetWorldLocation()
    closest = 1e18
    dt = 1.0 / 60.0
    for _ in range(2400):
        p = charger.GetWorldLocation()
        charger.SetWorldLocation(TGPoint3(p.x, p.y - charger_speed * dt, p.z))
        charger.SetVelocity(TGPoint3(0, -charger_speed, 0))
        tick_collision_avoidance()
        tick_all_ship_motion(dt)
        d = (charger.GetWorldLocation() - attacker.GetWorldLocation()).Length()
        closest = min(closest, d)

    moved = (attacker.GetWorldLocation() - start).Length()
    assert moved > 20.0, (
        f"AI ship pivoted in place instead of engaging engines; moved only "
        f"{moved:.1f} GU"
    )
    assert closest > sum_r, (
        f"parked AI ship failed to evade the charger: closest={closest:.1f} GU, "
        f"sum_radii={sum_r:.1f} GU"
    )

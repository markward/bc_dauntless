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


# ── W3 parity additions ────────────────────────────────────────────────────


def _make_blacklisted(pSet, cls, x, y, z, name, radius=20.0):
    """A non-ship obstacle of a blacklisted class type (Torpedo / Debris)."""
    obs = cls()
    obs.SetWorldLocation(TGPoint3(x, y, z))
    obs.SetRadius(radius)
    pSet.AddObjectToSet(obs, name)
    return obs


def test_blacklisted_type_torpedo_is_ignored():
    """A torpedo (CT_TORPEDO) on a dead-ahead collision course must NOT
    trigger a swerve — the SDK lDontAvoidTypes blacklist
    (Preprocessors.py:1660-1665) skips it. The AI ship holds course."""
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

    # Torpedo parked directly on the +Y flight path, well inside any margin.
    _make_blacklisted(pSet, App.Torpedo, 0, 120, 0, "Torp", radius=20.0)

    fwd0 = attacker.GetWorldForwardTG()
    for _ in range(120):  # 2 s
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)

    fwd1 = attacker.GetWorldForwardTG()
    # Heading is unchanged: the ship never deflected for a blacklisted type.
    align = fwd0.Dot(fwd1) / (fwd0.Length() * fwd1.Length())
    assert align > 0.999, (
        f"AI ship swerved for a blacklisted torpedo (alignment {align:.4f})"
    )
    # And it kept flying straight up +Y.
    p = attacker.GetWorldLocation()
    assert abs(p.x) < 1.0 and abs(p.z) < 1.0, (
        f"AI ship drifted off the +Y axis for a torpedo: {p}"
    )


def test_obstacle_beyond_minimum_radius_is_ignored():
    """An obstacle farther than fMinimumRadius (225 GU) from the ship's
    predicted position is prefiltered out (Preprocessors.py:1743-1749). A
    slow, dead-in-space AI ship next to a distant obstacle holds course."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetRadius(20.0)
    attacker.SetAI(object())
    pSet.AddObjectToSet(attacker, "Attacker")
    # No impulse: dead in space, so predicted position ~= current position and
    # the check radius collapses to fMinimumRadius = 225 GU.

    # Stationary obstacle far beyond 225 GU and off-axis.
    _make_obstacle(pSet, 0, 900, 0, "Far", radius=20.0)

    start = attacker.GetWorldLocation()
    for _ in range(120):
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)

    moved = (attacker.GetWorldLocation() - start).Length()
    assert moved < 1.0, (
        f"AI ship maneuvered for a far obstacle beyond 225 GU; moved {moved:.1f} GU"
    )


def test_in_warp_ship_does_not_swerve():
    """A ship doing an in-system warp must not divert course
    (Preprocessors.py:1692-1693). Even with a charger dead ahead, an
    in-warp AI ship holds its heading."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetRadius(20.0)
    attacker.SetAI(object())
    attacker._doing_in_system_warp = True  # flag the warp state
    pSet.AddObjectToSet(attacker, "Attacker")
    attacker.SetImpulse(1.0, TGPoint3(0, 1, 0),
                        PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    _make_obstacle(pSet, 0, 120, 0, "Obstacle", radius=20.0)

    fwd0 = attacker.GetWorldForwardTG()
    for _ in range(120):
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)

    fwd1 = attacker.GetWorldForwardTG()
    align = fwd0.Dot(fwd1) / (fwd0.Length() * fwd1.Length())
    assert align > 0.999, (
        f"in-warp AI ship swerved (alignment {align:.4f})"
    )


def test_radius_relative_clearance_scales_with_ship_radius():
    """Personal space is 2.5 * shipRadius (Preprocessors.py:1648, 1741), so a
    big ship keeps proportionally larger separation than a small one in the
    SAME geometry. Closest approach to the obstacle scales up with radius."""
    import engine.appc.collision_avoidance as ca

    def run(ship_radius):
        # Reset the RNG before each run so the small-vs-big comparison isolates
        # the radius effect rather than the seeded sampling sequence.
        ca.reset_avoidance_state()
        pSet = App.SetClass_Create(); pSet.SetName("S")
        App.g_kSetManager._sets["S"] = pSet
        try:
            ship = ShipClass_Create("Galaxy")
            _load_galaxy(ship)
            ship.SetWorldLocation(TGPoint3(0, 0, 0))
            ship.SetRadius(ship_radius)
            ship.SetAI(object())
            pSet.AddObjectToSet(ship, "Ship")
            ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
            obstacle = _make_obstacle(pSet, 0, 150, 0, "Obstacle", radius=5.0)

            closest = 1e18
            for _ in range(1200):
                tick_collision_avoidance()
                tick_all_ship_motion(1.0 / 60.0)
                d = (obstacle.GetWorldLocation()
                     - ship.GetWorldLocation()).Length()
                closest = min(closest, d)
            return closest
        finally:
            App.g_kSetManager._sets.clear()
            App.g_kModelPropertyManager.ClearLocalTemplates()
            for k in list(sys.modules):
                if k == "ships" or k.startswith("ships."):
                    del sys.modules[k]

    small = run(8.0)
    big = run(40.0)
    assert big > small, (
        f"larger ship did not keep larger clearance: small_r closest={small:.1f}, "
        f"big_r closest={big:.1f}"
    )


def test_evasion_is_deterministic_across_runs():
    """The 8 sampled candidate directions use a module-level seeded RNG, so a
    fixed scenario produces a byte-identical evasion trajectory on repeat
    runs (resetting the RNG seed between runs)."""
    import engine.appc.collision_avoidance as ca

    def run():
        ca.reset_avoidance_state()
        pSet = App.SetClass_Create(); pSet.SetName("S")
        App.g_kSetManager._sets["S"] = pSet
        try:
            ship = ShipClass_Create("Galaxy")
            _load_galaxy(ship)
            ship.SetWorldLocation(TGPoint3(0, 0, 0))
            ship.SetRadius(20.0)
            ship.SetAI(object())
            pSet.AddObjectToSet(ship, "Ship")
            ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
            _make_obstacle(pSet, 0, 150, 0, "Obstacle", radius=20.0)

            for _ in range(300):
                tick_collision_avoidance()
                tick_all_ship_motion(1.0 / 60.0)
            p = ship.GetWorldLocation()
            f = ship.GetWorldForwardTG()
            return (p.x, p.y, p.z, f.x, f.y, f.z)
        finally:
            App.g_kSetManager._sets.clear()
            App.g_kModelPropertyManager.ClearLocalTemplates()
            for k in list(sys.modules):
                if k == "ships" or k.startswith("ships."):
                    del sys.modules[k]

    a = run()
    b = run()
    assert a == b, f"non-deterministic evasion: {a} != {b}"

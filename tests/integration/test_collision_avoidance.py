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


def test_avoidance_honors_per_pair_disabled_collisions():
    """A ship docking with a starbase must be able to fly right up to it. The
    SDK signals this by calling ``pShip.EnableCollisionsWith(pStarbase, 0)``
    (AI.Compound.DockWithStarbase.SetupCutscene). Collision AVOIDANCE must honor
    that per-pair disable exactly as ``collisions.resolve_collisions`` does —
    otherwise it treats the dock target as an obstacle, overrides the docking
    AI's steering every tick, and the ship spirals off (E6M2 fly-in flew off
    'downward'). With collisions disabled for the pair, avoidance must NOT
    engage against that object even though it is dead ahead with a real radius."""
    from engine.appc import collision_avoidance
    collision_avoidance.reset_avoidance_state()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass_Create("Galaxy")
    _load_galaxy(ship)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship.SetRadius(20.0)
    ship.SetAI(object())
    pSet.AddObjectToSet(ship, "Ship")

    # Big obstacle dead ahead — but it's the dock target: collisions disabled.
    target = _make_obstacle(pSet, 0, 150, 0, "Target", radius=150.0)
    ship.EnableCollisionsWith(target, 0)

    # Full-ahead toward the target.
    ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                    PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    for _ in range(120):                 # 2 s @ 60 Hz
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)

    # Avoidance never engaged against the collision-disabled dock target.
    assert collision_avoidance.is_overriding(ship) is False


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


def test_immobile_ship_with_ai_is_not_steered(monkeypatch):
    """Stations/drydocks (like the E1M1 docks) carry a Stay AI, so GetAI()
    is non-None. Without the IsImmobile() guard, avoidance would try to
    steer them; they must instead be skipped entirely (never evaluated,
    never recorded in the per-ship override state).

    NOTE: iter_collidables() is imported *locally* inside
    tick_collision_avoidance (not a module-level name on `ca`), so it must
    be exercised via a real set (App.g_kSetManager), not monkeypatched —
    matching every other test in this file."""
    import engine.appc.collision_avoidance as ca

    ca.reset_avoidance_state()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    # A stationary ship that (like the E1M1 docks) carries a Stay AI.
    dock = ShipClass_Create("Dock")
    dock.SetStationary(1)
    dock.SetRadius(5.0)
    dock.SetAI(object())  # non-None AI: would otherwise be steered
    pSet.AddObjectToSet(dock, "Dock")

    # If avoidance tried to steer it, it would call _test_course_override.
    called = []
    monkeypatch.setattr(ca, "_test_course_override",
                        lambda *a, **k: called.append(1) or (None, None))

    ca.tick_collision_avoidance(1.0 / 60.0)

    assert called == []                      # never evaluated
    assert ca.is_overriding(dock) is False    # no state recorded


# ── Shape-aware obstacles: a hull is its PIECES, not one big sphere ──────────

def test_ship_in_a_docking_bay_is_not_avoided():
    """THE undock lurch, at the real geometry.

    FinishedUndocking leaves the player ~125 GU from the starbase centre and
    re-enables collisions with it — but the starbase's model-wide bound is
    ~150 GU, so with a single sphere the ship reads as INSIDE the station for
    the whole flight out. _need_to_avoid returns True unconditionally for
    anything already within personal_space + radius, and you cannot steer out
    of something you are inside, so the scorer picks an arbitrary heading and
    commands AVOID_SAFE_SPEED. Measured live: the ship lurched to 3969 kph,
    swung through every axis, and at one point moved back TOWARD the starbase.

    A docking bay is a void BETWEEN hull pieces. Given the pieces, the ship in
    the bay is inside none of them and nothing engages — no special case."""
    from engine.appc import collision_avoidance
    from engine.appc.hull_bounds import cache_hull_bound_spheres
    collision_avoidance.reset_avoidance_state()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass_Create("Galaxy")
    _load_galaxy(ship)
    ship.SetWorldLocation(TGPoint3(0, 125, 0))     # in the bay
    ship.SetRadius(4.03)
    ship.SetAI(object())
    pSet.AddObjectToSet(ship, "Ship")

    starbase = _make_obstacle(pSet, 0, 0, 0, "Starbase 12", radius=150.0)
    # Two hull masses either side of the bay the ship is sitting in. Raw model
    # (NIF) units: cache_hull_bound_spheres applies the NIF->world factor.
    inv = 1.0 / 0.01
    cache_hull_bound_spheres(starbase, [
        (0.0,  400.0 * inv, 0.0, 40.0 * inv),
        (0.0, -400.0 * inv, 0.0, 40.0 * inv),
    ])

    ship.SetImpulse(2.0 / 9.0, TGPoint3(0, 1, 0),
                    PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    for _ in range(120):
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)

    assert collision_avoidance.is_overriding(ship) is False


def test_a_real_hull_piece_in_the_way_is_still_avoided():
    """The guard on the above: descending to pieces must not disable avoidance.
    Same starbase, but now the ship is heading straight into one of its hull
    masses rather than through the gap."""
    from engine.appc import collision_avoidance
    from engine.appc.hull_bounds import cache_hull_bound_spheres
    collision_avoidance.reset_avoidance_state()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass_Create("Galaxy")
    _load_galaxy(ship)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship.SetRadius(20.0)
    ship.SetAI(object())
    pSet.AddObjectToSet(ship, "Ship")

    starbase = _make_obstacle(pSet, 0, 150, 0, "Starbase 12", radius=20.0)
    inv = 1.0 / 0.01
    cache_hull_bound_spheres(starbase, [(0.0, 0.0, 0.0, 20.0 * inv)])

    ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                    PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    for _ in range(600):
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)
        if collision_avoidance.is_overriding(ship):
            break

    assert collision_avoidance.is_overriding(ship) is True


def test_an_obstacle_whose_pieces_are_all_out_of_range_is_not_avoided():
    """A hull is up to 128 pieces, so they are culled to the ones in range
    before any of them is transformed into world space. That makes an empty
    result ambiguous — "no pieces" and "no pieces NEARBY" look identical — and
    resolving it the wrong way reinstates the whole-model sphere for exactly
    the concave hulls the pieces exist to describe.

    A shell-shaped station is the real case: its centre is close enough to
    check, its geometry is nowhere near."""
    from engine.appc import collision_avoidance
    from engine.appc.hull_bounds import cache_hull_bound_spheres
    collision_avoidance.reset_avoidance_state()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass_Create("Galaxy")
    _load_galaxy(ship)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship.SetRadius(20.0)
    ship.SetAI(object())
    pSet.AddObjectToSet(ship, "Ship")

    station = _make_obstacle(pSet, 0, 30, 0, "Shell", radius=20.0)
    inv = 1.0 / 0.01
    cache_hull_bound_spheres(station, [        # all of it 5000 GU away
        (0.0, 5000.0 * inv, 0.0, 10.0 * inv),
        (0.0, -5000.0 * inv, 0.0, 10.0 * inv),
    ])

    ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                    PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    for _ in range(600):
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)
        assert collision_avoidance.is_overriding(ship) is False


def test_an_obstacle_with_no_cached_pieces_still_uses_its_whole_bound():
    """Fall back, don't fail open. Anything unrealized (headless, load failure)
    has no pieces and must keep the single-sphere behaviour — otherwise adding
    the hierarchy would silently switch avoidance off for most of the game."""
    from engine.appc import collision_avoidance
    collision_avoidance.reset_avoidance_state()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass_Create("Galaxy")
    _load_galaxy(ship)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship.SetRadius(20.0)
    ship.SetAI(object())
    pSet.AddObjectToSet(ship, "Ship")

    _make_obstacle(pSet, 0, 150, 0, "Rock", radius=20.0)   # no pieces cached

    ship.SetImpulse(1.0, TGPoint3(0, 1, 0),
                    PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    for _ in range(600):
        tick_collision_avoidance()
        tick_all_ship_motion(1.0 / 60.0)
        if collision_avoidance.is_overriding(ship):
            break

    assert collision_avoidance.is_overriding(ship) is True

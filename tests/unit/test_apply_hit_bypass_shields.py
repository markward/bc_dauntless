"""Explosion / collision damage bypasses shields — BC's second damage primitive.

Verified against the real engine by dev-console probe q02: AddDamage routes
the full damage to hull/subsystems and never touches the shield faces, unlike
normal weapon fire (strict shield cascade). apply_hit(bypass_shields=True) and
DamageableObject.AddDamage(...) take that path; warp-core breach and collisions
use it.
"""
from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _ship_with_powered_shields(hull_max=2000.0, face_max=1000.0):
    """Yellow alert so the generator is IsOn(); shields seeded full."""
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def test_bypass_shields_skips_absorption_even_when_healthy():
    """A healthy, powered generator absorbs normal fire — but bypass_shields
    routes straight to the hull, leaving every face at full HP."""
    ship = _ship_with_powered_shields()
    gen = ship.GetShields()
    assert gen.IsOn() == 1 and gen.IsDisabled() == 0

    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None, bypass_shields=True)

    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert gen.GetCurrentShields(f) == 1000.0   # no face touched
    assert ship.GetHull().GetCondition() == 1500.0  # hull took the full hit


def test_default_still_cascades_through_shields():
    """Regression guard: without the flag, healthy shields still absorb."""
    ship = _ship_with_powered_shields()
    gen = ship.GetShields()

    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)

    assert gen.GetCurrentShields(0) == 500.0         # face absorbed it
    assert ship.GetHull().GetCondition() == 2000.0   # hull intact


def test_add_damage_primitive_bypasses_shields():
    """DamageableObject.AddDamage(pos, radius, damage) is the explosion
    primitive — shields untouched, hull takes the damage (probe q02)."""
    ship = _ship_with_powered_shields()
    gen = ship.GetShields()

    ship.AddDamage(TGPoint3(0, 10, 0), 5.0, 500.0)

    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert gen.GetCurrentShields(f) == 1000.0
    assert ship.GetHull().GetCondition() < 2000.0

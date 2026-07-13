"""combat.apply_hit must bypass shield absorption when the shield
generator subsystem is disabled (condition <= disabled threshold) or
destroyed. Mirrors the powered-down gate already covered by
test_combat_skips_powered_down_shields.py — that test exercises the
IsOn axis (cloak / green alert), this one exercises the IsDisabled /
IsDestroyed axis (subsystem damage).

BC reference (docs/gameplay/combat-and-damage.md
§"Shield bypass paths"): both `shieldClass+0x9C == 0` (powered-down) and
`FUN_0056C350(...)` (subsystem destroyed) bypass absorption. HP on the
faces is preserved — only absorption + recharge stop.
"""
from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _ship_with_powered_shields(hull_max=2000.0, face_max=1000.0,
                                gen_max_condition=100.0,
                                gen_disabled_pct=0.25):
    """Yellow alert so the generator is IsOn(); shields seeded full."""
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(gen_max_condition)
    ss.SetDisabledPercentage(gen_disabled_pct)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def test_disabled_generator_bypasses_shield_absorption():
    """Damage condition to the generator below DisabledPercentage and the
    next hit must skip ApplyDamage entirely — face HP preserved, hull
    takes the full damage."""
    ship = _ship_with_powered_shields()
    gen = ship.GetShields()
    gen.SetCondition(10.0)  # 10 <= 0.25 * 100 = 25 → disabled
    assert gen.IsDisabled() == 1
    assert gen.IsOn() == 1  # still powered — gate must be on disabled, not IsOn

    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)

    assert gen.GetCurrentShields(0) == 1000.0  # face HP preserved
    assert ship.GetHull().GetCondition() == 1500.0  # hull took it


def test_destroyed_generator_bypasses_shield_absorption():
    """Generator destroyed → shields bypass, hull takes the hit."""
    ship = _ship_with_powered_shields()
    gen = ship.GetShields()
    gen.SetCondition(0.0)
    assert gen.IsDestroyed() == 1

    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)

    assert gen.GetCurrentShields(0) == 1000.0
    assert ship.GetHull().GetCondition() == 1500.0


def test_healthy_powered_generator_still_absorbs():
    """Regression guard: with a healthy, powered generator the existing
    absorption path keeps working — shields take the hit, hull is intact."""
    ship = _ship_with_powered_shields()
    gen = ship.GetShields()
    assert gen.IsDisabled() == 0
    assert gen.IsOn() == 1

    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)

    assert gen.GetCurrentShields(0) == 500.0
    assert ship.GetHull().GetCondition() == 2000.0

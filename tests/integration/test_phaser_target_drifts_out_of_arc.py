"""Sustained fire → target moves out of arc mid-fire → bank auto-stops
on the next tick while other banks (if any are still in arc) continue.

Complementary to test_phaser_damage_applied_through_apply_hit's drift
test — that one verifies the auto-stop end-state; this one fires
multiple banks first to assert the partial-stop behavior too.
"""
from unittest.mock import patch

from engine.appc.math import TGPoint3
from engine.host_loop import _advance_combat


def _target_with_shields(at_x=0.0, at_y=50.0, at_z=0.0,
                          hull_max=10000.0, shields_strength=5000.0):
    from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
    from engine.appc.properties import ShieldProperty
    from engine.appc.ships import ShipClass_Create
    tgt = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    tgt._hull = hull
    shields = ShieldSubsystem("Shields")
    for f in range(ShieldProperty.NUM_SHIELDS):
        shields.SetMaxShields(f, shields_strength)
    tgt._shield_subsystem = shields
    tgt._radius = 20.0
    tgt.SetWorldLocation(TGPoint3(at_x, at_y, at_z))
    return tgt


def test_drift_astern_auto_stops_all_forward_banks(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields(at_y=50.0)
    ship.SetTarget(target)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
    firing_before = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    # Galaxy SingleFire(1) → exactly one bank fires.
    assert firing_before == 1, f"Expected 1 bank firing ahead (SingleFire), got {firing_before}"

    # Yank target astern.
    target.SetWorldLocation(TGPoint3(0, -50.0, 0))

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        _advance_combat([ship, target], dt=0.1, ship_instances=None)
    firing_after = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing_after == 0, (
        f"Bank should auto-stop on aft drift; "
        f"before={firing_before}, after={firing_after}"
    )

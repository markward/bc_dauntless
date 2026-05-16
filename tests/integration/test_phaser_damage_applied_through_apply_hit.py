"""Hold-fire on a target ahead routes phaser damage through apply_hit
each tick (so shield/hull condition decreases)."""
from unittest.mock import patch

from engine.appc.math import TGPoint3
from engine.host_loop import _advance_combat


def _target_with_shields(at_y=50.0, hull_max=10000.0, shields_strength=5000.0):
    """Stand-in target ship with hull + full shields at ship_pos+Y*at_y."""
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
    return tgt


def test_held_fire_decreases_target_shield(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    front_before = target.GetShields().GetCurrentShields(0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        _advance_combat([ship, target], dt=0.1, host=None, ship_instances=None)
    front_after = target.GetShields().GetCurrentShields(0)
    assert front_after < front_before, (
        f"Held-fire should decrement front shield; before={front_before}, after={front_after}"
    )


def test_target_drifts_out_of_arc_bank_auto_stops(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
    firing_before = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    # Galaxy SingleFire(1) → exactly one bank fires.
    assert firing_before == 1

    # Move target directly astern of the player.
    target.SetWorldLocation(TGPoint3(p.x, p.y - 50.0, p.z))

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        _advance_combat([ship, target], dt=0.1, host=None, ship_instances=None)
    firing_after = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing_after == 0, (
        f"Out-of-arc auto-stop; before={firing_before}, after={firing_after}"
    )

"""PhaserSystem dispatch — single-bank or multi-bank depending on
SetSingleFire on the property.  Galaxy's hardpoint sets SingleFire(1)
so only one bank fires at a time; flipping it to 0 unlocks the
all-eligible-fire-at-once path."""
from unittest.mock import patch

import App


def _make_target_ahead(player, distance=100.0):
    class _Target:
        def __init__(self, pos):
            self._pos = pos
        def GetWorldLocation(self):  return self._pos
        def IsDead(self):            return 0
    from engine.appc.math import TGPoint3
    p = player.GetWorldLocation()
    return _Target(TGPoint3(p.x, p.y + distance, p.z))


def test_galaxy_single_fire_engages_one_bank_at_a_time(galaxy_red):
    """Galaxy ships have SingleFire(1) — StartFiring fires exactly one
    eligible PhaserBank.  Replaces the old multi-bank assertion."""
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    assert sys_.GetSingleFire() == 1, "Galaxy phasers should be SingleFire"
    target = _make_target_ahead(ship)
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)

    firing = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing == 1, f"SingleFire should fire exactly 1 bank, got {firing}"


def test_multi_fire_engages_every_eligible_bank(galaxy_red):
    """Flip SingleFire(0) and the same target dispatches every
    forward-arc bank simultaneously."""
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    sys_.SetSingleFire(0)
    target = _make_target_ahead(ship)
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)

    firing = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing >= 2, f"Multi-fire should engage ≥2 banks, got {firing}"


def test_target_directly_behind_fires_no_forward_banks(galaxy_red):
    """Target behind the ship → forward-facing banks must NOT fire,
    regardless of SingleFire mode."""
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    from engine.appc.math import TGPoint3
    class _Behind:
        def GetWorldLocation(self):
            p = ship.GetWorldLocation()
            return TGPoint3(p.x, p.y - 100.0, p.z)
        def IsDead(self): return 0
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(_Behind())

    firing = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing == 0, f"Expected no forward banks firing on aft target, got {firing}"


def test_uncharged_banks_skipped(galaxy_red):
    """A bank with _charge_level < _min_firing_charge must not fire even
    when alert + arc allow it."""
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    target = _make_target_ahead(ship)
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = 0.0

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)

    firing = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing == 0, f"Drained banks must not fire, got {firing} firing"

"""Interim cross-set weapon guard (system-frames Plan 2, controller Ruling 5).

Phaser/tractor engagement still compares raw set-local coordinates. Until
frame-aware weapon engagement lands (spec §6 widening list), a target that is
not in the SAME set as the firing ship is out of range, and a bank left firing
at such a target deals no damage. Without the guard a bank could damage a ship
in another set whose raw numbers happen to coincide -- invisibly, because the
beam builder already drops cross-frame beams.

Each cross-set case is mirrored by the identical pair in ONE set, which must
behave exactly as before.
"""
from unittest.mock import patch

import App
from engine.appc.math import TGPoint3
from engine.appc.weapon_subsystems import PhaserSystem, TractorBeamSystem
from engine.host_loop import _advance_combat
from tests.helpers.beams import prime_lit_banks


def _target(at_y=50.0):
    """Hull + full shields, YELLOW alert (shields powered) -- the same stand-in
    as test_phaser_damage_applied_through_apply_hit."""
    from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
    from engine.appc.properties import ShieldProperty
    from engine.appc.ships import ShipClass, ShipClass_Create
    tgt = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(10000.0)
    tgt._hull = hull
    shields = ShieldSubsystem("Shields")
    for f in range(ShieldProperty.NUM_SHIELDS):
        shields.SetMaxShields(f, 5000.0)
    tgt._shield_subsystem = shields
    tgt._radius = 20.0
    tgt.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return tgt


def _placed_target(ship, target_set):
    target = _target()
    target._containing_set = target_set
    p = ship.GetWorldLocation()
    # Identical raw coordinates in both variants of every test.
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)
    return target


def _charge(sys_):
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge


# ── range gate: phasers ──────────────────────────────────────────────────────

def test_phaser_target_in_another_set_is_out_of_range(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, App.SetClass_Create())
    assert ship.GetPhaserSystem()._target_in_system_range(ship, target) is False


def test_phaser_target_in_the_same_set_is_in_range(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, ship.GetContainingSet())
    assert ship.GetPhaserSystem()._target_in_system_range(ship, target) is True


def test_phaser_setless_target_is_out_of_range(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, None)
    assert ship.GetPhaserSystem()._target_in_system_range(ship, target) is False


# ── range gate: tractors ─────────────────────────────────────────────────────

def test_tractor_cannot_engage_a_target_in_another_set(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, App.SetClass_Create())
    assert TractorBeamSystem("Tractors")._can_engage(ship, target) is False


def test_tractor_can_engage_the_same_target_in_the_same_set(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, ship.GetContainingSet())
    assert TractorBeamSystem("Tractors")._can_engage(ship, target) is True


# ── damage tick: a bank LEFT firing across sets ──────────────────────────────

def _fire_one_primed_tick(ship, target):
    """StartFiring + prime a flush-ready pulse, then one combat tick. The
    range gate is bypassed at StartFiring AND at the held-weapon pump so the
    damage tick itself is what is under test: a bank left firing by a path
    that never re-checked range (the scenario Ruling 5 closes)."""
    sys_ = ship.GetPhaserSystem()
    _charge(sys_)
    with patch.object(PhaserSystem, "_can_engage", lambda self, s, t: True), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        assert prime_lit_banks(sys_) >= 1
        _advance_combat([ship, target], dt=0.1, ship_instances=None)
    return sys_


def test_bank_left_firing_at_a_target_in_another_set_deals_no_damage(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, App.SetClass_Create())
    before = target.GetShields().GetCurrentShields(0)
    hull_before = target.GetHull().GetCondition()
    sys_ = _fire_one_primed_tick(ship, target)
    assert target.GetShields().GetCurrentShields(0) == before
    assert target.GetHull().GetCondition() == hull_before
    assert not any(sys_.GetWeapon(i).IsFiring()
                   for i in range(sys_.GetNumWeapons()))


def test_bank_firing_at_the_same_target_in_the_same_set_deals_damage(galaxy_red):
    ship = galaxy_red
    target = _placed_target(ship, ship.GetContainingSet())
    before = target.GetShields().GetCurrentShields(0)
    _fire_one_primed_tick(ship, target)
    assert target.GetShields().GetCurrentShields(0) < before

"""Phaser damage: inverse-square falloff scaled by MaxDamageDistance.

`damage = MaxDamage / (1 + (dist / MaxDamageDistance)**2) * dt`. At
dist=MaxDamageDistance damage is half MaxDamage; far field ∝ 1/dist².
No hard upper cutoff in this function — the system-level fire gate
(PhaserSystem at PHASER_MAX_RANGE_GU = 700 GU) handles out-of-range.
"""
from engine.host_loop import _phaser_damage_for_tick


def test_dist_zero_full_damage():
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=0.0,
                                    dt=0.1) == 25.0  # 250 / 1 * 0.1


def test_dist_at_max_damage_distance_is_half():
    # damage = 250 / (1 + 1) * 0.1 = 12.5
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=60.0,
                                    dt=0.1) == 12.5


def test_dist_double_max_distance_is_one_fifth():
    # damage = 250 / (1 + 4) * 0.1 = 5.0
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=120.0,
                                    dt=0.1) == 5.0


def test_far_field_inverse_square_dominates():
    # At dist = 10 * mdd: damage ≈ 250 / 101 * 0.1 ≈ 0.2475
    result = _phaser_damage_for_tick(max_damage=250.0,
                                      max_damage_distance=60.0,
                                      dist=600.0,
                                      dt=0.1)
    assert abs(result - (250.0 / 101.0 * 0.1)) < 1e-9


def test_zero_max_damage_distance_returns_zero():
    """Defensive: if MaxDamageDistance is 0 (uninitialized property),
    return 0 rather than dividing by zero."""
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=0.0,
                                    dist=10.0,
                                    dt=0.1) == 0.0

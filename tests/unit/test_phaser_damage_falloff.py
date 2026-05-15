"""Damage falloff: MaxDamage × max(0, 1 − dist/MaxDamageDistance) × dt."""
from engine.host_loop import _phaser_damage_for_tick


def test_dist_zero_full_damage():
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=0.0,
                                    dt=0.1) == 25.0  # 250 × 1 × 0.1


def test_dist_half_distance_half_damage():
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=30.0,
                                    dt=0.1) == 12.5


def test_dist_at_max_zero_damage():
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=60.0,
                                    dt=0.1) == 0.0


def test_dist_beyond_max_zero_damage():
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=120.0,
                                    dt=0.1) == 0.0


def test_zero_max_damage_distance_returns_zero():
    """Defensive: if MaxDamageDistance is 0 (uninitialized property),
    return 0 rather than dividing by zero."""
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=0.0,
                                    dist=10.0,
                                    dt=0.1) == 0.0

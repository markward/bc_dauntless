"""Phaser damage falloff: plateau within MaxDamageDistance, then R/d decay.

Verified against the real BC engine via dev-console instrumentation
(docs/instrumented_experiments/2026-06-29-weapon-exchange-console-probe.md,
probe q09): damage is FULL while dist <= MaxDamageDistance (R), then decays
~inverse-linearly as `R/dist` beyond R — weapons still deal ~30% at ~2.9*R.
This replaced the earlier inverse-square `MaxDamage/(1+(dist/R)**2)` guess,
which decayed far too fast. No hard upper cutoff in this function — the
system-level fire gate (PhaserSystem at PHASER_MAX_RANGE_GU = 700 GU) handles
out-of-range.
"""
from engine.host_loop import _phaser_damage_for_tick


def test_dist_zero_full_damage():
    # Inside the plateau: full damage = 250 * 0.1.
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=0.0,
                                    dt=0.1) == 25.0


def test_dist_at_max_damage_distance_is_full():
    # Plateau edge (dist == R): still full damage = 250 * 0.1 = 25.0.
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=60.0,
                                    dt=0.1) == 25.0


def test_dist_double_max_distance_is_half():
    # R/d decay at 2*R: damage = 250 * (60 / 120) * 0.1 = 12.5.
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=120.0,
                                    dt=0.1) == 12.5


def test_far_field_inverse_linear_decay():
    # At dist = 10*R: damage = 250 * (60 / 600) * 0.1 = 2.5.
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=60.0,
                                    dist=600.0,
                                    dt=0.1) == 2.5


def test_zero_max_damage_distance_returns_zero():
    """Defensive: if MaxDamageDistance is 0 (uninitialized property),
    return 0 rather than dividing by zero."""
    assert _phaser_damage_for_tick(max_damage=250.0,
                                    max_damage_distance=0.0,
                                    dist=10.0,
                                    dt=0.1) == 0.0

"""Tests for combat._splash_weight — linear falloff per spec §3.4."""

from engine.appc.combat import _splash_weight


def test_impact_at_subsystem_centre_yields_full_weight():
    # d=0, R_sub=0.3, R_hit=0.15 → (0.3+0.15-0)/0.15 = 3.0 → clamped to 1.0
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=0.0) == 1.0


def test_impact_at_subsystem_surface_still_full_weight():
    # d=R_sub, formula yields R_hit/R_hit = 1.0 (clamped from floating-point)
    assert abs(_splash_weight(r_sub=0.3, r_hit=0.15, d=0.3) - 1.0) < 1e-9


def test_impact_just_outside_subsystem_surface_starts_falloff():
    # d = R_sub + half R_hit, weight = 0.5
    w = _splash_weight(r_sub=0.3, r_hit=0.15, d=0.3 + 0.075)
    assert abs(w - 0.5) < 1e-9


def test_impact_at_splash_edge_yields_zero():
    # d = R_sub + R_hit
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=0.45) == 0.0


def test_impact_beyond_splash_edge_yields_zero():
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=1.0) == 0.0


def test_zero_radius_subsystem_only_hit_when_d_inside_r_hit():
    # R_sub=0: w = (0 + 0.15 - d) / 0.15
    assert _splash_weight(r_sub=0.0, r_hit=0.15, d=0.0) == 1.0
    assert abs(_splash_weight(r_sub=0.0, r_hit=0.15, d=0.075) - 0.5) < 1e-9
    assert _splash_weight(r_sub=0.0, r_hit=0.15, d=0.15) == 0.0


def test_r_hit_zero_safe_no_division_by_zero():
    # R_hit=0 is a degenerate weapon; guard returns 0.0 rather than divide.
    assert _splash_weight(r_sub=0.3, r_hit=0.0, d=0.0) == 0.0

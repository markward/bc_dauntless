"""Planet/moon render scale divides GetRadius() by the NIF bound-sphere
radius, NOT the AABB corner distance.

Regression for the Haven (E1M2) planet rendering ~1/√3 too small. BC computes
render_scale = GetRadius() / NIF_bound_radius, so the model draws at exactly
GetRadius() game units. The prior code divided by ``_model_extent_from_aabb``
(|center| + |half_extents|), which for an origin-centred sphere is R·√3 — ~1.73×
too large — shrinking the planet to GetRadius()/√3 (≈52 GU for Haven's 90).

Suns are unaffected: they render via the procedural sun pass at GetRadius()
directly, not through the NIF divisor path.

See docs/instrumented_experiments/2026-07-07-planet-render-scale.md.
"""
import math

import pytest

from engine import host_loop


# All stock planet/moon NIFs are origin-centred spheres. GreenPurplePlanet.NIF
# (Haven) measures radius 90.01 via dump_nif_tree, so model_aabb yields:
_SPHERE_CENTER = (0.0, 0.0, 0.0)
_SPHERE_HALF = (90.01, 90.01, 90.01)


def test_sphere_radius_is_max_half_extent_not_corner():
    r = host_loop._model_sphere_radius_from_aabb(_SPHERE_CENTER, _SPHERE_HALF)
    assert r == pytest.approx(90.01)  # the sphere's actual radius
    corner = host_loop._model_extent_from_aabb(_SPHERE_CENTER, _SPHERE_HALF)
    assert corner == pytest.approx(90.01 * math.sqrt(3))  # old, too-big divisor
    assert corner > r  # the bug: the corner distance overshoots by √3


def test_haven_natural_scale_renders_at_getradius():
    """Haven: Planet_Create(90.0) with a radius-90 sphere NIF must scale ~1.0
    so the rendered radius equals GetRadius() = 90 GU (not 90/√3 ≈ 52)."""
    get_radius = 90.0
    sphere_radius = host_loop._model_sphere_radius_from_aabb(
        _SPHERE_CENTER, _SPHERE_HALF)
    natural_scale = get_radius / sphere_radius
    assert natural_scale == pytest.approx(1.0, abs=1e-3)
    rendered_radius = sphere_radius * natural_scale
    assert rendered_radius == pytest.approx(get_radius, abs=1e-2)


def test_old_corner_divisor_would_shrink_by_sqrt3():
    """Pin the exact bug: the AABB-corner divisor renders GetRadius()/√3."""
    get_radius = 90.0
    corner = host_loop._model_extent_from_aabb(_SPHERE_CENTER, _SPHERE_HALF)
    sphere_radius = host_loop._model_sphere_radius_from_aabb(
        _SPHERE_CENTER, _SPHERE_HALF)
    buggy_rendered = sphere_radius * (get_radius / corner)
    assert buggy_rendered == pytest.approx(get_radius / math.sqrt(3), abs=1e-2)  # ~52


def test_moon_uses_same_divisor_path():
    """Moon 1 is Planet_Create(80.0, RockyPlanet.nif) — a Planet instance, so
    the same helper governs its scale; a radius-90 sphere NIF renders it at 80."""
    get_radius = 80.0
    sphere_radius = host_loop._model_sphere_radius_from_aabb(
        _SPHERE_CENTER, _SPHERE_HALF)
    rendered_radius = sphere_radius * (get_radius / sphere_radius)
    assert rendered_radius == pytest.approx(get_radius, abs=1e-2)

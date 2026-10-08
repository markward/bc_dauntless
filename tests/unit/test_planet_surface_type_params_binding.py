"""The native planet surface-detail type-table bindings (spec 2026-10-08 §7):
`planet_detail_target_type`, `get_surface_type_params`,
`set_surface_type_params`, `set_planet_detail_budget`,
`set_planet_detail_debug`. Pure C++ state -- no GL context needed.

`set_surface_type_params` writes into the SAME `live_params` table
`PlanetDetailPass::update` reads every frame; its shape-field -> cold-refill
behaviour is covered end-to-end by the native
`PlanetDetailPassTest.SurfaceShapeChangeResetsTheClipmap` gtest
(native/tests/renderer/planet_detail_pass_test.cc), which mutates
`live_params(Rocky).amplitude` directly and asserts the clipmap resets.
"""
import pytest


@pytest.fixture
def reset_live_params():
    import _dauntless_host as h
    yield h
    # 1 == rocky's default params (native/src/renderer/planet_detail_noise.cc).
    h.set_surface_type_params(1, {
        "base_wavelength_gu": 40.0, "max_octaves": 9, "gain": 0.5, "ridged": 1.0,
        "amplitude": 1.0, "bump": 0.35, "albedo": 0.10, "roughness": 0.30,
        "roughness_var": 0.5, "crack_width": 0.0, "stretch": 1.0, "warp": 0.0,
        "gas_rate_gups": 0.0, "gas_period_s": 40.0, "coast_k": 0.08, "coast_a": 0.25,
    })


def test_planet_detail_target_type_is_zero_with_no_renderer_target(reset_live_params):
    h = reset_live_params
    assert h.planet_detail_target_type() == 0


def test_get_surface_type_params_returns_every_field(reset_live_params):
    h = reset_live_params
    p = h.get_surface_type_params(1)   # 1 == rocky
    for field in ("base_wavelength_gu", "max_octaves", "gain", "ridged", "amplitude",
                  "bump", "albedo", "roughness", "roughness_var", "crack_width",
                  "stretch", "warp", "gas_rate_gups", "gas_period_s", "coast_k",
                  "coast_a"):
        assert field in p, field
    assert p["bump"] == pytest.approx(0.35)


def test_set_surface_type_params_writes_named_fields(reset_live_params):
    h = reset_live_params
    h.set_surface_type_params(1, {"bump": 0.5, "coast_k": 0.2})
    p = h.get_surface_type_params(1)
    assert p["bump"] == pytest.approx(0.5)
    assert p["coast_k"] == pytest.approx(0.2)
    # Untouched fields survive.
    assert p["albedo"] == pytest.approx(0.10)


def test_set_surface_type_params_rejects_unknown_key(reset_live_params):
    h = reset_live_params
    with pytest.raises(ValueError):
        h.set_surface_type_params(1, {"bogus_field": 1.0})


def test_set_surface_type_params_rejects_out_of_range_type(reset_live_params):
    h = reset_live_params
    with pytest.raises(ValueError):
        h.set_surface_type_params(99, {"bump": 1.0})
    with pytest.raises(ValueError):
        h.get_surface_type_params(-1)


def test_set_planet_detail_budget_and_debug_do_not_raise(reset_live_params):
    h = reset_live_params
    h.set_planet_detail_budget(1024)
    h.set_planet_detail_debug(True)
    h.set_planet_detail_debug(False)

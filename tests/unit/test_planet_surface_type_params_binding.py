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

Fix round 1, M1: get/set_surface_type_params hand-list the same 16 field
names side by side in host_bindings.cc -- two lists, not one shared table,
so nothing in the C++ *prevents* them drifting apart. What actually catches
a drift is `test_get_set_round_trip_for_every_type` below: if a field were
ever added to one list and not the other, either the round trip would drop
a value or `get_surface_type_params` would omit/gain a key.
"""
import pytest


@pytest.fixture
def reset_live_params():
    """Snapshot type 1 (rocky)'s LIVE params (not a hard-coded default) and
    restore exactly that snapshot after the test (fix round 1, M3) -- so a
    test run against a tree that already changed rocky's factory defaults
    still leaves the process-global live table as it found it, rather than
    overwriting it with this file's own stale idea of "default"."""
    import _dauntless_host as h
    snapshot = h.get_surface_type_params(1)
    yield h
    h.set_surface_type_params(1, snapshot)


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


def test_set_surface_type_params_writes_named_fields(reset_live_params):
    h = reset_live_params
    before = h.get_surface_type_params(1)
    h.set_surface_type_params(1, {"bump": 0.5, "coast_k": 0.2})
    p = h.get_surface_type_params(1)
    assert p["bump"] == pytest.approx(0.5)
    assert p["coast_k"] == pytest.approx(0.2)
    # Untouched fields survive.
    assert p["albedo"] == pytest.approx(before["albedo"])


def test_set_surface_type_params_writes_shape_fields_amplitude_and_max_octaves(reset_live_params):
    """Fix round 1, M3: exercise the two SHAPE fields explicitly -- `amplitude`
    (a plain float) and `max_octaves` (a C++ int, round-tripped through the
    binding's float cast on both the Python->C++ write and the dict value
    pybind hands back)."""
    h = reset_live_params
    h.set_surface_type_params(1, {"amplitude": 2.5, "max_octaves": 3})
    p = h.get_surface_type_params(1)
    assert p["amplitude"] == pytest.approx(2.5)
    assert p["max_octaves"] == 3
    assert isinstance(p["max_octaves"], int)


@pytest.mark.parametrize("surface_type", [0, 1, 2, 3, 4, 5])
def test_get_set_round_trip_for_every_type(reset_live_params, surface_type):
    """set(get()) must reproduce get() exactly, for every type -- the live
    guard against get_surface_type_params / set_surface_type_params's two
    hand-written field lists drifting apart (fix round 1, M1)."""
    h = reset_live_params
    before = h.get_surface_type_params(surface_type)
    h.set_surface_type_params(surface_type, before)
    after = h.get_surface_type_params(surface_type)
    assert after == before


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

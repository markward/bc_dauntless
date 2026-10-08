"""Surface dial group (spec 2026-10-08 §7)."""
import pytest

from engine.planets import atmosphere as atmo
from engine.planets import surface as surf
from engine.planets import surface_dials as dials


_TYPE_PARAMS = {
    "base_wavelength_gu": 40.0, "max_octaves": 9, "gain": 0.5, "ridged": 1.0,
    "amplitude": 1.0, "bump": 0.35, "albedo": 0.10, "roughness": 0.30,
    "roughness_var": 0.5, "crack_width": 0.0, "stretch": 1.0, "warp": 0.0,
    "gas_rate_gups": 0.0, "gas_period_s": 40.0, "coast_k": 0.08, "coast_a": 0.25,
}


def _setup():
    pushes = []
    set_calls = []
    budget_calls = []
    atmo.reload()
    surf.reload()
    surf.clear_live()
    # surface.record_live(iid, set_name, obj_name, nif_path) -- no `key` arg
    # (unlike atmosphere.record_live), so the catalogue key below comes only
    # from the NIF stem ("pinkgasplanet" / "iceplanet").
    surf.record_live("a", "Albirea3", "Albirea 3", "x/PinkGasPlanet.nif")
    surf.record_live("b", "Geble3", "Geble 3", "x/PinkGasPlanet.nif")
    surf.record_live("c", "Savoy2", "Savoy 2", "x/IcePlanet.nif")

    type_tables = {4: dict(_TYPE_PARAMS)}  # 4 == gas, matches pinkgasplanet's type

    def get_fn(t):
        return dict(type_tables[t])

    def set_fn(t, params):
        set_calls.append((t, dict(params)))
        type_tables[t].update(params)

    dials.set_target_fn(lambda: surf.live()[0])
    dials.set_push_fn(lambda iid, s: pushes.append((iid, s)))
    dials.set_target_type_fn(lambda: 4)
    dials.set_type_params_fns(get_fn, set_fn)
    dials.set_budget_fn(lambda cost: budget_calls.append(cost))
    dials._budget = 65536 * 8
    return pushes, set_calls, budget_calls, type_tables


@pytest.fixture(autouse=True)
def _reset_catalogue(tmp_path, monkeypatch):
    path = tmp_path / "atmospheres.json"
    import json
    path.write_text(json.dumps({
        "pinkgasplanet": {"color": "#FF9A96", "thickness": 0.06, "density": 1.4, "limb": 1.0,
                          "surface": {"type": "gas"}},
        "iceplanet": {"color": "#87B4FF", "thickness": 0.02, "density": 1.0, "limb": 1.0,
                     "surface": {"type": "ice"}},
    }))
    monkeypatch.setattr(atmo, "catalogue_path", lambda: path)
    atmo.reload()
    surf.reload()
    yield
    atmo.reload()
    surf.reload()
    surf.clear_live()


def test_register_adds_the_group():
    from engine import dev_dial_groups
    dev_dial_groups.reset()
    dials.register()
    assert "surface" in dev_dial_groups.groups()


def test_dial_order_and_steps():
    assert dials.DIAL_ORDER == ("strength", "albedo", "scale", "bump", "roughness",
                                "coast_k", "ocean_tolerance", "gas_rate_gups",
                                "gas_period_s", "budget")
    assert dials.STEPS["strength"] == pytest.approx(0.05)
    assert dials.STEPS["albedo"] == pytest.approx(0.05)
    assert dials.STEPS["scale"] == pytest.approx(0.05)
    assert dials.STEPS["bump"] == pytest.approx(0.05)
    assert dials.STEPS["roughness"] == pytest.approx(0.02)
    assert dials.STEPS["coast_k"] == pytest.approx(0.01)
    assert dials.STEPS["ocean_tolerance"] == pytest.approx(0.01)
    assert dials.STEPS["gas_rate_gups"] == pytest.approx(0.05)
    assert dials.STEPS["gas_period_s"] == pytest.approx(5.0)


def test_current_with_no_target_is_empty():
    _setup()
    dials.set_target_fn(lambda: None)
    dials.set_target_type_fn(lambda: 0)
    assert dials.current() == {}


def test_current_reports_catalogue_fields_for_target():
    _setup()
    d = dials.current()
    assert d["strength"] == pytest.approx(1.0)
    assert d["albedo"] == pytest.approx(1.0)
    assert d["scale"] == pytest.approx(1.0)
    assert d["ocean_tolerance"] == pytest.approx(0.15)


def test_current_reports_type_table_fields_for_target_type():
    _setup()
    d = dials.current()
    assert d["bump"] == pytest.approx(0.35)
    assert d["roughness"] == pytest.approx(0.30)
    assert d["coast_k"] == pytest.approx(0.08)
    assert d["gas_rate_gups"] == pytest.approx(0.0)
    assert d["gas_period_s"] == pytest.approx(40.0)


def test_current_includes_budget_only_with_a_target():
    _setup()
    assert dials.current()["budget"] == 65536 * 8
    dials.set_target_fn(lambda: None)
    dials.set_target_type_fn(lambda: 0)
    assert "budget" not in dials.current()


def test_step_bump_calls_set_surface_type_params_with_incremented_value():
    _, set_calls, _, _ = _setup()
    dials.step("bump", +1)
    assert set_calls == [(4, {"bump": pytest.approx(0.40)})]
    assert dials.current()["bump"] == pytest.approx(0.40)


def test_step_bump_down_decrements():
    _, set_calls, _, _ = _setup()
    dials.step("bump", -1)
    assert set_calls == [(4, {"bump": pytest.approx(0.30)})]


def test_step_bump_clamps_at_zero_and_max():
    _, set_calls, _, type_tables = _setup()
    for _ in range(100):
        dials.step("bump", -1)
    assert type_tables[4]["bump"] == pytest.approx(0.0)
    for _ in range(300):
        dials.step("bump", +1)
    assert type_tables[4]["bump"] == pytest.approx(4.0)


def test_step_roughness_clamps_to_one():
    _, _, _, type_tables = _setup()
    for _ in range(300):
        dials.step("roughness", +1)
    assert type_tables[4]["roughness"] == pytest.approx(1.0)


def test_step_roughness_clamps_to_the_shader_floor():
    """opaque.frag clamps rough to (0.02, 1.0) -- the dial floor must match
    (fix round 1, M4), not 0.0 (which would be a no-op the shader silently
    overrides anyway)."""
    _, _, _, type_tables = _setup()
    for _ in range(300):
        dials.step("roughness", -1)
    assert type_tables[4]["roughness"] == pytest.approx(0.02)


def test_step_coast_k_clamps_to_one():
    _, _, _, type_tables = _setup()
    for _ in range(300):
        dials.step("coast_k", +1)
    assert type_tables[4]["coast_k"] == pytest.approx(1.0)


def test_step_gas_rate_and_period():
    _, set_calls, _, type_tables = _setup()
    dials.step("gas_rate_gups", +1)
    assert type_tables[4]["gas_rate_gups"] == pytest.approx(0.05)
    dials.step("gas_period_s", +1)
    assert type_tables[4]["gas_period_s"] == pytest.approx(45.0)


def test_step_type_table_no_target_prints_warning(capsys):
    _setup()
    dials.set_target_type_fn(lambda: 0)
    dials.step("bump", +1)
    assert "no planet surface-detail target" in capsys.readouterr().err


def test_step_strength_updates_catalogue_override_and_repushes_shared_key_only():
    pushes = _setup()[0]
    dials.step("strength", +1)
    assert sorted(i for i, _ in pushes) == ["a", "b"]
    assert all(s.strength == pytest.approx(1.05) for _, s in pushes)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").strength \
        == pytest.approx(1.05)
    # Savoy2/iceplanet (different key) untouched.
    assert surf.resolve_surface("Savoy2", "Savoy 2", "x/IcePlanet.nif").strength \
        == pytest.approx(1.0)


def test_step_strength_clamps_to_spec_range():
    _setup()
    for _ in range(300):
        dials.step("strength", +1)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").strength \
        == pytest.approx(4.0)
    for _ in range(300):
        dials.step("strength", -1)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").strength \
        == pytest.approx(0.0)


def test_step_scale_clamps_to_spec_range():
    _setup()
    for _ in range(300):
        dials.step("scale", -1)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").scale \
        == pytest.approx(0.25)
    for _ in range(300):
        dials.step("scale", +1)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").scale \
        == pytest.approx(4.0)


def test_step_ocean_tolerance_clamps():
    _setup()
    for _ in range(300):
        dials.step("ocean_tolerance", -1)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").ocean_tolerance \
        == pytest.approx(0.001)
    for _ in range(300):
        dials.step("ocean_tolerance", +1)
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").ocean_tolerance \
        == pytest.approx(1.0)


def test_step_catalogue_no_target_prints_warning(capsys):
    _setup()
    dials.set_target_fn(lambda: None)
    dials.step("strength", +1)
    assert "no surface planet nearby" in capsys.readouterr().err


def test_reload_drops_catalogue_overrides():
    _setup()
    dials.step("strength", +1)
    atmo.reload()
    surf.reload()
    assert surf.resolve_surface("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").strength \
        == pytest.approx(1.0)


def test_repush_live_restores_catalogue_values_after_override():
    pushes, _, _, _ = _setup()
    dials.step("strength", +1)
    pushes.clear()
    atmo.reload()
    surf.reload()
    dials.repush_live()
    got = dict(pushes)
    assert sorted(got) == ["a", "b", "c"]
    assert got["a"].strength == pytest.approx(1.0) and got["b"].strength == pytest.approx(1.0)
    assert got["c"].type == "ice"


def test_step_budget_doubles_and_halves():
    _, _, budget_calls, _ = _setup()
    dials.step("budget", +1)
    assert budget_calls[-1] == 65536 * 8 * 2
    dials.step("budget", -1)
    assert budget_calls[-1] == 65536 * 8


def test_step_budget_clamps_at_floor():
    _, _, budget_calls, _ = _setup()
    for _ in range(40):
        dials.step("budget", -1)
    assert budget_calls[-1] == 1024


def test_label_names_catalogue_and_type_target():
    _setup()
    text = dials.label()
    assert "Albirea 3 (Albirea3) [pinkgasplanet]" in text
    assert "type=4" in text


def test_label_is_none_with_no_target():
    _setup()
    dials.set_target_fn(lambda: None)
    dials.set_target_type_fn(lambda: 0)
    assert dials.label() is None


def test_step_unknown_dial_raises():
    _setup()
    with pytest.raises(ValueError):
        dials.step("bogus", +1)


# ── _nearest_live_surface_planet (host_loop) ────────────────────────────────


def _loc(x, y, z):
    import types
    return types.SimpleNamespace(x=x, y=y, z=z)


class _FakePlanet:
    """A plain hashable stand-in -- mirrors test_planet_atmosphere_dials's
    _FakePlanet (session.planet_instances is keyed on the planet object)."""

    def __init__(self, x, y, z, radius):
        self._loc = _loc(x, y, z)
        self._radius = radius

    def GetWorldLocation(self):
        return self._loc

    def GetRadius(self):
        return self._radius


def test_nearest_live_surface_planet_picks_surface_distance_not_centre_distance(monkeypatch):
    import types
    from engine import host_loop
    from engine.appc import sensor_contacts
    from engine.systems import frames

    _setup()
    surf.clear_live()
    surf.record_live("near", "S", "Near", "x/PinkGasPlanet.nif")
    surf.record_live("far", "S", "Far", "x/PinkGasPlanet.nif")

    player = types.SimpleNamespace(GetWorldLocation=lambda: _loc(0.0, 0.0, 0.0))
    # far_planet's CENTRE is closer (5 < 10) but its surface is farther
    # (5 - 0.5 = 4.5) than near_planet's (10 - 9 = 1.0).
    near_planet = _FakePlanet(10.0, 0.0, 0.0, 9.0)
    far_planet = _FakePlanet(5.0, 0.0, 0.0, 0.5)
    session = types.SimpleNamespace(
        planet_instances={near_planet: "near", far_planet: "far"},
        celestial_instances={}, celestial_placed={})

    monkeypatch.setattr(sensor_contacts, "current_player", lambda: player)
    monkeypatch.setattr(frames, "viewing_set", lambda: "VIEW")
    monkeypatch.setattr(frames, "containing_set", lambda obj: "VIEW")
    monkeypatch.setattr(frames, "in_view", lambda view, pSet, x, y, z: (x, y, z))

    result = host_loop._nearest_live_surface_planet(session)
    assert result is not None and result.iid == "near"
    surf.clear_live()


def test_nearest_live_surface_planet_returns_none_with_no_live_planets(monkeypatch):
    import types
    from engine import host_loop
    from engine.appc import sensor_contacts
    from engine.systems import frames

    _setup()
    surf.clear_live()
    player = types.SimpleNamespace(GetWorldLocation=lambda: _loc(0.0, 0.0, 0.0))
    session = types.SimpleNamespace(
        planet_instances={}, celestial_instances={}, celestial_placed={})

    monkeypatch.setattr(sensor_contacts, "current_player", lambda: player)
    monkeypatch.setattr(frames, "viewing_set", lambda: "VIEW")
    monkeypatch.setattr(frames, "containing_set", lambda obj: "VIEW")
    monkeypatch.setattr(frames, "in_view", lambda view, pSet, x, y, z: (x, y, z))

    assert host_loop._nearest_live_surface_planet(session) is None


def test_nearest_live_surface_planet_skips_a_no_detail_entry(monkeypatch):
    import types
    import json
    from engine import host_loop
    from engine.appc import sensor_contacts
    from engine.systems import frames

    _setup()
    surf.clear_live()
    surf.record_live("parent", "S", "Parent", "x/PinkGasPlanet.nif")   # has surface
    surf.record_live("moon", "S", "Moon", "x/moon.nif")                # no catalogue entry

    player = types.SimpleNamespace(GetWorldLocation=lambda: _loc(0.0, 0.0, 0.0))
    moon = _FakePlanet(3.0, 0.0, 0.0, 1.0)         # surface 2 GU away
    parent = _FakePlanet(100.0, 0.0, 0.0, 50.0)    # surface 50 GU away
    session = types.SimpleNamespace(
        planet_instances={moon: "moon", parent: "parent"},
        celestial_instances={}, celestial_placed={})

    monkeypatch.setattr(sensor_contacts, "current_player", lambda: player)
    monkeypatch.setattr(frames, "viewing_set", lambda: "VIEW")
    monkeypatch.setattr(frames, "containing_set", lambda obj: "VIEW")
    monkeypatch.setattr(frames, "in_view", lambda view, pSet, x, y, z: (x, y, z))

    result = host_loop._nearest_live_surface_planet(session)
    assert result is not None and result.iid == "parent"
    surf.clear_live()

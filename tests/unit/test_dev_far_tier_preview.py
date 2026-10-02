"""Developer "Far Tier" preview missions (Mark, 2026-10-02: "have the ship
start POINTING at the stuff you want me to tweak, and put the ship the right
distance away").

Each mission runs through the real harness (the path a picker pick takes) and
the test checks where the player is and which way it faces.
"""
import math

import pytest

import App
import tools.mission_harness as mh
from engine import dev_dial_groups

FIELD_CENTRE = (797.714355, 977.248474, 1268.854858)   # Beol 4 Asteroid Field 1


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    dev_dial_groups.reset()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    dev_dial_groups.reset()


def _loc(obj):
    p = obj.GetWorldLocation()
    return (p.x, p.y, p.z)


def _forward(obj):
    f = obj.GetWorldRotation().GetCol(1)
    return (f.x, f.y, f.z)


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_both_missions_are_in_the_developer_picker_family():
    from engine.host_loop import _developer_family_entry
    names = {m.module_name for m in _developer_family_entry().episodes[0].missions}
    assert "engine.dev_missions.far_tier_field" in names
    assert "engine.dev_missions.far_tier_belt" in names
    assert "engine.dev_missions.rock_fields_inside" in names


def test_field_mission_points_the_player_at_the_field_from_6000_gu():
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.far_tier_field")
    assert status == "pass", exc
    pSet = App.g_kSetManager.GetSet("Beol4")
    player = pSet.GetObject("player")
    pos = _loc(player)
    to_centre = tuple(c - p for c, p in zip(FIELD_CENTRE, pos))
    assert math.dist(pos, FIELD_CENTRE) == pytest.approx(6000.0, abs=1.0)
    assert _dot(_unit(_forward(player)), _unit(to_centre)) > 0.9999


def test_field_mission_puts_a_ladder_rock_ahead_of_the_player():
    from engine.rocks.rock import is_rock, effective_radius
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.far_tier_field")
    assert status == "pass", exc
    pSet = App.g_kSetManager.GetSet("Beol4")
    player = pSet.GetObject("player")
    rock = pSet.GetObject("Far Tier Test Rock")
    assert rock is not None and is_rock(rock)
    d = tuple(r - p for r, p in zip(_loc(rock), _loc(player)))
    ahead = _dot(d, _unit(_forward(player)))
    assert ahead == pytest.approx(250.0, abs=1.0)
    assert 1.5 <= effective_radius(rock) <= 3.0     # a ~2 GU major


def test_inside_beol4_mission_is_listed_and_starts_inside_the_field():
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.rock_fields_inside")
    assert status == "pass", exc
    pSet = App.g_kSetManager.GetSet("Beol4")
    player = pSet.GetObject("player")
    field = pSet.GetObject("Asteroid Field 1")
    centre = _loc(field)
    radius = float(field.GetFieldRadius())
    pos = _loc(player)
    dist = math.dist(pos, centre)
    assert dist < 1000.0
    assert dist == pytest.approx(radius - 300.0, abs=1.0)
    to_centre = tuple(c - p for c, p in zip(centre, pos))
    assert _dot(_unit(_forward(player)), _unit(to_centre)) > 0.9999


def test_belt_mission_puts_the_player_mid_band_looking_along_it():
    from engine.systems import frames
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.far_tier_belt")
    assert status == "pass", exc
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    player = pSet.GetObject("player")
    key, x, y, z = frames.system_position(player)
    assert key == ("system", "Vesuvi")
    assert math.hypot(x, y) == pytest.approx(278000.0, abs=5.0)
    assert abs(z) < 1.0
    radial = _unit((x, y, 0.0))
    fwd = _unit(_forward(player))
    assert abs(_dot(fwd, radial)) < 1e-3          # tangential: along the band
    assert abs(fwd[2]) < 1e-3                     # in the system plane


@pytest.mark.parametrize("module,dial", [
    ("engine.dev_missions.far_tier_field", "tile_haze_brightness"),   # Beol 4: no belt
    ("engine.dev_missions.far_tier_belt", "haze_brightness"),
    ("engine.dev_missions.rock_fields_inside", "near_large_density"),
])
def test_the_dial_keys_start_on_the_rock_fields_group(module, dial):
    from engine.rocks import far_dials, minor_dials
    dev_dial_groups.register_group("nebula", ("veil",), lambda: {"veil": 1.0},
                                   lambda d, s: None)
    minor_dials.register()
    far_dials.register()
    assert dev_dial_groups.active() == "nebula"
    mh.setup_sdk()
    status, exc = mh.run_mission(module)
    assert status == "pass", exc
    assert dev_dial_groups.active() == "rock fields"
    assert dev_dial_groups.selected() == dial


def test_set_active_selects_a_group_by_name():
    dev_dial_groups.register_group("a", ("x",), lambda: {"x": 1}, lambda d, s: None)
    dev_dial_groups.register_group("b", ("y",), lambda: {"y": 2}, lambda d, s: None)
    assert dev_dial_groups.set_active("b") is True
    assert dev_dial_groups.active() == "b"
    assert dev_dial_groups.set_active("nope") is False
    assert dev_dial_groups.active() == "b"


def test_start_on_far_dials_with_a_missing_dial_name_returns(monkeypatch):
    """Final review 5: the select loop is bounded by the group's dial count.
    A dial name the group lacks stops after one full cycle instead of
    spinning forever."""
    from engine.dev_missions import _far_tier_common as common
    dev_dial_groups.register_group("rock fields", ("a", "b", "c"),
                                   lambda: {"a": 1, "b": 2, "c": 3}, lambda d, s: None)
    calls = []
    real = dev_dial_groups.cycle_dial

    def counting():
        calls.append(1)
        if len(calls) > 10:
            raise RuntimeError("unbounded dial cycling")
        real()

    monkeypatch.setattr(dev_dial_groups, "cycle_dial", counting)
    common.start_on_far_dials("no_such_dial")
    assert len(calls) <= 3
    assert dev_dial_groups.active() == "rock fields"

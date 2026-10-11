"""Object lights (spec §13.2)."""
import pytest

from engine.bridge_editor import behaviour as bh, lighting_doc as ld, lights


def _doc():
    d = ld.empty_doc("x")
    d["materials"]["alcove"] = {"modifiers": [
        {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
        {"type": "emitter", "scope": ["red"], "tint": [1, 0.5, 0.5], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2, "min": 0.2}]}
    e = ld.object_entry(d, 5, "roof")
    e["material"] = "alcove"
    e["lights"] = [{"position": [1, 2, 3], "direction": [0, 0, -1], "intensity": 100},
                   {"position": [4, 5, 6], "direction": [0, 0, -1], "intensity": 50}]
    ld.object_entry(d, 6, "lamp")["lights"] = [
        {"position": [0, 0, 9], "direction": [0, 0, -1], "inner_deg": 10, "outer_deg": 20,
         "range": 50, "intensity": 900, "light_scale": 2}]
    return d


MATCHED = {"5:roof": 1, "6:lamp": 2}


def test_every_object_light_is_listed_in_mesh_order():
    spots, warnings = lights.spots(_doc(), MATCHED)
    assert [s[0] for s in spots] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]
    assert warnings == []


def test_no_material_is_steady_white_with_light_scale():
    spots, _ = lights.spots(_doc(), {"6:lamp": 2})
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 1800,
                      (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))]


def test_capture_colours_are_steady_states_only():
    (a, b, _), _ = lights.spots(_doc(), MATCHED)
    assert a[7] == pytest.approx((1.0, 1.0, 1.0))      # green steady
    assert a[8] == (0.0, 0.0, 0.0)                       # yellow: nothing scoped


def test_live_colour_is_linear_radiance_and_off_states_are_zero():
    cols = lights.live_colours(_doc(), MATCHED, bh.StateFade("yellow"), 0.0)
    assert cols[0] == (0.0, 0.0, 0.0) and len(cols) == 3
    cols = lights.live_colours(_doc(), MATCHED, bh.StateFade("red"), 0.0)
    assert cols[0] == pytest.approx(tuple(100 * c for c in lights.to_linear((0.5, 0.25, 0.25))))


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "s")["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1]}] * 34
    spots, warnings = lights.spots(d, {"1:s": 1})
    assert len(spots) == 32
    assert warnings == ["1:s light 33: dropped (more than 32 bridge lights)",
                        "1:s light 34: dropped (more than 32 bridge lights)"]

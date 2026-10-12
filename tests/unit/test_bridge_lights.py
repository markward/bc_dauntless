"""Object lights (spec §13.2)."""
import pytest

from engine.bridge_editor import behaviour as bh, lighting_doc as ld, lights


def _doc():
    d = ld.empty_doc("x")
    d["materials"]["alcove"] = {"emission": 0, "modifiers": [
        {"type": "state", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
        {"type": "state", "scope": ["red"], "tint": [1, 0.5, 0.5], "level": 0.5},
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


def _links(d, matched):
    """The resolved {mesh: material} for meshes with no texture: links only."""
    return ld.resolve(d, [{"mesh": i} for i in matched.values()], matched)


def test_every_object_light_is_listed_in_mesh_order():
    spots, warnings = lights.spots(_doc(), MATCHED, _links(_doc(), MATCHED))
    assert [s[0] for s in spots] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]
    assert warnings == []


def test_no_material_is_steady_white_with_light_scale():
    spots, _ = lights.spots(_doc(), {"6:lamp": 2}, _links(_doc(), {"6:lamp": 2}))
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 1800,
                      (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))]


def test_capture_colours_are_steady_states_only():
    (a, b, _), _ = lights.spots(_doc(), MATCHED, _links(_doc(), MATCHED))
    assert a[7] == pytest.approx((1.0, 1.0, 1.0))      # green steady
    assert a[8] == (0.0, 0.0, 0.0)                       # yellow: nothing scoped


def test_live_colour_is_linear_radiance_and_off_states_are_zero():
    cols = lights.live_colours(_doc(), MATCHED, _links(_doc(), MATCHED), bh.StateFade("yellow"), 0.0)
    assert cols[0] == (0.0, 0.0, 0.0) and len(cols) == 3
    cols = lights.live_colours(_doc(), MATCHED, _links(_doc(), MATCHED), bh.StateFade("red"), 0.0)
    assert cols[0] == pytest.approx(tuple(100 * c for c in lights.to_linear((0.5, 0.25, 0.25))))


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "s")["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1]}] * 34
    spots, warnings = lights.spots(d, {"1:s": 1}, _links(d, {"1:s": 1}))
    assert len(spots) == 32
    assert warnings == ["1:s light 33: dropped (more than 32 bridge lights)",
                        "1:s light 34: dropped (more than 32 bridge lights)"]


def test_a_finish_only_material_keeps_the_light_steady_white():
    # Review C1: DBridge 299/320 upgrade to {"roughness": 0} + a light; with
    # no emitter the light must stay white (as v1's no-profile light was),
    # not go dark.
    d = ld.empty_doc("x")
    d["materials"]["material 1"] = {"roughness": 0}
    e = ld.object_entry(d, 299, "")
    e["material"] = "material 1"
    e["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1], "intensity": 10000}]
    (spot,), _ = lights.spots(d, {"299:": 1}, _links(d, {"299:": 1}))
    assert spot[7] == (1.0, 1.0, 1.0) and spot[8] == (1.0, 1.0, 1.0)
    for s in ("green", "red", "offline"):
        (c,) = lights.live_colours(d, {"299:": 1}, _links(d, {"299:": 1}), bh.StateFade(s), 0.0)
        assert c == pytest.approx((10000.0, 10000.0, 10000.0))


def test_a_light_on_an_unlinked_object_follows_its_texture_material():
    d = _doc()
    d["objects"]["5:roof"].pop("material")
    d["textures"] = {"map 3.tga": "alcove"}
    meshes = [{"mesh": 1, "block": 5, "name": "roof", "textures": ["Map 3.tga"]},
              {"mesh": 2, "block": 6, "name": "lamp", "textures": []}]
    resolved = ld.resolve(d, meshes, MATCHED)
    cols = lights.live_colours(d, MATCHED, resolved, bh.StateFade("yellow"), 0.0)
    assert cols[0] == (0.0, 0.0, 0.0)          # alcove has no yellow State: off



def test_a_light_follows_the_finish_emission_level():
    d = _doc()
    d["materials"]["alcove"] = {"emission": 2}
    cols = lights.live_colours(d, MATCHED, _links(d, MATCHED), bh.StateFade("yellow"), 0.0)
    assert cols[0] == pytest.approx((2.0 ** 2.2 * 100,) * 3)


def test_on_a_mapped_mesh_an_unset_emission_lights_like_the_map():
    """The default emission is the map as painted (1) on a mapped texture:
    a State only at red leaves green at 1, not dark."""
    d = _doc()
    d["materials"]["alcove"] = {"modifiers": [
        {"type": "state", "scope": ["red"], "tint": [1, 0, 0], "level": 1}]}
    links = _links(d, MATCHED)
    green = bh.StateFade("green")
    assert lights.live_colours(d, MATCHED, links, green, 0.0, mapped={1})[0] == (100.0,) * 3
    assert lights.live_colours(d, MATCHED, links, green, 0.0)[0] == (0.0,) * 3


# ── strips and panels (spec §16.1, §16.3) ───────────────────────────────────

from engine.bridge_editor import light_shapes as ls

PANEL_FRAME = ls.Frame(right=(1.0, 0.0, 0.0), up=(0.0, 0.0, 1.0), facing=(0.0, -1.0, 0.0),
                       centre=(20.0, 50.0, 20.0), half=(20.0, 10.0, 0.0))


def _area_doc():
    d = _doc()
    ld.object_entry(d, 6, "lamp")["lights"].append(
        {"shape": "strip", "edge": "top", "intensity": 40, "range": 150})
    ld.object_entry(d, 7, "wall")["lights"] = [{"shape": "panel", "intensity": 2}]
    return d


AREA_MATCHED = {"5:roof": 1, "6:lamp": 2, "7:wall": 3}


def test_spots_leave_out_strips_and_panels():
    d = _area_doc()
    spots, _ = lights.spots(d, AREA_MATCHED, _links(d, AREA_MATCHED))
    assert [s[0] for s in spots] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]


def test_area_rows_carry_the_rectangle_range_colour_and_intensity():
    d = _area_doc()
    rows, warnings = lights.areas(d, AREA_MATCHED, _links(d, AREA_MATCHED),
                                  lambda mesh: PANEL_FRAME)
    assert warnings == [] and len(rows) == 2
    strip, panel = rows
    want = ls.strip_rect(PANEL_FRAME, "top")
    assert strip[:3] == (want.centre, want.half_u, want.half_v)
    assert strip[3] == 150 and strip[5] == 40
    assert panel[3] == lights.DEFAULT_RANGE and panel[5] == 2
    assert panel[4] == panel[6] == (1.0, 1.0, 1.0)      # no material: steady white


def test_spots_and_area_lights_share_one_budget_in_mesh_order():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")["lights"] = [
        {"position": [0, 0, i], "direction": [0, 0, -1]} for i in range(20)]
    ld.object_entry(d, 2, "b")["lights"] = [{"shape": "panel"} for _ in range(20)]
    matched = {"1:a": 1, "2:b": 2}
    resolved = _links(d, matched)
    spots, warnings = lights.spots(d, matched, resolved)
    rows, area_warnings = lights.areas(d, matched, resolved, lambda m: PANEL_FRAME)
    assert len(spots) == 20 and len(rows) == 12
    assert len(warnings) == 8 and "2:b light 13" in warnings[0]
    assert area_warnings == []                        # the cap is reported once, by spots()


def test_a_light_without_geometry_is_skipped_and_the_colours_stay_aligned():
    d = ld.empty_doc("x")
    d["materials"]["red"] = {"emission": 0, "modifiers": [
        {"type": "state", "scope": list(ld.STATES), "tint": [1, 0, 0], "level": 1}]}
    ld.object_entry(d, 1, "gone")["lights"] = [{"shape": "panel", "intensity": 1}]
    o = ld.object_entry(d, 2, "here")
    o["material"] = "red"
    o["lights"] = [{"shape": "panel", "intensity": 3}]
    matched = {"1:gone": 1, "2:here": 2}
    resolved = _links(d, matched)
    frames = {2: PANEL_FRAME}
    rows, warnings = lights.areas(d, matched, resolved, frames.get)
    assert len(rows) == 1 and warnings == ["1:gone light 1: no geometry for its object; skipped"]
    fade = bh.StateFade("green")
    live = lights.live_area_colours(d, matched, resolved, fade, 0.0, frames.get)
    assert len(live) == 1 and live[0][0] > 0 and live[0][1] == 0     # the red light's colour

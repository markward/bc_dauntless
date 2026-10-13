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
    b = lights.build(_doc(), MATCHED, _links(_doc(), MATCHED))
    assert [s[0] for s in b.spot_rows] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]
    assert b.warnings == []


def test_no_material_is_steady_white_with_light_scale():
    b = lights.build(_doc(), {"6:lamp": 2}, _links(_doc(), {"6:lamp": 2}))
    assert b.spot_rows == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 1800,
                            (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))]


def test_capture_colours_are_steady_states_only():
    b = lights.build(_doc(), MATCHED, _links(_doc(), MATCHED))
    a, _b, _c = b.spot_rows
    assert a[7] == pytest.approx((1.0, 1.0, 1.0))      # green steady
    assert a[8] == (0.0, 0.0, 0.0)                       # yellow: nothing scoped


def test_live_colour_is_linear_radiance_and_off_states_are_zero():
    d = _doc()
    cols, _ = lights.live(lights.build(d, MATCHED, _links(d, MATCHED)), bh.StateFade("yellow"), 0.0)
    assert cols[0] == (0.0, 0.0, 0.0) and len(cols) == 3
    cols, _ = lights.live(lights.build(d, MATCHED, _links(d, MATCHED)), bh.StateFade("red"), 0.0)
    assert cols[0] == pytest.approx(tuple(100 * c for c in lights.to_linear((0.5, 0.25, 0.25))))


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "s")["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1]}] * 34
    b = lights.build(d, {"1:s": 1}, _links(d, {"1:s": 1}))
    assert len(b.spot_rows) == 32
    assert b.warnings == ["1:s light 33: dropped (needs 1 of the 32 bridge lights, 0 left)",
                          "1:s light 34: dropped (needs 1 of the 32 bridge lights, 0 left)"]


def test_a_finish_only_material_keeps_the_light_steady_white():
    # Review C1: DBridge 299/320 upgrade to {"roughness": 0} + a light; with
    # no emitter the light must stay white (as v1's no-profile light was),
    # not go dark.
    d = ld.empty_doc("x")
    d["materials"]["material 1"] = {"roughness": 0}
    e = ld.object_entry(d, 299, "")
    e["material"] = "material 1"
    e["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1], "intensity": 10000}]
    built = lights.build(d, {"299:": 1}, _links(d, {"299:": 1}))
    (spot,) = built.spot_rows
    assert spot[7] == (1.0, 1.0, 1.0) and spot[8] == (1.0, 1.0, 1.0)
    for s in ("green", "red", "offline"):
        (c,), _ = lights.live(built, bh.StateFade(s), 0.0)
        assert c == pytest.approx((10000.0, 10000.0, 10000.0))


def test_a_light_on_an_unlinked_object_follows_its_texture_material():
    d = _doc()
    d["objects"]["5:roof"].pop("material")
    d["textures"] = {"map 3.tga": "alcove"}
    meshes = [{"mesh": 1, "block": 5, "name": "roof", "textures": ["Map 3.tga"]},
              {"mesh": 2, "block": 6, "name": "lamp", "textures": []}]
    resolved = ld.resolve(d, meshes, MATCHED)
    built = lights.build(d, MATCHED, resolved)
    cols, _ = lights.live(built, bh.StateFade("yellow"), 0.0)
    assert cols[0] == (0.0, 0.0, 0.0)          # alcove has no yellow State: off



def test_a_light_follows_the_finish_emission_level():
    d = _doc()
    d["materials"]["alcove"] = {"emission": 2}
    built = lights.build(d, MATCHED, _links(d, MATCHED))
    cols, _ = lights.live(built, bh.StateFade("yellow"), 0.0)
    assert cols[0] == pytest.approx((2.0 ** 2.2 * 100,) * 3)


def test_on_a_mapped_mesh_an_unset_emission_lights_like_the_map():
    """The default emission is the map as painted (1) on a mapped texture:
    a State only at red leaves green at 1, not dark."""
    d = _doc()
    d["materials"]["alcove"] = {"modifiers": [
        {"type": "state", "scope": ["red"], "tint": [1, 0, 0], "level": 1}]}
    links = _links(d, MATCHED)
    green = bh.StateFade("green")
    mapped_cols, _ = lights.live(lights.build(d, MATCHED, links, mapped={1}), green, 0.0)
    assert mapped_cols[0] == (100.0,) * 3
    unmapped_cols, _ = lights.live(lights.build(d, MATCHED, links), green, 0.0)
    assert unmapped_cols[0] == (0.0,) * 3


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
    b = lights.build(d, AREA_MATCHED, _links(d, AREA_MATCHED), lambda m: PANEL_FRAME)
    assert [s[0] for s in b.spot_rows] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]


def test_area_rows_carry_the_rectangle_range_colour_and_intensity():
    d = _area_doc()
    b = lights.build(d, AREA_MATCHED, _links(d, AREA_MATCHED), lambda mesh: PANEL_FRAME)
    assert b.warnings == [] and len(b.area_rows) == 2
    strip, panel = b.area_rows
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
    b = lights.build(d, matched, resolved, lambda m: PANEL_FRAME)
    assert len(b.spot_rows) == 20 and len(b.area_rows) == 12
    # Review item 9: 20 spots fill the budget to 20; 12 of "b"'s 20 panels
    # fit (20 -> 32); the other 8 (light 13..20) each find 0 left.
    assert b.warnings == [
        f"2:b light {n}: dropped (needs 1 of the 32 bridge lights, 0 left)"
        for n in range(13, 21)]


def test_a_zero_size_area_light_is_skipped_and_the_colours_stay_aligned():
    # Review finding 1: a zero-size rectangle (start == end / x0 == x1, valid
    # in format 4) must be dropped in Python, exactly like "no geometry" --
    # otherwise set_bridge_area_lights drops the row in C++ (threshold 1e-8)
    # while live() still emits a colour for it, misaligning every colour
    # after it with its predecessor's light.
    d = ld.empty_doc("x")
    d["materials"]["red"] = {"emission": 0, "modifiers": [
        {"type": "state", "scope": list(ld.STATES), "tint": [1, 0, 0], "level": 1}]}
    ld.object_entry(d, 1, "zero")["lights"] = [
        {"shape": "panel", "x": [0.4, 0.4], "intensity": 5}]
    o2 = ld.object_entry(d, 2, "red")
    o2["material"] = "red"
    o2["lights"] = [{"shape": "panel", "intensity": 3}]
    ld.object_entry(d, 3, "white")["lights"] = [{"shape": "panel", "intensity": 1}]
    matched = {"1:zero": 1, "2:red": 2, "3:white": 3}
    resolved = _links(d, matched)
    built = lights.build(d, matched, resolved, lambda mesh: PANEL_FRAME)
    assert len(built.area_rows) == 2
    assert built.warnings == ["1:zero light 1: zero size; skipped"]
    fade = bh.StateFade("green")
    _spot_live, live = lights.live(built, fade, 0.0)
    assert len(live) == 2
    assert live[0][0] > 0 and live[0][1] == 0          # red
    assert live[1][0] == live[1][1] == live[1][2] > 0  # white


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
    built = lights.build(d, matched, resolved, frames.get)
    assert len(built.area_rows) == 1
    assert built.warnings == ["1:gone light 1: no geometry for its object; skipped"]
    fade = bh.StateFade("green")
    _spot_live, live = lights.live(built, fade, 0.0)
    assert len(live) == 1 and live[0][0] > 0 and live[0][1] == 0     # the red light's colour


# ── one builder, the budget in segments (spec §16.8) ────────────────────────

def _rects(n):
    return [ls.Rect((float(i), 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -0.25, 0.0), 0) for i in range(n)]


def test_the_budget_counts_segments_and_drops_a_strip_whole(monkeypatch):
    from engine.bridge_editor import edge_snap
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")["lights"] = [
        {"position": [0, 0, i], "direction": [0, 0, -1]} for i in range(28)]
    ld.object_entry(d, 2, "b")["lights"] = [
        {"shape": "strip", "edge": "top", "anchor": [0, 0, 0]},     # 6 segments: does not fit
        {"shape": "panel"}]                                          # 1: fits
    monkeypatch.setattr(edge_snap, "light_rects",
                        lambda light, fr: _rects(6 if light["shape"] == "strip" else 1))
    monkeypatch.setattr(edge_snap, "snap", lambda fr, anchor: object())
    matched = {"1:a": 1, "2:b": 2}
    b = lights.build(d, matched, _links(d, matched), lambda m: PANEL_FRAME)
    assert len(b.spot_rows) == 28 and len(b.area_rows) == 1
    # Review item 9: the strip needs 6 of the 4 left after 28 spots, so it is
    # dropped whole; the panel after it still fits (28 + 1 <= 32).
    assert b.warnings == ["2:b light 1: dropped (needs 6 of the 32 bridge lights, 4 left)"]
    assert len(b.area_lit) == len(b.area_rows) and len(b.spot_lit) == len(b.spot_rows)


def test_live_colours_follow_the_built_rows(monkeypatch):
    d = _area_doc()
    built = lights.build(d, AREA_MATCHED, _links(d, AREA_MATCHED), lambda m: PANEL_FRAME)
    spot_cols, area_cols = lights.live(built, bh.StateFade("green"), 0.0)
    assert len(spot_cols) == len(built.spot_rows) and len(area_cols) == len(built.area_rows)


def test_a_snap_with_nothing_in_reach_warns_and_keeps_the_box_edge():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "w")["lights"] = [
        {"shape": "strip", "edge": "top", "anchor": [900.0, 900.0, 900.0], "intensity": 4}]
    verts = [(0.0, 50.0, 10.0), (40.0, 50.0, 10.0), (40.0, 50.0, 30.0),
             (0.0, 50.0, 10.0), (40.0, 50.0, 30.0), (0.0, 50.0, 30.0)]
    eye = (20.0, 0.0, 20.0)
    fr = ls.frame(verts, ls.oriented_normal_sum(verts, eye), 800.0, eye)
    b = lights.build(d, {"1:w": 1}, {}, lambda m: fr)
    assert len(b.area_rows) == 1
    assert b.area_rows[0][0] == ls.strip_rect(fr, "top", offset=0.0).centre
    assert any("no sharp edge" in w for w in b.warnings)


# ── a State may light without glowing (spec §16.9) ─────────────────────────

def test_a_lights_only_state_colours_the_light_and_its_captures():
    d = ld.empty_doc("x")
    d["materials"]["wall"] = {"modifiers": [
        {"type": "state", "scope": list(ld.STATES), "tint": [1, 0.5, 0.25], "level": 1,
         "glows": False}]}
    o = ld.object_entry(d, 1, "w")
    o["material"] = "wall"
    o["lights"] = [{"position": [0, 0, 9], "direction": [0, 0, -1], "intensity": 10}]
    matched = {"1:w": 1}
    b = lights.build(d, matched, _links(d, matched))
    [spot] = b.spot_rows
    want = tuple(c ** 2.2 for c in (1.0, 0.5, 0.25))
    assert spot[5] == pytest.approx(want) and spot[7] == pytest.approx(want)
    [live] = lights.live(b, bh.StateFade("green"), 0.0)[0]
    assert live == pytest.approx(tuple(10 * c for c in want))

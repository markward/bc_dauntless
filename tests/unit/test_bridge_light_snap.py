"""SPIKE (edge snap, 2026-10-12): a strip with an `anchor` sits on the mesh's
sharp edge nearest the clicked point instead of the object's box edge -- the
fix for compound meshes such as DBridge's Map 3 walls, whose box spans a whole
wall of alcoves. Synthetic double-sided alcove, no GL."""
import json

import pytest

from engine.bridge_editor import editing, light_shapes as ls, lighting_doc as ld, lights

EYE = (15.0, 0.0, 10.0)


def _quads_to_tris(quads, both_sides=True):
    """Triangles of the quads; with `both_sides` each also gets a reversed
    copy, as DBridge's walls do."""
    v = []
    for a, b, c, d in quads:
        v += [a, b, c, a, c, d]
        if both_sides:
            v += [a, c, b, a, d, c]
    return v


# An alcove open toward -y: back wall y = 60, top z = 20, bottom z = 0, sides x = 0 / 30.
ALCOVE = _quads_to_tris([
    ((0, 60, 0), (30, 60, 0), (30, 60, 20), (0, 60, 20)),
    ((0, 50, 20), (0, 60, 20), (30, 60, 20), (30, 50, 20)),
    ((0, 50, 0), (30, 50, 0), (30, 60, 0), (0, 60, 0)),
    ((0, 50, 0), (0, 60, 0), (0, 60, 20), (0, 50, 20)),
    ((30, 50, 0), (30, 50, 20), (30, 60, 20), (30, 60, 0)),
])


def _frame():
    v = [tuple(float(c) for c in p) for p in ALCOVE]
    return ls.frame(v, ls.oriented_normal_sum(v, EYE), 1.0, EYE)


def approx(v, w, tol=1e-6):
    return all(abs(a - b) <= tol for a, b in zip(v, w))


def test_a_click_under_the_lip_snaps_to_the_whole_lip():
    poly, ns = ls.snap_edge(_frame(), (15.0, 51.0, 20.0))
    assert sorted(p[0] for p in (poly[0], poly[-1])) == [0, 30]
    assert all(approx(p[1:], (50, 20)) for p in poly)
    assert approx(ns, (0, 0, -1))                    # the ceiling, facing the room
    # A ceiling's "top" is its edge farther from the eye (frame()'s rule), so
    # left to right runs -x here.
    assert approx(poly[0], (30, 50, 20))


def test_on_a_wall_the_run_goes_left_to_right_as_seen_from_the_room():
    poly, ns = ls.snap_edge(_frame(), (15.0, 60.0, 19.0))     # back wall, under its top crease
    assert approx(ns, (0, -1, 0))
    assert approx(poly[0], (0, 60, 20)) and approx(poly[-1], (30, 60, 20))


def test_the_snapped_strip_washes_the_clicked_surface_and_offset_moves_it_off_it():
    light = {"shape": "strip", "edge": "top", "anchor": [15.0, 51.0, 20.0], "offset": 1.0}
    [r] = ls.snapped_strip_rects(_frame(), light)
    assert approx(r.centre, (15, 50, 19)) and approx(r.half_u, (-15, 0, 0))
    assert r.normal[1] > 0 and r.normal[2] > 0       # into the alcove, back onto the ceiling
    assert abs(r.normal[0]) < 1e-9                   # perpendicular to the edge


def test_start_and_end_cut_the_snapped_run():
    light = {"shape": "strip", "edge": "top", "anchor": [15.0, 51.0, 20.0],
             "start": 0.5, "end": 1.0}
    [r] = ls.snapped_strip_rects(_frame(), light)
    assert approx(r.centre, (7.5, 50, 20)) and approx(r.half_u, (-7.5, 0, 0))


def test_nothing_in_reach_falls_back_to_the_box_edge_and_warns():
    fr = _frame()
    light = {"shape": "strip", "edge": "top", "anchor": [500.0, 500.0, 500.0]}
    assert ls.snap_edge(fr, light["anchor"]) is None
    assert ls.light_rects(light, fr) == [ls.light_rect(light, fr)]
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "alcove")["lights"] = [dict(light, intensity=4)]
    rows, warnings = lights.areas(d, {"1:alcove": 1}, {}, lambda m: fr)
    assert len(rows) == 1 and "no sharp edge near its snap point" in warnings[0]


def test_a_curved_run_becomes_several_segments():
    # A lip of radius 100 bent through 30 degrees in 10-degree steps: one run, kept as a
    # polyline (a chord would sit 3.4 units off it).
    import math
    pts = [(100 * math.cos(math.radians(a)), 100 * math.sin(math.radians(a)), 20.0)
           for a in (0, 10, 20, 30)]
    quads = []
    for p, q in zip(pts, pts[1:]):           # a ceiling strip hanging inward from the lip
        quads.append((p, q, (q[0] * 0.8, q[1] * 0.8, 20.0), (p[0] * 0.8, p[1] * 0.8, 20.0)))
    v = [tuple(c) for c in _quads_to_tris(quads)]
    eye = (0.0, 0.0, 0.0)
    fr = ls.frame(v, ls.oriented_normal_sum(v, eye), 1.0, eye)
    poly, _ns = ls.snap_edge(fr, (95 * 0.98, 95 * 0.17, 20.0))
    assert len(poly) >= 3                    # not one chord across the curve


def test_the_anchor_is_validated_and_editable():
    d = ld.empty_doc("x")
    light = {"shape": "strip", "edge": "top"}
    ld.object_entry(d, 1, "alcove")["lights"] = [light]
    editing.snap_light(light, (1, 2, 3))
    assert light["anchor"] == [1.0, 2.0, 3.0]
    ld.validate(d)
    editing.unsnap_light(light)
    assert "anchor" not in light
    light["anchor"] = [1, 2]
    with pytest.raises(ld.BridgeLightingError, match="anchor"):
        ld.validate(d)


def test_a_panel_cannot_be_snapped():
    light = {"shape": "panel"}
    editing.snap_light(light, (1, 2, 3))
    assert "anchor" not in light

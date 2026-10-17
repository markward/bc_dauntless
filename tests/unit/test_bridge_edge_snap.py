"""Edge snap (spec 2026-10-08-bridge-emitters §16.8): a strip with an
`anchor` sits on the mesh's sharp edge nearest the clicked point instead of
the object's box edge -- the fix for compound meshes such as DBridge's Map 3
walls, whose box spans a whole wall of alcoves. Synthetic double-sided
alcove, no GL."""
import json

import pytest

from engine.bridge_editor import edge_snap, editing, light_shapes as ls, lighting_doc as ld, lights

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
    s = edge_snap.snap(_frame(), (15.0, 51.0, 20.0))
    poly, ns = s.polyline, s.surface_normal
    assert sorted(p[0] for p in (poly[0], poly[-1])) == [0, 30]
    assert all(approx(p[1:], (50, 20)) for p in poly)
    assert approx(ns, (0, 0, -1))                    # the ceiling, facing the room
    # Ordering follows frame()'s hint for a near-horizontal surface: the
    # horizontal direction from the eye (15, 0, 10) to the run's midpoint
    # (15, 50, 20) is +y, giving right = up x ns = -x, so left to right
    # runs -x here.
    assert approx(poly[0], (30, 50, 20))


def test_the_ceiling_ordering_follows_frame_s_hint_not_a_fixed_axis():
    """Review item 2 (Important): edge_snap used to project ROOM_UP onto the
    surface and fall back to a fixed (0, 1, 0) only when that projection was
    exactly degenerate -- which it always is for a flat ceiling/floor,
    regardless of where the eye is. frame()'s own rule for a near-horizontal
    surface is different: the hint is the horizontal direction from the eye
    to the run's midpoint. Moving the eye to the opposite side of the room
    must reverse which end of the polyline is "left"."""
    near = edge_snap.snap(_frame(), (15.0, 51.0, 20.0))
    v = [tuple(float(c) for c in p) for p in ALCOVE]
    far_eye = (15.0, 110.0, 10.0)
    far_fr = ls.frame(v, ls.oriented_normal_sum(v, far_eye), 1.0, far_eye)
    far = edge_snap.snap(far_fr, (15.0, 51.0, 20.0))
    assert approx(near.surface_normal, far.surface_normal)    # same ceiling plane
    assert approx(near.polyline[0], far.polyline[-1])
    assert approx(near.polyline[-1], far.polyline[0])


def test_on_a_wall_the_run_goes_left_to_right_as_seen_from_the_room():
    s = edge_snap.snap(_frame(), (15.0, 60.0, 19.0))     # back wall, under its top crease
    poly, ns = s.polyline, s.surface_normal
    assert approx(ns, (0, -1, 0))
    assert approx(poly[0], (0, 60, 20)) and approx(poly[-1], (30, 60, 20))


def _alcove_with_reversed_ceiling_first():
    """The same alcove as ALCOVE, but the ceiling quad's back-facing
    (reversed-winding) copy is listed BEFORE its room-facing one -- so
    `_welded`'s "whichever copy comes first" rule keeps the reversed
    winding for that triangle (review item 1 repro: DBridge block 652 keeps
    79 of 281 triangles with this same reversed winding)."""
    other = [
        ((0, 60, 0), (30, 60, 0), (30, 60, 20), (0, 60, 20)),
        ((0, 50, 0), (30, 50, 0), (30, 60, 0), (0, 60, 0)),
        ((0, 50, 0), (0, 60, 0), (0, 60, 20), (0, 50, 20)),
        ((30, 50, 0), (30, 50, 20), (30, 60, 20), (30, 60, 0)),
    ]
    v = list(_quads_to_tris(other))
    a, b, c, d = (0, 50, 20), (0, 60, 20), (30, 60, 20), (30, 50, 20)   # the ceiling quad
    v += [a, c, b, a, d, c, a, b, c, a, c, d]          # reversed copy FIRST, normal second
    return [tuple(float(x) for x in p) for p in v]


def test_the_clicked_surface_normal_is_winding_independent():
    """Review item 1 (Critical): `_welded` always orients a kept triangle's
    STORED normal toward the eye, but it never touches the triangle's own
    vertex order -- so when the kept copy is the back-facing one, that
    normal was flipped relative to the triangle's own winding. The old
    inside-test in `_surface_normal` assumed every edge term is
    >= -eps (consistent winding), so it never matched the ceiling triangle
    under the click and a different, wrong triangle won instead."""
    v = _alcove_with_reversed_ceiling_first()
    eye = EYE
    fr = ls.frame(v, ls.oriented_normal_sum(v, eye), 1.0, eye)
    s = edge_snap.snap(fr, (15.0, 51.0, 20.0))
    assert approx(s.surface_normal, (0, 0, -1))
    light = {"shape": "strip", "edge": "top", "anchor": [15.0, 51.0, 20.0], "offset": 1.0}
    [r] = edge_snap.strip_rects(fr, light)
    assert r.normal[1] > 0 and r.normal[2] > 0       # into the alcove, back onto the ceiling


def test_the_snapped_strip_washes_the_clicked_surface_and_offset_moves_it_off_it():
    light = {"shape": "strip", "edge": "top", "anchor": [15.0, 51.0, 20.0], "offset": 1.0}
    [r] = edge_snap.strip_rects(_frame(), light)
    assert approx(r.centre, (15, 50, 19)) and approx(r.half_u, (-15, 0, 0))
    assert r.normal[1] > 0 and r.normal[2] > 0       # into the alcove, back onto the ceiling
    assert abs(r.normal[0]) < 1e-9                   # perpendicular to the edge


def test_start_and_end_cut_the_snapped_run():
    light = {"shape": "strip", "edge": "top", "anchor": [15.0, 51.0, 20.0],
             "start": 0.5, "end": 1.0}
    [r] = edge_snap.strip_rects(_frame(), light)
    assert approx(r.centre, (7.5, 50, 20)) and approx(r.half_u, (-7.5, 0, 0))


def test_nothing_in_reach_falls_back_to_the_box_edge_and_warns():
    fr = _frame()
    light = {"shape": "strip", "edge": "top", "anchor": [500.0, 500.0, 500.0]}
    assert edge_snap.snap(fr, light["anchor"]) is None
    assert edge_snap.light_rects(light, fr) == [ls.light_rect(light, fr)]
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "alcove")["lights"] = [dict(light, intensity=4)]
    b = lights.build(d, {"1:alcove": 1}, {}, lambda m: fr)
    assert len(b.area_rows) == 1 and "no sharp edge near its snap point" in b.warnings[0]


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
    s = edge_snap.snap(fr, (95 * 0.98, 95 * 0.17, 20.0))
    poly = s.polyline
    assert len(poly) >= 3                    # not one chord across the curve


def test_a_snapped_strip_with_zero_length_cut_warns_like_the_unsnapped_case():
    """Review item 4 (Minor): edge_snap.light_rects returns [] OUTRIGHT for a
    snapped strip whose start == end (zero-length cut) -- not a per-
    rectangle zero area -- so lights.build's MIN_AREA loop never ran at
    all, and the light vanished with no warning whatsoever."""
    fr = _frame()
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "alcove")["lights"] = [
        {"shape": "strip", "edge": "top", "anchor": [15.0, 51.0, 20.0],
         "start": 0.5, "end": 0.5, "intensity": 4}]
    b = lights.build(d, {"1:alcove": 1}, {}, lambda m: fr)
    assert b.area_rows == []
    assert b.warnings == ["1:alcove light 1: zero size; skipped"]


def test_a_snapped_strip_s_join_bits_reach_lights_build():
    """Review item 3 (Important): the join-bit path from edge_snap through
    lights.build into the renderer row shape was never exercised end to
    end. The 9th element of an area row is the join bits; a lone (unsnapped
    or single-segment) light's is 0."""
    import math
    pts = [(100 * math.cos(math.radians(a)), 100 * math.sin(math.radians(a)), 20.0)
           for a in (0, 10, 20, 30)]
    quads = [(p, q, (q[0] * 0.8, q[1] * 0.8, 20.0), (p[0] * 0.8, p[1] * 0.8, 20.0))
             for p, q in zip(pts, pts[1:])]
    v = [tuple(c) for c in _quads_to_tris(quads)]
    eye = (0.0, 0.0, 0.0)
    curve_fr = ls.frame(v, ls.oriented_normal_sum(v, eye), 1.0, eye)
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "curve")["lights"] = [
        {"shape": "strip", "edge": "top", "anchor": [95 * 0.98, 95 * 0.17, 20.0]}]
    ld.object_entry(d, 2, "lone")["lights"] = [{"shape": "panel"}]
    matched = {"1:curve": 1, "2:lone": 2}
    frames = {1: curve_fr, 2: _frame()}
    b = lights.build(d, matched, {}, frames.get)
    assert b.warnings == []
    joins = [row[9] for row in b.area_rows]
    n = len(joins) - 1                                # the last row is the lone panel
    assert n >= 2
    assert joins[:n] == [2] + [3] * (n - 2) + [1]
    assert joins[-1] == 0


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


def test_snapped_segments_flag_their_joined_ends():
    import math
    pts = [(100 * math.cos(math.radians(a)), 100 * math.sin(math.radians(a)), 20.0)
           for a in (0, 10, 20, 30)]
    quads = [(p, q, (q[0] * 0.8, q[1] * 0.8, 20.0), (p[0] * 0.8, p[1] * 0.8, 20.0))
             for p, q in zip(pts, pts[1:])]
    v = [tuple(c) for c in _quads_to_tris(quads)]
    eye = (0.0, 0.0, 0.0)
    fr = ls.frame(v, ls.oriented_normal_sum(v, eye), 1.0, eye)
    rects = edge_snap.strip_rects(fr, {"shape": "strip", "edge": "top",
                                       "anchor": [95 * 0.98, 95 * 0.17, 20.0]})
    assert [r.joins for r in rects] == [2] + [3] * (len(rects) - 2) + [1]
    [lone] = edge_snap.strip_rects(_frame(), {"shape": "strip", "edge": "top",
                                               "anchor": [15.0, 51.0, 20.0]})
    assert lone.joins == 0


def test_constants_match_the_spec():
    assert (edge_snap.CREASE_DEG, edge_snap.STRAIGHT_DEG, edge_snap.SNAP_REACH, edge_snap.SNAP_TIE,
            edge_snap.SIMPLIFY_TOL, edge_snap.MAX_SEGMENTS, edge_snap.WASH_DEPTH) == \
        (30.0, 20.0, 20.0, 2.0, 0.5, 6, 10.0)

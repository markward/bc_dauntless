"""Lights with size: the front rectangle and the strips / panels cut from it
(spec 2026-10-08-bridge-emitters §16.2). Synthetic meshes, no GL."""
import math

import pytest

from engine.bridge_editor import light_shapes as ls

EYE = (20.0, 0.0, 20.0)


def _mesh(quads):
    """(vertices, normal_sum, area) for quads given as 4 corners each, wound
    so cross(b - a, d - a) points where the quad faces."""
    verts, n, area = [], [0.0, 0.0, 0.0], 0.0
    for a, b, c, d in quads:
        for tri in ((a, b, c), (a, c, d)):
            p, q, r = tri
            e1 = [q[i] - p[i] for i in range(3)]
            e2 = [r[i] - p[i] for i in range(3)]
            cr = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2],
                  e1[0] * e2[1] - e1[1] * e2[0])
            for i in range(3):
                n[i] += cr[i] / 2
            area += math.sqrt(sum(c * c for c in cr)) / 2
            verts.extend(tri)
    return verts, tuple(n), area


def approx(v, w, tol=1e-6):
    return all(abs(a - b) <= tol for a, b in zip(v, w))


# A wall panel x 0..40, z 10..30 at y = 50, facing -Y (into the room).
WALL = [((0, 50, 10), (40, 50, 10), (40, 50, 30), (0, 50, 30))]


def test_a_flat_wall_panel_faces_the_room_with_room_up():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    assert approx(fr.facing, (0, -1, 0)) and approx(fr.up, (0, 0, 1))
    assert approx(fr.right, (1, 0, 0))            # the viewer's right, seen from the room
    assert approx(fr.centre, (20, 50, 20)) and approx(fr.half, (20, 10, 0))


def test_a_top_strip_runs_along_the_top_edge_aimed_at_the_centre():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.strip_rect(fr, "top")
    assert approx(r.centre, (20, 50, 30)) and approx(r.half_u, (20, 0, 0))
    assert approx(r.normal, (0, 0, -1))           # down the panel, perpendicular to the edge
    assert math.isclose(math.sqrt(sum(c * c for c in r.half_v)), ls.STRIP_WIDTH / 2)


def test_start_and_end_cut_the_edge():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.strip_rect(fr, "top", 0.0, 0.5)
    assert approx(r.centre, (10, 50, 30)) and approx(r.half_u, (10, 0, 0))
    r = ls.strip_rect(fr, "bottom", 0.25, 0.75)
    assert approx(r.centre, (20, 50, 10)) and approx(r.half_u, (10, 0, 0))
    assert approx(r.normal, (0, 0, 1))


def test_left_and_right_are_the_viewers():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    left, right = ls.strip_rect(fr, "left"), ls.strip_rect(fr, "right")
    assert approx(left.centre, (0, 50, 20)) and approx(left.normal, (1, 0, 0))
    assert approx(right.centre, (40, 50, 20)) and approx(right.normal, (-1, 0, 0))
    assert approx(left.half_u, (0, 0, 10))


def test_offset_moves_the_strip_out_and_tilts_it_back_onto_the_panel():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.strip_rect(fr, "top", offset=2.0)
    assert approx(r.centre, (20, 48, 30))
    assert r.normal[1] > 0 and r.normal[2] < 0     # toward the wall and down it
    assert abs(r.normal[0]) < 1e-9                 # still perpendicular to the edge


def test_a_panel_covers_its_span_of_the_front_and_faces_out():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.panel_rect(fr)
    assert approx(r.centre, (20, 50, 20)) and approx(r.normal, (0, -1, 0))
    assert approx(r.half_u, (20, 0, 0)) and approx(r.half_v, (0, 0, 10))
    r = ls.panel_rect(fr, x=(0.0, 0.5), y=(0.5, 1.0), offset=1.0)
    assert approx(r.centre, (10, 49, 25))
    assert approx(r.half_u, (10, 0, 0)) and approx(r.half_v, (0, 0, 5))


def test_a_sloped_console_keeps_top_as_the_higher_edge():
    # A 45° console face rising away from the room (+Y up the slope).
    s = [((0, 0, 0), (20, 0, 0), (20, 10, 10), (0, 10, 10))]
    fr = ls.frame(*_mesh(s), eye=(10, -50, 20))
    assert approx(fr.facing, (0, -math.sqrt(0.5), math.sqrt(0.5)))
    top, bottom = ls.strip_rect(fr, "top"), ls.strip_rect(fr, "bottom")
    assert top.centre[2] > bottom.centre[2]


def test_an_alcove_lights_from_its_lip_into_the_recess():
    # Open toward -Y: back wall at y = 60, top / bottom / side walls y 50..60.
    back = ((0, 60, 0), (30, 60, 0), (30, 60, 20), (0, 60, 20))                 # faces -y
    top = ((0, 50, 20), (0, 60, 20), (30, 60, 20), (30, 50, 20))       # faces down
    bottom = ((0, 50, 0), (30, 50, 0), (30, 60, 0), (0, 60, 0))        # faces up
    left = ((0, 50, 0), (0, 60, 0), (0, 60, 20), (0, 50, 20))          # faces +x
    right = ((30, 50, 0), (30, 50, 20), (30, 60, 20), (30, 60, 0))     # faces -x
    fr = ls.frame(*_mesh([back, top, bottom, left, right]), eye=(15, 0, 10))
    assert approx(fr.facing, (0, -1, 0))
    r = ls.strip_rect(fr, "top")
    assert math.isclose(r.centre[1], 50.0) and math.isclose(r.centre[2], 20.0)
    assert r.normal[1] > 0 and r.normal[2] < 0     # down and back into the alcove


def test_a_closed_shape_faces_the_eye():
    lo, hi = -5, 5
    cube = [((lo, lo, lo), (lo, hi, lo), (hi, hi, lo), (hi, lo, lo)),     # -z
            ((lo, lo, hi), (hi, lo, hi), (hi, hi, hi), (lo, hi, hi)),     # +z
            ((lo, lo, lo), (hi, lo, lo), (hi, lo, hi), (lo, lo, hi)),     # -y
            ((lo, hi, lo), (lo, hi, hi), (hi, hi, hi), (hi, hi, lo)),     # +y
            ((lo, lo, lo), (lo, lo, hi), (lo, hi, hi), (lo, hi, lo)),     # -x
            ((hi, lo, lo), (hi, hi, lo), (hi, hi, hi), (hi, lo, hi))]     # +x
    fr = ls.frame(*_mesh(cube), eye=(0, -100, 30))
    assert approx(fr.facing, (0, -1, 0)) and approx(fr.up, (0, 0, 1))


def test_a_ceiling_piece_tops_on_the_edge_farther_from_the_chair():
    ceil = [((-10, 70, 100), (-10, 90, 100), (10, 90, 100), (10, 70, 100))]   # faces down
    fr = ls.frame(*_mesh(ceil), eye=(0, 0, 20))
    assert approx(fr.facing, (0, 0, -1)) and approx(fr.up, (0, 1, 0))
    assert math.isclose(ls.strip_rect(fr, "top").centre[1], 90.0)


def test_a_ceiling_piece_right_over_the_eye_still_gets_a_frame():
    ceil = [((-10, -10, 100), (-10, 10, 100), (10, 10, 100), (10, -10, 100))]
    fr = ls.frame(*_mesh(ceil), eye=(0, 0, 20))
    assert fr is not None and abs(sum(a * b for a, b in zip(fr.up, fr.facing))) < 1e-9


def test_no_vertices_is_no_frame():
    assert ls.frame([], (0, 0, 0), 0.0, eye=EYE) is None


def test_light_rect_reads_a_lights_keys_with_their_defaults():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    assert ls.light_rect({"shape": "strip", "edge": "top"}, fr) == ls.strip_rect(fr, "top")
    assert ls.light_rect({"shape": "panel", "x": [0, 0.5], "offset": 1}, fr) == \
        ls.panel_rect(fr, x=(0, 0.5), offset=1)

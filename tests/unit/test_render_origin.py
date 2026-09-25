"""The floating render origin, Python half (system-frames Plan 3, Task 6).

The renderer draws the Space pass in RENDER space: view coordinates (the
viewed set's) minus one render origin, the exterior camera eye. Every
Space-pass position crosses into the renderer through frames.to_render,
which is frames.in_view minus that origin:

  * same set, origin (0,0,0): byte-identical to in_view (the point itself),
  * a sibling region: in_view's converted point, minus the origin,
  * another frame: None, whatever the origin.
"""
import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import frames
from tests.helpers.mapped_regions import load_region


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        frames.reset_render_origin()
    _clear()
    yield
    _clear()


@pytest.fixture
def world():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "QuickBattle")
    off = frames.offset_between(ona1, ona2)
    assert off is not None and any(off), "premise: regions differ"
    return ona1, ona2, other, off


P = (450000.25, -3.5, 12.0)
O = (449970.0, 1.0, -2.0)


def test_the_origin_starts_at_zero_and_resets_to_zero():
    assert frames.render_origin() == (0.0, 0.0, 0.0)
    frames.set_render_origin(O)
    assert frames.render_origin() == O
    frames.reset_render_origin()
    assert frames.render_origin() == (0.0, 0.0, 0.0)


def test_same_set_at_origin_zero_is_in_view_itself(world):
    ona1, *_ = world
    got = frames.to_render(ona1, ona1, *P)
    assert got == frames.in_view(ona1, ona1, *P) == P


def test_to_render_is_in_view_minus_the_origin(world):
    ona1, ona2, _other, off = world
    frames.set_render_origin(O)
    assert frames.to_render(ona1, ona1, *P) == (P[0] - O[0], P[1] - O[1],
                                                P[2] - O[2])
    v = frames.in_view(ona1, ona2, *P)
    assert frames.to_render(ona1, ona2, *P) == (v[0] - O[0], v[1] - O[1],
                                                v[2] - O[2])


def test_a_point_450000_gu_out_lands_near_zero_in_render_space(world):
    ona1, *_ = world
    frames.set_render_origin((450000.0, 0.0, 0.0))
    x, y, z = frames.to_render(ona1, ona1, 450030.0, 0.0, 0.0)
    assert (x, y, z) == (30.0, 0.0, 0.0)


def test_another_frame_is_none_whatever_the_origin(world):
    ona1, _ona2, other, _off = world
    assert frames.to_render(ona1, other, *P) is None
    frames.set_render_origin(O)
    assert frames.to_render(ona1, other, *P) is None
    assert frames.to_render(None, ona1, *P) is None


def test_render_to_view_adds_the_origin_back(world):
    ona1, *_ = world
    frames.set_render_origin(O)
    r = frames.to_render(ona1, ona1, *P)
    assert frames.render_to_view(r) == pytest.approx(P, abs=1e-9)
    frames.reset_render_origin()
    assert frames.render_to_view(P) == P


# ── view_offset: a target's set-local points into the renderer's frame ─────

def test_view_offset_moves_a_sibling_sets_point_into_view_coordinates(world):
    ona1, ona2, other, _off = world
    App.g_kSetManager.MakeRenderedSet("Ona1")
    assert frames.viewing_set() is ona1
    assert frames.view_offset(ona2) == frames.offset_between(ona1, ona2)
    assert frames.view_offset(ona1) is None, "same set: no shift at all"
    assert frames.view_offset(other) is None, "another frame: no shift"
    assert frames.view_offset(None) is None

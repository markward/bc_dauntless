"""engine/systems/frames.py — the one accessor for comparing positions across sets."""
import math

import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import frames, resolve
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def _ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _plain_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def test_a_mapped_region_is_in_its_system_frame_at_its_anchor():
    ona1 = load_region("Ona", "Ona1")
    f = frames.frame_of(ona1)
    assert f.key == ("system", "Ona")
    assert f.anchor_gu == pytest.approx(resolve.anchor_of("Ona1"))


def test_an_unmapped_set_is_its_own_frame_with_zero_anchor():
    qb = _plain_set("QuickBattle")
    f = frames.frame_of(qb)
    assert f.key == ("set", qb)
    assert f.anchor_gu == (0.0, 0.0, 0.0)


def test_an_unmapped_set_with_a_region_name_is_its_own_frame():
    """Review Focus 2: a hand-built "Ona1" that no region module mapped holds
    BC-scale positions; shifting them by Ona1's anchor would be wrong."""
    raw = _plain_set("Ona1")
    assert frames.frame_of(raw).key == ("set", raw)
    assert frames.frame_of(raw).anchor_gu == (0.0, 0.0, 0.0)


def test_same_set_offset_is_zero():
    ona1 = load_region("Ona", "Ona1")
    assert frames.offset_between(ona1, ona1) == (0.0, 0.0, 0.0)


def test_two_regions_of_one_system_offset_by_their_anchor_difference():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    assert frames.offset_between(ona1, ona2) == pytest.approx(
        tuple(b - a for a, b in zip(a1, a2)))


def test_different_frames_have_no_offset():
    ona1 = load_region("Ona", "Ona1")
    qb = _plain_set("QuickBattle")
    assert frames.offset_between(ona1, qb) is None
    assert frames.offset_between(None, ona1) is None


def test_same_set_distance_equals_raw_distance():
    """The invariant: same-set pairs are byte-identical to raw positions."""
    ona1 = load_region("Ona", "Ona1")
    a = _ship(ona1, "a", (10.0, 20.0, 30.0))
    b = _ship(ona1, "b", (13.0, 24.0, 30.0))
    assert frames.system_distance(a, b) == 5.0
    assert frames.same_frame(a, b)


def test_cross_region_distance_uses_system_positions():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    # b sits at the SAME system position as a, expressed in Ona2's local frame.
    a = _ship(ona1, "a", (0.0, 0.0, 0.0))
    b = _ship(ona2, "b", tuple(x1 - x2 for x1, x2 in zip(a1, a2)))
    assert frames.system_distance(a, b) == pytest.approx(0.0, abs=1e-6)
    # Same local numbers in two regions are far apart in the system.
    c = _ship(ona2, "c", (0.0, 0.0, 0.0))
    assert frames.system_distance(a, c) == pytest.approx(math.dist(a1, a2))


def test_cross_frame_distance_is_infinite():
    ona1 = load_region("Ona", "Ona1")
    qb = _plain_set("QuickBattle")
    a = _ship(ona1, "a", (0.0, 0.0, 0.0))
    b = _ship(qb, "b", (0.0, 0.0, 0.0))
    assert frames.system_distance(a, b) == math.inf
    assert not frames.same_frame(a, b)


def test_setless_object_has_no_frame():
    loose = App.ShipClass_Create()
    ona1 = load_region("Ona", "Ona1")
    a = _ship(ona1, "a", (0.0, 0.0, 0.0))
    assert frames.frame_of_object(loose) is None
    assert frames.system_distance(a, loose) == math.inf
    assert not frames.same_frame(loose, loose)


def test_system_position_is_local_plus_anchor():
    ona2 = load_region("Ona", "Ona2")
    a = _ship(ona2, "a", (1.0, 2.0, 3.0))
    key, x, y, z = frames.system_position(a)
    ax, ay, az = resolve.anchor_of("Ona2")
    assert key == ("system", "Ona")
    assert (x, y, z) == pytest.approx((ax + 1.0, ay + 2.0, az + 3.0))


def test_local_in_expresses_an_object_in_another_sets_coordinates():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    b = _ship(ona2, "b", (5.0, 0.0, 0.0))
    off = frames.offset_between(ona1, ona2)
    assert frames.local_in(ona1, b) == pytest.approx((5.0 + off[0], off[1], off[2]))
    assert frames.local_in(_plain_set("QuickBattle"), b) is None


def test_viewing_set_prefers_the_explicit_rendered_set():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    App.g_kSetManager.MakeRenderedSet("Ona2")
    assert frames.viewing_set() is ona2


def test_system_of_does_not_deep_copy():
    """frames reads system_of per comparison; it must be an index lookup."""
    import copy
    calls = []
    real = copy.deepcopy
    copy.deepcopy = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        assert resolve.system_of("Ona1") == "Ona"
    finally:
        copy.deepcopy = real
    assert calls == []


def test_containing_set_is_the_public_accessor():
    ona1 = load_region("Ona", "Ona1")
    s = _ship(ona1, "S", (0.0, 0.0, 0.0))
    assert frames.containing_set(s) is ona1
    assert frames.containing_set(None) is None

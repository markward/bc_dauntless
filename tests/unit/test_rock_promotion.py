"""Rock promotion (rock-promotion plan Task 4, spec 2026-10-05 §2-§3): the
nearest big near-band rocks around the player become real RockClass
objects, go back to scenery when the player leaves, and a session record
brings damaged rocks back damaged and never regrows destroyed ones.

Only the renderer is faked (FakeR answers rockfield_query_large from a hit
list in SYSTEM coords); the set, player, rocks and targeting are real.
The viewed set's anchor is the origin, so system == view coords here.
"""
import math

import App
import pytest

from engine.rocks import promotion
from engine.rocks import far_dials
from engine.appc.ships import ShipClass_Create
from tests.helpers.viewed_set import viewed_set, release_viewed_set


class FakeR:
    def __init__(self, hits):
        self.hits = hits              # list of query dicts, system coords
        self.promoted_pushes = []

    def far_enabled(self):
        return True

    def rockfield_query_large(self, c, radius, min_r):
        out = [h for h in self.hits
               if h["radius"] >= min_r and math.dist(h["pos"], c) <= radius]
        return sorted(out, key=lambda h: (math.dist(h["pos"], c), h["key"]))

    def rockfield_set_promoted(self, keys):
        self.promoted_pushes.append(list(keys))


def hit(key, x, y=0.0, z=0.0, radius=4.5, rock=0):
    return {"key": key, "pos": (x, y, z), "radius": radius, "rock": rock,
            "axis": (0.0, 0.0, 1.0), "rate": 0.3, "phase": 1.0}


def _move_player(player, x):
    player.SetTranslateXYZ(x, 0.0, 0.0)


def _move_rock(rock, x):
    rock.SetTranslateXYZ(x, 0.0, 0.0)


@pytest.fixture
def world(monkeypatch):
    """A viewed set holding the player at the origin, anchor (0,0,0)."""
    App.g_kSetManager._sets.clear()
    far_dials.reset()
    pset = viewed_set()
    player = ShipClass_Create("Player")
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    pset.AddObjectToSet(player, "Player")
    monkeypatch.setattr("engine.rocks.far_tier.frame_for",
                        lambda vs: ("Test", (0.0, 0.0, 0.0)))
    promotion.reset()
    yield pset, player
    promotion.reset()
    far_dials.reset()
    release_viewed_set()
    App.g_kSetManager._sets.clear()


def test_promotes_the_nearest_up_to_the_cap(world):
    pset, player = world
    r = FakeR([hit(k, 20.0 * k) for k in range(1, 13)])   # 12 rocks, 20..240 GU
    promotion.tick(player, pset, 0.0, r)
    assert sorted(promotion.promoted()) == list(range(1, 9))
    assert r.promoted_pushes[-1] == list(range(1, 9))


def test_promoted_rock_matches_its_generator_rock(world):
    pset, player = world
    r = FakeR([hit(77, 100.0, 5.0, -3.0, radius=4.37)])
    promotion.tick(player, pset, 2.0, r)
    rock = promotion.promoted()[77]
    loc = rock.GetWorldLocation()
    assert (loc.x, loc.y, loc.z) == pytest.approx((100.0, 5.0, -3.0))
    from engine.rocks.rock import effective_radius
    assert effective_radius(rock) == pytest.approx(4.37)
    assert rock.GetName() == "Field Rock 004D"
    assert not rock.GetName().startswith("Asteroid")
    assert rock.IsTargetable() and rock.IsScannable() and not rock.IsHailable()
    assert pset.GetObject("Field Rock 004D") is rock
    assert rock._field_key == 77


def test_promoted_rock_pose_follows_the_generator_tumble(world):
    pset, player = world
    now = 2.0
    promotion.tick(player, pset, now, FakeR([hit(9, 50.0)]))
    rock = promotion.promoted()[9]
    angle = 1.0 + 0.3 * far_dials.get("near_tumble_scale") * now
    R = rock.GetWorldRotation()
    # Rotation about +Z by `angle`: column 0 is (cos, sin, 0).
    c0 = R.GetCol(0)
    assert (c0.x, c0.y, c0.z) == pytest.approx(
        (math.cos(angle), math.sin(angle), 0.0))
    w = rock.GetAngularVelocity()
    assert (w.x, w.y, w.z) == pytest.approx(
        (0.0, 0.0, 0.3 * far_dials.get("near_tumble_scale")))


def test_small_rocks_and_far_rocks_are_not_promoted(world):
    pset, player = world
    r = FakeR([hit(1, 50.0, radius=3.9), hit(2, 350.0, radius=4.9)])
    promotion.tick(player, pset, 0.0, r)
    assert promotion.promoted() == {}


def test_no_flicker_at_the_range_edge(world):     # Review Focus 1
    pset, player = world
    r = FakeR([hit(5, 299.0)])
    promotion.tick(player, pset, 0.0, r)
    assert 5 in promotion.promoted()
    r.hits = [hit(5, 301.0)]                       # outside promote range, inside demote range
    _move_rock(promotion.promoted()[5], 301.0)
    for t in (1.0, 2.0, 3.0):
        promotion.tick(player, pset, t, r)
    assert 5 in promotion.promoted()


def test_demotes_beyond_the_capped_demote_range(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    _move_player(player, -350.0)                    # rock now 450 GU away (> 400 cap)
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    assert promotion.promoted() == {}
    assert pset.GetObject("Field Rock 0005") is None
    assert r.promoted_pushes[-1] == []


def test_demote_range_is_capped_below_the_billboard_edge(world):
    """R1: 300 x 1.5 = 450 would outrun the large billboard edge
    (405 - 4 - 1 = 400); a rock 420 GU away is demoted."""
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    _move_player(player, -320.0)                    # 420 GU: < 450, > 400
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    assert promotion.promoted() == {}


def test_targeted_rock_is_not_demoted(world):     # Review Focus 2
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    player.SetTarget(promotion.promoted()[5].GetName())
    assert player.GetTarget() is promotion.promoted()[5]
    _move_player(player, -600.0)
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    assert 5 in promotion.promoted()


def test_dying_rock_is_reaped_without_a_set_call(world, monkeypatch):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    rock = promotion.promoted()[5]
    monkeypatch.setattr("engine.rocks.death.is_dying_rock",
                        lambda x: x is rock)
    _move_player(player, -600.0)
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    assert 5 not in promotion.promoted()
    assert pset.GetObject("Field Rock 0005") is rock   # death owns removal
    assert 5 in r.promoted_pushes[-1]


def test_a_nearer_candidate_replaces_the_farthest_when_full(world):
    pset, player = world
    r = FakeR([hit(k, 20.0 * k) for k in range(1, 9)])    # 8 rocks, 20..160
    promotion.tick(player, pset, 0.0, r)
    assert sorted(promotion.promoted()) == list(range(1, 9))
    r.hits = r.hits + [hit(99, 10.0)]                     # nearer than all
    promotion.tick(player, pset, 1.0, r)
    assert sorted(promotion.promoted()) == [1, 2, 3, 4, 5, 6, 7, 99]
    assert pset.GetObject("Field Rock 0008") is None


def test_a_full_set_keeps_a_targeted_farthest_rock(world):
    pset, player = world
    r = FakeR([hit(k, 20.0 * k) for k in range(1, 9)])
    promotion.tick(player, pset, 0.0, r)
    player.SetTarget(promotion.promoted()[8].GetName())
    r.hits = r.hits + [hit(99, 10.0)]
    promotion.tick(player, pset, 1.0, r)
    assert 8 in promotion.promoted() and 99 in promotion.promoted()
    assert 7 not in promotion.promoted()
    assert len(promotion.promoted()) == 8


def test_damaged_rock_comes_back_damaged(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    hull = promotion.promoted()[5].GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.25)
    _move_player(player, -600.0)
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    _move_player(player, 0.0)
    r.hits = [hit(5, 100.0)]
    promotion.tick(player, pset, 2.0, r)
    h2 = promotion.promoted()[5].GetHull()
    assert h2.GetCondition() / h2.GetMaxCondition() == pytest.approx(0.25)


def test_destroyed_rock_never_regrows(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    rock = promotion.promoted()[5]
    pset.RemoveObjectFromSet(rock.GetName())        # what ship_death.retire does
    promotion.tick(player, pset, 1.0, r)
    assert 5 not in promotion.promoted()
    promotion.tick(player, pset, 2.0, r)
    assert 5 not in promotion.promoted()
    assert 5 in r.promoted_pushes[-1]               # stays excluded natively


def test_rate_limited(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    n = len(r.promoted_pushes)
    r.hits = [hit(5, 100.0), hit(6, 110.0)]
    promotion.tick(player, pset, 0.1, r)            # < 1/4 s later
    assert 6 not in promotion.promoted() and len(r.promoted_pushes) == n


def test_pushes_the_exclusion_on_every_acting_tick(world):
    """Controller ruling R-A: native drops the exclusion when the field's
    sources change, so the list is re-pushed every acting tick even when
    nothing changed."""
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    promotion.tick(player, pset, 1.0, r)
    promotion.tick(player, pset, 2.0, r)
    assert r.promoted_pushes == [[5], [5], [5]]


def test_muted_while_dashing(world, monkeypatch):
    pset, player = world
    monkeypatch.setattr("engine.rocks.minor_contact._muted", lambda p: True)
    promotion.tick(player, pset, 0.0, FakeR([hit(5, 100.0)]))
    assert promotion.promoted() == {}


def test_muted_when_the_player_is_not_in_the_viewed_set(world):
    pset, player = world
    from engine.appc.sets import SetClass_Create
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Other")
    promotion.tick(player, other, 0.0, FakeR([hit(5, 100.0)]))
    assert promotion.promoted() == {}


def test_muted_when_the_field_is_disabled(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    r.far_enabled = lambda: False
    promotion.tick(player, pset, 0.0, r)
    assert promotion.promoted() == {}


def test_tick_never_raises_on_a_broken_renderer(world):
    pset, player = world

    class Broken(FakeR):
        def rockfield_query_large(self, *a):
            raise RuntimeError("boom")

        def rockfield_set_promoted(self, keys):
            raise RuntimeError("boom")

    promotion.tick(player, pset, 0.0, Broken([]))
    promotion.tick(None, pset, 1.0, Broken([]))
    assert promotion.promoted() == {}


def test_reset_removes_objects_and_forgets(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    promotion.reset(r)
    assert promotion.promoted() == {}
    assert pset.GetObject("Field Rock 0005") is None
    assert r.promoted_pushes[-1] == []


def test_promoted_rocks_get_no_halo(world):
    pset, player = world
    promotion.tick(player, pset, 0.0, FakeR([hit(5, 100.0)]))
    from engine.rocks import minors
    assert minors.halo_spec(promotion.promoted()[5], iid=1) is None


def test_field_name():
    assert promotion.field_name(0x1234ABCD) == "Field Rock ABCD"


def test_promotion_dials_are_python_only():
    from engine.rocks import far_dials as fd
    assert fd.DEFAULTS["promote_min_radius_gu"] == 4.0
    assert fd.DEFAULTS["promote_range_gu"] == 300.0
    assert fd.DEFAULTS["promote_max"] == 8
    assert fd.DEFAULTS["demote_range_mult"] == 1.5
    assert fd.DEFAULTS["promote_hz"] == 4.0
    assert fd.DEFAULTS["avoid_query_radius_gu"] == 150.0
    assert not (fd.PROMOTION_KEYS & fd.NATIVE_KEYS)


def test_promotion_dials_do_not_repush_far_tier_sources():
    from engine.rocks import far_tier
    far_tier.reset()
    try:
        far_tier.on_dials_changed({"promote_range_gu", "promote_hz"})
        assert far_tier._sources_dirty is False
        assert far_tier._dials_dirty is False
    finally:
        far_tier.reset()


def test_promotion_and_ramp_dials_sit_together_in_the_rock_fields_group():
    """Controller ruling R-B: the six promotion dials and large_ramp_lo/hi
    are adjacent in the / L O order, with additive steps."""
    order = list(far_dials.DIAL_ORDER)
    keys = ["promote_min_radius_gu", "promote_range_gu", "promote_max",
            "demote_range_mult", "promote_hz", "avoid_query_radius_gu",
            "large_ramp_lo", "large_ramp_hi"]
    i = order.index(keys[0])
    assert order[i:i + len(keys)] == keys
    d = far_dials.DEFAULTS
    s = far_dials.step
    assert s(d, "large_ramp_lo", +1)["large_ramp_lo"] == pytest.approx(0.55)
    assert s(d, "large_ramp_hi", +1)["large_ramp_hi"] == pytest.approx(1.0)  # clamped
    assert s(d, "promote_min_radius_gu", -1)["promote_min_radius_gu"] == pytest.approx(3.75)
    assert s(d, "promote_range_gu", +1)["promote_range_gu"] == pytest.approx(325.0)
    assert s(d, "promote_max", +1)["promote_max"] == 9
    assert s(d, "demote_range_mult", +1)["demote_range_mult"] == pytest.approx(1.6)
    assert s(d, "promote_hz", +1)["promote_hz"] == pytest.approx(5.0)
    assert s({**d, "promote_hz": 1.0}, "promote_hz", -1)["promote_hz"] == pytest.approx(1.0)
    assert s(d, "avoid_query_radius_gu", +1)["avoid_query_radius_gu"] == pytest.approx(175.0)

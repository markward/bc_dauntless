"""engine/systems/handoff.py -- the player hand-off between regions.

Spec: docs/superpowers/specs/2026-09-25-in-system-warp-design.md section 3.
Ships here are built bare, as tests/unit/test_warp_flight.py does; regions
are created through BC's own region module
(tests/helpers/mapped_regions.load_region) so they are mapped exactly as
they would be in play.
"""
import math

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.warp_flight import WarpFlight
from engine.systems import frames, handoff, resolve
from tests.helpers.mapped_regions import load_region

_MARGIN = handoff.HANDOFF_MARGIN_GU


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def _make_ship(xyz, pSet, name="player"):
    s = ShipClass()
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


@pytest.fixture
def posted(monkeypatch):
    """Every event the engine posts during the test, in order."""
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


# ── 1. hand_off keeps system_position, rotation and velocity ───────────────

def test_hand_off_keeps_system_position_rotation_and_velocity():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1 = resolve.anchor_of("Ona1")
    ship = _make_ship((10.0, 20.0, 30.0), ona1)
    ship.AlignToVectors(TGPoint3(1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    ship.SetVelocity(TGPoint3(1.5, -2.5, 3.5))
    before = frames.system_position(ship)
    fwd_before = ship.GetWorldRotation().GetCol(1)
    v_before = ship.GetVelocity()

    handoff.hand_off(ship, ona2)

    assert ona1.GetObject("player") is None
    assert ona2.GetObject("player") is ship
    after = frames.system_position(ship)
    assert after[0] == before[0]
    assert after[1:] == pytest.approx(before[1:], abs=1e-6)
    fwd_after = ship.GetWorldRotation().GetCol(1)
    assert (fwd_after.x, fwd_after.y, fwd_after.z) == pytest.approx(
        (fwd_before.x, fwd_before.y, fwd_before.z))
    v_after = ship.GetVelocity()
    assert (v_after.x, v_after.y, v_after.z) == pytest.approx(
        (v_before.x, v_before.y, v_before.z))
    # Sanity: system_position actually moved in Ona1's own frame.
    assert a1 is not None


# ── 2. Event order: ET_EXITED_SET, ET_ENTERED_SET, ET_EXITED_WARP ──────────

def test_hand_off_posts_exited_set_then_entered_set_then_exited_warp(posted):
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    ship = _make_ship((0.0, 0.0, 0.0), ona1)
    events = posted
    events.clear()   # drop the ET_ENTERED_SET from _make_ship's own AddObjectToSet

    handoff.hand_off(ship, ona2)

    types = [e.GetEventType() for e in events]
    assert types == [App.ET_EXITED_SET, App.ET_ENTERED_SET, App.ET_EXITED_WARP]
    exited_warp = events[-1]
    assert exited_warp.GetSource() is ship


# ── 3. tick hands off across a real system map ──────────────────────────────

def test_tick_hands_off_into_the_sphere_that_now_contains_the_player():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    # System position == Ona2's own anchor: dead centre of its sphere, and
    # a1<->a2 is ~100,000 GU apart -- nowhere near Ona1's radius + margin.
    local = tuple(a2[i] - a1[i] for i in range(3))
    ship = _make_ship(local, ona1)
    App.Game_SetCurrentPlayer(ship)

    dest = handoff.tick(ship)

    assert dest is ona2
    assert ona2.GetObject("player") is ship
    assert ona1.GetObject("player") is None


# ── 4. Rule H: hysteresis, no flicker circling a sphere's edge ─────────────

def test_rule_h_just_outside_radius_but_within_margin_is_no_op():
    ona1 = load_region("Ona", "Ona1")
    load_region("Ona", "Ona2")
    r1 = resolve.map_of("Ona").region("Ona1").radius_gu
    ship = _make_ship((r1 + 500.0, 0.0, 0.0), ona1)
    App.Game_SetCurrentPlayer(ship)

    assert handoff.tick(ship) is None
    assert ona1.GetObject("player") is ship


def test_rule_h_circling_the_new_spheres_edge_never_hands_back():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    local = tuple(a2[i] - a1[i] for i in range(3))
    ship = _make_ship(local, ona1)
    App.Game_SetCurrentPlayer(ship)
    assert handoff.tick(ship) is ona2

    r2 = resolve.map_of("Ona").region("Ona2").radius_gu
    for delta in (10.0, -10.0, 10.0, -10.0):
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(r2 + delta, p.y, p.z)
        assert handoff.tick(ship) is None
        assert ona2.GetObject("player") is ship
        assert ona1.GetObject("player") is None


# ── 5. Deferred during a dash ───────────────────────────────────────────────

def test_tick_defers_while_the_player_is_dashing():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    local = tuple(a2[i] - a1[i] for i in range(3))
    ship = _make_ship(local, ona1)
    App.Game_SetCurrentPlayer(ship)
    ship.begin_warp_flight(WarpFlight(heading=(1.0, 0.0, 0.0),
                                      speed_policy="heading"))

    assert handoff.tick(ship) is None
    assert ona1.GetObject("player") is ship
    assert ona2.GetObject("player") is None


def test_tick_does_not_defer_an_ai_policy_flight_on_the_player():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    local = tuple(a2[i] - a1[i] for i in range(3))
    ship = _make_ship(local, ona1)
    App.Game_SetCurrentPlayer(ship)
    target = _make_ship((0.0, 0.0, 0.0), ona1, "target")
    ship._insystem_warp_transit = WarpFlight(target=target, speed_policy="ai")

    assert handoff.tick(ship) is ona2


# ── 6. Rule N: an NPC is never handed off ───────────────────────────────────

def test_tick_never_moves_an_npc():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    local = tuple(a2[i] - a1[i] for i in range(3))
    npc = _make_ship(local, ona1, "npc")
    # No current player set at all -- npc is definitely not it.

    assert handoff.tick(npc) is None
    assert ona1.GetObject("npc") is npc
    assert ona2.GetObject("npc") is None


# ── 7. Review Focus 4: an unmapped set posts nothing ────────────────────────

def test_tick_in_an_unmapped_set_returns_none_and_posts_nothing(posted):
    from engine.appc.sets import SetClass_Create
    arena = SetClass_Create()
    App.g_kSetManager.AddSet(arena, "Arena")
    ship = _make_ship((0.0, 0.0, 0.0), arena)
    App.Game_SetCurrentPlayer(ship)
    posted.clear()

    assert handoff.tick(ship) is None
    assert posted == []


# ── 8. The target is cleared on hand-off ────────────────────────────────────

def test_hand_off_clears_the_players_target():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    ship = _make_ship((0.0, 0.0, 0.0), ona1)
    target = _make_ship((0.0, 0.0, 0.0), ona1, "target")
    ship.SetTarget(target)
    assert ship.GetTarget() is target

    handoff.hand_off(ship, ona2)

    assert ship.GetTarget() is None


# ── 9. Fix round R11.2: a cross-frame hand_off must fail loud ───────────────

def test_hand_off_raises_when_src_and_dest_are_not_the_same_frame():
    from engine.appc.sets import SetClass_Create
    ona1 = load_region("Ona", "Ona1")
    arena = SetClass_Create()
    App.g_kSetManager.AddSet(arena, "Arena")
    ship = _make_ship((0.0, 0.0, 0.0), arena)

    with pytest.raises(ValueError, match="Ona1"):
        handoff.hand_off(ship, ona1)

    # The failed rebase left the player exactly where it was.
    assert arena.GetObject("player") is ship
    assert ona1.GetObject("player") is None


# ── 10. Fix round R11.3: region_at directly ─────────────────────────────────

def test_region_at_returns_the_containing_sphere():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    # Dead centre of Ona2's own sphere, held in Ona1's set-local coordinates.
    local = tuple(a2[i] - a1[i] for i in range(3))
    ship = _make_ship(local, ona1)

    assert handoff.region_at(ship) is ona2


def test_region_at_returns_none_in_open_space():
    ona1 = load_region("Ona", "Ona1")
    load_region("Ona", "Ona2")
    r1 = resolve.map_of("Ona").region("Ona1").radius_gu
    # Just past Ona1's own radius (well past the margin too) and nowhere near
    # any other loaded region's sphere -- open space.
    ship = _make_ship((r1 + 50000.0, 0.0, 0.0), ona1)

    assert handoff.region_at(ship) is None


# ── 11. Mark 2026-09-28: arriving near a planet from ANY side enters ──────
#
# A region contains the player inside its sphere OR within reach(body) =
# arrival_range(body) + HANDOFF_MARGIN_GU of any body it owns. Ona 2's sphere
# sits on its Player Start side of the planet (anchor == Player Start, 4,058
# GU from the centre; radius 7,358), so the far side of the planet is outside
# the sphere but inside the planet's reach (5,558).

def _ona2_far_side(dist_gu):
    """System point `dist_gu` from Ona 2's centre, directly AWAY from
    Ona2's anchor (the side the sphere does not cover)."""
    m = resolve.map_of("Ona")
    centre = m.body("Ona 2").position_gu
    anchor = m.region("Ona2").anchor_gu
    a = [anchor[i] - centre[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in a))
    return tuple(centre[i] - dist_gu * a[i] / n for i in range(3))


def _local_in_ona1(system_point):
    a1 = resolve.anchor_of("Ona1")
    return tuple(system_point[i] - a1[i] for i in range(3))


def _local_in_ona2(system_point):
    a2 = resolve.anchor_of("Ona2")
    return tuple(system_point[i] - a2[i] for i in range(3))


def test_arrival_range_is_the_distance_from_the_body_to_the_player_start():
    load_region("Ona", "Ona2")
    body = resolve.map_of("Ona").body("Ona 2")
    ps = frames.system_position(
        App.g_kSetManager.GetSet("Ona2").GetObject("Player Start"))
    assert handoff.arrival_range(body) == pytest.approx(
        math.dist(body.position_gu, ps[1:]))
    assert handoff.region_reach(body) == pytest.approx(
        handoff.arrival_range(body) + _MARGIN)


def test_reach_falls_back_to_two_radii_when_the_region_is_not_loaded():
    body = resolve.map_of("Ona").body("Ona 2")      # Ona2 never loaded
    assert handoff.arrival_range(body) is None
    assert handoff.region_reach(body) == pytest.approx(
        2.0 * body.radius_gu + _MARGIN)


def test_impulse_approach_from_the_far_side_hands_off_within_reach():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    region = resolve.map_of("Ona").region("Ona2")
    body = resolve.map_of("Ona").body("Ona 2")
    p = _ona2_far_side(5000.0)
    assert math.dist(p, region.anchor_gu) > region.radius_gu     # off-sphere
    assert 5000.0 <= handoff.region_reach(body)
    ship = _make_ship(_local_in_ona1(p), ona1)
    App.Game_SetCurrentPlayer(ship)

    assert handoff.tick(ship) is ona2
    assert frames.system_position(ship)[1:] == pytest.approx(p, abs=1e-6)


def test_a_point_outside_both_sphere_and_reach_does_not_hand_off():
    ona1 = load_region("Ona", "Ona1")
    load_region("Ona", "Ona2")
    body = resolve.map_of("Ona").body("Ona 2")
    p = _ona2_far_side(handoff.region_reach(body) + 10.0)
    ship = _make_ship(_local_in_ona1(p), ona1)
    App.Game_SetCurrentPlayer(ship)

    assert handoff.region_at(ship) is None
    assert handoff.tick(ship) is None
    assert ona1.GetObject("player") is ship


def test_rule_h_holds_the_region_until_beyond_reach_plus_margin(monkeypatch):
    """Inside Ona2 on the far side of its planet, with another region
    claiming the point (region_at forced to Ona1): the player stays while
    within reach + margin of Ona 2 -- circling the reach edge never
    flickers -- and leaves only once beyond it (and beyond the sphere +
    margin, which the far side already is)."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    region = resolve.map_of("Ona").region("Ona2")
    reach = handoff.region_reach(resolve.map_of("Ona").body("Ona 2"))
    ship = _make_ship(_local_in_ona2(_ona2_far_side(1000.0)), ona2)
    App.Game_SetCurrentPlayer(ship)
    monkeypatch.setattr(handoff, "region_at", lambda _p: ona1)

    for d in (reach - 10.0, reach + 10.0, reach + _MARGIN - 10.0, reach):
        ship.SetTranslateXYZ(*_local_in_ona2(_ona2_far_side(d)))
        assert handoff.tick(ship) is None
        assert ona2.GetObject("player") is ship

    p = _ona2_far_side(reach + _MARGIN + 10.0)
    assert math.dist(p, region.anchor_gu) > region.radius_gu + _MARGIN
    ship.SetTranslateXYZ(*_local_in_ona2(p))
    assert handoff.tick(ship) is ona1


def test_overlapping_regions_prefer_the_nearest_owned_body_or_sphere():
    """Synthetic map: two regions whose containments both hold the point.
    The one whose nearest shape centre (sphere anchor or owned body) is
    closer wins, whichever order the regions are listed in."""
    from engine.systems.map import Body, Region, SystemMap
    m = SystemMap(system="Synth", bodies=[
        Body(name="A b", display_name="A b", radius_gu=1000.0,
             position_gu=(0.0, 0.0, 0.0), owner_region="SynthA"),
        Body(name="B b", display_name="B b", radius_gu=1000.0,
             position_gu=(6000.0, 0.0, 0.0), owner_region="SynthB"),
    ], regions=[
        Region(set_name="SynthA", anchor_gu=(-9000.0, 0.0, 0.0),
               radius_gu=20000.0),
        Region(set_name="SynthB", anchor_gu=(50000.0, 0.0, 0.0),
               radius_gu=100.0),
    ])
    # Unloaded sets: reach = 2 * 1000 + margin = 3500. The point is 3400
    # from B's body (in its reach) and inside A's big sphere; A's nearest
    # centre is its body, 2600 away -- closer than B's 3400.
    p = (2600.0, 0.0, 0.0)
    assert handoff.nearest_region(m, p, ["SynthA", "SynthB"]) == "SynthA"
    assert handoff.nearest_region(m, p, ["SynthB", "SynthA"]) == "SynthA"
    q = (4000.0, 0.0, 0.0)          # 4000 from A's body, 2000 from B's
    assert handoff.nearest_region(m, q, ["SynthA", "SynthB"]) == "SynthB"
    assert handoff.nearest_region(m, (0.0, 90000.0, 0.0),
                                  ["SynthA", "SynthB"]) is None

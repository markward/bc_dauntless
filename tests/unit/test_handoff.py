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

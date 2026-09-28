"""An AI in-system warp (``ShipClass.InSystemWarp``, "ai" policy) signals
warp and waits for the ship's articulated parts, like the player's dash
(in-system-warp spec section 1; Mark's option A, 2026-09-28).

* Accepted with parts to move: ``WES_WARP_INITIATED`` at once, and the ship
  does not leave at warp speed until ``time_to_reach(ship, "warp")`` + one
  tick has passed; it flies its impulse orders meanwhile (the SDK's Intercept
  keeps turning it), InSystemWarp keeps returning 1 and IsDoingInSystemWarp
  is 1. Then ``WES_WARPING`` and the flight exactly as before.
* No parts: no hold; ``WES_WARPING`` from acceptance.
* Every end -- arrival and each abort -- puts it back to ``WES_NOT_WARPING``.
* The player's dash policies keep managing their own state (dash.py).
"""
import pytest

import App
from engine.appc import articulation, articulated_part as ap, warp_flight
from engine.appc.math import TGPoint3
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.ships import ShipClass
from engine.appc.subsystems import WarpEngineSubsystem
from engine.core.loop import TICK_DELTA

_DT = TICK_DELTA
_WES = WarpEngineSubsystem
_WARP_SPEED = ShipClass.IN_SYSTEM_WARP_SPEED_GUPS


def _state(ship):
    return ship.GetWarpEngineSubsystem().GetWarpState()


def _npc_and_target(dy=10000.0):
    ship = ShipClass()
    ship.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Drive"))
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)          # identity: nose on +Y
    target = ShipClass()
    target.SetTranslateXYZ(0.0, dy, 0.0)
    return ship, target


def _parts_need(monkeypatch, seconds):
    monkeypatch.setattr(articulation, "time_to_reach",
                        lambda ship, state: seconds if state == "warp" else 0.0)


def _run_until_done(ship, max_ticks=200_000):
    for _ in range(max_ticks):
        if ship._insystem_warp_transit is None:
            return
        _step_ship_motion(ship, _DT)
    raise AssertionError("warp transit never completed")


# ── rigged: signal at once, hold for the parts ─────────────────────────────

def test_rigged_npc_enters_warp_initiated_at_acceptance(monkeypatch):
    _parts_need(monkeypatch, 1.0)
    ship, target = _npc_and_target()
    assert ship.InSystemWarp(target, 100.0) == 1
    assert _state(ship) == _WES.WES_WARP_INITIATED
    assert ship.IsDoingInSystemWarp() == 1


def test_rigged_npc_holds_until_the_parts_settle_then_flies(monkeypatch):
    _parts_need(monkeypatch, 1.0)
    ship, target = _npc_and_target()
    assert ship.InSystemWarp(target, 100.0) == 1
    t_parts = 1.0 + TICK_DELTA
    elapsed = 0.0
    while elapsed + _DT < t_parts - 1e-9:
        _step_ship_motion(ship, _DT)
        elapsed += _DT
        # No warp-speed translation during the hold (no impulse orders here,
        # so it does not move at all), and the warp is still "in progress".
        assert ship.GetTranslate().y == pytest.approx(0.0)
        assert _state(ship) == _WES.WES_WARP_INITIATED
        assert ship.InSystemWarp(target, 100.0) == 1
        assert ship.IsDoingInSystemWarp() == 1
    # The tick that reaches t_parts engages: WES_WARPING and a warp-speed step.
    _step_ship_motion(ship, _DT)
    assert _state(ship) == _WES.WES_WARPING
    assert ship.GetTranslate().y == pytest.approx(_WARP_SPEED * _DT)
    _run_until_done(ship)
    assert ship.GetTranslate().y == pytest.approx(10000.0 - 100.0)
    assert _state(ship) == _WES.WES_NOT_WARPING


def test_rigged_npc_coasts_on_its_impulse_orders_during_the_hold(monkeypatch):
    """The hold flies the ship's own impulse orders (the ones Intercept set
    before the warp was accepted): it cruises along its nose at impulse,
    never at warp speed."""
    _parts_need(monkeypatch, 1.0)
    ship, target = _npc_and_target()
    ship.SetSpeed(2.0, TGPoint3(0.0, 1.0, 0.0),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship._current_speed = 2.0
    assert ship.InSystemWarp(target, 100.0) == 1
    for _ in range(30):
        _step_ship_motion(ship, _DT)
    assert ship.GetTranslate().y == pytest.approx(2.0 * 30 * _DT, rel=1e-6)
    assert _state(ship) == _WES.WES_WARP_INITIATED


# ── unrigged: no hold, WES_WARPING while flying ────────────────────────────

def test_unrigged_npc_warps_at_once_and_reads_warping_in_flight(monkeypatch):
    _parts_need(monkeypatch, 0.0)
    ship, target = _npc_and_target()
    assert ship.InSystemWarp(target, 100.0) == 1
    assert _state(ship) == _WES.WES_WARPING
    _step_ship_motion(ship, _DT)
    assert ship.GetTranslate().y == pytest.approx(_WARP_SPEED * _DT)
    assert _state(ship) == _WES.WES_WARPING
    _run_until_done(ship)
    assert _state(ship) == _WES.WES_NOT_WARPING


def test_a_refused_warp_leaves_the_state_alone(monkeypatch):
    _parts_need(monkeypatch, 1.0)
    ship, target = _npc_and_target()
    target.SetTranslateXYZ(9000.0, 100.0, 0.0)   # far off the nose
    assert ship.InSystemWarp(target, 100.0) == 0
    assert _state(ship) == _WES.WES_NOT_WARPING


# ── every end puts the state back ──────────────────────────────────────────

def _abort_stop(ship, target):
    ship.StopInSystemWarp()


def _abort_set_ai(ship, target):
    ship.SetAI(None)


def _abort_clear_ai(ship, target):
    ship.ClearAI()


def _abort_complete_stop(ship, target):
    ship.CompleteStop()


def _abort_death(ship, target):
    from engine.appc import ship_death
    ship_death._mark_dead(ship)


def _abort_target_lost(ship, target):
    ship._insystem_warp_transit.target = object()
    _step_ship_motion(ship, _DT)


def _abort_left_frame(ship, target):
    orig = warp_flight.target_local
    warp_flight.target_local = lambda s, t: None
    try:
        _step_ship_motion(ship, _DT)
    finally:
        warp_flight.target_local = orig


_ABORTS = [_abort_stop, _abort_set_ai, _abort_clear_ai, _abort_complete_stop,
           _abort_death, _abort_target_lost, _abort_left_frame]


@pytest.mark.parametrize("abort", _ABORTS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("parts", [1.0, 0.0], ids=["in_hold", "in_flight"])
def test_every_abort_returns_to_not_warping(monkeypatch, abort, parts):
    _parts_need(monkeypatch, parts)
    ship, target = _npc_and_target()
    assert ship.InSystemWarp(target, 100.0) == 1
    _step_ship_motion(ship, _DT)
    assert _state(ship) != _WES.WES_NOT_WARPING
    abort(ship, target)
    assert ship._insystem_warp_transit is None
    assert _state(ship) == _WES.WES_NOT_WARPING


# ── the player's dash policies are dash.py's to manage ─────────────────────

@pytest.mark.parametrize("policy", ["set_course", "heading"])
def test_dash_policies_do_not_touch_the_warp_state(policy):
    ship = ShipClass()
    ship.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Drive"))
    ship.GetWarpEngineSubsystem().SetWarpState(_WES.WES_WARPING)
    ship.begin_warp_flight(warp_flight.WarpFlight(
        heading=(0.0, 1.0, 0.0), speed_policy=policy))
    ship._end_in_system_warp("aborted")
    assert _state(ship) == _WES.WES_WARPING


# ── the parts actually swing to their warp pose ────────────────────────────

def test_npc_parts_reach_their_warp_pose_before_it_leaves(monkeypatch):
    """A real (monkeypatched-rig) articulated NPC: its parts head for the
    warp pose at acceptance, have settled by the time it leaves at warp
    speed, and head back to cruise once it has arrived."""
    part = ap.ArticulatedPartProperty_Create("wing")
    part.SetAnchor(0.0, 0.0, 0.0)
    part.SetTransitionSeconds(0.5)
    part.SetStatePose("warp", 0.0, 0.0, 0.0, 0.0, 90.0, 0.0)
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: (part,) if leaf == "rigtest" else ())
    articulation.set_dev_override(None)
    ship, target = _npc_and_target()
    ship._articulation_leaf = "rigtest"
    warp_pose = articulation.target_pose(part, "warp")
    assert ship.InSystemWarp(target, 100.0) == 1
    assert articulation.state_for(ship) == "warp"
    left_at = None
    for _ in range(20_000):
        if ship._insystem_warp_transit is None:
            break
        # The loop's order: the parts tick, then the ship moves.
        articulation.tick_ship(ship, _DT)
        y0 = ship.GetTranslate().y
        _step_ship_motion(ship, _DT)
        if left_at is None and ship.GetTranslate().y - y0 > 1.0:
            left_at = ship._articulation_poses["wing"]
    assert left_at is not None
    assert articulation._poses_equal(left_at, warp_pose)
    assert articulation.state_for(ship) == "cruise"

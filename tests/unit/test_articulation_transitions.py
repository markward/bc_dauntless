"""Transitions between state poses (spec 2026-09-25 §4.1)."""
import math

import pytest

from engine.appc import articulation, articulated_part as ap, part_pose as pp


def _part():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetAnchor(0.0, 0.0, 0.0)
    p.SetTransitionSeconds(2.0)
    p.SetStatePose("cruise", 0.0, 0.0, 0.0, 0.0, 90.0, 0.0)
    return p


class _Ship:
    def __init__(self, part, state):
        self._part, self.state = part, state
        self._articulation_leaf = "rigtest"


@pytest.fixture
def rig(monkeypatch):
    part = _part()
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: (part,) if leaf == "rigtest" else ())
    monkeypatch.setattr(articulation, "state_for", lambda ship: ship.state)
    return part


def _tip(ship, part):
    return pp.apply(articulation.pose_for_part(ship, part), (1.0, 0.0, 0.0))


def test_a_transition_takes_transition_seconds(rig):
    ship = _Ship(rig, "cruise")
    articulation.tick_ship(ship, 1.0)
    assert 0.0 < math.dist(_tip(ship, rig), (1.0, 0.0, 0.0)) < math.sqrt(2)
    articulation.tick_ship(ship, 1.0)
    assert _tip(ship, rig) == pytest.approx(
        pp.apply(rig.pose_for("cruise"), (1.0, 0.0, 0.0)), abs=1e-9)


def test_interrupted_transition_starts_from_the_current_pose(rig):
    """Review focus #2: never snaps back to the start."""
    ship = _Ship(rig, "cruise")
    articulation.tick_ship(ship, 1.0)
    mid = _tip(ship, rig)
    ship.state = "red"                     # red = NIF pose (identity)
    articulation.tick_ship(ship, 1e-6)
    assert math.dist(_tip(ship, rig), mid) < 1e-3, "must not jump"
    articulation.tick_ship(ship, 5.0)
    assert _tip(ship, rig) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_a_settled_part_does_not_restart(rig):
    ship = _Ship(rig, "cruise")
    articulation.tick_ship(ship, 5.0)
    articulation.tick_ship(ship, 0.1)
    assert not getattr(ship, "_articulation_transitions", {})


def test_force_part_pose_poses_only_that_part(rig):
    ship = _Ship(rig, "red")
    articulation.force_part_pose(ship, "left wing", rig.pose_for("cruise"))
    assert _tip(ship, rig) == pytest.approx(
        pp.apply(rig.pose_for("cruise"), (1.0, 0.0, 0.0)))
    articulation.force_pose(ship, None)
    assert _tip(ship, rig) == pytest.approx((1.0, 0.0, 0.0))


# ── Interrupted swings keep the old constant-rate feel (fix round 1) ────────
#
# A transition's duration is transition_seconds x the fraction of the part's
# full swing still to travel, so a partial move takes proportionally less --
# which is exactly the old constant-rate `ease_angle` for a hinge.

def _hinge_rig(monkeypatch, pivot=(0.0, 0.0, 0.0), deg=45.0,
               states=("cruise",)):
    part = ap.ArticulatedPartProperty_Create("left wing")
    part.SetAnchor(*pivot)
    part.SetTransitionSeconds(2.0)
    p6 = pp.pose_to6(pp.hinge_pose(pivot, (0.0, 1.0, 0.0), deg))
    for s in states:
        part.SetStatePose(s, *p6)
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: (part,) if leaf == "rigtest" else ())
    monkeypatch.setattr(articulation, "state_for", lambda ship: ship.state)
    return part


def test_reversing_mid_swing_takes_the_remaining_time(monkeypatch):
    part = _hinge_rig(monkeypatch)
    ship = _Ship(part, "cruise")
    articulation.tick_ship(ship, 1.0)              # halfway: 22.5 degrees
    ship.state = "red"
    articulation.tick_ship(ship, 0.5)
    assert not pp.is_identity(articulation.pose_for_part(ship, part), 1e-6), (
        "0.5 s into a 1 s return it must not be home yet")
    articulation.tick_ship(ship, 0.5)
    assert _tip(ship, part) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_switching_between_states_with_the_same_pose_does_not_restart(
        monkeypatch):
    part = _hinge_rig(monkeypatch, states=("cruise", "yellow"))
    ship = _Ship(part, "cruise")
    articulation.tick_ship(ship, 1.0)
    ship.state = "yellow"
    articulation.tick_ship(ship, 0.25)
    # Literally not restarted: the in-flight record keeps its ORIGINAL start
    # pose (the NIF pose) and progress, only re-labelled to "yellow". (With
    # the proportional duration a restart would trace the same path, so the
    # record is the only place the difference is observable.)
    pose0, st, u = ship._articulation_transitions["left wing"][:3]
    assert pose0 == pp.IDENTITY
    assert st == "yellow"
    assert u == pytest.approx(0.625)
    articulation.tick_ship(ship, 0.75)
    assert _tip(ship, part) == pytest.approx(
        pp.apply(part.pose_for("cruise"), (1.0, 0.0, 0.0)), abs=1e-9)


def test_bop_interrupted_swing_matches_the_old_constant_rate_ease(monkeypatch):
    """Reference: the retired `ease_angle` -- the angle moves toward the
    target at 45 deg / 2 s, clamped -- computed inline, against a schedule of
    state flips at uneven dt."""
    pivot = (-0.16, 0.0, 0.05)
    part = _hinge_rig(monkeypatch, pivot=pivot, deg=45.0,
                      states=("cruise", "yellow", "warp"))
    ship = _Ship(part, "cruise")
    target_deg = {"cruise": 45.0, "yellow": 45.0, "warp": 45.0, "red": 0.0}
    rate = 45.0 / 2.0
    angle = 0.0
    tip = (-1.0, 0.45, -0.67)
    schedule = ([("cruise", 0.13)] * 5 + [("red", 0.07)] * 4 +
                [("yellow", 0.31)] * 3 + [("red", 0.011)] * 17 +
                [("warp", 0.4)] + [("cruise", 0.05)] * 3 +
                [("red", 0.9)] * 3 + [("cruise", 0.25)] * 9)
    for state, dt in schedule:
        ship.state = state
        articulation.tick_ship(ship, dt)
        tgt = target_deg[state]
        step = rate * dt
        angle = tgt if abs(tgt - angle) <= step else (
            angle + (step if tgt > angle else -step))
        want = pp.apply(pp.hinge_pose(pivot, (0.0, 1.0, 0.0), angle), tip)
        assert _tip_at(ship, part, tip) == pytest.approx(want, abs=1e-9), (
            state, dt, angle)


def _tip_at(ship, part, x):
    return pp.apply(articulation.pose_for_part(ship, part), x)

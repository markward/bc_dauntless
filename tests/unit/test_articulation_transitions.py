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

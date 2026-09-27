"""`articulation.time_to_reach(ship, state)`: how long until every part has
settled at its pose for `state`. The warp sequence holds its burst on this so
a ship never jumps while its wings are still swinging into the warp pose."""
import pytest

from engine.appc import articulation, articulated_part as ap


def _part(name="wing left", seconds=4.75):
    p = ap.ArticulatedPartProperty_Create(name)
    p.SetAnchor(0.0, 0.0, 0.0)
    p.SetTransitionSeconds(seconds)
    p.SetStatePose("warp", 0.0, 0.0, 0.0, 0.0, 90.0, 0.0)
    return p


class _Ship:
    def __init__(self, state):
        self.state = state
        self._articulation_leaf = "rigtest"


@pytest.fixture
def rig(monkeypatch):
    parts = (_part("wing left", 4.75), _part("wing right", 3.0))
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: parts if leaf == "rigtest" else ())
    monkeypatch.setattr(articulation, "state_for", lambda ship: ship.state)
    articulation.set_dev_override(None)
    yield parts
    articulation.set_dev_override(None)


def test_from_rest_it_is_the_slowest_parts_full_transition(rig):
    assert articulation.time_to_reach(_Ship("cruise"), "warp") == pytest.approx(4.75)


def test_an_in_flight_transition_counts_only_what_is_left(rig):
    ship = _Ship("warp")
    articulation.tick_ship(ship, 1.0)
    assert articulation.time_to_reach(ship, "warp") == pytest.approx(3.75, abs=1e-6)


def test_a_settled_ship_needs_no_time(rig):
    ship = _Ship("warp")
    articulation.tick_ship(ship, 10.0)
    assert articulation.time_to_reach(ship, "warp") == 0.0


def test_an_unrigged_ship_needs_no_time(rig):
    ship = _Ship("cruise")
    ship._articulation_leaf = "no_rig"
    assert articulation.time_to_reach(ship, "warp") == 0.0


def test_a_dev_override_pins_the_parts_so_nothing_is_awaited(rig):
    articulation.set_dev_override("cruise")
    assert articulation.time_to_reach(_Ship("cruise"), "warp") == 0.0

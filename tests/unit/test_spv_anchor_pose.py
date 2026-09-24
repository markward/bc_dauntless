"""The SPV draws the hull in its NIF pose, so mounts are edited in the frame
they are stored in.

The hologram re-draws the LIVE player instance and honours node_overrides by
design (hologram_pass.cc:51-56 -- it must, or pins on an articulated part land
wrong). Opening the SPV freezes the sim but does not reset the pose:
_sync_ship_articulation runs in the RENDER pass, not the sim tick, so it keeps
re-pushing the frozen deflection. A Bird of Prey opened at green alert is drawn
wings-up and every mount authored through it is ~0.9 ship units out.
"""
import pytest

from engine.appc import articulation


class _Session:
    def __init__(self):
        self.ship_articulation = {}


class _Ship:
    """`deflection` is a test convenience, not a production concept any
    more: it scales each part's authored "cruise" angle (the fully-deflected,
    up/cold pose) into `_articulation_angles`, the ONLY thing
    `_sync_ship_articulation` (via `articulation.angle_for_part`) reads.
    Building the dict here, rather than going through `tick_ship`, is
    deliberate for the tests in this file: they are about a FIXED pose and
    the render-sync's own guard/force_rest logic, not about motion over
    time."""

    def __init__(self, deflection=1.0):
        self._articulation_leaf = "birdofprey"
        self._articulation_angles = {
            p.GetName(): p.angle_for("cruise") * deflection
            for p in articulation.rig_for("birdofprey")
        }


@pytest.fixture
def pushes(monkeypatch):
    """Record every set_instance_node_rotation the sync makes."""
    from engine import host_io
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_rotation",
        lambda iid, node, pivot, axis, theta: seen.append((node, theta)))
    return seen


def test_the_fixture_ship_actually_articulates(pushes):
    """Guard. If the BoP rig ever stops resolving, every test below would pass
    vacuously by pushing nothing at all."""
    from engine import host_loop
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7)
    assert pushes, "the fixture must push a real pose, or the tests prove nothing"
    assert any(theta != 0.0 for _node, theta in pushes)


def test_force_rest_pushes_ZERO_rotation_on_every_part(pushes):
    """THE POINT. Not 'pushes nothing' -- pushing nothing would leave the
    previous articulated pose standing in node_overrides."""
    from engine import host_loop
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7,
                                      force_rest=True)
    assert pushes, "the rest pose must be pushed, not merely not-overwritten"
    assert all(theta == 0.0 for _node, theta in pushes), pushes


def test_force_rest_does_not_mutate_the_ship(pushes):
    """_sync_ship_articulation is READ-ONLY on game state -- a mutation in the
    render path is what once gave the player's phasers half a second aiming at
    a destroyed subsystem."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)
    before = dict(ship._articulation_angles)
    host_loop._sync_ship_articulation(_Session(), ship, 7, force_rest=True)
    assert ship._articulation_angles == before


def test_the_change_guard_still_fires_on_the_open_and_close_edges(pushes):
    """The sync is guarded on CHANGE so a settled ship costs one float compare.
    Forcing rest must not defeat that, and must not be defeated BY it: opening
    the SPV has to push once, and closing has to push the live pose back."""
    from engine import host_loop
    session, ship = _Session(), _Ship(deflection=1.0)

    host_loop._sync_ship_articulation(session, ship, 7)            # live
    live = list(pushes); pushes.clear()
    assert live

    host_loop._sync_ship_articulation(session, ship, 7, force_rest=True)
    assert pushes, "the open edge must re-push"
    assert all(theta == 0.0 for _n, theta in pushes)
    pushes.clear()

    host_loop._sync_ship_articulation(session, ship, 7, force_rest=True)
    assert pushes == [], "a settled forced pose must not re-push every frame"

    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes, "the close edge must restore the live pose"
    assert any(theta != 0.0 for _n, theta in pushes)


def test_a_severed_part_stays_severed_while_forced(pushes, monkeypatch):
    """A severed part is HIDDEN through the same node_overrides slot this
    rotation writes. Pushing a rest rotation onto it would snap the wing back
    onto the hull and then erase the hide for good."""
    from engine import host_loop
    from engine.appc import part_severance
    monkeypatch.setattr(part_severance, "is_detached",
                        lambda s, node: node == "left wing")
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7,
                                      force_rest=True)
    assert pushes, "the other wing must still be posed"
    assert all(node != "left wing" for node, _t in pushes)


def test_an_unrigged_ship_is_untouched(pushes):
    from engine import host_loop
    ship = _Ship()
    ship._articulation_leaf = ""
    host_loop._sync_ship_articulation(_Session(), ship, 7, force_rest=True)
    assert pushes == []

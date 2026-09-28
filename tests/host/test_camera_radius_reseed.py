"""_reconcile_camera_radius (system-frames follow-up): QuickBattle's
RecreatePlayer creates the new player ship in the preload-done event before
ShipClass realization sets its radius (host_loop.py ~5631's
`if ship.GetRadius() <= 0.0: ship.SetRadius(...)`), which runs later in the
same frame's scene reconcile. _sync_player_identity's on_player_change
callback (Ruling 11, pre-sim) therefore seeds the chase/tracking cameras from
a radius of 0 -- and _ChaseCamera.set_ship_radius clamps that to a 1e-6
floor, placing the eye at the ship's centre -- with nothing left to correct
it once the reconcile realizes the ship and gives it a real radius.

_reconcile_camera_radius is the fix: called every frame, after the scene
reconcile, it re-seeds the cameras once the real radius is known and snaps
exactly once for that identity change."""
from engine.cameras.director import _CameraDirector
from engine import host_loop


class _FakePlayer:
    def __init__(self, radius: float):
        self.radius = radius

    def GetRadius(self) -> float:
        return self.radius


def test_unknown_radius_then_realized_reseeds_and_snaps_once():
    d = _CameraDirector()
    player = _FakePlayer(0.0)

    # Mimic _on_player_change seeding the cameras from an unrealized (0)
    # radius -- the live bug's starting state.
    d.chase.set_ship_radius(player.GetRadius())
    d.tracking.set_ship_radius(player.GetRadius())
    assert d.chase.ship_radius == 1e-6  # the floor clamp, i.e. "unknown"

    snap_calls = []
    d.snap = lambda: snap_calls.append(1)

    # Still unrealized this frame: no-op.
    host_loop._reconcile_camera_radius(d, player)
    assert snap_calls == []
    assert d.chase.ship_radius == 1e-6

    # Realization (host_loop.py ~5631) sets the real radius.
    player.radius = 42.0
    host_loop._reconcile_camera_radius(d, player)

    assert d.chase.ship_radius == 42.0
    assert snap_calls == [1]

    # A further frame with the same (now-known) radius is a no-op.
    host_loop._reconcile_camera_radius(d, player)
    assert snap_calls == [1]
    assert d.chase.ship_radius == 42.0


def test_known_radius_at_swap_is_unchanged():
    """A ship whose radius was already known at the swap must behave exactly
    as today: no extra reseed, no extra snap."""
    d = _CameraDirector()
    player = _FakePlayer(17.5)

    # Mimic _on_player_change seeding the cameras from an already-known
    # radius.
    d.chase.set_ship_radius(player.GetRadius())
    d.tracking.set_ship_radius(player.GetRadius())
    assert d.chase.ship_radius == 17.5

    snap_calls = []
    d.snap = lambda: snap_calls.append(1)

    for _ in range(5):
        host_loop._reconcile_camera_radius(d, player)

    assert snap_calls == []
    assert d.chase.ship_radius == 17.5


def test_no_player_is_a_noop():
    d = _CameraDirector()
    snap_calls = []
    d.snap = lambda: snap_calls.append(1)
    host_loop._reconcile_camera_radius(d, None)
    assert snap_calls == []

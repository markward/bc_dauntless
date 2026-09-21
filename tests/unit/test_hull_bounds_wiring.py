"""Prove BOTH host_loop instance-registration sites cache the hull PIECES
(engine.appc.hull_bounds) -- the same two-site trap test_hull_volume_wiring.py
guards for the hull-volume resolution.

Live 2026-09-21 (Collision Sim): every collision line read pieces=a:0/b:0 --
the shape-aware narrow phase was inert for every ship realized through
_MissionLoader._realize_session (QuickBattle boot / the ordinary load path),
which created the instance, seeded the radius, pushed the hull volume and
set the rim, and never cached the pieces. Only realize_set_objects did. A
hull with no pieces collides as a 2x-inflated whole-body sphere: the ship is
shoved off the other hull long before the meshes can touch, and the scuff it
leaves is a zero-energy sphere kiss.
"""
import App
from engine.appc.sets import SetClass_Create
from engine.appc import hull_bounds


class _FakeRenderer:
    def __init__(self):
        self._next = 1

    def load_model(self, path, search, texture_replacements=None):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def model_bounds(self, h):
        return [(0.0, 0.0, 0.0, 10.0), (5.0, 0.0, 0.0, 4.0)]

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        return iid

    def destroy_instance(self, iid):
        pass

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def test_realize_set_objects_caches_hull_pieces(monkeypatch):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("rock")
    s.AddObjectToSet(ship, "rock")

    hl.realize_set_objects(sess, s, _FakeRenderer())

    assert ship in sess.ship_instances
    assert hull_bounds.hull_piece_count(ship) == 2


def test_realize_session_caches_hull_pieces(monkeypatch):
    from tools import mission_harness
    mission_harness.setup_sdk()
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    controller = hl.HostController()
    controller.renderer = _FakeRenderer()
    controller.loader = hl._MissionLoader(controller, verbose=False)
    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert player is not None and player in session.ship_instances
    assert hull_bounds.hull_piece_count(player) == 2, \
        "the controller's realize path left the player with no hull pieces"

"""Layered damage phase 4 §2.1 (fix round 3): a rigged ship's render
instance is flagged native-side at BOTH realize sites, so a hit taken at the
identity pose -- no node overrides, e.g. a Bird of Prey at red alert -- is
still filed on the part it struck (attribute_rest_point) and stays on it when
the part later swings. An unrigged ship is never flagged (its hits stay on the
free -1 path)."""
import App
from engine.appc import articulation
from engine.appc.sets import SetClass_Create

from tests.unit.test_trace_accel_prewarm import _FakeRenderer


class _RigRecorder(_FakeRenderer):
    def __init__(self):
        super().__init__()
        self.rigged = []

    def set_instance_rigged(self, iid, rigged):
        self.rigged.append((iid, rigged))


def _rig_only(monkeypatch, rigged_ship):
    real = articulation.parts_for_ship
    monkeypatch.setattr(articulation, "parts_for_ship",
                        lambda ship: (object(),) if ship is rigged_ship else real(ship))


def test_realize_set_objects_flags_a_rigged_ship_only(monkeypatch):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "RigS")
    rigged = App.ShipClass_Create()
    rigged.SetName("rigged")
    s.AddObjectToSet(rigged, "rigged")
    plain = App.ShipClass_Create()
    plain.SetName("plain")
    s.AddObjectToSet(plain, "plain")
    _rig_only(monkeypatch, rigged)

    r = _RigRecorder()
    hl.realize_set_objects(sess, s, r)

    assert r.rigged == [(sess.ship_instances[rigged], True)]


def test_realize_session_flags_a_rigged_player(monkeypatch):
    from tools import mission_harness
    mission_harness.setup_sdk()
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    monkeypatch.setattr(articulation, "parts_for_ship", lambda ship: (object(),))

    controller = hl.HostController()
    r = _RigRecorder()
    controller.renderer = r
    controller.loader = hl._MissionLoader(controller, verbose=False)
    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert (session.ship_instances[player], True) in r.rigged


def test_a_failing_flag_never_blocks_spawn(monkeypatch):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "RigS2")
    ship = App.ShipClass_Create()
    ship.SetName("rigged2")
    s.AddObjectToSet(ship, "rigged2")
    _rig_only(monkeypatch, ship)
    r = _FakeRenderer()          # no set_instance_rigged at all
    hl.realize_set_objects(sess, s, r)
    assert ship in sess.ship_instances


def test_renderer_facade_forwards_to_the_binding(monkeypatch):
    from engine import renderer
    seen = []

    class _H:
        def set_instance_rigged(self, iid, rigged):
            seen.append((iid, rigged))

    monkeypatch.setattr(renderer, "_h", _H())
    renderer.set_instance_rigged(5, True)
    assert seen == [(5, True)]
    assert "set_instance_rigged" in renderer._REQUIRED_BINDINGS

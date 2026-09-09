"""Prove BOTH host_loop instance-registration sites push the hull-volume
resolution -- not just that engine.appc.hull_volume.push_resolution works in
isolation.

There are two places a ship gets a renderer instance: realize_set_objects()
(mission load / per-tick reconciliation) and _MissionLoader._realize_session()
(QuickBattle boot, and the ordinary load() path). A test that only exercises
push_resolution() directly would stay green even if zero call sites were
wired -- these two tests exercise the actual host_loop code paths and assert
push_resolution was actually called with the ship that was realized and the
iid the (fake) renderer actually handed back.
"""
import App
from engine.appc.sets import SetClass_Create


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()

    def load_model(self, path, search, texture_replacements=None):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def test_realize_set_objects_pushes_resolution(monkeypatch):
    """Site 1: engine/host_loop.py's realize_set_objects (mission load / the
    per-tick reconciliation pass) must call push_resolution for every ship it
    realizes, with the exact (ship, iid) pair it just created."""
    from engine import host_loop as hl
    import engine.appc.hull_volume as hull_volume_mod

    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    calls = []

    def fake_push(ship, iid):
        calls.append((ship, iid))
        return True

    monkeypatch.setattr(hull_volume_mod, "push_resolution", fake_push)

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("rock")
    s.AddObjectToSet(ship, "rock")

    hl.realize_set_objects(sess, s, r)

    assert ship in sess.ship_instances
    iid = sess.ship_instances[ship]
    assert calls == [(ship, iid)]


def test_realize_set_objects_prewarms_the_field(monkeypatch):
    """Site 1 must also call prewarm_field for every ship it realizes (I1:
    bake the hull field at spawn/mission-load, not lazily on the ship's first
    combat hit) -- a separate call from push_resolution above, so a test that
    only checks push_resolution cannot see this call site going missing."""
    from engine import host_loop as hl
    import engine.appc.hull_volume as hull_volume_mod

    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    monkeypatch.setattr(hull_volume_mod, "push_resolution",
                        lambda ship, iid: True)

    calls = []

    def fake_prewarm(iid):
        calls.append(iid)

    monkeypatch.setattr(hull_volume_mod, "prewarm_field", fake_prewarm)

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("rock")
    s.AddObjectToSet(ship, "rock")

    hl.realize_set_objects(sess, s, r)

    assert ship in sess.ship_instances
    iid = sess.ship_instances[ship]
    assert calls == [iid]


def test_realize_session_pushes_resolution(monkeypatch):
    """Site 2: _MissionLoader._realize_session (the QuickBattle boot path)
    must call push_resolution for every ship it realizes too -- this is the
    second, differently-indented call site the first test cannot reach."""
    from tools import mission_harness
    mission_harness.setup_sdk()

    from engine import host_loop as hl
    import engine.appc.hull_volume as hull_volume_mod

    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    calls = []

    def fake_push(ship, iid):
        calls.append((ship, iid))
        return True

    monkeypatch.setattr(hull_volume_mod, "push_resolution", fake_push)

    controller = hl.HostController()
    controller.renderer = _FakeRenderer()
    controller.loader = hl._MissionLoader(controller, verbose=False)

    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert player is not None
    assert player in session.ship_instances
    iid = session.ship_instances[player]
    assert (player, iid) in calls


def test_realize_session_prewarms_the_field(monkeypatch):
    """Site 2 (_MissionLoader._realize_session / QuickBattle boot) must also
    call prewarm_field for every ship it realizes -- the second call site
    site 1's test above cannot reach."""
    from tools import mission_harness
    mission_harness.setup_sdk()

    from engine import host_loop as hl
    import engine.appc.hull_volume as hull_volume_mod

    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    monkeypatch.setattr(hull_volume_mod, "push_resolution",
                        lambda ship, iid: True)

    calls = []

    def fake_prewarm(iid):
        calls.append(iid)

    monkeypatch.setattr(hull_volume_mod, "prewarm_field", fake_prewarm)

    controller = hl.HostController()
    controller.renderer = _FakeRenderer()
    controller.loader = hl._MissionLoader(controller, verbose=False)

    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert player is not None
    assert player in session.ship_instances
    iid = session.ship_instances[player]
    assert iid in calls

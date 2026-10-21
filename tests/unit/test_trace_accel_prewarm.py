"""A hull's ray-trace BVH is built at spawn and in the warp preload, not on
its first trace.

The BVH (renderer::prewarm_trace_accel) otherwise builds lazily on the hull's
first ray trace -- a station's first combat trace cost the frame 7.7 ms
(perf-register SIG-039/040). It used to ride along with the carve's
hull_volume_prewarm / hull_volume_prewarm_model bindings; when the carve was
removed (layered damage phase 4) it got its own binding, prewarm_trace_accel,
called at BOTH ship realize sites and from the warp-tunnel preload.
"""
import App
from engine.appc.sets import SetClass_Create
from engine.appc import hull_volume


class _FakeRenderer:
    """Just enough renderer for both realize sites, recording the prewarms."""

    def __init__(self):
        self._next = 1
        self.trace_prewarms = []

    def load_model(self, path, search, texture_replacements=None, decals=None):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def model_bounds(self, h):
        return [(0.0, 0.0, 0.0, 10.0)]

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

    def set_surface_rock(self, iid, rock):
        pass

    def set_rim_strength(self, iid, s):
        pass

    def prefetch_hull_fill(self, handle):
        pass

    def prewarm_trace_accel(self, handle):
        self.trace_prewarms.append(handle)


def test_realize_set_objects_prewarms_the_trace_bvh(monkeypatch):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("hull")
    s.AddObjectToSet(ship, "hull")

    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)

    assert ship in sess.ship_instances
    assert r.trace_prewarms == [100]


def test_realize_session_prewarms_the_trace_bvh(monkeypatch):
    from tools import mission_harness
    mission_harness.setup_sdk()
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    controller = hl.HostController()
    r = _FakeRenderer()
    controller.renderer = r
    controller.loader = hl._MissionLoader(controller, verbose=False)
    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert player is not None and player in session.ship_instances
    assert 100 in r.trace_prewarms, \
        "the controller's realize path never prewarmed the hull's trace BVH"


def test_a_failing_prewarm_never_blocks_spawn(monkeypatch):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S2")
    ship = App.ShipClass_Create()
    ship.SetName("hull2")
    s.AddObjectToSet(ship, "hull2")

    r = _FakeRenderer()

    def boom(handle):
        raise RuntimeError("stale .so")
    r.prewarm_trace_accel = boom
    hl.realize_set_objects(sess, s, r)

    assert ship in sess.ship_instances


class _PreloadRecorder:
    def __init__(self):
        self.calls = []

    def prefetch_hull_fill(self, handle):
        self.calls.append(("fill", handle))

    def prewarm_trace_accel(self, handle):
        self.calls.append(("bvh", handle))


def test_warp_preload_prewarms_the_trace_bvh(monkeypatch):
    rec = _PreloadRecorder()
    monkeypatch.setattr(hull_volume, "_renderer", rec)
    hull_volume.prewarm_for_model(7)
    assert ("bvh", 7) in rec.calls
    assert ("fill", 7) in rec.calls


def test_renderer_facade_forwards_to_the_binding(monkeypatch):
    from engine import renderer

    seen = []

    class _H:
        def prewarm_trace_accel(self, handle):
            seen.append(handle)

    monkeypatch.setattr(renderer, "_h", _H())
    renderer.prewarm_trace_accel(42)
    assert seen == [42]
    assert "prewarm_trace_accel" in renderer._REQUIRED_BINDINGS

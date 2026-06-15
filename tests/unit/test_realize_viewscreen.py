"""Host-side realization of the SDK-created viewscreen object into a render
instance. Uses a fake renderer so it runs headless (never touches GL).
Mirrors tests/unit/test_realize_bridge_model.py."""
import App
from engine.appc.bridge_set import BridgeSet, ViewScreenObject
from engine.host_loop import _realize_viewscreen

VS_NIF = "data/Models/Sets/DBridge/DBridgeViewScreen.nif"


class _FakeRenderer:
    def __init__(self):
        self.loaded = []          # (nif_abs, tex_abs)
        self.created = []         # handles passed to create_bridge_instance
        self.transformed = []     # (iid, mat4)
        self.destroyed = []       # iids
        self._next_handle = 200
        self._next_iid = 800

    def load_model(self, nif_abs, tex_abs):
        self.loaded.append((nif_abs, tex_abs))
        self._next_handle += 1
        return self._next_handle

    def create_bridge_instance(self, handle):
        self.created.append(handle)
        self._next_iid += 1
        return self._next_iid

    def set_world_transform(self, iid, mat4):
        self.transformed.append((iid, mat4))

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


class _FakeController:
    def __init__(self):
        self.viewscreen_instance = None
        self.nif_to_handle = {}


def _make_bridge_with_viewscreen(nif=VS_NIF, record_env=True):
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")
    vs = ViewScreenObject(nif)
    bridge.SetViewScreen(vs, "viewscreen")
    if record_env:
        App.g_kModelManager.LoadModel(nif, None, "data/Models/Sets/DBridge/High/")
    return bridge, vs


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kModelManager._env.clear()


def test_realizes_instance_and_harvests_iid():
    _bridge, vs = _make_bridge_with_viewscreen()
    r = _FakeRenderer()
    ctl = _FakeController()

    _realize_viewscreen(ctl, r)

    assert len(r.loaded) == 1
    nif_abs, tex_abs = r.loaded[0]
    assert nif_abs.endswith("game/data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    assert tex_abs.endswith("game/data/Models/Sets/DBridge/High")
    assert len(r.created) == 1
    assert vs.render_instance == ctl.viewscreen_instance
    assert ctl.viewscreen_instance is not None
    assert ctl.nif_to_handle[nif_abs] == r.created[0]
    # World transform applied once (identity — bridge-local space).
    assert len(r.transformed) == 1


def test_same_config_reuse_is_noop():
    _bridge, _vs = _make_bridge_with_viewscreen()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    first_iid = ctl.viewscreen_instance

    _realize_viewscreen(ctl, r)        # same object, render_instance set
    assert ctl.viewscreen_instance == first_iid
    assert len(r.loaded) == 1
    assert len(r.created) == 1
    assert r.destroyed == []


def test_fresh_object_destroys_prior_instance():
    _bridge, _vs = _make_bridge_with_viewscreen()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    prior_iid = ctl.viewscreen_instance

    # Config change / set rebuild: a fresh viewscreen object replaces the old.
    _bridge2, _vs2 = _make_bridge_with_viewscreen(
        nif="data/Models/Sets/EBridge/EBridgeViewScreen.nif", record_env=False)
    _realize_viewscreen(ctl, r)

    assert prior_iid in r.destroyed
    assert ctl.viewscreen_instance != prior_iid
    assert len(r.created) == 2
    # No env recorded -> falls back to the default High tex dir.
    assert r.loaded[1][1].endswith("game/data/Models/Sets/DBridge/High")
    assert r.loaded[1][0].endswith("game/data/Models/Sets/EBridge/EBridgeViewScreen.nif")
    # The new object's slot was harvested too (not just the controller's).
    assert _vs2.render_instance == ctl.viewscreen_instance


def test_no_viewscreen_is_noop():
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")   # set exists, no viewscreen
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    assert r.loaded == []
    assert ctl.viewscreen_instance is None


def test_no_bridge_set_is_noop():
    App.g_kSetManager._sets.clear()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    assert r.loaded == []
    assert ctl.viewscreen_instance is None

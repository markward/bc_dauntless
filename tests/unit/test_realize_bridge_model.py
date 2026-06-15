"""Host-side realization of the SDK-created bridge object into a render
instance. Uses a fake renderer so it runs headless (never touches GL)."""
import App
from engine.appc.bridge_set import BridgeSet, BridgeObjectClass
from engine.host_loop import _realize_bridge_model


class _FakeRenderer:
    def __init__(self):
        self.loaded = []          # (nif_abs, tex_abs)
        self.created = []         # handles passed to create_bridge_instance
        self.transformed = []     # (iid, mat4)
        self.destroyed = []       # iids
        self._next_handle = 100
        self._next_iid = 900

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
        self.bridge_instance = None
        self.nif_to_handle = {}
        self.current_bridge_nif_abs = None


def _make_bridge_with_object(nif="data/Models/Sets/DBridge/DBridge.nif",
                             record_env=True):
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")
    obj = BridgeObjectClass(nif)
    bridge.AddObjectToSet(obj, "bridge")
    if record_env:
        App.g_kModelManager.LoadModel(nif, None, "data/Models/Sets/DBridge/High/")
    return bridge, obj


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kModelManager._env.clear()


def test_realizes_instance_and_harvests_iid():
    _bridge, obj = _make_bridge_with_object()
    r = _FakeRenderer()
    ctl = _FakeController()

    _realize_bridge_model(ctl, r)

    assert len(r.loaded) == 1
    nif_abs, tex_abs = r.loaded[0]
    assert nif_abs.endswith("game/data/Models/Sets/DBridge/DBridge.nif")
    # Texture search uses the env path recorded by LoadModel.
    assert tex_abs.endswith("game/data/Models/Sets/DBridge/High")
    assert len(r.created) == 1
    assert obj.render_instance == ctl.bridge_instance
    assert ctl.bridge_instance is not None
    assert ctl.current_bridge_nif_abs == nif_abs
    assert ctl.nif_to_handle[nif_abs] == r.created[0]
    # World transform applied once.
    assert len(r.transformed) == 1


def test_same_config_reuse_is_noop():
    _bridge, obj = _make_bridge_with_object()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_bridge_model(ctl, r)
    first_iid = ctl.bridge_instance

    # Second pass with the SAME object (render_instance already set): no-op.
    _realize_bridge_model(ctl, r)
    assert ctl.bridge_instance == first_iid
    assert len(r.loaded) == 1
    assert len(r.created) == 1
    assert r.destroyed == []


def test_fresh_object_destroys_prior_instance():
    _bridge, _obj = _make_bridge_with_object()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_bridge_model(ctl, r)
    prior_iid = ctl.bridge_instance

    # Simulate a config change / set rebuild: a fresh bridge object with no
    # render_instance replaces the old one in the set.
    _bridge2, _obj2 = _make_bridge_with_object(
        nif="data/Models/Sets/EBridge/EBridge.nif", record_env=False)
    _realize_bridge_model(ctl, r)

    assert prior_iid in r.destroyed
    assert ctl.bridge_instance != prior_iid
    assert len(r.created) == 2
    # No env recorded for EBridge -> falls back to the default High tex dir.
    assert r.loaded[1][1].endswith("game/data/Models/Sets/DBridge/High")
    assert r.loaded[1][0].endswith("game/data/Models/Sets/EBridge/EBridge.nif")


def test_no_bridge_object_is_noop():
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")   # set exists, no "bridge" object
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_bridge_model(ctl, r)
    assert r.loaded == []
    assert ctl.bridge_instance is None

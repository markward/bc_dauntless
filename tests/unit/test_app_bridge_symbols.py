import App
from engine.appc.bridge_set import BridgeSet


def test_app_exposes_bridge_factories():
    assert App.BridgeSet_Cast(None) is None              # not a _NamedStub
    bs = App.BridgeSet_Create()
    assert isinstance(bs, BridgeSet)
    assert App.BridgeSet_Cast(bs) is bs


def test_app_model_manager_present():
    # Real attribute, not the _NamedStub catch-all.
    assert App.g_kModelManager.LoadModel("x.nif", None, "env/") is None


def test_light_unilluminate_is_noop():
    bs = App.BridgeSet_Create()
    bs.CreateAmbientLight(1.0, 1.0, 1.0, 0.7, "ambientlight1")
    light = bs.GetLight("ambientlight1")
    assert light is not None
    light.UnilluminateEntireSet()        # must not raise

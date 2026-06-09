from engine.appc.properties import EngineProperty


def test_engine_type_round_trips():
    p = EngineProperty("Port Warp")
    p.SetEngineType(EngineProperty.EP_WARP)
    assert p.GetEngineType() == EngineProperty.EP_WARP


def test_engine_type_defaults_to_impulse():
    p = EngineProperty("Center Impulse")
    assert p.GetEngineType() == EngineProperty.EP_IMPULSE

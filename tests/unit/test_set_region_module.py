from engine.appc.sets import SetClass


def test_round_trip():
    s = SetClass()
    s.SetRegionModule("Systems.Vesuvi.Vesuvi4")
    assert s.GetRegionModule() == "Systems.Vesuvi.Vesuvi4"


def test_default_is_none():
    assert SetClass().GetRegionModule() is None

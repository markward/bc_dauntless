import App
from engine.appc.sets import SetClass_Create


def _ship_at(x, y, z):
    s = App.ShipClass_Create(); s.SetName("s")
    s.SetTranslateXYZ(x, y, z); s.Update(0)
    return s


def test_field_radius_membership():
    App.g_kSetManager._sets.clear()
    pSet = SetClass_Create(); App.g_kSetManager.AddSet(pSet, "F")
    f = App.AsteroidFieldPlacement_Create("Asteroid Field 1", "F", None)
    f.SetTranslateXYZ(0.0, 0.0, 0.0); f.SetFieldRadius(100.0); f.Update(0)
    assert f.IsShipInside(_ship_at(50.0, 0.0, 0.0))      # inside
    assert not f.IsShipInside(_ship_at(150.0, 0.0, 0.0))  # outside
    assert f in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)
    assert App.AsteroidField_Cast(f) is f


def test_authored_setters_are_accepted():
    f = App.AsteroidFieldPlacement_Create("AF", None, None)
    # These authored calls must not raise (they drive rendering, not gating).
    f.SetNumTilesPerAxis(3); f.SetNumAsteroidsPerTile(2)
    f.SetAsteroidSizeFactor(10.0); f.UpdateNodeOnly(); f.ConfigField()

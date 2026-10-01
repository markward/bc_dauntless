"""AsteroidFieldPlacement keeps the tile setters BC scripts call (minor-rocks
spec §1): the minor registry builds a field's cloud from them."""
from engine.appc.asteroid_field import AsteroidField, AsteroidFieldPlacement_Create


def test_defaults():
    f = AsteroidField()
    assert f.GetNumTilesPerAxis() == 1
    assert f.GetNumAsteroidsPerTile() == 0
    assert f.GetAsteroidSizeFactor() == 1.0


def test_setters_round_trip_like_beol4():
    f = AsteroidFieldPlacement_Create("Asteroid Field 1")
    f.SetFieldRadius(1000.0)
    f.SetNumTilesPerAxis(3)
    f.SetNumAsteroidsPerTile(15)
    f.SetAsteroidSizeFactor(7.0)
    f.ConfigField()
    f.UpdateNodeOnly()
    assert f.GetFieldRadius() == 1000.0
    assert f.GetNumTilesPerAxis() == 3
    assert f.GetNumAsteroidsPerTile() == 15
    assert f.GetAsteroidSizeFactor() == 7.0


def test_is_ship_inside_unchanged():
    class _P:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z
    class _Ship:
        def GetWorldLocation(self):
            return _P(5.0, 0.0, 0.0)
    f = AsteroidField()
    f.SetFieldRadius(10.0)
    assert f.IsShipInside(_Ship()) == 1

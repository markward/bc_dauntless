"""AsteroidField placement — point-in-sphere field volume (gating geometry).

Mirrors the SDK App.AsteroidFieldPlacement_Create surface. The rendering setters
(tiles/asteroids/size) are accepted and ignored; only position + field radius +
IsShipInside matter for warp gating. Subclasses the bare App.AsteroidField base
so CT_ASTEROID_FIELD isinstance/GetClassObjectList/AsteroidField_Cast all match.
"""
from App import AsteroidField as _AsteroidFieldBase


class AsteroidField(_AsteroidFieldBase):
    def __init__(self):
        super().__init__()
        self._field_radius = 0.0

    def SetFieldRadius(self, r):
        self._field_radius = float(r)

    def GetFieldRadius(self):
        return self._field_radius

    def IsShipInside(self, ship):
        loc = ship.GetWorldLocation()
        c = self.GetWorldLocation()
        dx, dy, dz = loc.x - c.x, loc.y - c.y, loc.z - c.z
        r = self._field_radius
        return 1 if (dx * dx + dy * dy + dz * dz <= r * r) else 0

    # Authored render-config setters — accepted, no-op for gating.
    def SetNumTilesPerAxis(self, *a): pass
    def SetNumAsteroidsPerTile(self, *a): pass
    def SetAsteroidSizeFactor(self, *a): pass
    def ConfigField(self, *a): pass
    def UpdateNodeOnly(self, *a): pass


def AsteroidFieldPlacement_Create(name, set_name=None, parent=None):
    f = AsteroidField()
    f.SetName(name)
    import App
    s = App.g_kSetManager.GetSet(set_name) if set_name else None
    if s is not None:
        s.AddObjectToSet(f, name)
    return f


def AsteroidField_Cast(obj):
    return obj if isinstance(obj, _AsteroidFieldBase) else None

"""AsteroidField placement — point-in-sphere field volume.

Mirrors the SDK App.AsteroidFieldPlacement_Create surface. Position + field
radius + IsShipInside drive warp gating (warp_gates.py). The tile setters are
REMEMBERED (minor-rocks spec §1): engine/rocks/minors.py builds each field's
minor cloud from radius, tiles³ × per-tile and the size factor. ConfigField /
UpdateNodeOnly stay no-ops. Subclasses the bare App.AsteroidField base so
CT_ASTEROID_FIELD isinstance/GetClassObjectList/AsteroidField_Cast all match.
"""
from App import AsteroidField as _AsteroidFieldBase


class AsteroidField(_AsteroidFieldBase):
    def __init__(self):
        super().__init__()
        self._field_radius = 0.0
        self._tiles_per_axis = 1
        self._per_tile = 0
        self._size_factor = 1.0

    def SetFieldRadius(self, r):
        self._field_radius = float(r)

    def GetFieldRadius(self):
        return self._field_radius

    def SetNumTilesPerAxis(self, n):
        self._tiles_per_axis = int(n)

    def GetNumTilesPerAxis(self):
        return self._tiles_per_axis

    def SetNumAsteroidsPerTile(self, n):
        self._per_tile = int(n)

    def GetNumAsteroidsPerTile(self):
        return self._per_tile

    def SetAsteroidSizeFactor(self, f):
        self._size_factor = float(f)

    def GetAsteroidSizeFactor(self):
        return self._size_factor

    def IsShipInside(self, ship):
        loc = ship.GetWorldLocation()
        c = self.GetWorldLocation()
        dx, dy, dz = loc.x - c.x, loc.y - c.y, loc.z - c.z
        r = self._field_radius
        return 1 if (dx * dx + dy * dy + dz * dz <= r * r) else 0

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

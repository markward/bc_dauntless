"""MetaNebula — point-in-sphere nebula volume (gating geometry only).

Mirrors the SDK App.MetaNebula_Create + AddNebulaSphere + IsObjectInNebula
surface. Rendering and environmental damage are out of scope; this exists so
WarpPressed-style gating (and GetClassObjectList(CT_NEBULA)) works.
"""
from App import Nebula


class MetaNebula(Nebula):
    def __init__(self, r=0.0, g=0.0, b=0.0, visibility=0.0, sensor_density=0.0,
                 internal_tex="", external_tex=""):
        super().__init__()
        self._rgb = (r, g, b)
        self._visibility = visibility
        self._sensor_density = sensor_density
        self._internal_tex = internal_tex
        self._external_tex = external_tex
        self._spheres = []          # list of (x, y, z, radius)
        self._damage = (0.0, 0.0)   # (hull, shields) — stored, unused

    def AddNebulaSphere(self, x, y, z, radius):
        self._spheres.append((float(x), float(y), float(z), float(radius)))

    def GetNebulaSpheres(self):
        return list(self._spheres)

    def SetupDamage(self, hull, shields):
        self._damage = (float(hull), float(shields))

    def IsObjectInNebula(self, obj):
        loc = obj.GetWorldLocation()
        px, py, pz = loc.x, loc.y, loc.z
        for (cx, cy, cz, rad) in self._spheres:
            dx, dy, dz = px - cx, py - cy, pz - cz
            if dx * dx + dy * dy + dz * dz <= rad * rad:
                return 1
        return 0


def MetaNebula_Create(r=0.0, g=0.0, b=0.0, visibility=0.0, sensor_density=0.0,
                      internal_tex="", external_tex=""):
    return MetaNebula(r, g, b, visibility, sensor_density,
                      internal_tex, external_tex)


def Nebula_Cast(obj):
    return obj if isinstance(obj, Nebula) else None

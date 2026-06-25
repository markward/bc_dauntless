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
        self._fbm = (0.02, 1.5, 0.30)  # freq, gain, density_floor (tunable)
        self._seed = None               # lazily derived from first sphere

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

    def GetTintRGB(self):
        return self._rgb

    def GetVisibility(self):
        return self._visibility

    def GetSensorDensity(self):
        return self._sensor_density

    def GetInternalTexture(self):
        return self._internal_tex

    def GetExternalTexture(self):
        return self._external_tex

    def GetDamage(self):
        return self._damage

    # ── fbm dials + seed (consumed by sensor_detection.concealment_at) ──────

    def SetFbmDials(self, freq, gain, floor):
        """Override the default fbm parameters for this nebula's density field.

        freq  — spatial frequency multiplier (default 0.02)
        gain  — output gain (default 1.2; raise for denser cores)
        floor — density_floor subtracted before saturate (default 0.5)
        """
        self._fbm = (float(freq), float(gain), float(floor))

    def GetFbmDials(self):
        """Return (freq, gain, density_floor) as set by SetFbmDials or defaults."""
        return self._fbm

    def GetSeed(self):
        """Deterministic per-nebula seed tuple derived from the first sphere.

        Lazily evaluated on first call; returns (0,0,0)-based seed if no
        spheres have been added yet.
        """
        if self._seed is None:
            from engine.appc.nebula_density import seed_for
            if self._spheres:
                cx, cy, cz, _ = self._spheres[0]
            else:
                cx = cy = cz = 0.0
            self._seed = seed_for(cx, cy, cz)
        return self._seed


def MetaNebula_Create(r=0.0, g=0.0, b=0.0, visibility=0.0, sensor_density=0.0,
                      internal_tex="", external_tex=""):
    return MetaNebula(r, g, b, visibility, sensor_density,
                      internal_tex, external_tex)


def Nebula_Cast(obj):
    return obj if isinstance(obj, Nebula) else None


def MetaNebula_Cast(obj):
    return obj if isinstance(obj, MetaNebula) else None

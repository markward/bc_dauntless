"""Planet / Sun celestial-body classes.

Mirrors sdk/.../App.py:6071+.  Mission scripts and per-system placement
files (Systems/*/...) build planets with::

    pPlanet = App.Planet_Create(200.0, "data/models/environment/IcePlanet.nif")
    pPlanet.SetName("Tezle 1")
    pSet.AddObjectToSet(pPlanet, "Tezle 1")
    pPlanet.SetHailable(TRUE)

and later look them up::

    pPlanet = App.Planet_GetObject(pSet, "Tezle 1")

Phase 1 captures the data — radius, atmosphere, hailable flag, environmental
damage tunables — but the visual mesh ("data/models/.../*.nif") is rendered
in Phase 2.  Hailable + atmosphere damage are real gameplay logic.
"""

from engine.appc.objects import ObjectClass


class Planet(ObjectClass):
    def __init__(self, radius: float = 0.0, model_path: str = ""):
        super().__init__()
        self.SetRadius(radius)
        self._model_path = model_path
        self._atmosphere_radius: float = 0.0
        self._hailable: bool = False
        self._env_shield_damage: float = 0.0
        self._env_hull_damage: float = 0.0
        # Attached objects — moons, stations, etc. parented to the planet's
        # transform.  AttachObject mirrors ObjectClass.AttachObject which is
        # a no-op in the base; here we record the attachment for queries.
        self._attached: list = []

    def GetModelPath(self) -> str:
        return self._model_path

    # ── Atmosphere ──────────────────────────────────────────────────────────
    def SetAtmosphereRadius(self, r: float) -> None:
        self._atmosphere_radius = float(r)

    def GetAtmosphereRadius(self) -> float:
        return self._atmosphere_radius

    def SetEnvironmentalShieldDamage(self, damage: float) -> None:
        self._env_shield_damage = float(damage)

    def GetEnvironmentalShieldDamage(self) -> float:
        return self._env_shield_damage

    def SetEnvironmentalHullDamage(self, damage: float) -> None:
        self._env_hull_damage = float(damage)

    def GetEnvironmentalHullDamage(self) -> float:
        return self._env_hull_damage

    # ── Hailable flag ───────────────────────────────────────────────────────
    # Mission scripts (E1M2.py:2346, E2M1.py:685, E7M6.py:1429) toggle this
    # to enable/disable the bridge "Hail" menu option targeting the planet.
    def SetHailable(self, value) -> None:
        self._hailable = bool(value)

    def IsHailable(self) -> int:
        return 1 if self._hailable else 0

    # ── Object attachment ───────────────────────────────────────────────────
    def AttachObject(self, obj, *args) -> None:
        if obj not in self._attached:
            self._attached.append(obj)

    def DetachObject(self, obj, *args) -> None:
        if obj in self._attached:
            self._attached.remove(obj)

    def GetAttachedObjects(self) -> tuple:
        return tuple(self._attached)


class Sun(Planet):
    """Sun — Planet subclass.  Same data surface; rendering differs."""
    pass


# ── Factories ────────────────────────────────────────────────────────────────

def Planet_Create(radius: float = 0.0, model_path: str = "") -> Planet:
    """Construct a Planet.  SDK signature: ``Planet_Create(radius, model_path)``.

    The model path is renderer-side data; Phase 1 stashes it on the instance
    for round-trip but doesn't load the NIF (Phase 2 work).
    """
    return Planet(float(radius), str(model_path))


def Sun_Create(
    radius: float = 0.0,
    atmosphere_thickness: float = 0.0,
    damage_per_sec: float = 0.0,
    base_texture: str = "",
    flare_texture: str = "",
) -> Sun:
    """SDK signature: ``Sun_Create(radius, atmosphere_thickness, damage_per_sec,
    base_texture=None, flare_texture=None)``.

    Different from Planet_Create — Sun stars take an atmosphere thickness
    (the corona thickness, in scene units) plus a damage-per-second value
    that drives environmental hull damage when ships fly into the corona.
    Texture args (base + flare) are renderer-side data; Phase 1 stashes
    them on the instance for round-trip.
    """
    s = Sun(float(radius), str(base_texture))
    s.SetAtmosphereRadius(float(atmosphere_thickness))
    s.SetEnvironmentalHullDamage(float(damage_per_sec))
    s._flare_texture = str(flare_texture)
    return s


def Planet_GetObject(pSet, name) -> "Planet | None":
    """Look up a planet by name within a SetClass.

    SDK pattern (E1M2/E2M1/E6M4/E7M6 mission scripts): planets are added to
    the system set via AddObjectToSet, then queried by name.  Returns None
    when no planet under the name (or a non-Planet object squats it).
    """
    if pSet is None or not hasattr(pSet, "GetObject"):
        return None
    obj = pSet.GetObject(str(name))
    return obj if isinstance(obj, Planet) else None


def Planet_Cast(obj) -> "Planet | None":
    return obj if isinstance(obj, Planet) else None


# ── ProximityManager ────────────────────────────────────────────────────────
# SDK call sites (Maelstrom/.../E6M4.py): pSet.GetProximityManager().AddObject(pProbe)
# Per-set proximity tracker — Phase 1 stores added objects so SDK chains
# round-trip; the per-tick proximity evaluation is Phase 2.

class ProximityManager:
    def __init__(self, pSet=None):
        self._set = pSet
        self._objects: list = []

    def AddObject(self, obj) -> None:
        if obj not in self._objects:
            self._objects.append(obj)

    def RemoveObject(self, obj) -> None:
        if obj in self._objects:
            self._objects.remove(obj)

    def UpdateObject(self, obj) -> None:
        # SDK pattern (QuickBattle.py:2726): notifies the proximity tracker
        # that an object's position has changed and its bucket assignment
        # may need recomputing.  Phase 1: idempotent ensure-present.
        if obj not in self._objects:
            self._objects.append(obj)

    def GetNumObjects(self) -> int:
        return len(self._objects)

    def GetNearObjects(self, *args) -> tuple:
        # Phase 1: returns the full tracked list.  Real distance filtering
        # against the (point, radius) args is Phase 2 simulation work.
        return tuple(self._objects)

    def GetLineIntersectObjects(self, *args) -> tuple:
        return ()

    def EndObjectIteration(self) -> None:
        pass

    def DumpCollisions(self) -> None:
        pass

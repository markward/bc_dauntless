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


_SUN_DEFAULT_TEXTURE = "data/Textures/SunBase.tga"


def aggregate_suns_for_renderer(project_root, pSets):
    """Return list[dict] for all Sun objects across pSets.

    Suns with no base_texture fall back to SunBase.tga (the BC engine default).
    Suns whose resolved texture path does not exist are dropped with a
    once-per-object warning (suppressed after first fire via _sun_warned).
    Suns with radius <= 0 are dropped silently.
    """
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            if not isinstance(obj, Sun):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            # SDK scripts may resize a sun mid-mission via SetScale (no stock
            # script does this for suns today, but the contract matches ships
            # and planets). Apply it to both the body and the corona so the
            # ratio stays constant.
            try:
                scale = float(obj.GetScale())
            except Exception:
                scale = 1.0
            loc = obj.GetWorldLocation()
            tex_rel = obj.GetModelPath() or _SUN_DEFAULT_TEXTURE
            abs_path = (project_root / "game" / tex_rel).resolve()
            if not abs_path.is_file():
                if not obj.__dict__.get("_sun_warned", False):
                    print(
                        f"[suns] texture not found: {tex_rel!r}; skipping",
                        flush=True,
                    )
                    obj.__dict__["_sun_warned"] = True
                continue
            out.append({
                "position":          (loc.x, loc.y, loc.z),
                "radius":            radius * scale,
                "base_texture_path": str(abs_path),
                "corona_radius":     (radius + obj.GetAtmosphereRadius()) * scale,
            })
    return out


# ── ProximityManager ────────────────────────────────────────────────────────
# SDK call sites (Maelstrom/.../E6M4.py): pSet.GetProximityManager().AddObject(pProbe)
# Per-set proximity tracker — Phase 1 stores added objects so SDK chains
# round-trip; the per-tick proximity evaluation is Phase 2.

class ProximityManager:
    def __init__(self, pSet=None):
        self._set = pSet
        self._objects: list = []
        # Eager init — TGObject.__getattr__ returns a truthy _Stub for
        # missing attrs, so the lazy `getattr(..., None)` idiom would
        # mis-resolve.  See engine/appc/events.py TGPythonInstanceWrapper.
        self._proximity_checks: list = []

    def AddObject(self, obj) -> None:
        if obj not in self._objects:
            self._objects.append(obj)
        # SDK ConditionInRange.SetupProximitySphere calls
        # pProximityManager.AddObject(pProx) — the proximity check is
        # registered here so the per-tick evaluator can find it. We track
        # it in _proximity_checks too (anchor=None — anchor will be set
        # by ObjectClass.AttachObject(prox) which is called immediately
        # after).
        from engine.appc.ai import ProximityCheck
        if isinstance(obj, ProximityCheck):
            entry = (obj, None)
            if entry not in self._proximity_checks:
                self._proximity_checks.append(entry)

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

    def GetNearObjects(self, point, radius, eType=None) -> tuple:
        """Return objects within `radius` world-space units of `point`.
        Used by SDK conditions (ConditionInRange) to gate on proximity.

        SDK call sites pass an optional third arg (MissionLib.py:5035 passes
        ``1`` — a type filter / encompassing-volume flag in the real engine);
        Phase 1 accepts and ignores it so SDK call sites round-trip."""
        r2 = float(radius) * float(radius)
        result = []
        for obj in self._objects:
            loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
            if loc is None:
                continue
            dx = loc.x - point.x
            dy = loc.y - point.y
            dz = loc.z - point.z
            if dx * dx + dy * dy + dz * dz <= r2:
                result.append(obj)
        return tuple(result)

    def GetLineIntersectObjects(self, *args) -> tuple:
        return ()

    def GetNextObject(self, iterator=None):
        """Return the next object from a proximity iterator.

        Phase 1 stub: GetLineIntersectObjects returns (), so the
        iterator is always empty — this method returns None to terminate
        SDK while-loops on the first call. Real iteration lands when
        the proximity subsystem itself gets real work (planet/large-ship
        avoidance for AI scripts like Intercept).
        """
        return None

    def EndObjectIteration(self, iterator=None) -> None:
        """Release a proximity iterator handle. Phase 1 stub: no-op
        because GetLineIntersectObjects returns () and the iterator
        handle is opaque."""
        pass

    def DumpCollisions(self) -> None:
        pass

    def AddProximityCheck(self, check, anchor_obj) -> None:
        """Register a ProximityCheck for per-tick evaluation against an
        anchor object (typically the ship that owns the check). The
        anchor's world location is the center of the proximity radius."""
        entry = (check, anchor_obj)
        if entry not in self._proximity_checks:
            self._proximity_checks.append(entry)


def evaluate_proximity_checks() -> None:
    """Walk every live ProximityManager and dispatch each ProximityCheck's
    per-tick evaluation.  Called from GameLoop.tick between tick_all_ai and
    tick_all_ship_motion so the SDK conditions see fresh transitions before
    the motion integrator advances ships further.

    The (check, anchor) tuple stores an explicit anchor when the call
    site used AddProximityCheck(check, anchor); SDK condition flow
    instead leaves anchor=None and relies on ObjectClass.AttachObject
    having stored the anchor on the check itself."""
    import App
    for pSet in App.g_kSetManager._sets.values():
        pm = pSet.GetProximityManager() if hasattr(pSet, "GetProximityManager") else None
        if pm is None:
            continue
        checks = getattr(pm, "_proximity_checks", ())
        for check, anchor in checks:
            check.Evaluate(anchor)

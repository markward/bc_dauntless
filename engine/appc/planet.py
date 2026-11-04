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

from array import array

from engine.appc.objects import ObjectClass, PhysicsObjectClass
from engine.appc import proximity_cache
from engine.appc import proximity_table
from engine.appc.transform_store import get_store
from engine.core import frame_profiler


class Planet(ObjectClass):
    def __init__(self, radius: float = 0.0, model_path: str = ""):
        super().__init__()
        self.SetRadius(radius)
        self._model_path = model_path
        self._atmosphere_radius: float = 0.0
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

    # Hailable state (SetHailable / IsHailable) is inherited from ObjectClass,
    # which fires ET_HAILABLE_CHANGE on change so the SDK bridge builds/removes
    # the Helm "Hail" button. Mission scripts (E1M2.py:2346, E2M1.py:685,
    # E7M6.py:1429) toggle it to offer the planet as a hail target.

    # ── Object attachment ───────────────────────────────────────────────────
    def AttachObject(self, obj, *args) -> None:
        # The base anchors a ProximityCheck on us (MissionLib.ProximityCheck
        # attaches it to its main object); skipping it left every
        # planet-anchored check (E6M4's Tezle 1 pair) anchorless and dead.
        super().AttachObject(obj, *args)
        if obj not in self._attached:
            self._attached.append(obj)

    def DetachObject(self, obj, *args) -> None:
        super().DetachObject(obj, *args)
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

# Thin halo around the body sphere. The renderer's sun_pass draws the
# corona at this ratio of body radius; the wider visible glow is the
# separate flare-overlay billboard plus the lens flare.
_CORONA_SHELL_RATIO = 1.1


def aggregate_suns_for_renderer(game_root, pSets):
    """Return list[dict] for all Sun objects across pSets.

    Suns with no base_texture fall back to SunBase.tga (the BC engine default).
    Suns whose resolved base_texture path does not exist are dropped with a
    once-per-object warning (suppressed after first fire via _sun_warned).
    Suns with radius <= 0 are dropped silently.

    The corona is rendered as a thin 1.1x halo around the body. SDK
    atmosphere_thickness is gameplay-only (Planet.AtmosphereRadius is the
    AI keep-out / damage zone) and is NOT used for visual sizing. See
    docs/superpowers/specs/2026-05-28-sun-render-fidelity-design.md.

    flare_texture_path resolves the Sun's _flare_texture (5th arg to
    Sun_Create). Empty string when unset OR when the file is missing on
    disk (warned once via _flare_warned). Renderer treats empty as
    "skip the overlay layer" — body and corona still draw.
    """
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            if not isinstance(obj, Sun):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            try:
                scale = float(obj.GetScale())
            except Exception:
                scale = 1.0
            loc = obj.GetWorldLocation()
            tex_rel = obj.GetModelPath() or _SUN_DEFAULT_TEXTURE
            abs_path = (game_root / tex_rel).resolve()
            if not abs_path.is_file():
                if not obj.__dict__.get("_sun_warned", False):
                    print(
                        f"[suns] texture not found: {tex_rel!r}; skipping",
                        flush=True,
                    )
                    obj.__dict__["_sun_warned"] = True
                continue

            flare_rel = getattr(obj, "_flare_texture", "") or ""
            flare_abs_str = ""
            if flare_rel:
                flare_abs = (game_root / flare_rel).resolve()
                if flare_abs.is_file():
                    flare_abs_str = str(flare_abs)
                elif not obj.__dict__.get("_flare_warned", False):
                    print(
                        f"[suns] flare texture not found: {flare_rel!r}; "
                        f"sun will render without overlay",
                        flush=True,
                    )
                    obj.__dict__["_flare_warned"] = True

            out.append({
                "position":           (loc.x, loc.y, loc.z),
                "radius":             radius * scale,
                "base_texture_path":  str(abs_path),
                "corona_radius":      radius * _CORONA_SHELL_RATIO * scale,
                "flare_texture_path": flare_abs_str,
            })
    return out


# ── ProximityManager ────────────────────────────────────────────────────────
# SDK call sites (Maelstrom/.../E6M4.py): pSet.GetProximityManager().AddObject(pProbe)
# Per-set proximity tracker.

def _is_proximity_participant(obj) -> bool:
    """Whether `obj` belongs in the set's proximity index at all.

    A SetClass holds authoring and rendering bookkeeping next to real objects:
    the QuickBattle region ships a `Waypoint` ("Player Start"), two
    `LightPlacement`s and a `GridClass`, all at the origin and all radius 0.
    Handing those to the SDK's proximity walks does real damage — measured,
    AvoidObstacles steered around "LightPlacement(Ambient Light)" 166 times in
    300 ticks, and DockWithStarbase divided by zero on an object sitting
    exactly on the docking-entry placement it measures from.

    That last one is also the evidence for where BC drew this line: the SDK
    guards the zero-distance case at DockWithStarbase.py:94, and Python 2's
    cross-type comparison meant the guard never fired — so BC cannot have been
    returning zero-distance markers there either.

    Physics objects qualify unconditionally, NOT on radius: headless has no
    renderer realize step, so a real ship reports GetRadius() == 0, and a
    radius test would empty every proximity walk in exactly the environment the
    tests run in. Everything else has to actually occupy space, which keeps
    planets and suns (real radii, and AvoidObstacles is written to expect
    non-physics objects — it null-checks PhysicsObjectClass_Cast) and drops the
    markers.
    """
    from engine.appc.objects import PhysicsObjectClass

    if isinstance(obj, PhysicsObjectClass):
        return True
    # _radius_participates (below) mirrors this non-physics half for the
    # cached queries; the oracle differential in
    # tests/unit/test_proximity_cached_candidates.py guards the two.
    try:
        return float(obj.GetRadius()) > 0.0
    except Exception:
        return False


class _ProximityIteration(tuple):
    """The handle returned by GetNearObjects, walked by GetNextObject.

    Seven shipped SDK call sites use the same three-call contract — the handle
    is opaque to them and the cursor lives with it, not with the manager
    (FireScript's occlusion walk and AvoidObstacles' scan both run inside one
    tick, and a manager-held cursor would let one consume the other's objects).

    A tuple subclass, so a caller that treats the return value as the result
    set — which is what our own code and tests did while GetNextObject was a
    placeholder — keeps working unchanged.
    """
    # No __slots__: a tuple subclass cannot have a non-empty one (the base is
    # variable-length), so the cursor lives in the instance __dict__.
    def __new__(cls, items):
        self = super().__new__(cls, items)
        self._cursor = 0
        return self

    def next_object(self):
        if self._cursor >= len(self):
            return None
        obj = self[self._cursor]
        self._cursor += 1
        return obj


_deps = None


def _query_deps():
    """(ProximityCheck, SetClass, projectiles), imported once.

    Not at module scope: engine.appc.ai and projectiles sit above this module
    in the import graph. Cached so a query does no per-call import."""
    global _deps
    if _deps is None:
        from engine.appc.ai import ProximityCheck
        from engine.appc.sets import SetClass
        from engine.appc import projectiles
        _deps = (ProximityCheck, SetClass, projectiles)
    return _deps


class _Cand:
    """One manager's candidate list for one membership generation.

    `objs` is ProximityManager._candidates()'s order, except that it lists
    EVERY set member (participant or not; a member under two names once) and
    no ProximityCheck. Per entry: `is_set`, `physics` (a PhysicsObjectClass:
    always participates), `stored` (location_is_stored) and `dup_of` (a
    manager entry that is also a set member: that member's index, else -1).
    `packed` holds the stored entries' (index, generation) handles flat, and
    `packed_pos` their positions in `objs`; `unstored_pos` the rest.

    Holds strong references, so no listed object's transform slot can be
    freed while the cache lists it (a stale handle would raise).

    `stored` and `physics` are frozen at build: a class swap must go through
    native_combat.reclassify, and a patched GetWorldLocation through a
    proximity_cache.bump(), or the cache keeps the old answer."""
    __slots__ = ("gen", "objs", "is_set", "physics", "stored", "dup_of",
                 "packed", "packed_pos", "unstored_pos")


def _radius_participates(obj) -> bool:
    """_is_proximity_participant for a known non-physics object."""
    try:
        return float(obj.GetRadius()) > 0.0
    except Exception:
        return False


def _size(obj) -> float:
    """BC's size rule (ruling 4): the bounding radius a near query adds to its
    reach, read live: GetRadius() (the scaled world radius); one that raises
    counts as 0. A value that is not > 0 is made 0 by the compare itself."""
    try:
        return float(obj.GetRadius())
    except Exception:
        return 0.0


def _within_reach(dx, dy, dz, r, size) -> bool:
    """The size rule's compare, rounded as near_indices_sized rounds it."""
    reach = r + (size if size > 0.0 else 0.0)
    return dx * dx + dy * dy + dz * dz <= reach * reach


def _reports(cand, i) -> bool:
    """Whether entry `i` is a candidate THIS query (the uncached walk's
    rule): a set member when it participates now; a manager entry unless its
    set twin participates (then it was reported at the set slot)."""
    if cand.is_set[i]:
        return cand.physics[i] or _radius_participates(cand.objs[i])
    d = cand.dup_of[i]
    return d < 0 or not (cand.physics[d] or _radius_participates(cand.objs[d]))


class ProximityManager:
    def __init__(self, pSet=None):
        self._set = pSet
        self._objects: list = []
        # The cached candidate list (_cached); None until the first query.
        self._cand = None
        # Eager init — TGObject.__getattr__ returns a truthy _Stub for
        # missing attrs, so the lazy `getattr(..., None)` idiom would
        # mis-resolve.  See engine/appc/events.py TGPythonInstanceWrapper.
        self._proximity_checks: list = []

    def AddObject(self, obj) -> None:
        ProximityCheck = _query_deps()[0]
        is_check = isinstance(obj, ProximityCheck)
        if obj not in self._objects:
            self._objects.append(obj)
            # A check is never a candidate (_build_cand skips it), so it
            # changes no cache: ConditionInRange re-adds one per retarget.
            if not is_check:
                proximity_cache.bump()
        # SDK ConditionInRange.SetupProximitySphere calls
        # pProximityManager.AddObject(pProx) — the proximity check is
        # registered here so the per-tick evaluator can find it. We track
        # it in _proximity_checks too (anchor=None — anchor will be set
        # by ObjectClass.AttachObject(prox) which is called immediately
        # after).
        if is_check:
            # The set this manager belongs to is the check's set when it has
            # no anchor (E6M3.CreateProximityCheck never calls AttachObject).
            obj._manager_set = self._set
            entry = (obj, None)
            if entry not in self._proximity_checks:
                self._proximity_checks.append(entry)
                proximity_table.touch()

    def RemoveObject(self, obj) -> None:
        if obj in self._objects:
            self._objects.remove(obj)
            if not isinstance(obj, _query_deps()[0]):     # see AddObject
                proximity_cache.bump()

    def UpdateObject(self, obj) -> None:
        # SDK pattern (QuickBattle.py:2726): notifies the proximity tracker
        # that an object's position has changed and its bucket assignment
        # may need recomputing.  Phase 1: idempotent ensure-present.
        if obj not in self._objects:
            self._objects.append(obj)
            if not isinstance(obj, _query_deps()[0]):     # see AddObject
                proximity_cache.bump()

    def _forget(self, obj) -> None:
        """`obj` has left this manager's set: drop every occurrence of it from
        the list (ruling 6, native-motion design s3), so a ship Quick Battle
        UpdateObject'd in is not returned after it is evicted, deleted or
        warps away. Also drops the cached candidates, which hold it strongly,
        so a manager never queried again does not keep it alive. Checks are
        left alone: their lifetime is RemoveAndDelete / _proximity_checks."""
        if not self._holds(obj) or isinstance(obj, _query_deps()[0]):
            return
        self._objects = [o for o in self._objects if o is not obj]
        self._cand = None
        proximity_cache.bump()

    def _holds(self, obj) -> bool:
        return any(o is obj for o in self._objects)

    def GetNumObjects(self) -> int:
        return len(self._objects)

    def _candidates(self):
        """Everything this manager can report: the containing set's objects,
        plus anything hand-registered through AddObject.

        BC's ProximityManager IS the set's spatial index. Its QUERIES
        (GetNearObjects / GetLineIntersectObjects) never return a
        ProximityCheck (ruling 1, native-motion design s3), so they skip
        checks; this list still holds them, because AddObject registers them
        here. The per-tick check evaluator (proximity_table) does not read
        this list. Ours only ever held what AddObject was called with, and
        nothing registers ships, so a live QuickBattle scene had 5 ships in the
        world and GetNumObjects() == 0.

        Read through to the set each call rather than mirroring it into
        ``_objects``: a private copy goes stale the moment a ship is destroyed,
        and handing a dead ship back to AvoidObstacles makes it dodge a hole in
        space. AddObject entries that are also set members are reported once
        (E6M4 registers a probe that is in the set too), because the SDK loops
        only skip the searching ship itself and would otherwise score one
        object as two obstacles at the same point.
        """
        out = []
        seen = set()
        pSet = self._set
        if pSet is not None:
            # Torpedoes never occupy space unless something gives one a
            # radius, so while none has, walk the set's non-torpedo index
            # (SetClass._non_torpedo): same members, same order, without
            # stepping through every torpedo in flight.
            _, SetClass, projectiles = _query_deps()
            if isinstance(pSet, SetClass) and not projectiles.sized_torpedo_in(pSet):
                members = list(pSet._non_torpedo.values())
            else:
                try:
                    members = pSet.GetObjectList()
                except Exception:
                    members = ()
            for obj in members:
                if id(obj) not in seen and _is_proximity_participant(obj):
                    seen.add(id(obj))
                    out.append(obj)
        for obj in self._objects:
            if id(obj) not in seen:
                seen.add(id(obj))
                out.append(obj)
        return out

    def _cached(self):
        """This manager's _Cand for the current membership generation, or
        None when the query must take the uncached Python path: a set that
        is not a SetClass (no `_non_torpedo` index to cache), or one holding
        a sized torpedo (then every member is walked, as `_candidates` does).

        The key is (proximity_cache.generation(), sized_torpedo_in(set)); a
        sized torpedo is never cached and its transitions bump the
        generation, so the generation alone decides a rebuild."""
        _, SetClass, projectiles = _query_deps()
        pSet = self._set
        if pSet is not None and (not isinstance(pSet, SetClass)
                                 or projectiles.sized_torpedo_in(pSet)):
            return None
        gen = proximity_cache.generation()
        cand = self._cand
        if cand is None or cand.gen != gen:
            cand = self._cand = self._build_cand(gen)
        return cand

    def _build_cand(self, gen):
        ProximityCheck = _query_deps()[0]
        objs, is_set, dup_of = [], [], []
        at = {}                 # id(set member) -> its index in objs
        if self._set is not None:
            for obj in self._set._non_torpedo.values():
                if id(obj) in at or isinstance(obj, ProximityCheck):
                    continue
                at[id(obj)] = len(objs)
                objs.append(obj)
                is_set.append(True)
                dup_of.append(-1)
        seen = set()
        for obj in self._objects:
            if id(obj) in seen or isinstance(obj, ProximityCheck):
                continue
            seen.add(id(obj))
            objs.append(obj)
            is_set.append(False)
            dup_of.append(at.get(id(obj), -1))
        cand = _Cand()
        cand.gen = gen
        cand.objs = objs
        cand.is_set = is_set
        cand.dup_of = dup_of
        cand.physics = [isinstance(o, PhysicsObjectClass) for o in objs]
        cand.stored = [proximity_table.location_is_stored(o) for o in objs]
        cand.packed = array("I")
        cand.packed_pos = []
        cand.unstored_pos = []
        for i, obj in enumerate(objs):
            if cand.stored[i]:
                index, generation = obj._xform
                cand.packed.append(index)
                cand.packed.append(generation)
                cand.packed_pos.append(i)
            else:
                cand.unstored_pos.append(i)
        return cand

    def GetNearObjects(self, point, radius, eType=None):
        """Objects whose surface is within `radius` world-space units of
        `point`: BC's size rule (ruling 4), `|location - point| <= radius +
        max(GetRadius(), 0)`, boundary included. GetRadius() is the scaled
        world radius, read live on every query; one that raises counts as 0,
        so a radius-0 object (every headless ship) keeps the centre rule.

        Returns an iteration handle (also a plain sequence — see
        _ProximityIteration). SDK callers walk it with GetNextObject and
        release it with EndObjectIteration; ConditionInRange and our own code
        read it directly.

        SDK call sites pass an optional third arg (MissionLib.py:5035 passes
        ``1`` — BC's includeSize flag, which in the near query only widens the
        axis prune and so cannot change the answer); accepted and ignored.

        Timed as `prox.near` (native motion + proximity phase 0).

        Answered from the cached candidate list (_cached) with one native
        `near_indices_sized` call for every store-backed entry; same objects,
        same order as the uncached walk (tests/helpers/proximity_oracle.py).
        """
        with frame_profiler.scope("prox.near"):
            return self._near_objects(point, radius)

    def _near_objects(self, point, radius):
        cand = self._cached()
        if cand is None:
            return self._near_objects_python(point, radius)
        r = float(radius)
        px, py, pz = point.x, point.y, point.z
        objs = cand.objs
        keep = []
        if cand.packed:
            pos = cand.packed_pos
            radii = array("d", [_size(objs[i]) for i in pos])
            for k in get_store().near_indices_sized(cand.packed, radii,
                                                    px, py, pz, r):
                i = pos[k]
                if _reports(cand, i):
                    keep.append(i)
        if cand.unstored_pos:
            # Asked themselves (none in a fight). Participation first, as the
            # uncached walk never asks a non-candidate where it is.
            more = []
            for i in cand.unstored_pos:
                if not _reports(cand, i):
                    continue
                obj = objs[i]
                loc = (obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation")
                       else None)
                if loc is None:
                    continue
                if _within_reach(loc.x - px, loc.y - py, loc.z - pz, r,
                                 _size(obj)):
                    more.append(i)
            if more:
                keep = sorted(keep + more) if keep else more
        return _ProximityIteration([objs[i] for i in keep])

    def _near_objects_python(self, point, radius):
        """The uncached query: a set holding a sized torpedo, or no SetClass."""
        r = float(radius)
        px, py, pz = point.x, point.y, point.z
        ProximityCheck = _query_deps()[0]
        candidates = [o for o in self._candidates()
                      if not isinstance(o, ProximityCheck)]
        # Every ConditionInRange registers a proximity check here, so a
        # 64-ship fight walks ~337 candidates per AvoidObstacles query; one
        # store crossing each was 40% of all AI time. Objects whose location
        # IS their transform-store slot are tested in ONE store call
        # (near_indices_sized: the compare below, rounded the same way). One
        # that answers GetWorldLocation itself (DebrisChunk, subsystems, ...)
        # is still asked.
        stored = [obj for obj in candidates
                  if proximity_table.location_is_stored(obj)]
        inside = {}
        if stored:
            packed = array("I")
            for obj in stored:
                packed.extend(obj._xform)
            radii = array("d", [_size(obj) for obj in stored])
            inside = dict.fromkeys(map(id, stored), False)
            for k in get_store().near_indices_sized(packed, radii,
                                                    px, py, pz, r):
                inside[id(stored[k])] = True
        result = []
        for obj in candidates:
            f = inside.get(id(obj))
            if f is not None:
                if f:
                    result.append(obj)
                continue
            loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
            if loc is None:
                continue
            if _within_reach(loc.x - px, loc.y - py, loc.z - pz, r, _size(obj)):
                result.append(obj)
        return _ProximityIteration(result)

    def GetLineIntersectObjects(self, start, end, radius=0.0, flag=None):
        """Objects whose sphere intersects the capsule swept along start→end.

        The second of the manager's two iteration producers; walked with
        GetNextObject / EndObjectIteration exactly like GetNearObjects. Four SDK
        call sites use it:

            Conditions/ConditionInLineOfSight.py:128  (start, end, 0)
            AI/Preprocessors.py:373        FireScript occlusion, radius 0.5
            AI/PlainAI/Intercept.py:269    (start, dest, shipRadius*4, 1)
            MissionLib.py:4930             warp-path obstacles

        A SEGMENT, not an infinite line: Intercept and MissionLib are both
        reasoning about a finite leg, and an infinite line would report
        obstacles behind the ship. Endpoints are included — FireScript and
        ConditionInLineOfSight pass object positions as the endpoints and filter
        them out themselves by id / name.

        ⚠️ This was a hardcoded ``return ()`` — a Phase-1 placeholder alongside
        ``GetNextObject``'s ``return None``. Fixing GetNextObject alone left all
        four of these dead, which is why an earlier commit message overstated
        what it revived.

        The trailing flag is accepted and ignored, as on GetNearObjects: it is
        BC's ``includeSize`` flag. In BC it does reach the line query's exact
        test as an object "own size" term whose meaning is still open
        (docs/reference/engine/native-motion/open-questions-by-reading.md
        Q3(d)). Two SDK callers pass it (AI/PlainAI/Intercept.py:269,
        MissionLib.py:4930).

        Timed as `prox.line` (native motion + proximity phase 0). Walks the
        cached candidate list (_cached), reading each participant's radius at
        query time; the segment math is unchanged.
        """
        with frame_profiler.scope("prox.line"):
            return self._line_objects(start, end, radius)

    def _line_objects(self, start, end, radius):
        cand = self._cached()
        if cand is None:
            ProximityCheck = _query_deps()[0]
            candidates = [o for o in self._candidates()
                          if not isinstance(o, ProximityCheck)]
        else:
            objs = cand.objs
            candidates = [objs[i] for i in range(len(objs)) if _reports(cand, i)]
        r = float(radius)
        ax, ay, az = start.x, start.y, start.z
        dx, dy, dz = end.x - ax, end.y - ay, end.z - az
        seg_len2 = dx * dx + dy * dy + dz * dz
        result = []
        for obj in candidates:
            loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
            if loc is None:
                continue
            px, py, pz = loc.x - ax, loc.y - ay, loc.z - az
            if seg_len2 <= 1e-12:
                # Degenerate leg (Intercept can ask for one when it is already
                # at its destination): a point query, not a division by zero.
                t = 0.0
            else:
                t = (px * dx + py * dy + pz * dz) / seg_len2
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            cx, cy, cz = px - t * dx, py - t * dy, pz - t * dz
            try:
                reach = r + float(obj.GetRadius())
            except Exception:
                reach = r
            if cx * cx + cy * cy + cz * cz <= reach * reach:
                result.append(obj)
        return _ProximityIteration(result)

    def GetNextObject(self, iterator=None):
        """Advance a proximity iteration handle; None when it is exhausted.

        ⚠️ This was a hardcoded ``return None`` — a Phase-1 placeholder — which
        meant every SDK ``while pObject != None:`` walk exited BEFORE its first
        iteration. Seven shipped call sites were silent no-ops as a result, the
        load-bearing one being AvoidObstacles.TestCourseOverride: it always
        returned "nothing to avoid", so AI collision avoidance never ran for any
        ship. A placeholder returning a real value leaves no attribute miss, so
        docs/stub_heatmap.md could never have shown it.

        Tolerant of a handle we did not issue (None, or a plain sequence from
        older code): those simply report exhausted rather than raising, matching
        how the rest of the SDK surface degrades.
        """
        if isinstance(iterator, _ProximityIteration):
            return iterator.next_object()
        return None

    def EndObjectIteration(self, iterator=None) -> None:
        """Release a proximity iteration handle. Nothing to free — the handle
        owns its own cursor — but SDK code calls this on paths where the handle
        was never created (ConditionInLineOfSight bails early), so it must
        accept anything."""
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
            proximity_table.touch()


def evaluate_proximity_checks() -> None:
    """Walk every live ProximityManager and dispatch each ProximityCheck's
    per-tick evaluation.  Called from GameLoop.tick between tick_all_ai and
    tick_all_ship_motion so the SDK conditions see fresh transitions before
    the motion integrator advances ships further.

    The (check, anchor) tuple stores an explicit anchor when the call
    site used AddProximityCheck(check, anchor); SDK condition flow
    instead leaves anchor=None and relies on ObjectClass.AttachObject
    having stored the anchor on the check itself.

    That is: for every set, for every (check, anchor) its manager holds,
    check.Evaluate(anchor). proximity_table runs exactly that from a cached
    pair table, so only the pairs that could fire reach Python."""
    proximity_table.evaluate()

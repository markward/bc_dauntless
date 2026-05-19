"""
Object class hierarchy for Phase 1 headless engine.

ObjectClass        — named, positioned, oriented, scaled game object
PhysicsObjectClass — adds velocity, mass, direction-space constants
DamageableObject   — placeholder for hull/shield state (Phase 2)
ObjectGroup        — named membership list (friendly/enemy/neutral groups)
"""

from engine.appc.events import TGEventHandlerObject
from engine.appc.math import TGPoint3, TGMatrix3


class _NodeStub:
    """Chainable stub for animation/render node — truthy, accepts any call."""
    def __getattr__(self, name):
        return self
    def __call__(self, *args, **kwargs):
        return _NodeStub()
    def __bool__(self):
        return True
    def __repr__(self):
        return "<_NodeStub>"


class ObjectClass(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._name: str = ""
        self._script: str = ""
        self._radius: float = 0.0
        self._scale: float = 1.0
        self._hidden: bool = False
        self._position: TGPoint3 = TGPoint3(0.0, 0.0, 0.0)
        self._rotation: TGMatrix3 = TGMatrix3()   # identity
        self._containing_set = None

    # ── Identity ──────────────────────────────────────────────────────────────

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def GetScript(self) -> str:
        return self._script

    def SetScript(self, script: str) -> None:
        self._script = script

    def GetRadius(self) -> float:
        return self._radius

    def SetRadius(self, r: float) -> None:
        self._radius = float(r)

    def GetScale(self) -> float:
        return self._scale

    def SetScale(self, s: float) -> None:
        self._scale = float(s)

    def IsHidden(self) -> bool:
        return self._hidden

    def SetHidden(self, hidden: bool) -> None:
        self._hidden = bool(hidden)

    def GetDisplayName(self) -> str:
        return self._name

    def SetDisplayName(self, name: str) -> None:
        self._name = name

    # ── Set membership ────────────────────────────────────────────────────────

    def GetContainingSet(self):
        return self._containing_set

    # ── Translation ───────────────────────────────────────────────────────────

    def SetTranslateXYZ(self, x: float, y: float, z: float) -> None:
        self._position = TGPoint3(float(x), float(y), float(z))

    def SetTranslate(self, point: TGPoint3) -> None:
        self._position = TGPoint3(point.x, point.y, point.z)

    def SetWorldLocation(self, pos) -> None:
        """Test/host-side helper to position an object via (x, y, z) tuple
        or TGPoint3. Not part of the SDK API surface — SDK scripts use
        SetTranslate(TGPoint3) or SetTranslateXYZ. Do not call from
        engine code that simulates SDK behavior.
        """
        if hasattr(pos, 'x'):
            self._position = TGPoint3(float(pos.x), float(pos.y), float(pos.z))
        else:
            self._position = TGPoint3(float(pos[0]), float(pos[1]), float(pos[2]))

    def GetTranslate(self) -> TGPoint3:
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetWorldLocation(self) -> TGPoint3:
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    # ── Rotation ──────────────────────────────────────────────────────────────

    def SetMatrixRotation(self, matrix: TGMatrix3) -> None:
        self._rotation = matrix

    def GetRotation(self) -> TGMatrix3:
        result = TGMatrix3()
        result._m = [row[:] for row in self._rotation._m]
        return result

    def GetWorldRotation(self) -> TGMatrix3:
        result = TGMatrix3()
        result._m = [row[:] for row in self._rotation._m]
        return result

    def SetAngleAxisRotation(self, angle: float, axis: TGPoint3) -> None:
        m = TGMatrix3()
        m.MakeRotation(angle, axis)
        self._rotation = m

    def AlignToVectors(self, forward: TGPoint3, up: TGPoint3) -> None:
        """Build an orthonormal rotation matrix from forward and up vectors.

        Convention (matching BC/Gamebryo NiMatrix3 column-vector form):
          row 0 = right  = normalize(forward × up) ... nope: up × forward
          Actually we use: right = up.Cross(forward), then re-derive up.
        """
        fwd = TGPoint3(forward.x, forward.y, forward.z)
        fwd.Unitize()
        u = TGPoint3(up.x, up.y, up.z)
        # Orthogonalize up against forward
        dot = fwd.Dot(u)
        u = TGPoint3(u.x - dot * fwd.x, u.y - dot * fwd.y, u.z - dot * fwd.z)
        u.Unitize()
        # right = up × forward (right-handed, Z-up Y-forward)
        right = u.Cross(fwd)
        right.Unitize()
        m = TGMatrix3()
        m.SetRow(0, right)
        m.SetRow(1, fwd)
        m.SetRow(2, u)
        self._rotation = m

    def Rotate(self, *args) -> None:
        pass

    # ── Placement ─────────────────────────────────────────────────────────────

    def PlaceObjectByName(self, name: str) -> None:
        """Copy position and rotation from a named waypoint in the global registry."""
        from engine.appc.placement import _waypoint_registry
        wp = _waypoint_registry.get(name)
        if wp is not None:
            self.SetTranslate(wp.GetWorldLocation())
            self.SetMatrixRotation(wp.GetWorldRotation())

    # ── Scene-graph stubs ─────────────────────────────────────────────────────

    def UpdateNodeOnly(self) -> None:
        pass

    def Update(self, *args) -> None:
        pass

    def AttachObject(self, *args) -> None:
        # SDK ConditionInRange.SetupProximitySphere calls
        # pObject1.AttachObject(self.pProx) so the proximity check is
        # parented to the anchor object's transform. Phase 1 has no
        # scene graph, but we do need the anchor reference so the
        # per-tick proximity evaluator can center the radius correctly.
        if args:
            obj = args[0]
            # Late import: ai → planet → ai cycles otherwise.
            from engine.appc.ai import ProximityCheck
            if isinstance(obj, ProximityCheck):
                obj._anchor = self

    def DetachObject(self, *args) -> None:
        pass

    def SetDeleteMe(self, *args) -> None:
        pass

    def GetNode(self):
        return None

    def GetAnimNode(self) -> "_NodeStub":
        return _NodeStub()

    def GetWorldForwardTG(self) -> TGPoint3:
        """World-forward = R · model_forward = column 1 of R.

        Column-vector convention matches the integrator
        (engine/appc/ship_motion.py uses MultMatrixLeft) and the SDK's
        TurnToOrientation.Update. Same fix shape as commit 68f6220
        which closed the equivalent bug in GetRelativePositionInfo.
        """
        return self._rotation.GetCol(1)

    def GetContainingSetName(self) -> str:
        if self._containing_set is not None:
            return self._containing_set.GetName()
        return ""


class PhysicsObjectClass(ObjectClass):
    DIRECTION_MODEL_SPACE = 0
    DIRECTION_WORLD_SPACE = 1

    def __init__(self):
        super().__init__()
        self._velocity: TGPoint3 = TGPoint3(0.0, 0.0, 0.0)
        self._angular_velocity: TGPoint3 = TGPoint3(0.0, 0.0, 0.0)
        self._mass: float = 0.0
        self._rotational_inertia: float = 0.0
        self._static: bool = False
        self._use_physics: bool = False

    # ── Velocity ──────────────────────────────────────────────────────────────

    def SetVelocity(self, v: TGPoint3) -> None:
        self._velocity = TGPoint3(v.x, v.y, v.z)

    def GetVelocity(self, space: int = DIRECTION_WORLD_SPACE) -> TGPoint3:
        return TGPoint3(self._velocity.x, self._velocity.y, self._velocity.z)

    def GetVelocityTG(self) -> TGPoint3:
        return TGPoint3(self._velocity.x, self._velocity.y, self._velocity.z)

    def GetAccelerationTG(self) -> TGPoint3:
        """Phase 1: kinematic model stores no acceleration on the object —
        acceleration is the integrator's per-tick ramp. Returns a fresh
        zero vec so callers can mutate without leaking state. SDK Intercept
        uses this as the `a` arg to GetPredictedPosition; with a = 0 the
        prediction degenerates to p + v·t, correct at near-constant
        velocity."""
        return TGPoint3(0.0, 0.0, 0.0)

    def SetAngularVelocity(self, v: TGPoint3, space: int = DIRECTION_WORLD_SPACE) -> None:
        self._angular_velocity = TGPoint3(v.x, v.y, v.z)

    def GetAngularVelocity(self, space: int = DIRECTION_WORLD_SPACE) -> TGPoint3:
        return TGPoint3(self._angular_velocity.x, self._angular_velocity.y, self._angular_velocity.z)

    def GetAngularVelocityTG(self) -> TGPoint3:
        return TGPoint3(self._angular_velocity.x, self._angular_velocity.y, self._angular_velocity.z)

    # ── Mass / inertia ────────────────────────────────────────────────────────

    def GetMass(self) -> float:
        return self._mass

    def SetMass(self, m: float) -> None:
        self._mass = float(m)

    def GetRotationalInertia(self) -> float:
        return self._rotational_inertia

    def SetRotationalInertia(self, i: float) -> None:
        self._rotational_inertia = float(i)

    # ── Force / acceleration (Phase 1 no-ops) ────────────────────────────────

    def ApplyForce(self, *args) -> None:
        pass

    def SetAcceleration(self, *args) -> None:
        pass

    def SetAngularAcceleration(self, *args) -> None:
        pass

    def SetAngularAccelerationLinear(self, *args) -> None:
        pass

    def TurnTowardOrientation(self, *args) -> None:
        pass

    def SetAngularDirectionType(self, *args) -> None:
        pass

    def GetAngularDirectionType(self) -> int:
        return 0

    # ── Physics flags ─────────────────────────────────────────────────────────

    def SetStatic(self, static: bool) -> None:
        self._static = bool(static)

    def IsStatic(self) -> bool:
        return self._static

    def SetUsePhysics(self, use: bool) -> None:
        self._use_physics = bool(use)

    def IsUsingPhysics(self) -> bool:
        return self._use_physics

    # ── Net type ──────────────────────────────────────────────────────────────

    def SetNetType(self, *args) -> None:
        pass

    def GetNetType(self) -> int:
        return 0

    def SetDoNetUpdate(self, *args) -> None:
        pass

    def IsDoingNetUpdate(self) -> bool:
        return False

    # ── AI (Phase 1 stubs) ────────────────────────────────────────────────────

    def SetAI(self, *args) -> None:
        pass

    def ClearAI(self) -> None:
        pass

    def HasBuildingAIs(self) -> bool:
        return False

    def SetupModel(self, *args) -> None:
        pass


class DamageableObject(PhysicsObjectClass):
    """Placeholder — hull/shield damage state lives here in Phase 2.

    Owns a ``TGModelPropertySet`` populated by hardpoint scripts via
    ``mod.LoadPropertySet(pShip.GetPropertySet())`` (see SDK
    loadspacehelper.py:87).  ``SetupProperties()`` then walks the set to
    plumb template values onto the live ship + subsystem instances.
    """

    def __init__(self):
        super().__init__()
        from engine.appc.properties import TGModelPropertySet
        self._property_set = TGModelPropertySet()

    def GetPropertySet(self):
        return self._property_set

    def DamageSystem(self, subsystem, amount: float) -> None:
        """Apply damage to a subsystem.  Decrement its condition floored
        at zero.  If the subsystem is this object's hull and condition
        reaches zero, mark the object as dying — mission scripts trigger
        the destruction sequence via the existing SetDying/SetDead path.
        """
        if subsystem is None:
            return
        amt = float(amount)
        if amt <= 0.0:
            return
        cur = subsystem.GetCondition()
        new_cond = max(0.0, cur - amt)
        subsystem.SetCondition(new_cond)
        hull = self.GetHull() if hasattr(self, "GetHull") else None
        if subsystem is hull and new_cond <= 0.0 and hasattr(self, "SetDying"):
            self.SetDying(True)


class ObjectGroup(TGEventHandlerObject):
    GROUP_CHANGED = 1
    ENTERED_SET = 2
    EXITED_SET = 3
    DESTROYED = 4

    def __init__(self):
        super().__init__()
        self._names: list[str] = []
        # Per-name event flags (SetEventFlag/ClearEventFlag/IsEventFlagSet).
        # SDK uses these to mark group-membership events as already-handled.
        self._event_flags: dict[str, set[int]] = {}

    def AddName(self, name: str) -> None:
        if name not in self._names:
            self._names.append(name)

    def RemoveName(self, name: str) -> None:
        if name in self._names:
            self._names.remove(name)
        self._event_flags.pop(name, None)

    def RemoveAllNames(self) -> None:
        self._names.clear()
        self._event_flags.clear()

    def IsNameInGroup(self, name: str) -> int:
        return 1 if name in self._names else 0

    def GetNumActiveObjects(self) -> int:
        return len(self._names)

    # ── Name iteration ───────────────────────────────────────────────────────
    def GetNameTuple(self) -> tuple:
        # Returned to SDK callers like MissionLib.SetupWeaponHitHandlers which
        # expect to call ``list(group.GetNameTuple())``.
        return tuple(self._names)

    # ── Active-object lookup against a SetClass ──────────────────────────────
    def GetActiveObjectTupleInSet(self, pSet) -> tuple:
        """Return live ObjectClass instances from pSet whose name is in this group.

        Mirrors sdk/.../App.py:ObjectGroup_GetActiveObjectTupleInSet.  Callers:
        E1M2.py:3364 (proximity check), TacticalInterfaceHandlers.py (target
        list), MissionLib.py:4132 (player containing-set scan).
        """
        if pSet is None:
            return ()
        result = []
        for name in self._names:
            obj = pSet.GetObject(name) if hasattr(pSet, "GetObject") else None
            if obj is not None:
                result.append(obj)
        return tuple(result)

    def GetActiveObjectTuple(self) -> tuple:
        """No-arg variant: walk every live set in g_kSetManager looking for
        any object whose name matches one of our watched names. SDK
        conditions use this when they don't know which set their target
        lives in yet."""
        import App
        result = []
        for pSet in App.g_kSetManager._sets.values():
            for name in self._names:
                obj = pSet.GetObject(name) if hasattr(pSet, "GetObject") else None
                if obj is not None and obj not in result:
                    result.append(obj)
        return tuple(result)

    # ── Event flags ──────────────────────────────────────────────────────────
    def SetEventFlag(self, *args) -> None:
        """Two forms:
            SetEventFlag(name, flag)  → per-name flag (legacy callers)
            SetEventFlag(flag)        → group-level: apply to all watched names
        SDK conditions use the single-arg form to mark "I want enter/exit
        events for everything in my group."
        """
        if len(args) == 1:
            flag = int(args[0])
            for name in self._names:
                self._event_flags.setdefault(name, set()).add(flag)
        elif len(args) == 2:
            name, flag = args
            self._event_flags.setdefault(name, set()).add(int(flag))

    def ClearEventFlag(self, name: str, flag: int) -> None:
        flags = self._event_flags.get(name)
        if flags is not None:
            flags.discard(int(flag))

    def IsEventFlagSet(self, name: str, flag: int) -> int:
        return 1 if int(flag) in self._event_flags.get(name, set()) else 0


class ObjectGroupWithInfo(ObjectGroup):
    """ObjectGroup with per-name metadata.

    FixApp.py wires `__getitem__/__setitem__/__delitem__` onto this class
    so SDK callers can use dict-syntax (``group[name] = info``) — but the
    underlying named methods (``GetInfo`` / ``AddNameAndInfo`` / ``RemoveName``)
    are what FixApp aliases.
    """
    def __init__(self):
        super().__init__()
        self._info: dict[str, object] = {}

    def AddNameAndInfo(self, name: str, info) -> None:
        self.AddName(name)
        self._info[name] = info

    def GetInfo(self, name: str):
        return self._info.get(name)

    def RemoveName(self, name: str) -> None:
        super().RemoveName(name)
        self._info.pop(name, None)

    def __getitem__(self, name: str) -> dict:
        """Per-name info dict, or empty dict for unknown names.

        SDK SelectTarget rating reads pGroupWithInfo[sTarget]["Priority"]
        then chains `.has_key("Priority")` — the empty-dict fallback
        keeps that pattern safe for targets without recorded info.
        """
        return self._info.get(name, {})

    def __setitem__(self, name: str, info) -> None:
        self.AddNameAndInfo(name, info)

    def __delitem__(self, name: str) -> None:
        self.RemoveName(name)


# ── Module-level helpers ──────────────────────────────────────────────────────

def ObjectGroup_ForceToGroup(arg) -> ObjectGroup:
    """Coerce a name list / single name / existing ObjectGroup to an ObjectGroup.

    SDK call sites (E1M2.py:3363, AI/Compound/CloakAttack.py:16, AI/PlainAI/
    Flee.py:33, etc.) pass either a list of object names or an already-built
    ObjectGroup; the helper hands back a usable ObjectGroup either way.

    Also unwrap a single-element tuple/list whose only element is already an
    ObjectGroup — `AI.Preprocessors.SelectTarget.__init__` collects its arg
    via `*pTargetGroup` and then forwards the resulting tuple here. The real
    SDK helper unwraps that tuple so the ObjectGroupWithInfo identity (and
    its priority dict) is preserved. Without this unwrap the priority/info
    factor in `GetTargetRating` always reads as 0.
    """
    if isinstance(arg, ObjectGroup):
        return arg
    if isinstance(arg, (tuple, list)) and len(arg) == 1 and isinstance(arg[0], ObjectGroup):
        return arg[0]
    group = ObjectGroup()
    if isinstance(arg, str):
        group.AddName(arg)
    elif arg is not None:
        for name in arg:
            group.AddName(str(name))
    return group


def ObjectGroup_FromModule(module_name: str, attr_name: str) -> ObjectGroup:
    """Re-fetch ``module.attr_name`` and coerce it to an ObjectGroup.

    SDK pattern used by AI templates: each AI invocation re-imports the
    mission module and reads ``pEnemies`` / ``pFriendlies`` etc., letting
    those lists change at runtime as ships join or die.
    """
    import importlib
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return ObjectGroup()
    arg = getattr(mod, attr_name, None)
    return ObjectGroup_ForceToGroup(arg) if arg is not None else ObjectGroup()


def ObjectGroupWithInfo_Cast(obj):
    return obj if isinstance(obj, ObjectGroupWithInfo) else None


# ── ObjectClass module-level helpers ──────────────────────────────────────────

def ObjectClass_Cast(obj) -> "ObjectClass | None":
    """Return obj if it is an ObjectClass, else None.

    SDK callers (Effects.py:555, MissionLib.py:1516/3919) chain
    ``App.ObjectClass_Cast(pUnknown).GetName()`` after a downcast — in
    Phase 1 the cast is a runtime isinstance check.  Returns None for
    non-ObjectClass inputs so SDK guards (`if pObject:`) short-circuit
    correctly.
    """
    return obj if isinstance(obj, ObjectClass) else None


def PhysicsObjectClass_Cast(obj) -> "PhysicsObjectClass | None":
    """Return obj if it is a PhysicsObjectClass, else None.

    SDK pattern (AI/PlainAI/Intercept.py): cast a generic target to its
    physics-object form before reading velocity/acceleration. Targets
    that are bare ObjectClass / PlacementObject have no velocity, so
    callers fall back to current position when this returns None.
    """
    return obj if isinstance(obj, PhysicsObjectClass) else None


def DamageableObject_Cast(obj) -> "DamageableObject | None":
    """Return obj if it is a DamageableObject, else None.

    SDK pattern (AI/Preprocessors.py:1438 — SelectTarget.FindGoodTarget):
    ``pDam = App.DamageableObject_Cast(pOldTarget)`` then guard with
    ``if pDam:`` before checking ``pDam.IsDead()`` / ``pDam.IsDying()``.
    None for non-damageable targets keeps the SDK's truthiness guards
    correct (the dead/dying skip only applies when the cast succeeds).
    """
    return obj if isinstance(obj, DamageableObject) else None


def ObjectClass_GetObject(pSet, name) -> "ObjectClass | None":
    """Look up an object by name within a SetClass.

    SDK pattern: ``App.ObjectClass_GetObject(pSet, sObjectName)`` (Camera.py:374).
    Mirrors the per-class GetObject helpers (ShipClass_GetObject, CharacterClass_GetObject)
    but without the type filter — returns whatever is registered under the name.
    """
    if pSet is None or not hasattr(pSet, "GetObject"):
        return None
    obj = pSet.GetObject(str(name))
    return obj if isinstance(obj, ObjectClass) else None


def ObjectClass_GetObjectByID(pSet, obj_id) -> "ObjectClass | None":
    """Look up an object by integer ID, scoped to pSet (or globally if None).

    SDK pattern (MissionLib.py:3219): ``App.ObjectClass_GetObjectByID(
    App.SetClass_GetNull(), idTarget)`` — a None pSet means "search the
    null set", which in Appc semantics scans the global object table.
    Phase 1 routes through ``engine.core.ids.get_object_by_id``.
    """
    from engine.core.ids import get_object_by_id
    obj = get_object_by_id(int(obj_id))
    return obj if isinstance(obj, ObjectClass) else None


# ── IsNull ────────────────────────────────────────────────────────────────────

def IsNull(obj) -> int:
    """Return 1 when obj is the null sentinel, 0 otherwise.

    SDK iteration pattern (MissionLib.HideCharacters, CharacterMenuInterface):

        pObject = pSet.GetFirstObject()
        while not App.IsNull(pObject):
            ...
            pObject = pSet.GetNextObject(pObject.GetObjID())
            if (pObject.GetObjID() == pFirstObject.GetObjID()):
                pObject = App.CharacterClass_CreateNull()   # null sentinel

    Considers as "null":
    * Python None
    * Any object marked with ``_is_null = True`` (CharacterClass_CreateNull
      sets this flag so the iteration loop exits cleanly)
    * App._NamedStub fall-through stubs — these represent unimplemented
      engine calls.  Treating them as null lets iteration loops over not-yet-
      implemented set methods (GetFirstObject / GetNextObject) terminate
      after the first iteration instead of looping forever.

    Note: TGObject.__getattr__ returns a truthy _Stub for any unknown attr,
    so plain ``getattr(obj, "_is_null", False)`` would always succeed.
    Inspect the instance dict directly to bypass the stub fallback.
    """
    if obj is None:
        return 1
    # Detect stub-class instances by class name (avoids importing App at
    # module load time and the resulting circular dependency).  All three
    # stub families represent "no real implementation" — for the SDK iteration
    # patterns IsNull guards, treating them as null lets the loop exit.
    cls_name = type(obj).__name__
    if cls_name in ("_NamedStub", "_Stub", "_RendererStub", "_NodeStub"):
        return 1
    try:
        if obj.__dict__.get("_is_null", False):
            return 1
    except AttributeError:
        pass
    return 0

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
        pass

    def DetachObject(self, *args) -> None:
        pass

    def SetDeleteMe(self, *args) -> None:
        pass

    def GetNode(self):
        return None

    def GetAnimNode(self) -> "_NodeStub":
        return _NodeStub()

    def GetWorldForwardTG(self) -> TGPoint3:
        """Return forward vector (row 1 of rotation matrix, BC uses Y-forward)."""
        return self._rotation.GetRow(1)

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
    """Placeholder — hull/shield damage state lives here in Phase 2."""
    pass


class ObjectGroup(TGEventHandlerObject):
    GROUP_CHANGED = 1
    ENTERED_SET = 2
    EXITED_SET = 3
    DESTROYED = 4

    def __init__(self):
        super().__init__()
        self._names: list[str] = []

    def AddName(self, name: str) -> None:
        if name not in self._names:
            self._names.append(name)

    def RemoveName(self, name: str) -> None:
        if name in self._names:
            self._names.remove(name)

    def RemoveAllNames(self) -> None:
        self._names.clear()

    def IsNameInGroup(self, name: str) -> bool:
        return name in self._names

    def GetNumActiveObjects(self) -> int:
        return len(self._names)

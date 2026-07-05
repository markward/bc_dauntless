"""
Object class hierarchy for Phase 1 headless engine.

ObjectClass        — named, positioned, oriented, scaled game object
PhysicsObjectClass — adds velocity, mass, direction-space constants
DamageableObject   — placeholder for hull/shield state (Phase 2)
ObjectGroup        — named membership list (friendly/enemy/neutral groups)
"""

import math
import random
import weakref

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


class _ObjectNodeRef(_NodeStub):
    """GetNode() result in the deferred-renderer model: no scene graph exists,
    so the "node" is a weak handle back to the owning object. Consumers that
    need spatial anchoring (TGSoundAction.SetNode → positional playback)
    resolve GetWorldLocation(); everything else inherits _NodeStub
    chainability. Weak so a queued sound/effect action never keeps a dead
    ship alive."""
    def __init__(self, owner):
        self._owner = weakref.ref(owner)

    def GetWorldLocation(self):
        owner = self._owner()
        return None if owner is None else owner.GetWorldLocation()

    def __repr__(self):
        owner = self._owner()
        return "<_ObjectNodeRef %r>" % (owner.GetName() if owner else None)


class ObjectClass(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._name: str = ""
        # Localized display name, distinct from the internal _name. BC keeps
        # these separate: _name is the identity key (set membership / group
        # AddName / mission GetName() checks / target selection) while the
        # display name is the localized label shown in the Hail menu and target
        # list. MUST NOT alias _name — writing the display name onto _name
        # reclassifies the object (breaks friendly/enemy grouping and target
        # selection) and breaks mission logic that matches GetName().
        self._display_name: str = ""
        self._script: str = ""
        self._radius: float = 0.0
        self._scale: float = 1.0
        self._hidden: bool = False
        self._position: TGPoint3 = TGPoint3(0.0, 0.0, 0.0)
        self._rotation: TGMatrix3 = TGMatrix3()   # identity
        self._containing_set = None
        # Set via SetDeleteMe(1); the host loop removes flagged objects from
        # their set each tick (BC's engine deletes delete-me-flagged objects).
        # Eager init so the host's __dict__-based read never sees a TGObject
        # __getattr__ _Stub (which is truthy and would delete everything).
        self._delete_me: bool = False
        # Whether the bridge "Hail" menu offers this object as a target. Eager
        # init (not a __getattr__ _Stub) so IsHailable / the change-guard read
        # a real bool. See SetHailable for the ET_HAILABLE_CHANGE broadcast.
        self._hailable: bool = False

    # ── Identity ──────────────────────────────────────────────────────────────

    def IsTypeOf(self, cls) -> int:
        # SDK runtime class check: pObject.IsTypeOf(CT_X). CT_ constants are
        # classes (CT_PLANET=Planet, CT_SUN=Sun). `cls` may be a fall-through
        # _NamedStub for an unmapped CT_, so guard with isinstance(cls, type).
        # Sun(Planet): a Sun IsTypeOf CT_PLANET and CT_SUN; a plain Planet
        # IsTypeOf CT_SUN is 0 — this is what filters suns out of the orbit menu.
        return 1 if isinstance(cls, type) and isinstance(self, cls) else 0

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
        # Falls back to the internal name when no display name has been set —
        # matching Appc, where an object's display name defaults to its name.
        return self._display_name if self._display_name else self._name

    def SetDisplayName(self, name: str) -> None:
        self._display_name = str(name)

    # ── Hailable state ────────────────────────────────────────────────────────
    # BC's C++ ObjectClass::SetHailable fires ET_HAILABLE_CHANGE, which the SDK
    # bridge relies on: Bridge/HelmMenuHandlers.HailableChange adds (bool=1) or
    # removes (bool=0) the object's per-target button under the Helm "Hail"
    # menu. Mission scripts toggle this at runtime (E1M2 FirstHavenHail makes
    # the Haven colony hailable only after the asteroids are cleared), so the
    # broadcast — not just the flag — is what makes the hail button appear.
    def SetHailable(self, value) -> None:
        new_value = bool(value)
        if new_value == self._hailable:
            return
        self._hailable = new_value
        try:
            import App
            evt = App.TGBoolEvent_Create()
            evt.SetEventType(App.ET_HAILABLE_CHANGE)
            evt.SetSource(self)
            evt.SetBool(1 if new_value else 0)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            import engine.dev_mode as dev_mode
            dev_mode.log_swallowed("SetHailable broadcast", _e)

    def IsHailable(self) -> int:
        return 1 if self._hailable else 0

    def ReplaceTexture(self, new_texture_path: str, old_texture_name: str) -> None:
        """BC ObjectClass::ReplaceTexture — swap a texture on this object's model.

        Used pervasively to render a Federation hull's registry / ship name
        ("Dauntless", "Sovereign", ...): `old_texture_name` ("ID") is matched
        against the NIF's embedded texture basenames and replaced with the TGA at
        `new_texture_path` (game/-relative). Because our renderer bakes the swap
        into the Model at load time (a per-registry cache variant), the request
        is QUEUED here and consumed when the ship's render instance is built — see
        engine.appc.registry_texture and the two ship-build loops in
        engine.host_loop. It therefore takes effect the next time the instance is
        (re)built; every SDK caller (mission Initialize, the MissionLib
        ship-change path, QuickBattle setup) issues it before realization, so the
        named hull shows on first appearance. Was previously a silent __getattr__
        `_Stub` no-op (why every Federation hull rendered as the default
        Enterprise registry)."""
        from engine.appc import registry_texture
        registry_texture.queue_replace(self, new_texture_path, old_texture_name)

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

    def GetRandomPointOnModel(self) -> TGPoint3:
        """BC ObjectClass::GetRandomPointOnModel — random world-space point on
        this object's model surface. The SDK's death-effect scatter primitive:
        Effects.py seeds each debris explosion / spark burst and the death
        AddDamage at a fresh sample (E1M2 asteroids, E7M1 freighter, E3M2
        probe), so repeated calls must vary. Was previously a silent
        __getattr__ `_Stub` no-op, so death debris emitted from a bogus
        position instead of the hull.

        Prefers the render instance's baked hull surface points (already
        world-transformed — the same sample the nebula hull discharges use);
        headless or instance-less objects fall back to a uniform random point
        on the bounding sphere (GetRadius() is already world-scale), and a
        radius-less object degrades to its world location."""
        from engine.appc import render_instances
        iid = render_instances.instance_for(self)
        if iid is not None:
            try:
                from engine import renderer
                pts = renderer.instance_surface_points(iid)
            except Exception:
                pts = []
            if pts:
                x, y, z = pts[random.randrange(len(pts))]
                return TGPoint3(float(x), float(y), float(z))
        center = self.GetWorldLocation()
        radius = self.GetRadius()
        if radius <= 0.0:
            return center
        dx = random.gauss(0.0, 1.0)
        dy = random.gauss(0.0, 1.0)
        dz = random.gauss(0.0, 1.0)
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        if norm < 1e-12:
            return center
        k = radius / norm
        return TGPoint3(center.x + dx * k, center.y + dy * k, center.z + dz * k)

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

        Column-vector convention (see CLAUDE.md ↦ "Rotation matrix
        convention"): col 0 = right, col 1 = forward, col 2 = up. A
        body vector v_body maps to world via R · v_body; e.g.
        v_body = model_forward = (0, 1, 0) selects column 1, the
        world-forward axis.

        `right = forward × up` is a RIGHT-HANDED basis (det = +1) in BC's
        Z-up / Y-forward coordinate system, so `GetCol(0)` is the true
        starboard axis. The renderer draws this rotation directly with no
        reflection (`engine/host_loop.py:_world_matrix_from` no longer negates
        X; `pipeline.cc` uses `glFrontFace(GL_CCW)`). This was converted from
        the historical left-handed (`up × forward`, det = -1) convention on
        2026-06-18 — see docs/superpowers/plans/2026-06-18-render-handedness-
        unmirror.md. Do not reorder the cross back without restoring that flip
        and the GL front-face state.
        """
        fwd = TGPoint3(forward.x, forward.y, forward.z)
        fwd.Unitize()
        u = TGPoint3(up.x, up.y, up.z)
        # Orthogonalize up against forward
        dot = fwd.Dot(u)
        u = TGPoint3(u.x - dot * fwd.x, u.y - dot * fwd.y, u.z - dot * fwd.z)
        u.Unitize()
        right = fwd.Cross(u)
        right.Unitize()
        m = TGMatrix3()
        m.SetCol(0, right)
        m.SetCol(1, fwd)
        m.SetCol(2, u)
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

    def SetDeleteMe(self, flag=1) -> None:
        # QuickBattle.EndSimulation flags every non-player ship (and torpedoes)
        # with SetDeleteMe(1) to clear the battle; the host loop removes flagged
        # objects from their set each tick.
        self._delete_me = bool(flag)

    def IsDeleteMe(self) -> int:
        return 1 if self._delete_me else 0

    def GetDeleteMe(self) -> int:
        return self.IsDeleteMe()

    def GetNode(self):
        # Deferred renderer: no scene-graph node to hand out. Return a weak
        # handle to self so SDK patterns like pSound.SetNode(pObj.GetNode())
        # can resolve a world position for positional playback.
        return _ObjectNodeRef(self)

    def GetAnimNode(self) -> "_NodeStub":
        return _NodeStub()

    def GetWorldForwardTG(self) -> TGPoint3:
        """World-forward = R · model_forward = column 1 of R.

        See CLAUDE.md ↦ "Rotation matrix convention" — column-vector is
        the project-wide convention. Prefer this helper over reading
        `GetWorldRotation().GetCol(1)` at the call site.
        """
        return self._rotation.GetCol(1)

    # World-direction siblings of GetWorldForwardTG (column-vector convention:
    # col0=right, col1=forward, col2=up). Without these, ObjectClass is a
    # TGObject so the names fall through __getattr__ to a truthy _Stub —
    # QuickBattle.GenerateShips does pShip.AlignToVectors(player.GetWorldBackwardTG(),
    # player.GetWorldUpTG()), and stub "vectors" build a degenerate (zero-column)
    # rotation that later crashes render interpolation.
    def GetWorldBackwardTG(self) -> TGPoint3:
        f = self._rotation.GetCol(1)
        return TGPoint3(-f.x, -f.y, -f.z)

    def GetWorldUpTG(self) -> TGPoint3:
        return self._rotation.GetCol(2)

    def GetWorldDownTG(self) -> TGPoint3:
        u = self._rotation.GetCol(2)
        return TGPoint3(-u.x, -u.y, -u.z)

    def GetWorldRightTG(self) -> TGPoint3:
        return self._rotation.GetCol(0)

    def GetWorldLeftTG(self) -> TGPoint3:
        r = self._rotation.GetCol(0)
        return TGPoint3(-r.x, -r.y, -r.z)

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


def _is_critical(subsystem) -> bool:
    """True when a subsystem carries the engine's critical flag. Guarded so
    objects/subsystems without IsCritical (Phase 1 stubs) read as False."""
    if subsystem is None or not hasattr(subsystem, "IsCritical"):
        return False
    return bool(subsystem.IsCritical())


def _is_targetable(subsystem) -> bool:
    """True when a subsystem is targetable. Guarded so subsystems without
    IsTargetable (fakes/stubs) read as True — preserving the historical
    behaviour where every power plant breached."""
    if subsystem is None or not hasattr(subsystem, "IsTargetable"):
        return True
    return bool(subsystem.IsTargetable())


def _route_zero_crossing(ship, subsystem, crossed_zero: bool) -> None:
    """On a subsystem crossing >0 -> 0, arm the warp-core breach (when the
    subsystem is the ship's PowerSubsystem) or schedule the hull-death cascade
    (when it is the hull). No-op otherwise. Kept separate from the critical ->
    ship_death.begin path, which is unchanged.

    See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
    """
    if not crossed_zero:
        return
    power = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if power is not None and subsystem is power:
        # Only a real, targetable power plant / warp core breaches. Inert
        # objects (asteroids) carry a hidden, non-targetable Power Plant
        # (SetTargetable(0)); when the death cascade zeroes it, it must NOT
        # throw a warp-core explosion with its unique VFX + splash damage.
        if _is_targetable(power):
            from engine.appc import warp_core_breach
            warp_core_breach.arm(ship)
        return
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    if hull is not None and subsystem is hull:
        from engine.appc import subsystem_cascade
        subsystem_cascade.schedule(ship)


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
        # Per-ship visible-damage scale (SetVisibleDamage*Modifier, from
        # loadspacehelper hardpoint stats). Radius mod is applied to emitted
        # carves now; strength mod is stored-only until Gap 2 plumbs strength.
        self._vis_dmg_radius_mod: float = 1.0
        self._vis_dmg_strength_mod: float = 1.0

    def GetPropertySet(self):
        return self._property_set

    def HasClonedModel(self) -> int:
        """Whether this object has a cloned model carrying a separate
        warp-stretch radius override.

        Consumed by ``sdk/Build/scripts/Conditions/ConditionInRange.py``
        (warp branch, ~lines 211-212): it only consults
        ``GetClonedModelRadius()`` when this returns truthy, otherwise it
        keeps the value from ``GetRadius()``. Dauntless has no cloned-model
        warp-radius override yet, so this returns 0 and callers fall back to
        ``GetRadius()`` — the correct behaviour for normal play and warp
        alike until cloned-model support lands.
        """
        return 0

    def GetClonedModelRadius(self) -> float:
        """The cloned-model (unstretched) warp radius.

        Faithful placeholder for the same ConditionInRange consumer: since
        ``HasClonedModel()`` returns 0 this is never reached via that gate,
        but it must exist and return a sane radius so any caller that invokes
        it directly does not error. Mirrors ``GetRadius()``.
        """
        return self.GetRadius()

    def SetCollisionsOn(self, bOn) -> None:
        """SDK ``DamageableObject_SetCollisionsOn`` (App.py:5356): toggle this
        object's participation in collision detection. Missions disable it on
        dying/cutscene/warping objects (e.g. the E1M2 exploding asteroid,
        Warp.py warp-out) and re-enable afterwards. Honoured by
        ``engine.appc.collisions.tick_collisions``.
        """
        self._collisions_on = bool(bOn)

    def CanCollide(self) -> int:
        """SDK ``DamageableObject_CanCollide`` (App.py:5354): whether this
        object currently participates in collisions. Default TRUE."""
        return 1 if self.__dict__.get("_collisions_on", True) else 0

    # ── Visible (geometry) damage ───────────────────────────────────────────────
    # BC's DamageTool authored hull wrecks as body-frame damage spheres. These
    # methods route authored + runtime visible damage into our hull-carve
    # renderer via engine.appc.visible_damage (deferred until the ship's render
    # instance is realized). See
    # docs/original_game_reference/engine/damagetool-and-hull-damage-gaps.md.

    def AddObjectDamageVolume(self, x, y, z, influRad, strength) -> None:
        """Authored body-frame damage sphere (SDK pre-wreck Damage*.py scripts)."""
        from engine.appc import visible_damage
        visible_damage.queue_body_volume(self, x, y, z, influRad, strength)

    def AddDamage(self, pEmitPos, fRadius, fDamage) -> None:
        """SDK ``DamageableObject_AddDamage(pEmitPos, fRadius, fDamage)`` — the
        explosion / collision damage primitive (Effects.DeathExplosionDamage,
        mission ``*.AddDamage(...)``). Two faithful effects:

        1. Deposits the visible world-space hull carve (`pEmitPos` is a
           world-space point, e.g. GetRandomPointOnModel).
        2. Deals GAMEPLAY damage to hull/subsystems BYPASSING shields —
           verified by dev-console probe q02 (hull dropped, faces untouched),
           unlike normal weapon fire which strict-cascades through shields.

        The gameplay half runs only for full ships (``ShipClass`` carries the
        hull/shield/subsystem surface ``apply_hit`` needs); bare damageable
        props (wrecks, debris) just carve.
        """
        from engine.appc import visible_damage
        visible_damage.queue_world_carve(self, pEmitPos, fRadius, fDamage)
        from engine.appc.ships import ShipClass
        if isinstance(self, ShipClass) and all(
                hasattr(pEmitPos, ax) for ax in ("x", "y", "z")):
            from engine.appc import combat
            combat.apply_hit(self, float(fDamage), pEmitPos, source=None,
                             splash_radius=float(fRadius), bypass_shields=True)

    def DamageRefresh(self, *args) -> None:
        """Re-polygonize authored damage. No-op: our breach renderer is
        per-frame, so carves are already live."""
        return None

    def RemoveVisibleDamage(self) -> None:
        """Clear visible damage (Actions/ShipScriptActions.py). Drops PENDING
        volumes only; clearing already-emitted carves needs a native
        HullCarveField::clear() + binding (Gap-1 follow-up)."""
        from engine.appc import visible_damage
        visible_damage.clear_for(self)

    def SetVisibleDamageRadiusModifier(self, value) -> None:
        """Per-ship visible-damage radius scale (loadspacehelper hardpoint stats)."""
        try:
            self._vis_dmg_radius_mod = float(value)
        except (TypeError, ValueError):
            pass

    def SetVisibleDamageStrengthModifier(self, value) -> None:
        """Per-ship visible-damage strength scale. Stored-only until Gap 2."""
        try:
            self._vis_dmg_strength_mod = float(value)
        except (TypeError, ValueError):
            pass

    def DamageSystem(self, subsystem, amount: float, source=None) -> None:
        """Apply damage to a subsystem, flooring condition at zero. If the
        subsystem is critical and reaches zero, start the ship death
        sequence (covers hull AND warp core via SetCritical(1)). A >0 -> 0
        crossing also arms the warp-core breach / schedules the hull cascade.

        `source` (SDK-compatible optional 3rd arg — real callers pass 2) is the
        firing ship; combat.apply_hit threads it in so a fatal blow attributes
        the kill on the ET_OBJECT_EXPLODING event (friendly-fire detection)."""
        if subsystem is None:
            return
        amt = float(amount)
        if amt <= 0.0:
            return
        cur = subsystem.GetCondition()
        new_cond = max(0.0, cur - amt)
        subsystem.SetCondition(new_cond)
        _route_zero_crossing(self, subsystem, cur > 0.0 and new_cond <= 0.0)
        if new_cond <= 0.0 and _is_critical(subsystem) \
                and hasattr(self, "IsDying") and hasattr(self, "IsDead") \
                and not self.IsDying() and not self.IsDead():
            from engine.appc import ship_death
            ship_death.begin(self, killer=source)

    def DestroySystem(self, subsystem) -> None:
        """Force a subsystem to zero condition (mirrors SDK
        pShip.DestroySystem). Ship death is a side effect only when the
        subsystem is critical; DestroySystem(pSensors) just zeroes sensors. A
        >0 -> 0 crossing arms the warp-core breach / schedules the cascade."""
        if subsystem is None:
            return
        cur = subsystem.GetCondition()
        subsystem.SetCondition(0.0)
        if hasattr(subsystem, "SetDestroyed"):
            subsystem.SetDestroyed(True)
        _route_zero_crossing(self, subsystem, cur > 0.0)
        if _is_critical(subsystem) \
                and hasattr(self, "IsDying") and hasattr(self, "IsDead") \
                and not self.IsDying() and not self.IsDead():
            from engine.appc import ship_death
            ship_death.begin(self)


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
        try:
            import App
        except ImportError:
            return ()
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

    Also unwrap an ObjectGroup nested at *any* depth inside tuples/lists —
    `AI.Preprocessors.SelectTarget.__init__` collects its arg via
    `*pTargetGroup` and then forwards the resulting tuple here. The real
    SDK helper unwraps that wrapping so the ObjectGroupWithInfo identity (and
    its priority dict) is preserved. Without this unwrap the priority/info
    factor in `GetTargetRating` always reads as 0.

    Name lists are flattened to arbitrary depth. SDK compound AIs splat the
    targets positional through `*lpTargets` once per routing hop, so the
    nesting depth depends on the path: a direct
    ``BasicAttack.CreateAI(pShip, ["Galaxy 2"])`` arrives as
    ``(["Galaxy 2"],)``, but the cloak path
    (``BasicAttack → CloakAttackWrapper → BasicAttack → CloakAttack``) wraps it
    deeper. Recursing instead of flattening exactly one level turns every leaf
    into an individual name rather than stringifying an inner list into a bogus
    name like ``"['Galaxy 2']"`` (which the AI never resolves to a real object,
    leaving its target group empty).
    """
    if isinstance(arg, ObjectGroup):
        return arg
    nested_group = _find_nested_group(arg)
    if nested_group is not None:
        return nested_group
    group = ObjectGroup()
    _add_leaf_names(group, arg)
    return group


def _find_nested_group(arg):
    """Return the first ObjectGroup reachable through nested tuples/lists, else None."""
    if isinstance(arg, ObjectGroup):
        return arg
    if isinstance(arg, (tuple, list)):
        for item in arg:
            found = _find_nested_group(item)
            if found is not None:
                return found
    return None


def _add_leaf_names(group: "ObjectGroup", arg) -> None:
    """Recursively AddName(str(leaf)) for every scalar leaf in a nested name list."""
    if arg is None:
        return
    if isinstance(arg, str):
        group.AddName(arg)
    elif isinstance(arg, (tuple, list)):
        for item in arg:
            _add_leaf_names(group, item)
    else:
        group.AddName(str(arg))


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

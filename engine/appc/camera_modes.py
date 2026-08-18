"""Camera-mode object model for SDK-scripted in-space cutscene cameras.

The SDK's Actions/CameraScriptActions.py + Camera.py drive a stack of
CameraMode objects on a CameraObjectClass: each mode holds an attribute bag
and an Update() that computes the camera's world pose every frame from the
LIVE target object's transform. BC's modes lived in Appc C++; this is the
headless Python reimplementation of the subset the space cutscenes use.

Game units throughout; column-vector right-handed rotations (CLAUDE.md).
"""
import math as _math

from engine.appc.math import TGPoint3

SWEEP_TAU_S = 0.35   # exponential time constant for sweep glide

# Sweep-break thresholds: a jump larger than these between the current smoothed
# pose and the ideal is a discontinuity (teleport / set-swap), not tracking
# motion, so the mode cuts instead of gliding. Deliberately generous — real
# per-frame tracking moves the eye a fraction of a GU and rotates the forward a
# fraction of a degree; only a teleport clears these.
_SWEEP_BREAK_EYE_GU = 10.0      # eye jump (game units)
_SWEEP_BREAK_FWD_DOT = 0.90     # forward-direction dot < this ≈ >25° rotation

_next_obj_id = [0]


def _pose_discontinuity(cur, ideal) -> bool:
    """True if the ideal pose has jumped discontinuously from the current
    smoothed pose (eye moved > _SWEEP_BREAK_EYE_GU, or forward rotated past
    _SWEEP_BREAK_FWD_DOT) — the signal to cut the sweep rather than glide."""
    (ce, cf, _cu), (ie, if_, _iu) = cur, ideal
    dx, dy, dz = ie[0] - ce[0], ie[1] - ce[1], ie[2] - ce[2]
    if (dx * dx + dy * dy + dz * dz) > (_SWEEP_BREAK_EYE_GU * _SWEEP_BREAK_EYE_GU):
        return True
    dot = cf[0] * if_[0] + cf[1] * if_[1] + cf[2] * if_[2]
    return dot < _SWEEP_BREAK_FWD_DOT


def _alloc_obj_id():
    _next_obj_id[0] += 1
    return _next_obj_id[0]


def _unit(x, y, z):
    n = _math.sqrt(x * x + y * y + z * z)
    if n < 1e-9:
        return (0.0, 1.0, 0.0)
    return (x / n, y / n, z / n)


def _apply_rot(R, p):
    """Return R · p as a 3-tuple (body→world). MultMatrixLeft mutates a copy."""
    v = TGPoint3(p.x, p.y, p.z)
    v.MultMatrixLeft(R)
    return (v.x, v.y, v.z)


def _obj_pose(obj, pose_of):
    """(loc, rot) for a tracked object — the render-interpolated pose when a
    `pose_of` provider is supplied (smooth-motion fix, so a camera locked/
    chasing a 60 Hz-stepped ship tracks exactly what the renderer draws), else
    the live pose. pose_of falls back to live internally for non-ship targets
    (waypoints / placements are static, so it is a no-op for them)."""
    if pose_of is not None:
        return pose_of(obj)
    return obj.GetWorldLocation(), obj.GetWorldRotation()


class CameraMode:
    """Base mode: attribute bag + sweep-smoothed Update over a subclass ideal."""

    def __init__(self):
        self._attrs = {}
        self._obj_id = _alloc_obj_id()
        self._cur = None        # current (eye, fwd, up) for sweep; None until seeded
        self._snap = False      # force snap on next Update
        # The camera this mode was built for (CameraObjectClass.GetNamedCameraMode
        # tags it). BC modes are owned by their camera; ZoomTargetMode uses it as
        # the eye when no Source object was wired.
        self._owner_camera = None

    # ── Attribute bag (NewMode picks the setter by arg type) ──────────────────
    def SetAttrFloat(self, name, v):     self._attrs[name] = float(v)
    def SetAttrPoint(self, name, p):     self._attrs[name] = p
    def SetAttrIDObject(self, name, obj): self._attrs[name] = obj

    def GetAttrFloat(self, name, default=0.0):
        v = self._attrs.get(name, default)
        return float(v) if v is not None else default

    def GetAttrPoint(self, name):    return self._attrs.get(name)
    def GetAttrIDObject(self, name): return self._attrs.get(name)

    # ── Identity / validity ───────────────────────────────────────────────────
    def GetObjID(self):  return self._obj_id

    def IsValid(self):
        return 1 if self._ideal() is not None else 0

    # ── Sweep control ─────────────────────────────────────────────────────────
    def set_initial_pose(self, eye, fwd, up):
        self._cur = (tuple(eye), tuple(fwd), tuple(up))

    def SnapToIdealPosition(self):
        self._snap = True

    def Update(self, dt=None, pose_of=None):
        ideal = self._ideal(pose_of)
        if ideal is None:
            return self._cur if self._cur is not None else (
                (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        if self._cur is None or self._snap or dt is None:
            self._cur = ideal
            self._snap = False
            return self._cur
        # Break the sweep on a DISCONTINUITY (a teleport / set-swap): a docking
        # cutscene begins watching the ship, then SetupDockPositions teleports
        # the ship to the docking entry — gliding across that jump reads as an
        # unwanted camera swoop. Cut instead. Normal frame-to-frame tracking
        # motion is far below these thresholds, so ordinary sweeps are untouched.
        if _pose_discontinuity(self._cur, ideal):
            self._cur = ideal
            return self._cur
        a = 1.0 - _math.exp(-dt / SWEEP_TAU_S)
        self._cur = (
            tuple(self._cur[0][i] + a * (ideal[0][i] - self._cur[0][i]) for i in range(3)),
            _unit(*(self._cur[1][i] + a * (ideal[1][i] - self._cur[1][i]) for i in range(3))),
            _unit(*(self._cur[2][i] + a * (ideal[2][i] - self._cur[2][i]) for i in range(3))),
        )
        return self._cur

    def _ideal(self, pose_of=None):
        raise NotImplementedError


def _target_alive(obj):
    # Waypoints / PlacementObjects don't implement IsDying (it is
    # DamageableObject surface) and never die -- they are the Source of every
    # placement/zoom camera shot, so they must read as alive. Ask the MRO:
    # neither getattr-with-default nor hasattr can answer that on a TGObject,
    # whose __getattr__ hands back a truthy recursive _Stub. (This used to
    # sniff the returned value for isinstance(_Stub), which worked but called
    # a stub on the camera target every frame -- Waypoint.IsDying, rank 4 of
    # docs/stub_heatmap.md.)
    from engine.core.ids import implements
    if obj is None:
        return False
    if not implements(obj, "IsDying"):
        return True
    try:
        return not obj.IsDying()
    except Exception:
        return False


class PlaceByDirectionMode(CameraMode):
    """Bridge captain camera mode (CameraModes.GalaxyBridgeCaptain). A pure
    attribute bag holding the SDK's PlaceByDirection params — BasePosition,
    Movement, StartMoveAngle, EndMoveAngle — set via SetAttrPoint/SetAttrFloat.

    Unlike the in-space modes it has no live Update(): it isn't part of the
    cutscene stack. The bridge camera (host_loop._BridgeCamera) harvests these
    attrs and computes eye = BasePosition + Movement * frac(horizontal angle),
    so _ideal() is unused (returns None → IsValid()==0, which nothing probes)."""

    def __init__(self, kind="PlaceByDirection"):
        super().__init__()
        self.kind = kind

    def _ideal(self, pose_of=None):
        return None


def CameraMode_Create(kind, pCamera=None):
    """App.CameraMode_Create shim. The SDK's CameraModes.* builders and
    Camera.MakePlayerCamera call this with a mode-type string, then fill attrs
    via SetAttr*. Dispatch on `kind` to the matching mode class; `PlaceByDirection`
    and any unknown kind fall back to the PlaceByDirection attr-bag (the bridge
    captain path — unchanged). `pCamera` is tagged as the mode owner (used by
    ZoomTargetMode's Source fallback)."""
    if kind == "ReverseChase":
        # The SDK never passes this KIND (CameraModes.ReverseChase builds
        # "Chase"); it is a NAME in Camera.NewMode. Kept as a defensive mapping
        # so a direct create still points the right way — ahead of the target,
        # which for BC is purely the DefaultPosition sign.
        mode = ChaseMode()
        mode.SetAttrPoint("DefaultPosition", TGPoint3(0.0, 1.0, 0.1))
    else:
        _dispatch = {
            "Locked": LockedMode,
            "Chase": ChaseMode,
            "Target": TargetMode,
            "Placement": PlacementMode,
            # CameraModes.Placement (the SDK builder registered under the NAME
            # "Placement") passes the KIND "PlacementWatch" — the two strings
            # are not interchangeable. Both map to PlacementMode.
            "PlacementWatch": PlacementMode,
            "ZoomTarget": ZoomTargetMode,
            "DropAndWatch": DropAndWatchMode,
        }
        cls = _dispatch.get(kind)
        mode = cls() if cls is not None else PlaceByDirectionMode(kind)
    mode._owner_camera = pCamera
    return mode


class LockedMode(CameraMode):
    """Camera locked to a fixed pose in the target's local frame (LockedView /
    LockedViewAnyAngle). Position/Forward/Up are target-local; the spherical
    math is done SDK-side in Camera.py before the attrs are set here."""

    def _ideal(self, pose_of=None):
        t = self.GetAttrIDObject("Target")
        P = self.GetAttrPoint("Position")
        F = self.GetAttrPoint("Forward")
        U = self.GetAttrPoint("Up")
        if not _target_alive(t) or P is None or F is None or U is None:
            return None
        loc, R = _obj_pose(t, pose_of)
        op = _apply_rot(R, P)
        eye = (loc.x + op[0], loc.y + op[1], loc.z + op[2])
        fwd = _unit(*_apply_rot(R, F))
        up = _unit(*_apply_rot(R, U))
        return (eye, fwd, up)


# BC's authored Chase attrs (CameraModes.Chase, CameraModes.py:12-32).
# DefaultPosition is a body-frame DIRECTION; Distance is a multiple of the
# target's radius — the same shape our player chase camera independently uses
# (CAM_BACK_RADII et al, engine/cameras/__init__.py). Used when a mode is
# constructed bare, i.e. by anything that does not run the SDK builder.
CHASE_DEFAULT_POSITION = (0.0, -1.0, 0.1)
CHASE_DEFAULT_DISTANCE = 4.0


def _target_radius(obj, default=1.0):
    """Target radius in game units, or `default` when the object has no real
    GetRadius. Asks the MRO — a TGObject's __getattr__ hands back a truthy
    recursive _Stub, so hasattr/getattr cannot answer this (same reasoning as
    _target_alive above)."""
    from engine.core.ids import implements
    if not implements(obj, "GetRadius"):
        return default
    try:
        r = float(obj.GetRadius())
    except Exception:
        return default
    return r if r > 1e-6 else default


class ChaseMode(CameraMode):
    """Follow the target along DefaultPosition, looking back at it.

    BC ships ONE Chase mode class. CameraModes.Chase and CameraModes.ReverseChase
    both build kind "Chase" and differ only by the SIGN of DefaultPosition
    (CameraModes.py:22 vs :40) — there is no reverse flag, and adding one here
    made the mode ignore its authored attrs. Offset is built in the target body
    frame and mapped to world via the column-vector convention.
    """

    def _ideal(self, pose_of=None):
        t = self.GetAttrIDObject("Target")
        if not _target_alive(t):
            return None
        loc, R = _obj_pose(t, pose_of)
        d = self.GetAttrPoint("DefaultPosition")
        dx, dy, dz = (d.x, d.y, d.z) if d is not None else CHASE_DEFAULT_POSITION
        n = _math.sqrt(dx * dx + dy * dy + dz * dz)
        if n < 1e-9:
            return None
        reach = (self.GetAttrFloat("Distance", CHASE_DEFAULT_DISTANCE)
                 * _target_radius(t))
        off = _apply_rot(R, TGPoint3(dx / n * reach, dy / n * reach, dz / n * reach))
        eye = (loc.x + off[0], loc.y + off[1], loc.z + off[2])
        fwd = _unit(loc.x - eye[0], loc.y - eye[1], loc.z - eye[2])
        up = _unit(*_apply_rot(R, TGPoint3(0.0, 0.0, 1.0)))
        return (eye, fwd, up)


class TargetMode(CameraMode):
    """Look from a source object to a target object (TargetWatch)."""

    def _ideal(self, pose_of=None):
        src = self.GetAttrIDObject("Source")
        dst = self.GetAttrIDObject("Target")
        if not _target_alive(src) or not _target_alive(dst):
            return None
        s, sR = _obj_pose(src, pose_of)
        d, _dR = _obj_pose(dst, pose_of)
        eye = (s.x, s.y, s.z)
        fwd = _unit(d.x - s.x, d.y - s.y, d.z - s.z)
        up = _unit(*_apply_rot(sR, TGPoint3(0.0, 0.0, 1.0)))
        return (eye, fwd, up)


class PlacementMode(CameraMode):
    """Watch an object from a fixed placement (BC's "PlacementWatch" —
    Camera.LowPlacementWatch → NewMode("Placement", [("Source", pPlacement),
    ("Target", pTarget)]); PlacementOffsetWatch adds ("TargetOffsetWorld", v)).
    Eye sits at the Source placement's world position with its authored up
    (col2). Target set → look at the target (plus the optional world offset);
    Target None (legal — Camera.Placement's sTarget=None branch still calls
    SetAttrIDObject("Target", None)) → look along the Source's own forward
    (col1). A dead Target (or missing Source) makes the mode invalid."""

    def _ideal(self, pose_of=None):
        src = self.GetAttrIDObject("Source")
        if not _target_alive(src):
            return None
        s, R = _obj_pose(src, pose_of)
        eye = (s.x, s.y, s.z)
        u = R.GetCol(2)
        up = _unit(u.x, u.y, u.z)
        dst = self.GetAttrIDObject("Target")
        if dst is None:
            f = R.GetCol(1)
            fwd = _unit(f.x, f.y, f.z)
        else:
            if not _target_alive(dst):
                return None
            d, _dR = _obj_pose(dst, pose_of)
            off = self.GetAttrPoint("TargetOffsetWorld")
            if off is not None:
                dx, dy, dz = d.x + off.x, d.y + off.y, d.z + off.z
            else:
                dx, dy, dz = d.x, d.y, d.z
            fwd = _unit(dx - s.x, dy - s.y, dz - s.z)
        return (eye, fwd, up)


# BC's authored DropAndWatch attrs (CameraModes.DropAndWatch, CameraModes.py:
# 144-162), used when a mode is constructed bare — i.e. by anything that does
# not run the SDK builder. ForwardOffset/SideOffset are multiples of the
# target's radius (our inference, matching ChaseMode's authored Distance);
# AnticipationTime is seconds; AxisAvoidAngles is degrees.
DROP_DEFAULT_ANTICIPATION_TIME = 2.5
DROP_DEFAULT_FORWARD_OFFSET = 0.5
DROP_DEFAULT_SIDE_OFFSET = 3.0
DROP_DEFAULT_AWAY_DISTANCE = 0.0
DROP_DEFAULT_AWAY_DISTANCE_FACTOR = 1.2
DROP_DEFAULT_AXIS_AVOID_ANGLES = 45.0


def _distance(p, loc):
    """|p - loc| where p is a 3-tuple and loc a TGPoint3."""
    dx, dy, dz = p[0] - loc.x, p[1] - loc.y, p[2] - loc.z
    return _math.sqrt(dx * dx + dy * dy + dz * dz)


def _target_velocity(obj):
    """(vx, vy, vz) world velocity in GU/s, or zeros when the object has no
    real GetVelocityTG (it is PhysicsObjectClass surface, so waypoints and
    placements lack it). Asks the MRO for the same reason _target_alive does:
    a TGObject's __getattr__ hands back a truthy _Stub whose arithmetic
    silently collapses to 0, so hasattr/getattr cannot answer this."""
    from engine.core.ids import implements
    if not implements(obj, "GetVelocityTG"):
        return (0.0, 0.0, 0.0)
    try:
        v = obj.GetVelocityTG()
        return (float(v.x), float(v.y), float(v.z))
    except Exception:
        return (0.0, 0.0, 0.0)


class DropAndWatchMode(CameraMode):
    """Drop the camera at a fixed world point and watch the target fly past.

    ⚠️ THIS IS NOT A RECONSTRUCTION OF BC'S ALGORITHM. The clean-room reference
    has no DropAndWatch entry, so only half of this is sourced:

    * SOURCED — the attribute NAMES and their authored VALUES, read verbatim
      from CameraModes.DropAndWatch (CameraModes.py:144-162): AwayDistance 0.0,
      RotateSpeed 0.0, AnticipationTime 2.5, ForwardOffset 0.5, SideOffset 3.0,
      AwayDistanceFactor 1.2, AxisAvoidAngles 45.0, SlowSpeedThreshold 0.5,
      SlowRotationThreshold 0.1, RotateSpeedAccel 0.025, MaxRotateSpeed 0.2.
      Also sourced: the mode takes a "Target" (Camera.LowDropAndWatch,
      Camera.py:276) and WarpSequence.py:248-271 re-authors AwayDistance
      100000.0 / ForwardOffset 10.0 / a random SideOffset for its arrival shot.
    * INFERRED — everything below: that the drop point is
      target_loc + velocity*AnticipationTime offset by ForwardOffset/SideOffset
      in the target's body frame, that those offsets are radius-relative, the
      off-axis avoidance rule, and the re-drop rule. All of it is read off the
      parameter names and defaults, not recovered from the binary. Treat it as
      a plausible flyby shot that honours the authored numbers, not as BC.

    Placement (inferred):
      drop = target_loc + velocity*AnticipationTime
             + radius*(forward*ForwardOffset + right*SideOffset)
      Radius-relative because that is what ChaseMode's authored Distance is
      (a multiple of GetRadius), so the shot frames a Galaxy and a shuttle the
      same way. Body axes are column-vector right-handed: GetCol(0) = right,
      GetCol(1) = forward, GetCol(2) = up (CLAUDE.md).

    Off-axis avoidance (inferred): AxisAvoidAngles 45.0 reads as "never let the
    shot line up with the flight axis" — dead-ahead and dead-astern are the two
    framings a flyby exists to avoid, and both are the degenerate case of this
    placement (the anticipation term is along forward, so a fast target out-runs
    any SideOffset and the camera lands on its track). The drop point is pushed
    sideways — perpendicular to the target's forward axis, keeping its
    along-track component — until the view direction is at least
    AxisAvoidAngles off that axis. The perpendicular direction is the offset's
    own, or the target's right axis when the offset is purely along-track.

    Re-drop (inferred): d0 is the drop-point→target distance recorded AT DROP
    TIME, floored by AwayDistance; the camera re-drops once the target passes
    d0*AwayDistanceFactor away, and whenever there is no drop point yet or the
    Target changed identity. That reading is what makes WarpSequence's
    AwayDistance 100000.0 sensible: it floors d0 so high that the arrival shot
    never re-drops. The re-drop needs no cut logic of its own — a new drop point
    is a big jump, so the base Update()'s _pose_discontinuity check cuts rather
    than gliding (tested, not assumed).

    DELIBERATELY NOT IMPLEMENTED: the slow-orbit drift (RotateSpeed,
    RotateSpeedAccel, MaxRotateSpeed, SlowSpeedThreshold,
    SlowRotationThreshold). Those five read as "when the target is nearly
    stationary, orbit it slowly instead of staring", but their coordinate frame,
    axis and easing are pure guesswork — inventing camera motion is worse than
    holding still, so they are read from the SDK and left unused. Same for
    RangeAngle1-4, which only WarpSequence.py sets and CameraModes never
    authors.
    """

    def __init__(self):
        super().__init__()
        # STATEFUL — unlike the other five modes, whose _ideal() is a pure
        # function of the target's current pose. Staying put while the ship
        # moves IS the shot, so the drop point is computed only on a re-drop.
        self._drop = None            # world drop point (3-tuple) or None
        self._drop_dist = None       # d0: drop→target distance at drop time
        self._drop_target = None     # identity of the target we dropped for

    def _ideal(self, pose_of=None):
        t = self.GetAttrIDObject("Target")
        if not _target_alive(t):
            return None
        loc, R = _obj_pose(t, pose_of)
        if self._needs_drop(t, loc):
            self._drop = self._compute_drop(t, loc, R)
            self._drop_target = t
            self._drop_dist = max(
                _distance(self._drop, loc),
                self.GetAttrFloat("AwayDistance", DROP_DEFAULT_AWAY_DISTANCE))
        eye = self._drop
        fwd = _unit(loc.x - eye[0], loc.y - eye[1], loc.z - eye[2])
        u = R.GetCol(2)
        return (eye, fwd, _unit(u.x, u.y, u.z))

    def _needs_drop(self, t, loc):
        """True when the shot is over and the camera should drop again: no drop
        point yet, a different Target, or the target has flown past
        d0 * AwayDistanceFactor (INFERRED — see the class docstring)."""
        if self._drop is None or self._drop_target is not t:
            return True
        factor = self.GetAttrFloat("AwayDistanceFactor",
                                   DROP_DEFAULT_AWAY_DISTANCE_FACTOR)
        return _distance(self._drop, loc) > self._drop_dist * factor

    def _compute_drop(self, t, loc, R):
        """Where to put the camera for the next pass (INFERRED — see the class
        docstring; none of this shape is recovered from BC)."""
        r = _target_radius(t)
        vx, vy, vz = _target_velocity(t)
        lead = self.GetAttrFloat("AnticipationTime", DROP_DEFAULT_ANTICIPATION_TIME)
        # Drop where the ship is GOING, so it flies into the shot rather than
        # out of it.
        ax, ay, az = loc.x + vx * lead, loc.y + vy * lead, loc.z + vz * lead
        fo = self.GetAttrFloat("ForwardOffset", DROP_DEFAULT_FORWARD_OFFSET) * r
        so = self.GetAttrFloat("SideOffset", DROP_DEFAULT_SIDE_OFFSET) * r
        f, s = R.GetCol(1), R.GetCol(0)   # column-vector: 1 = forward, 0 = right
        drop = (ax + f.x * fo + s.x * so,
                ay + f.y * fo + s.y * so,
                az + f.z * fo + s.z * so)
        return self._avoid_axis(drop, loc, f, s)

    def _avoid_axis(self, drop, loc, f, s):
        """Push the drop point sideways until the shot is at least
        AxisAvoidAngles off the target's flight axis (INFERRED — see the class
        docstring). Decompose drop-target into its along-axis component `a` and
        its perpendicular `perp`: the view direction sits atan2(|perp|, |a|) off
        the axis, so the shot clears the cone as soon as
        |perp| >= |a| * tan(AxisAvoidAngles). Only |perp| is grown — the
        along-track lead the anticipation bought is left alone — and its
        direction is the offset's own, or the body right axis when the drop
        landed exactly on the track."""
        deg = self.GetAttrFloat("AxisAvoidAngles", DROP_DEFAULT_AXIS_AVOID_ANGLES)
        deg = min(max(deg, 0.0), 89.0)    # 90 deg would demand an infinite push
        if deg <= 0.0:
            return drop
        dx, dy, dz = drop[0] - loc.x, drop[1] - loc.y, drop[2] - loc.z
        a = dx * f.x + dy * f.y + dz * f.z
        px, py, pz = dx - a * f.x, dy - a * f.y, dz - a * f.z
        p = _math.sqrt(px * px + py * py + pz * pz)
        need = abs(a) * _math.tan(_math.radians(deg))
        if p >= need:
            return drop
        if p < 1e-9:
            px, py, pz, p = s.x, s.y, s.z, 1.0
        return (loc.x + a * f.x + px / p * need,
                loc.y + a * f.y + py / p * need,
                loc.z + a * f.z + pz / p * need)


class ZoomTargetMode(CameraMode):
    """Zoom onto a target (BC's "ZoomTarget" — Camera.LowZoomTarget →
    NewMode("ZoomTarget", [("Source", pSource), ("Target", pTarget)])). Eye at
    the Source object's position, looking at Target, up from Source col2.

    Source fallback: BC's Camera.MakePlayerCamera_PlayerChanged wires
    Source=player on the player camera's zoom modes; our shim never runs it, so
    when no live Source is wired the eye degrades to the OWNING camera's own
    pose (_owner_camera) — "zoom from the current viewpoint toward the target".
    A Source that was set but died invalidates the mode; only unset/None falls
    back to the camera."""

    def _ideal(self, pose_of=None):
        dst = self.GetAttrIDObject("Target")
        if not _target_alive(dst):
            return None
        src = self.GetAttrIDObject("Source")
        if src is not None:
            if not _target_alive(src):
                return None
            s, R = _obj_pose(src, pose_of)
        else:
            cam = self._owner_camera
            get_loc = getattr(cam, "GetWorldLocation", None)
            get_rot = getattr(cam, "GetWorldRotation", None)
            if not callable(get_loc) or not callable(get_rot):
                return None
            s = get_loc()
            R = get_rot()
            if s is None or R is None:            # camera pose not resolvable
                return None
        d, _dR = _obj_pose(dst, pose_of)
        eye = (s.x, s.y, s.z)
        fwd = _unit(d.x - s.x, d.y - s.y, d.z - s.z)
        u = R.GetCol(2)
        up = _unit(u.x, u.y, u.z)
        return (eye, fwd, up)

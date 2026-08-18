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
            "TorpCam": TorpCameraMode,
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


# BC's authored Target attrs (CameraModes.Target, CameraModes.py:55-73), used
# when a mode is constructed bare — i.e. by anything that does not run the SDK
# builder. Module-level so a live look can retune the framing without touching
# the SDK's authored numbers. See TargetMode's docstring for the units.
TARGET_DEFAULT_BACK_WATCH_POS = 7.95     # back component of the eye offset
TARGET_DEFAULT_UP_WATCH_POS = 0.95       # up component of the eye offset
TARGET_DEFAULT_LOOK_BETWEEN = 0.05       # aim fraction, target → source
TARGET_DEFAULT_DISTANCE = 4.0            # standoff, multiples of Source radius
TARGET_DEFAULT_MINIMUM_DISTANCE = 2.0    # GU floor on that standoff
TARGET_DEFAULT_MAXIMUM_DISTANCE = 40.0   # GU ceiling on that standoff


class TargetMode(CameraMode):
    """Over-the-shoulder shot of the Source, framing the Target (TargetWatch).

    BC ships ONE Target mode class and three builders feed it (CameraModes.py):
    Target (:55), WideTarget (:75) and CinematicReverseTarget (:334) — the last
    is what F3 drives (CinematicInterfaceHandlers.CameraTarget cycles its
    "Source" through SetClass.GetTargetableObjects). They differ ONLY in their
    authored numbers, so every one of them has to come out of this one class,
    exactly as Chase/ReverseChase already do.

    ⚠️ THE FRAMING IS INFERRED. The clean-room reference documents the camera
    cluster's object model and per-frame tick (spec/CameraObjectClass.md) but
    says nothing about any mode's placement algorithm, and every CameraMode
    attribute is set through the generic SWIG attr bag, so no reconstructed
    body names these attrs. What IS sourced is the attribute NAMES and their
    authored VALUES, read verbatim: SweepTime 1.0, PositionThreshold 0.01,
    DotThreshold 0.98, MinimumDistance 2.0, Distance 4.0, MaximumDistance 40.0,
    BackWatchPos 7.95, UpWatchPos 0.95, LookBetween 0.05, MaxLagDist 1.0,
    MaxUpAngleChange PI/2 — plus WideTarget's 8.0/32.0/64.0 + 8.0/1.25 and
    CinematicReverseTarget's 2.0/4.0/16.0 + 7.95/0.95. Everything below is read
    off those names and magnitudes.

    Placement (INFERRED):
      axis   = unit(target - source)                    # the look axis
      offset = unit(-axis*BackWatchPos + source_up*UpWatchPos)
      eye    = source + offset * reach
      lookat = target + (source - target) * LookBetween
      fwd    = unit(lookat - eye)
    so the camera stands BEHIND the Source along the source→target axis and
    slightly ABOVE it, with both objects in frame. This replaced putting the eye
    EXACTLY at the source's origin and staring at the target — the live F3
    defect (you sat inside the hull) — which used none of the authored attrs.

    BackWatchPos / UpWatchPos are read as a RATIO (a direction), not absolute
    game units: 7.95 : 0.95 is a 6.8° lift, the same shape as ChaseMode's
    authored DefaultPosition (0, -1.0, 0.1) — 5.7° — which our ChaseMode
    normalises and scales by Distance for exactly this reason. Reading their
    magnitudes as GU as well would have them fight `Distance` for control of the
    standoff, and would make WideTarget (8.0 / 1.25) an almost identical shot to
    Target (7.95 / 0.95) when the SDK plainly authors it as the wide one.

    `Distance` is the standoff, in multiples of the SOURCE's radius, clamped to
    [MinimumDistance, MaximumDistance] absolute GU. Two reasons for the
    radius-relative reading, both structural: Target authors the IDENTICAL
    triple to Chase (2.0 / 4.0 / 40.0), which our ChaseMode already reads as
    radius × Distance; and the eye is anchored to the Source, so the standoff
    must scale with the hull it is parked behind or the shot clips a starbase
    and abandons a shuttle. The clamps then do real work — they are the reason
    the triple is a triple — bounding the radius-scaled reach in absolute GU
    (a starbase Source at CinematicReverseTarget's Maximum 16.0 is pulled in
    from 80 GU; a probe is pushed out to the Minimum 2.0). The radius is the
    SOURCE's, not the Target's, because it is the Source the eye must clear.

    `LookBetween` interpolates FROM THE TARGET back toward the Source, so the
    authored 0.05 aims 5% off the target and keeps the source's shoulder in
    frame. The opposite reading is self-refuting: 0.05 from the source would
    aim the camera essentially AT the hull it is parked directly behind, with
    the target off-screen — the mode would frame nothing.

    Up is the SOURCE's up axis (GetCol(2), column-vector right-handed), which
    is also the elevation reference the UpWatchPos lift is measured along, so
    the shot stays level with the deck it is anchored to.

    Validity: a dead/absent Source or Target, or a Source and Target at the same
    point (no axis, so no shot) — BC's authored Target → Chase edge does the
    fallback (Camera.py:634), as it does for TorpCam.

    DELIBERATELY UNUSED: SweepTime, PositionThreshold, DotThreshold, MaxLagDist
    and MaxUpAngleChange. Our sweep is the base class's global SWEEP_TAU_S glide
    with the _pose_discontinuity cut, shared by all nine modes; there is no
    defensible mapping from a per-mode sweep duration, a position/dot
    convergence pair, a lag leash and an up-rotation rate limiter onto it that
    is not simply invented. The same three sweep attrs are already unused on
    every other mode that authors them (Chase, TorpCam, FreeOrbit...).
    """

    def _ideal(self, pose_of=None):
        src = self.GetAttrIDObject("Source")
        dst = self.GetAttrIDObject("Target")
        if not _target_alive(src) or not _target_alive(dst):
            return None
        s, sR = _obj_pose(src, pose_of)
        d, _dR = _obj_pose(dst, pose_of)
        ax, ay, az = d.x - s.x, d.y - s.y, d.z - s.z
        sep = _math.sqrt(ax * ax + ay * ay + az * az)
        if sep < 1e-6:
            return None            # no source→target axis ⇒ no shot
        ax, ay, az = ax / sep, ay / sep, az / sep
        up = _unit(*_apply_rot(sR, TGPoint3(0.0, 0.0, 1.0)))
        back = self.GetAttrFloat("BackWatchPos", TARGET_DEFAULT_BACK_WATCH_POS)
        rise = self.GetAttrFloat("UpWatchPos", TARGET_DEFAULT_UP_WATCH_POS)
        ox, oy, oz = (-ax * back + up[0] * rise,
                      -ay * back + up[1] * rise,
                      -az * back + up[2] * rise)
        n = _math.sqrt(ox * ox + oy * oy + oz * oz)
        if n < 1e-9:               # both components authored 0: straight back
            ox, oy, oz, n = -ax, -ay, -az, 1.0
        reach = self._reach(src)
        eye = (s.x + ox / n * reach, s.y + oy / n * reach, s.z + oz / n * reach)
        between = self.GetAttrFloat("LookBetween", TARGET_DEFAULT_LOOK_BETWEEN)
        look = (d.x + (s.x - d.x) * between,
                d.y + (s.y - d.y) * between,
                d.z + (s.z - d.z) * between)
        fwd = _unit(look[0] - eye[0], look[1] - eye[1], look[2] - eye[2])
        return (eye, fwd, up)

    def _reach(self, src):
        """Standoff from the Source: Distance × the Source's radius, clamped to
        [MinimumDistance, MaximumDistance] in absolute GU (INFERRED — see the
        class docstring)."""
        reach = (self.GetAttrFloat("Distance", TARGET_DEFAULT_DISTANCE)
                 * _target_radius(src))
        hi = self.GetAttrFloat("MaximumDistance", TARGET_DEFAULT_MAXIMUM_DISTANCE)
        if hi > 0.0:
            reach = min(reach, hi)
        return max(reach, self.GetAttrFloat("MinimumDistance",
                                            TARGET_DEFAULT_MINIMUM_DISTANCE))


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
# Slow-orbit drift. RotateSpeed is the INITIAL/current rate (state, not config)
# and RotateSpeedAccel ramps it to MaxRotateSpeed while the target is slow;
# 0.2 rad/s is ~11.5 deg/s, a full orbit in ~31 s, reached from rest in ~8 s.
# Radians/second is our reading of the units — see the class docstring.
DROP_DEFAULT_ROTATE_SPEED = 0.0
DROP_DEFAULT_ROTATE_SPEED_ACCEL = 0.025
DROP_DEFAULT_MAX_ROTATE_SPEED = 0.2
DROP_DEFAULT_SLOW_SPEED_THRESHOLD = 0.5        # GU/s
DROP_DEFAULT_SLOW_ROTATION_THRESHOLD = 0.1     # rad/s


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


def _rotate_about(p, centre, axis, angle):
    """Rodrigues: rotate point `p` (3-tuple) by `angle` radians about the axis
    `axis` (unit 3-tuple) through `centre` (TGPoint3). Distance from `centre`
    and the component along `axis` are both preserved exactly in exact
    arithmetic, so an orbit neither closes on nor climbs off the target."""
    vx, vy, vz = p[0] - centre.x, p[1] - centre.y, p[2] - centre.z
    kx, ky, kz = axis
    c, s = _math.cos(angle), _math.sin(angle)
    d = kx * vx + ky * vy + kz * vz
    cx, cy, cz = ky * vz - kz * vy, kz * vx - kx * vz, kx * vy - ky * vx
    return (centre.x + vx * c + cx * s + kx * d * (1.0 - c),
            centre.y + vy * c + cy * s + ky * d * (1.0 - c),
            centre.z + vz * c + cz * s + kz * d * (1.0 - c))


def _target_angular_velocity(obj):
    """(wx, wy, wz) angular velocity in rad/s, or zeros when the object has no
    real GetAngularVelocityTG — same PhysicsObjectClass-surface reasoning (and
    same MRO probe) as _target_velocity above."""
    from engine.core.ids import implements
    if not implements(obj, "GetAngularVelocityTG"):
        return (0.0, 0.0, 0.0)
    try:
        w = obj.GetAngularVelocityTG()
        return (float(w.x), float(w.y), float(w.z))
    except Exception:
        return (0.0, 0.0, 0.0)


def _magnitude(v):
    return _math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


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
      off-axis avoidance rule, the re-drop rule, and the slow-orbit drift. All
      of it is read off the parameter names and defaults, not recovered from
      the binary. Treat it as a plausible flyby shot that honours the authored
      numbers, not as BC.

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

    Slow-orbit drift (INFERRED): park the ship and the shot used to freeze
    solid — still camera, still subject — which is the one case where this mode
    stops being cinematic. The five remaining authored attrs read as the fix:
    when the target is nearly stationary, orbit it slowly instead of staring.
    SOURCED are only the five NUMBERS (RotateSpeed 0.0, RotateSpeedAccel 0.025,
    MaxRotateSpeed 0.2, SlowSpeedThreshold 0.5, SlowRotationThreshold 0.1) and
    their names; the magnitudes are what make the reading plausible — 0.2 rad/s
    is ~11.5 deg/s, a full orbit in ~31 s, reached from rest in ~8 s at
    0.025 rad/s^2. Everything about HOW they are used is our reading, NOT
    reverse-engineered, specifically:

      * that RotateSpeed is the INITIAL/current rate — state, not config —
        which RotateSpeedAccel ramps toward MaxRotateSpeed;
      * that the rates are radians/second (degrees would make MaxRotateSpeed a
        30-minute orbit, which is not a camera move);
      * that the slow test is an AND of the two thresholds (a station-keeping
        but tumbling ship already animates the frame);
      * that the DROP POINT is orbited, rather than the shot being re-derived —
        so the framing the placement chose is kept, and because rotating about
        an axis through the target holds |drop - target| at d0, the re-drop rule
        above is not tripped by the drift itself (tested, not assumed);
      * that the orbit axis is the target's up axis (GetCol(2), column-vector
        right-handed) through its CURRENT position, which also preserves the
        shot's elevation;
      * that the rate decays symmetrically once the target speeds up again. BC
        authors no separate decel term, so reusing RotateSpeedAccel is an
        assumption;
      * that a re-drop restarts the drift from the authored RotateSpeed, and
        that a fresh drop point is used as authored for the frame it was made.

    A target that implements neither GetVelocityTG nor GetAngularVelocityTG
    (waypoints, placements — it is PhysicsObjectClass surface) reads as fully
    stationary, so the drift engages for it.

    STILL DELIBERATELY NOT IMPLEMENTED: RangeAngle1-4, which only
    WarpSequence.py sets and CameraModes never authors.
    """

    def __init__(self):
        super().__init__()
        # STATEFUL — unlike the other five modes, whose _ideal() is a pure
        # function of the target's current pose. Staying put while the ship
        # moves IS the shot, so the drop point is computed only on a re-drop.
        self._drop = None            # world drop point (3-tuple) or None
        self._drop_dist = None       # d0: drop→target distance at drop time
        self._drop_target = None     # identity of the target we dropped for
        self._rotate_speed = None    # current orbit rate, rad/s (None = unseeded)
        # dt for the frame currently being computed, parked here by Update() so
        # _ideal() — whose signature carries no dt, and is shared by eight modes
        # — can integrate the orbit. None outside an Update (e.g. IsValid()'s
        # bare _ideal() probe), which reads as "no time passed": never drift.
        self._dt = None

    def Update(self, dt=None, pose_of=None):
        """Carry `dt` into _ideal() for the orbit integrator, then defer to the
        base sweep. Overridden here rather than widening _ideal()'s signature
        across all eight modes — DropAndWatch is the only stateful one."""
        self._dt = dt
        try:
            return super().Update(dt, pose_of)
        finally:
            self._dt = None

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
            # A fresh drop point is used as authored for the frame it was made;
            # the drift accumulates FROM it, starting next frame, from the
            # authored initial RotateSpeed (a re-drop is a new shot).
            self._rotate_speed = self.GetAttrFloat("RotateSpeed",
                                                  DROP_DEFAULT_ROTATE_SPEED)
        else:
            self._advance_orbit(t, loc, R)
        eye = self._drop
        fwd = _unit(loc.x - eye[0], loc.y - eye[1], loc.z - eye[2])
        u = R.GetCol(2)
        return (eye, fwd, _unit(u.x, u.y, u.z))

    def _is_slow(self, t):
        """True when the target is barely moving, so the shot needs the drift to
        stay alive: linear speed under SlowSpeedThreshold AND angular speed
        under SlowRotationThreshold. The conjunction is INFERRED — a ship that
        is stationary but spinning is already animating the frame. A target
        with neither physics accessor reads as fully stationary (waypoints and
        placements never move), so the drift engages for it."""
        return (_magnitude(_target_velocity(t))
                < self.GetAttrFloat("SlowSpeedThreshold",
                                    DROP_DEFAULT_SLOW_SPEED_THRESHOLD)
                and _magnitude(_target_angular_velocity(t))
                < self.GetAttrFloat("SlowRotationThreshold",
                                    DROP_DEFAULT_SLOW_ROTATION_THRESHOLD))

    def _advance_orbit(self, t, loc, R):
        """Drift the drop point one frame around the target (INFERRED — see the
        class docstring). The rate accelerates at RotateSpeedAccel toward
        MaxRotateSpeed; the orbit is about the target's up axis, through the
        target's current position, so the drop distance and elevation the shot
        was framed with are preserved."""
        dt = self._dt
        if not dt or dt <= 0.0:      # None (snap) or 0.0 (paused): no time passed
            return
        if self._rotate_speed is None:
            self._rotate_speed = self.GetAttrFloat("RotateSpeed",
                                                  DROP_DEFAULT_ROTATE_SPEED)
        accel = self.GetAttrFloat("RotateSpeedAccel",
                                  DROP_DEFAULT_ROTATE_SPEED_ACCEL)
        cap = self.GetAttrFloat("MaxRotateSpeed", DROP_DEFAULT_MAX_ROTATE_SPEED)
        if self._is_slow(t):
            self._rotate_speed = min(cap, self._rotate_speed + accel * dt)
        else:
            # BC authors no separate decel term; reusing RotateSpeedAccel to ease
            # back to rest is our symmetry assumption, not a recovered constant.
            self._rotate_speed = max(0.0, self._rotate_speed - accel * dt)
        angle = self._rotate_speed * dt
        if abs(angle) < 1e-12:
            return
        u = R.GetCol(2)
        self._drop = _rotate_about(self._drop, loc, _unit(u.x, u.y, u.z), angle)

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


# BC's authored TorpCam attrs (CameraModes.TorpCam, CameraModes.py:318-332),
# used when a mode is constructed bare — i.e. by anything that does not run the
# SDK builder. The two DISTANCES are read as ABSOLUTE game units (see the
# TorpCameraMode docstring); they are module-level so a live look can retune the
# ride without touching the SDK's authored numbers.
TORP_DEFAULT_START_DISTANCE = 4.0        # GU behind the torpedo at launch
TORP_DEFAULT_LATER_DISTANCE = 8.0        # GU behind it once the ramp is done
TORP_DEFAULT_MOVE_DISTANCE_TIME = 6.0    # seconds of ride time for that ramp
TORP_DEFAULT_DELAY_AFTER_TORP_GONE = 2.0  # seconds to hold the pose on the hit


class TorpCameraMode(CameraMode):
    """Ride behind the player's torpedo — BC's F4 cinematic camera.

    ⚠️ THIS IS NOT A RECONSTRUCTION OF BC'S ALGORITHM. The clean-room reference
    has no TorpCam entry, so only part of this is sourced:

    * SOURCED — the attribute NAMES and their authored VALUES, read verbatim
      from CameraModes.TorpCam (CameraModes.py:321-329): SweepTime 2.0,
      PositionThreshold 0.01, DotThreshold 0.98, DelayAfterTorpGone 2.0,
      StartDistance 4.0, LaterDistance 8.0, MoveDistanceTime 6.0. Also sourced:
      the mode's "Target" attr is the PLAYER SHIP, not a torpedo
      (Camera.MakePlayerCamera_PlayerChanged's 18-row table, Camera.py:702);
      F4 selects it by re-pointing AddModeHierarchy("InvalidCinematic",
      "TorpCam") (CinematicInterfaceHandlers.py:387); and an invalid TorpCam
      falls through the authored edge TorpCam -> Chase (Camera.py:642).
    * INFERRED — everything else below. Read off the parameter names and
      magnitudes, not recovered from the binary.

    Finding the torpedo (INFERRED): the Target is the FIRING ship, so the shot
    to ride is that ship's most recently fired in-flight torpedo — the highest
    _id among engine.appc.projectiles._active whose _source_ship is the Target.
    _source_ship is what weapon_subsystems._spawn_projectile stamps on every
    launch and what projectiles._matches_source already filters on.

    Latching (INFERRED): once riding a torpedo the mode keeps riding THAT one
    until it leaves the registry. Re-picking the newest every frame would make
    the camera hop down a salvo as each tube fires. Same statefulness as
    DropAndWatchMode's drop point. The latch holds only a plain reference and is
    dropped the instant the torpedo leaves _active, so it can never keep an
    expired torpedo alive or fight projectiles.expire().

    Placement (INFERRED): eye = torpedo_position - flight_direction * distance,
    forward = flight_direction. Behind it, looking along the flight path — which
    is also looking AT the torpedo, since the two coincide exactly when the eye
    is on the velocity axis. The flight direction is the torpedo's VELOCITY
    (it carries no rotation), so a homing torpedo that turns swings the camera
    round behind it; the last good direction is reused for a degenerate
    (zero-velocity) tick. Up is the FIRING SHIP's up axis (GetCol(2),
    column-vector right-handed) — the torpedo has no roll frame of its own, and
    this keeps the shot level with the deck it was fired from.

    Distance units (INFERRED, and the main judgement call): StartDistance /
    LaterDistance are ABSOLUTE game units, not radius multiples. ChaseMode's
    authored Distance is radius-relative because its Target IS the framed
    object; here the Target is the firing ship, so the same reading would put
    the camera 4 x a Galaxy's radius behind a torpedo and frame nothing. The
    magnitudes agree: a photon torpedo's authored glow quad is 3.0 GU across
    (Tactical/Projectiles/PhotonTorpedo.py:37), so 4 GU behind it is a close
    ride and 8 GU is a pulled-back one. Exposed as the module-level
    TORP_DEFAULT_* constants so a live look can retune them.

    Ramp (INFERRED): distance goes StartDistance -> LaterDistance LINEARLY over
    MoveDistanceTime seconds of RIDE time (time this torpedo has been ridden,
    not wall clock), then clamps — the camera eases back as the torpedo runs.
    Linear is the obvious default; nothing in the authored numbers implies a
    curve.

    DelayAfterTorpGone (INFERRED use, sourced value): when the torpedo leaves
    the registry — impact or TTL, projectiles.update_all expires both the same
    way — the last pose is HELD for DelayAfterTorpGone seconds so the hit is on
    screen, then the mode reports invalid and releases the latch, so the next
    shot gets its own ride.

    Validity: invalid with no Target, with a Target that has nothing in the air,
    and once the hold has elapsed. The mode does NOT implement a fallback of its
    own — BC's authored TorpCam -> Chase edge does that in
    CameraObjectClass.GetCurrentCameraMode's hierarchy walk (tested, not
    assumed: tests/unit/test_camera_mode_stack.py).

    DELIBERATELY UNUSED: SweepTime, PositionThreshold and DotThreshold. Our
    sweep is the base class's global SWEEP_TAU_S exponential glide with the
    _pose_discontinuity cut, shared by all nine modes; there is no defensible
    mapping from a per-mode sweep duration and a position/dot convergence pair
    onto it that is not just invented, and the same three attrs are already
    unused on every other mode that authors them (Chase, Target, FreeOrbit...).
    """

    def __init__(self):
        super().__init__()
        # STATEFUL — like DropAndWatchMode, and for the same kind of reason:
        # WHICH torpedo is being ridden is a latch, not a per-frame lookup.
        self._torp = None        # latched in-flight torpedo, or None
        self._ride_t = 0.0       # seconds this torpedo has been ridden (ramp)
        self._gone_t = None      # seconds since it left the registry (None = riding)
        self._final = None       # last pose while riding, held during _gone_t
        self._dir = None         # last good unit flight direction
        # dt for the frame currently being computed, parked here by Update() so
        # _ideal() — whose signature carries no dt, and is shared by nine modes
        # — can advance the ride/hold timers. None outside an Update (e.g.
        # IsValid()'s bare _ideal() probe), which reads as "no time passed".
        self._dt = None

    def Update(self, dt=None, pose_of=None):
        """Carry `dt` into _ideal() for the ride/hold timers, then defer to the
        base sweep. Overridden here rather than widening _ideal()'s signature
        across all nine modes — the same contained pattern DropAndWatchMode
        established."""
        self._dt = dt
        try:
            return super().Update(dt, pose_of)
        finally:
            self._dt = None

    # ── Timer helpers ─────────────────────────────────────────────────────────
    def _elapsed(self):
        """Seconds to charge the timers this frame. dt=None (snap) and dt=0.0
        (paused sim) are both "no time passed"."""
        dt = self._dt
        return dt if dt and dt > 0.0 else 0.0

    # ── Torpedo selection ─────────────────────────────────────────────────────
    def _still_in_flight(self, torp):
        """True while the latched torpedo is still in the live registry.
        Identity, not equality — and re-read every frame, so the latch tolerates
        projectiles.expire() removing it at any point."""
        from engine.appc import projectiles
        return any(t is torp for t in projectiles._active)

    def _acquire(self, target):
        """The Target ship's most recently fired in-flight torpedo (highest
        _id), or None. _source_ship is the same firing-object field
        projectiles._matches_source filters on."""
        from engine.appc import projectiles
        best = None
        for t in projectiles._active:
            if t._source_ship is not target:
                continue
            if best is None or t._id > best._id:
                best = t
        return best

    def _release(self):
        self._torp = None
        self._ride_t = 0.0
        self._gone_t = None
        self._final = None
        self._dir = None

    def _ideal(self, pose_of=None):
        t = self.GetAttrIDObject("Target")
        if not _target_alive(t):
            return None
        # The latched torpedo may vanish from the registry at any point
        # (update_all expires it on impact or TTL): notice, drop the reference,
        # and start the hold.
        if self._torp is not None and not self._still_in_flight(self._torp):
            self._torp = None
            self._gone_t = 0.0
        if self._torp is None and self._gone_t is None:
            self._torp = self._acquire(t)
            self._ride_t = 0.0
        if self._torp is None:
            return self._hold()
        return self._ride(t)

    def _hold(self):
        """Keep the final pose on screen for DelayAfterTorpGone seconds so the
        hit is seen, then go invalid and release the latch for the next shot."""
        if self._gone_t is None or self._final is None:
            return None
        if self._gone_t >= self.GetAttrFloat("DelayAfterTorpGone",
                                             TORP_DEFAULT_DELAY_AFTER_TORP_GONE):
            self._release()
            return None
        self._gone_t += self._elapsed()
        return self._final

    def _ride(self, target):
        """Sit `_distance()` behind the torpedo along its velocity, looking the
        way it is going (INFERRED — see the class docstring)."""
        p = self._torp.GetWorldLocation()
        v = self._torp.GetVelocityTG()
        speed = _math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if speed > 1e-9:
            self._dir = (v.x / speed, v.y / speed, v.z / speed)
        if self._dir is None:
            return None            # a torpedo that has never moved frames nothing
        fwd = self._dir
        d = self._distance()
        eye = (p.x - fwd[0] * d, p.y - fwd[1] * d, p.z - fwd[2] * d)
        _loc, R = _obj_pose(target, None)
        u = R.GetCol(2)
        pose = (eye, fwd, _unit(u.x, u.y, u.z))
        self._final = pose
        self._ride_t += self._elapsed()
        return pose

    def _distance(self):
        """StartDistance -> LaterDistance, linear over MoveDistanceTime seconds
        of ride time, then clamped (INFERRED — see the class docstring)."""
        start = self.GetAttrFloat("StartDistance", TORP_DEFAULT_START_DISTANCE)
        later = self.GetAttrFloat("LaterDistance", TORP_DEFAULT_LATER_DISTANCE)
        span = self.GetAttrFloat("MoveDistanceTime",
                                 TORP_DEFAULT_MOVE_DISTANCE_TIME)
        if span <= 0.0:
            return later
        return start + (later - start) * min(1.0, self._ride_t / span)


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

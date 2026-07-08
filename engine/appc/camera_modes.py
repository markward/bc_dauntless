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

_next_obj_id = [0]


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

    def Update(self, dt=None):
        ideal = self._ideal()
        if ideal is None:
            return self._cur if self._cur is not None else (
                (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        if self._cur is None or self._snap or dt is None:
            self._cur = ideal
            self._snap = False
            return self._cur
        a = 1.0 - _math.exp(-dt / SWEEP_TAU_S)
        self._cur = (
            tuple(self._cur[0][i] + a * (ideal[0][i] - self._cur[0][i]) for i in range(3)),
            _unit(*(self._cur[1][i] + a * (ideal[1][i] - self._cur[1][i]) for i in range(3))),
            _unit(*(self._cur[2][i] + a * (ideal[2][i] - self._cur[2][i]) for i in range(3))),
        )
        return self._cur

    def _ideal(self):
        raise NotImplementedError


def _target_alive(obj):
    if obj is None:
        return False
    is_dying = getattr(obj, "IsDying", None)
    if not callable(is_dying):
        return True
    try:
        dying = is_dying()
    except Exception:
        return False
    # Waypoints / PlacementObjects don't implement IsDying — TGObject's
    # __getattr__ returns a truthy recursive _Stub, which must read as
    # "not dying" (placement objects never die; they are the Source of every
    # placement/zoom camera shot).
    from engine.core.ids import _Stub
    if isinstance(dying, _Stub):
        return True
    return not dying


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

    def _ideal(self):
        return None


def CameraMode_Create(kind, pCamera=None):
    """App.CameraMode_Create shim. The SDK's CameraModes.* builders and
    Camera.MakePlayerCamera call this with a mode-type string, then fill attrs
    via SetAttr*. Dispatch on `kind` to the matching mode class; `PlaceByDirection`
    and any unknown kind fall back to the PlaceByDirection attr-bag (the bridge
    captain path — unchanged). `pCamera` is tagged as the mode owner (used by
    ZoomTargetMode's Source fallback)."""
    if kind == "ReverseChase":
        mode = ChaseMode(reverse=True)
    else:
        _dispatch = {
            "Locked": LockedMode,
            "Chase": ChaseMode,
            "Target": TargetMode,
            "Placement": PlacementMode,
            "ZoomTarget": ZoomTargetMode,
        }
        cls = _dispatch.get(kind)
        mode = cls() if cls is not None else PlaceByDirectionMode(kind)
    mode._owner_camera = pCamera
    return mode


class LockedMode(CameraMode):
    """Camera locked to a fixed pose in the target's local frame (LockedView /
    LockedViewAnyAngle). Position/Forward/Up are target-local; the spherical
    math is done SDK-side in Camera.py before the attrs are set here."""

    def _ideal(self):
        t = self.GetAttrIDObject("Target")
        P = self.GetAttrPoint("Position")
        F = self.GetAttrPoint("Forward")
        U = self.GetAttrPoint("Up")
        if not _target_alive(t) or P is None or F is None or U is None:
            return None
        R = t.GetWorldRotation()
        loc = t.GetWorldLocation()
        op = _apply_rot(R, P)
        eye = (loc.x + op[0], loc.y + op[1], loc.z + op[2])
        fwd = _unit(*_apply_rot(R, F))
        up = _unit(*_apply_rot(R, U))
        return (eye, fwd, up)


CHASE_DIST_GU = 12.0
CHASE_UP_GU = 3.0


class ChaseMode(CameraMode):
    """Follow the target from behind (ChaseCam) or ahead (ReverseChaseCam),
    looking at it. Offset built in the target body frame, mapped to world via
    the column-vector convention (mirrors engine/cameras/chase.py)."""

    def __init__(self, reverse=False):
        super().__init__()
        self._reverse = reverse

    def _ideal(self):
        t = self.GetAttrIDObject("Target")
        if not _target_alive(t):
            return None
        R = t.GetWorldRotation()
        loc = t.GetWorldLocation()
        sign = 1.0 if self._reverse else -1.0           # behind = -forward
        off = _apply_rot(R, TGPoint3(0.0, sign * CHASE_DIST_GU, CHASE_UP_GU))
        eye = (loc.x + off[0], loc.y + off[1], loc.z + off[2])
        fwd = _unit(loc.x - eye[0], loc.y - eye[1], loc.z - eye[2])
        up = _unit(*_apply_rot(R, TGPoint3(0.0, 0.0, 1.0)))
        return (eye, fwd, up)


class TargetMode(CameraMode):
    """Look from a source object to a target object (TargetWatch)."""

    def _ideal(self):
        src = self.GetAttrIDObject("Source")
        dst = self.GetAttrIDObject("Target")
        if not _target_alive(src) or not _target_alive(dst):
            return None
        s = src.GetWorldLocation()
        d = dst.GetWorldLocation()
        eye = (s.x, s.y, s.z)
        fwd = _unit(d.x - s.x, d.y - s.y, d.z - s.z)
        up = _unit(*_apply_rot(src.GetWorldRotation(), TGPoint3(0.0, 0.0, 1.0)))
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

    def _ideal(self):
        src = self.GetAttrIDObject("Source")
        if not _target_alive(src):
            return None
        s = src.GetWorldLocation()
        R = src.GetWorldRotation()
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
            d = dst.GetWorldLocation()
            off = self.GetAttrPoint("TargetOffsetWorld")
            if off is not None:
                dx, dy, dz = d.x + off.x, d.y + off.y, d.z + off.z
            else:
                dx, dy, dz = d.x, d.y, d.z
            fwd = _unit(dx - s.x, dy - s.y, dz - s.z)
        return (eye, fwd, up)


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

    def _ideal(self):
        dst = self.GetAttrIDObject("Target")
        if not _target_alive(dst):
            return None
        src = self.GetAttrIDObject("Source")
        if src is not None:
            if not _target_alive(src):
                return None
            s = src.GetWorldLocation()
            R = src.GetWorldRotation()
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
        d = dst.GetWorldLocation()
        eye = (s.x, s.y, s.z)
        fwd = _unit(d.x - s.x, d.y - s.y, d.z - s.z)
        u = R.GetCol(2)
        up = _unit(u.x, u.y, u.z)
        return (eye, fwd, up)

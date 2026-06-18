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
        if self._cur is None or self._snap or not dt:
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
    try:
        return not (callable(is_dying) and is_dying())
    except Exception:
        return True


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

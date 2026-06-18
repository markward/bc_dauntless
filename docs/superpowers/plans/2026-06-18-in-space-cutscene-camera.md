# In-space Cutscene-Camera Subsystem (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the exterior/space view through a mission-scripted cutscene camera (`LockedView`, `ChaseCam`, `TargetWatch`) by building the camera-mode subsystem the SDK drives and wiring the host loop to select it.

**Architecture:** A new pure-Python mode object model (`engine/appc/camera_modes.py`) provides `CameraMode` subclasses whose `Update(dt)` computes a world pose each frame from a target object's live transform. `CameraObjectClass` gains a real mode stack so `Camera.NewMode` can push live modes. The host loop's exterior branch selects the rendered set's active cutscene camera when one has a live mode, feeding its pose into the existing `r.set_camera(...)` call.

**Tech Stack:** Python 3.13, existing `engine/appc` shim layer, `engine/cameras` director, pytest. No C++/renderer changes — pure Python, no rebuild.

## Global Constraints

- Rotation: column-vector, right-handed. World-forward = `GetCol(1)`, world-up = `GetCol(2)`, world-right = `GetCol(0)`. Body→world: `v.MultMatrixLeft(R)` computes `R · v` in place.
- Game units throughout (1 GU = 175 m). Never name a variable `*_m` / `*_mps`; speed/range is `*_gu` / `*_gups`.
- SDK-faithful: honor `CutsceneCameraBegin` / `SetActiveCamera` / the camera-mode actions; never hardcode per-mission camera moves. Do not modify `sdk/Build/scripts/Camera.py` or `CameraScriptActions.py` — they are SDK ground truth and already call the surface we are building.
- Pure-Python shim changes need NO rebuild. `build/dauntless` is the only binary.
- TDD: failing test first, minimal implementation, then commit.
- Tests run via `uv run pytest <path>`; full suite via `scripts/run_tests.sh` (memory-safe).
- v1 scope: SPACE/exterior view only. Bridge-set cutscene cameras, `Placement`/`DropAndWatch`/warp-watch modes, `AddModeHierarchy` fallback tree, and the cinematic window are OUT.

---

### Task 1: `CameraMode` base + `LockedMode`

**Files:**
- Create: `engine/appc/camera_modes.py`
- Test: `tests/unit/test_camera_modes.py`

**Interfaces:**
- Consumes: `engine.appc.math.TGPoint3`, `engine.appc.math.TGMatrix3` (`MultMatrixLeft`, `MakeZRotation`).
- Produces:
  - `class CameraMode`: `SetAttrFloat(name, v)`, `SetAttrPoint(name, p)`, `SetAttrIDObject(name, obj)`, `GetAttrFloat(name, default=0.0)`, `GetAttrPoint(name)`, `GetAttrIDObject(name)`, `GetObjID() -> int`, `IsValid() -> int`, `SnapToIdealPosition() -> None`, `Update(dt=None) -> (eye, fwd, up)` where each is a 3-tuple of floats (world game units; fwd/up unit vectors). Subclasses override `_ideal() -> (eye, fwd, up) | None` (None ⇒ invalid). `set_initial_pose(eye, fwd, up)` seeds the sweep start.
  - `SWEEP_TAU_S = 0.35` (exponential time constant for sweep).
  - `class LockedMode(CameraMode)`: reads `Target` (object), `Position`/`Forward`/`Up` (target-local `TGPoint3`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_camera_modes.py
import math
from engine.appc.camera_modes import CameraMode, LockedMode, SWEEP_TAU_S
from engine.appc.math import TGPoint3, TGMatrix3


class _FakeTarget:
    """Minimal stand-in for an ObjectClass target."""
    def __init__(self, loc, rot=None):
        self._loc = TGPoint3(*loc)
        self._rot = rot if rot is not None else TGMatrix3()  # identity

    def GetWorldLocation(self):
        return TGPoint3(self._loc.x, self._loc.y, self._loc.z)

    def GetWorldRotation(self):
        return self._rot


def test_locked_mode_snap_identity_rotation():
    t = _FakeTarget((100.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))   # 10 GU behind (model -Y)
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()                                # no dt ⇒ snap
    assert eye == (100.0, -10.0, 0.0)
    assert fwd == (0.0, 1.0, 0.0)
    assert up == (0.0, 0.0, 1.0)


def test_locked_mode_applies_target_rotation():
    # Target yawed 180° about Z: model -Y maps to world +Y; model +Y to world -Y.
    r = TGMatrix3().MakeZRotation(math.pi)
    t = _FakeTarget((0.0, 0.0, 0.0), rot=r)
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert abs(eye[1] - 10.0) < 1e-6      # -10 model-Y → +10 world-Y
    assert abs(fwd[1] - (-1.0)) < 1e-6    # +Y model-fwd → -Y world


def test_locked_mode_invalid_without_target():
    m = LockedMode()
    assert not m.IsValid()


def test_camera_mode_obj_ids_unique():
    a, b = LockedMode(), LockedMode()
    assert a.GetObjID() != b.GetObjID()


def test_sweep_converges_toward_ideal():
    t = _FakeTarget((100.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, 0.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.set_initial_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    # One small step does NOT reach the ideal...
    eye1, _, _ = m.Update(0.016)
    assert 0.0 < eye1[0] < 100.0
    # ...but many steps do.
    for _ in range(600):
        eye, _, _ = m.Update(0.016)
    assert abs(eye[0] - 100.0) < 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_camera_modes.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.camera_modes'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/appc/camera_modes.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_camera_modes.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/camera_modes.py tests/unit/test_camera_modes.py
git commit -m "feat(cutscene-camera): CameraMode base + LockedMode geometry"
```

---

### Task 2: `ChaseMode` + `TargetMode`

**Files:**
- Modify: `engine/appc/camera_modes.py`
- Test: `tests/unit/test_camera_modes.py` (extend)

**Interfaces:**
- Consumes: `CameraMode`, `_apply_rot`, `_unit`, `_target_alive` from Task 1.
- Produces:
  - `class ChaseMode(CameraMode)`: reads `Target`; `__init__(self, reverse=False)`. Constants `CHASE_DIST_GU = 12.0`, `CHASE_UP_GU = 3.0`.
  - `class TargetMode(CameraMode)`: reads `Source` + `Target` (look from source to target).

- [ ] **Step 1: Write the failing test (append)**

```python
from engine.appc.camera_modes import ChaseMode, TargetMode, CHASE_DIST_GU


def test_chase_mode_sits_behind_target():
    t = _FakeTarget((0.0, 0.0, 0.0))           # identity rot: fwd = +Y (GetCol(1))
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    # Behind = -Y of forward, so eye.y is negative ~ -CHASE_DIST_GU; looks +Y.
    assert eye[1] < 0.0
    assert abs(eye[1] + CHASE_DIST_GU) < 1e-6
    assert fwd[1] > 0.9                         # looking toward the ship (+Y)


def test_reverse_chase_sits_in_front():
    t = _FakeTarget((0.0, 0.0, 0.0))
    m = ChaseMode(reverse=True)
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye[1] > 0.0                          # in front (+Y)
    assert fwd[1] < -0.9                          # looking back toward ship


def test_target_mode_looks_from_source_to_target():
    src = _FakeTarget((0.0, 0.0, 0.0))
    dst = _FakeTarget((0.0, 100.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye == (0.0, 0.0, 0.0)
    assert abs(fwd[1] - 1.0) < 1e-6              # +Y toward dst


def test_chase_invalid_without_target():
    assert not ChaseMode().IsValid()


def test_target_invalid_without_both():
    m = TargetMode()
    m.SetAttrIDObject("Source", _FakeTarget((0.0, 0.0, 0.0)))
    assert not m.IsValid()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_camera_modes.py -q`
Expected: FAIL — `ImportError: cannot import name 'ChaseMode'`.

- [ ] **Step 3: Add the implementation (append to `camera_modes.py`)**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_camera_modes.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/camera_modes.py tests/unit/test_camera_modes.py
git commit -m "feat(cutscene-camera): ChaseMode + TargetMode"
```

---

### Task 3: `CameraObjectClass` mode stack

**Files:**
- Modify: `engine/appc/bridge_set.py` (the `CameraObjectClass` class, currently ending at `GetWorldRotation` ~line 266)
- Test: `tests/unit/test_camera_mode_stack.py`

**Interfaces:**
- Consumes: `engine.appc.camera_modes.{LockedMode, ChaseMode, TargetMode}`.
- Produces, on `CameraObjectClass`:
  - `GetNamedCameraMode(name) -> CameraMode | None` (lazily built + cached; names: `"Locked"`, `"Chase"`, `"ReverseChase"`, `"Target"`; unknown ⇒ `None`).
  - `PushCameraMode(mode) -> None` (seeds `mode.set_initial_pose` from this camera's current world pose).
  - `PopCameraMode(mode=None) -> None`.
  - `GetCurrentCameraMode(arg=0) -> CameraMode | None` (top of stack).
  - `AddModeHierarchy(*a) -> None` (no-op; fallback tree out of scope).

These replace the `_LoudStub.__getattr__` no-ops, so `Camera.NewMode` (`sdk/Build/scripts/Camera.py:437`) pushes a live mode.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_camera_mode_stack.py
import App
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.camera_modes import LockedMode, ChaseMode, TargetMode
from engine.appc.math import TGPoint3


def _cam():
    return CameraObjectClass_Create(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")


def test_get_named_mode_builds_and_caches():
    c = _cam()
    m = c.GetNamedCameraMode("Locked")
    assert isinstance(m, LockedMode)
    assert c.GetNamedCameraMode("Locked") is m          # cached, same instance
    assert isinstance(c.GetNamedCameraMode("Chase"), ChaseMode)
    assert isinstance(c.GetNamedCameraMode("ReverseChase"), ChaseMode)
    assert isinstance(c.GetNamedCameraMode("Target"), TargetMode)


def test_get_named_mode_unknown_is_none():
    assert _cam().GetNamedCameraMode("Bogus") is None


def test_push_pop_current():
    c = _cam()
    assert c.GetCurrentCameraMode() is None
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m
    assert c.GetCurrentCameraMode(0) is m               # NewMode calls with arg 0
    c.PopCameraMode()
    assert c.GetCurrentCameraMode() is None


def test_push_seeds_initial_pose_from_camera():
    c = _cam()                                           # position (1,2,3)
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert m._cur is not None
    assert m._cur[0] == (1.0, 2.0, 3.0)                  # seeded eye = camera pos


def test_camera_new_mode_pushes_live_mode():
    """End-to-end through the SDK's Camera.NewMode."""
    import Camera
    c = _cam()
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    ok = Camera.NewMode(c, "Chase", 0, 1, [("Target", ship)])
    assert ok == 1
    assert isinstance(c.GetCurrentCameraMode(), ChaseMode)
    assert c.GetCurrentCameraMode().GetAttrIDObject("Target") is ship
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_camera_mode_stack.py -q`
Expected: FAIL — `GetNamedCameraMode` returns the `_LoudStub` no-op lambda result (`None`/non-mode), so `isinstance(... LockedMode)` fails / `NewMode` returns 0.

- [ ] **Step 3: Add the stack to `CameraObjectClass`**

Insert after `GetWorldRotation` (end of the class, before `def CameraObjectClass_CreateFromNiCamera`):

```python
    # ── Camera-mode stack ─────────────────────────────────────────────────────
    # Real replacement for the _LoudStub no-ops so the SDK's Camera.NewMode
    # (sdk/Build/scripts/Camera.py) can push live modes. The mode's Update()
    # then drives the rendered exterior view (host_loop._active_cutscene_camera).
    # AddModeHierarchy stays a no-op — the mode-fallback tree is out of v1 scope.

    _MODE_FACTORY = {
        "Locked": ("LockedMode", {}),
        "Chase": ("ChaseMode", {}),
        "ReverseChase": ("ChaseMode", {"reverse": True}),
        "Target": ("TargetMode", {}),
    }

    def GetNamedCameraMode(self, name, *args):
        if not hasattr(self, "_named_modes"):
            self._named_modes = {}
            self._mode_stack = []
        if name in self._named_modes:
            return self._named_modes[name]
        spec = self._MODE_FACTORY.get(name)
        if spec is None:
            return None
        from engine.appc import camera_modes
        cls = getattr(camera_modes, spec[0])
        mode = cls(**spec[1])
        self._named_modes[name] = mode
        return mode

    def _ensure_stack(self):
        if not hasattr(self, "_mode_stack"):
            self._named_modes = {}
            self._mode_stack = []
        return self._mode_stack

    def PushCameraMode(self, mode):
        stack = self._ensure_stack()
        R = self.GetWorldRotation()
        loc = self.GetWorldLocation()
        fwd = R.GetCol(1)
        up = R.GetCol(2)
        mode.set_initial_pose((loc.x, loc.y, loc.z),
                              (fwd.x, fwd.y, fwd.z), (up.x, up.y, up.z))
        stack.append(mode)

    def PopCameraMode(self, mode=None):
        stack = self._ensure_stack()
        if not stack:
            return None
        if mode is None:
            return stack.pop()
        # Named/object pop: remove the matching mode wherever it sits.
        for i in range(len(stack) - 1, -1, -1):
            if stack[i] is mode or (
                    hasattr(mode, "GetObjID") and stack[i].GetObjID() == mode.GetObjID()):
                return stack.pop(i)
        return None

    def GetCurrentCameraMode(self, *args):
        stack = self._ensure_stack()
        return stack[-1] if stack else None

    def AddModeHierarchy(self, *args):
        return None
```

Note: `__init__` is not changed — the stack is lazily created in `_ensure_stack`/`GetNamedCameraMode` so existing `CameraObjectClass(...)` construction sites are untouched.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_camera_mode_stack.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the cutscene + bridge regression**

Run: `uv run pytest tests/unit/test_cutscene_camera.py tests/unit/test_bridge_set.py tests/unit/test_bridge_set_stubs.py -q`
Expected: PASS (no regressions from adding real methods that shadow the `_LoudStub` fallthrough).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_camera_mode_stack.py
git commit -m "feat(cutscene-camera): real camera-mode stack on CameraObjectClass"
```

---

### Task 4: Host-loop render-path selection

**Files:**
- Modify: `engine/host_loop.py` — add `_active_cutscene_camera` near `_compute_camera` (~line 2214); add the selection branch in the exterior view path (~line 3422, right after `eye, target, up_vec = _compute_camera(...)` and before the `camera_shake.perturb` call).
- Test: `tests/host/test_cutscene_camera_selection.py`

**Interfaces:**
- Consumes: `App.g_kSetManager.GetRenderedSet()`, `SetClass.GetActiveCamera()`, `CameraObjectClass.GetCurrentCameraMode()`, `CameraMode.Update(dt)`/`IsValid()`.
- Produces: `_active_cutscene_camera(player) -> (camera, mode) | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/host/test_cutscene_camera_selection.py
import App
from engine.host_loop import _active_cutscene_camera
from engine.appc.bridge_set import BridgeSet_Create, CameraObjectClass_Create
from engine.appc.math import TGPoint3


def _space_set_with_cutscene_cam(name, target):
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    mode = cam.GetNamedCameraMode("Chase")
    mode.SetAttrIDObject("Target", target)
    cam.PushCameraMode(mode)
    App.g_kSetManager.MakeRenderedSet(name)
    return s, cam, mode


def test_active_cutscene_camera_found_when_rendered_set_has_live_mode():
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(10.0, 0.0, 0.0))
    s, cam, mode = _space_set_with_cutscene_cam("cc_sel_set", ship)
    got = _active_cutscene_camera(ship)
    assert got is not None
    assert got[0] is cam and got[1] is mode
    App.g_kSetManager.DeleteSet("cc_sel_set")


def test_none_when_no_mode_pushed():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "cc_none_set")
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    App.g_kSetManager.MakeRenderedSet("cc_none_set")
    assert _active_cutscene_camera(App.ShipClass_Create("Galaxy")) is None
    App.g_kSetManager.DeleteSet("cc_none_set")


def test_none_when_rendered_set_unset():
    App.g_kSetManager.MakeRenderedSet("__nonexistent__")
    assert _active_cutscene_camera(None) is None


def test_none_when_mode_target_dead():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "cc_dead_set")
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    mode = cam.GetNamedCameraMode("Chase")            # no Target set ⇒ invalid
    cam.PushCameraMode(mode)
    App.g_kSetManager.MakeRenderedSet("cc_dead_set")
    assert _active_cutscene_camera(None) is None
    App.g_kSetManager.DeleteSet("cc_dead_set")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/host/test_cutscene_camera_selection.py -q`
Expected: FAIL — `ImportError: cannot import name '_active_cutscene_camera'`.

- [ ] **Step 3: Add `_active_cutscene_camera` after `_compute_camera`**

Insert immediately after the `_compute_camera` function (after its `return director.compute(...)` line, ~2231):

```python
def _active_cutscene_camera(player):
    """If the rendered set has an active cutscene camera with a live mode,
    return (camera, mode); else None.

    Mission scripts do ChangeRenderedSet(space_set) + CutsceneCameraBegin +
    a camera-mode action (LockedView/ChaseCam/TargetWatch), which pushes a
    CameraMode onto the set's active camera. When that's present we drive the
    exterior view from the mode (see the exterior branch below). Otherwise we
    fall through to the player director, unchanged.

    Gated on a live IsValid() mode so plain comm 'maincamera's, mode-less
    cameras, and dead-target modes all return None and the director resumes.
    """
    import App as _App
    rendered = _App.g_kSetManager.GetRenderedSet()
    if rendered is None:
        return None
    get_active = getattr(rendered, "GetActiveCamera", None)
    cam = get_active() if callable(get_active) else None
    if cam is None:
        return None
    get_mode = getattr(cam, "GetCurrentCameraMode", None)
    mode = get_mode() if callable(get_mode) else None
    if mode is None or not mode.IsValid():
        return None
    return (cam, mode)
```

- [ ] **Step 4: Add the selection branch in the exterior view path**

Find (~3421-3424):

```python
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=_player_dt)
                # Camera shake — apply to the exterior view. The bridge
```

Insert the cutscene-camera override between the `_compute_camera` call and the `camera_shake.perturb` call:

```python
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=_player_dt)
                # In-space cutscene camera: if the rendered set has an active
                # cutscene camera with a live mode, drive the exterior view
                # from it instead of the player director (SDK CutsceneCamera*
                # + LockedView/ChaseCam/TargetWatch). Reverts automatically
                # when CutsceneCameraEnd removes the camera/mode.
                if not pause.is_open:
                    _cc = _active_cutscene_camera(player)
                    if _cc is not None:
                        eye, target, up_vec = _cc[1].Update(_player_dt)
                # Camera shake — apply to the exterior view. The bridge
```

(The existing `camera_shake.perturb(...)` line immediately below now perturbs the cutscene pose too — desired: shake still applies during space cutscenes.)

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/host/test_cutscene_camera_selection.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_cutscene_camera_selection.py
git commit -m "feat(cutscene-camera): drive exterior view from active cutscene camera mode"
```

---

### Task 5: Full-suite regression + live-verify handoff

**Files:** none (verification only).

- [ ] **Step 1: Run the memory-safe full suite**

Run: `scripts/run_tests.sh`
Expected: all pass (no regressions). If `run_tests.sh` is unavailable, run the affected trees: `uv run pytest tests/unit tests/host -q`.

- [ ] **Step 2: Confirm no rebuild needed**

These are pure-Python shim + host-loop changes. No `host_bindings.cc`, shaders, or `.so` touched. `build/dauntless` is unchanged.

- [ ] **Step 3: Live-verify handoff (Mark drives the GUI)**

Provide Mark these steps (no synthetic desktop interaction):
1. Launch `./build/dauntless --developer`.
2. Open the pause menu → "Load Mission…" → Maelstrom → Episode 7 → E7M2.
3. Play to the cutscene beat that runs `ChangeRenderedSet("Albirea3")` +
   `LockedView("Albirea3","player",0,190,10)`.
4. Confirm: the space view locks onto the player ship from the scripted spherical
   offset, glides in (sweep), holds during the dialogue, then reverts to the normal
   chase/tracking view after `CutsceneCameraEnd`.

Note the expected seam: the *bridge*-set cutscene beats earlier in E7M2
(`PlacementWatch("bridge", …)`) are out of v1 scope and behave as before — only
the `Albirea3` space shot is driven by this feature.

- [ ] **Step 4: If verified, finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to decide merge/PR.

---

## Self-Review

**Spec coverage:**
- LockedView mode → Task 1 (`LockedMode`). ✓
- Chase/Target modes → Task 2. ✓
- Sweep + snap (honor bSweep) → Task 1 base (`SWEEP_TAU_S`, `set_initial_pose`, `SnapToIdealPosition`); `NewMode` calls `SnapToIdealPosition` when `bSweep=0`. ✓
- Mode stack replacing `_LoudStub` (`GetNamedCameraMode`/Push/Pop/Current/`AddModeHierarchy`) → Task 3. ✓
- Render-path selection from rendered-set active camera → Task 4. ✓
- Clean revert on `CutsceneCameraEnd` → Task 4 (`GetActiveCamera`/mode goes away ⇒ `_active_cutscene_camera` returns None). ✓
- Error handling (dead/invalid target, degenerate geometry, missing attrs) → Task 1 `_target_alive` + `_unit` degenerate guard + `IsValid`; Task 4 gates on `IsValid()`. ✓
- Bridge view / pause / SPV untouched → Task 4 override is inside the `elif player is not None` exterior branch, guarded by `not pause.is_open`. ✓
- Model-up helpers exist (`TGPoint3_GetModelUp` etc., `engine/appc/math.py:303`) — used by unmodified Camera.py; no new shim needed. ✓
- E7M2 live verify → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `Update(dt)` returns `(eye, fwd, up)` 3-tuples in all of Tasks 1/2/4. `GetNamedCameraMode` names (`Locked`/`Chase`/`ReverseChase`/`Target`) match `_MODE_FACTORY` (Task 3) and the names `Camera.py` pushes (`Locked` via `LowLocked`, `Chase`/`ReverseChase`, `Target`). `GetObjID()` defined in Task 1, consumed by `Camera.NewMode` and Task 3 `PopCameraMode`. ✓

**Scope:** Single subsystem, one plan; warp-watch and bridge cutscene cameras explicitly deferred. ✓

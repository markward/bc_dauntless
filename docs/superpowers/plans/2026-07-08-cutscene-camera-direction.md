# Cutscene Camera-Direction System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make in-space cutscene camera actions (PlacementWatch / ZoomTarget) actually drive the rendered exterior view, so the E1M1 drydock undock shot shows the Enterprise pulling out of spacedock instead of staying on the bridge.

**Architecture:** Two new pure-Python `CameraMode` subclasses (`PlacementMode`, `ZoomTargetMode`) fill the SDK `Camera.NewMode` attr-setter contract; the `CameraObjectClass` mode factory and `CameraMode_Create` learn to build them. In host_loop, an active cutscene camera on the **explicitly-rendered set** overrides the bridge render pass and the main-scene camera pose — driven purely by `get_explicit_rendered_set()` + a live-valid-mode predicate, with the `bridge_flag()` source of truth never mutated (pull model).

**Tech Stack:** Python 3.11; pytest; SDK shim modules under `engine/appc/`; the C++ renderer host is untouched (no `dauntless` rebuild — all changes are Python).

**Spec:** `docs/superpowers/specs/2026-07-07-cutscene-camera-direction-design.md`

## Global Constraints

- **Game units (GU) throughout; column-vector right-handed rotations** — `R.GetCol(0)`=right, `GetCol(1)`=forward, `GetCol(2)`=up. Never `GetRow`. Never call a variable `*_m`/`*_mps`. (CLAUDE.md)
- **`bridge_flag()` / `GetRenderedSet()` are never written by this work.** `get_explicit_rendered_set()` is the render-target authority; `GetRenderedSet()` stays bridge-wins for SDK queries.
- **Production render path must stay byte-identical outside a scripted in-space cutscene** — when no live cutscene camera exists, `_active_cutscene_camera()` returns `None` and every render decision is unchanged.
- **Never orphan tests.** Any test that asserts old behavior of a changed function is updated in the same task. Run the relevant suite per task; run the full gate (`scripts/check_tests.sh`) before declaring done.
- **No `import X as Y` / f-string / `True`/`False`-literal constraints apply only to `tools/appc_logger.py`** (Python 1.5 snippet) — NOT to `engine/` code, which is normal Python 3.

---

## File Structure

- `engine/appc/camera_modes.py` — MODIFY. Add `PlacementMode`, `ZoomTargetMode`; add `_owner_camera` to base `CameraMode`; fix `_target_alive` (waypoint aliveness); make `CameraMode_Create` dispatch on `kind`.
- `engine/appc/bridge_set.py` — MODIFY. `CameraObjectClass._MODE_FACTORY` gains `Placement`/`ZoomTarget`; `GetNamedCameraMode` tags `_owner_camera`; `PopCameraMode` accepts a mode-name string.
- `engine/host_loop.py` — MODIFY. Add `_cutscene_pose` + `_apply_bridge_pass_state`; remove bridge-pass from `_apply_view_mode_side_effects`; wire the cutscene override into the render block.
- `tests/unit/test_camera_modes.py` — MODIFY. `_target_alive`, `PlacementMode`, `ZoomTargetMode`, `CameraMode_Create` dispatch.
- `tests/unit/test_camera_mode_stack.py` — MODIFY. Factory `Placement`/`ZoomTarget`, owner tagging, `PopCameraMode` string.
- `tests/host/test_view_mode.py` — MODIFY. Move bridge-pass assertions off `_apply_view_mode_side_effects`.
- `tests/host/test_cutscene_camera_override.py` — CREATE. End-to-end drydock choreography + bridge-pass override + `_cutscene_pose` regression + `bridge_flag()` untouched.

---

## Task 1: `_target_alive` — waypoints read as alive

**Problem:** `getattr(waypoint, "IsDying")` returns a truthy `_Stub` (TGObject's catch-all `__getattr__`), so the current `not (callable and is_dying())` reads a placement as **dead**, which would make every `PlacementMode`/`ZoomTargetMode` invalid forever.

**Files:**
- Modify: `engine/appc/camera_modes.py` (the module-level `_target_alive`, currently lines ~94-101)
- Test: `tests/unit/test_camera_modes.py`

**Interfaces:**
- Produces: `_target_alive(obj) -> bool` — `True` when `obj` is a live object OR a placement/waypoint whose `IsDying` resolves to a `_Stub`/non-bool; `False` for `None` or a real `IsDying()` returning truthy.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_camera_modes.py`:

```python
from engine.appc.camera_modes import _target_alive
from engine.appc.placement import Waypoint


class _Dying:
    def IsDying(self):
        return 1


class _NotDying:
    def IsDying(self):
        return 0


def test_target_alive_waypoint_reads_alive():
    # A Waypoint has no real IsDying; TGObject.__getattr__ hands back a truthy
    # _Stub, which must read as "not dying" (placements never die).
    assert _target_alive(Waypoint()) is True


def test_target_alive_none_is_dead():
    assert _target_alive(None) is False


def test_target_alive_real_is_dying():
    assert _target_alive(_Dying()) is False
    assert _target_alive(_NotDying()) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_camera_modes.py::test_target_alive_waypoint_reads_alive -v`
Expected: FAIL — a bare `Waypoint()` currently reads as dead (returns `False`).

- [ ] **Step 3: Write minimal implementation**

Replace the existing `_target_alive` in `engine/appc/camera_modes.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_camera_modes.py -v`
Expected: PASS (all existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/camera_modes.py tests/unit/test_camera_modes.py
git commit -m "fix(camera): _target_alive reads placement waypoints as alive

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `PlacementMode`

**Files:**
- Modify: `engine/appc/camera_modes.py` (append after `TargetMode`)
- Test: `tests/unit/test_camera_modes.py`

**Interfaces:**
- Consumes: `_target_alive`, `_unit`, `_apply_rot` (module locals); `CameraMode` base.
- Produces: `class PlacementMode(CameraMode)` — `_ideal()` returns `(eye, fwd, up)` in world GU. Attrs: `Source` (placement/object, required), `Target` (object or `None`), `TargetOffsetWorld` (`TGPoint3`, optional). Invalid if Source dead or Target-set-but-dead.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_camera_modes.py`:

```python
from engine.appc.camera_modes import PlacementMode


def test_placement_mode_eye_at_source_looks_at_target():
    src = _FakeTarget((-50.0, 0.0, 0.0))          # placement 50 GU to port
    tgt = _FakeTarget((0.0, 0.0, 0.0))            # ship at origin
    m = PlacementMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", tgt)
    eye, fwd, up = m.Update()                     # no dt => snap to ideal
    assert eye == (-50.0, 0.0, 0.0)
    assert abs(fwd[0] - 1.0) < 1e-6               # looks +X toward the ship
    assert up == (0.0, 0.0, 1.0)                  # source col2 (identity)


def test_placement_mode_target_none_looks_along_source_forward():
    src = _FakeTarget((-50.0, 0.0, 0.0))
    m = PlacementMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", None)
    eye, fwd, up = m.Update()
    assert eye == (-50.0, 0.0, 0.0)
    assert fwd == (0.0, 1.0, 0.0)                 # source col1 (identity forward)


def test_placement_mode_target_offset_world_shifts_lookat():
    src = _FakeTarget((0.0, -50.0, 0.0))          # 50 GU behind (model -Y)
    tgt = _FakeTarget((0.0, 0.0, 0.0))
    m = PlacementMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", tgt)
    m.SetAttrPoint("TargetOffsetWorld", TGPoint3(0.0, 0.0, 20.0))  # look 20 GU up
    eye, fwd, up = m.Update()
    # look-at = (0,0,20) from (0,-50,0) => mostly +Y, some +Z.
    assert fwd[1] > 0.0 and fwd[2] > 0.0


def test_placement_mode_invalid_without_source():
    m = PlacementMode()
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 0.0, 0.0)))
    assert not m.IsValid()


def test_placement_mode_invalid_when_target_dead():
    m = PlacementMode()
    m.SetAttrIDObject("Source", _FakeTarget((-50.0, 0.0, 0.0)))
    m.SetAttrIDObject("Target", _Dying())
    assert not m.IsValid()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_camera_modes.py::test_placement_mode_eye_at_source_looks_at_target -v`
Expected: FAIL — `ImportError: cannot import name 'PlacementMode'`.

- [ ] **Step 3: Write minimal implementation**

Append to `engine/appc/camera_modes.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_camera_modes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/camera_modes.py tests/unit/test_camera_modes.py
git commit -m "feat(camera): PlacementMode for PlacementWatch cutscene shots

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `ZoomTargetMode` + base `_owner_camera`

**Files:**
- Modify: `engine/appc/camera_modes.py` (base `CameraMode.__init__`; append `ZoomTargetMode`)
- Test: `tests/unit/test_camera_modes.py`

**Interfaces:**
- Consumes: `_target_alive`, `_unit`, `CameraMode`.
- Produces:
  - `CameraMode.__init__` sets `self._owner_camera = None` (the camera that built the mode; set by `GetNamedCameraMode` in Task 4).
  - `class ZoomTargetMode(CameraMode)` — `_ideal()` returns `(eye, fwd, up)`. Attrs: `Target` (required), `Source` (optional). `Source` unset/`None` → eye/rot from `self._owner_camera` (`GetWorldLocation`/`GetWorldRotation`). Invalid if Target dead, Source-set-but-dead, or the owner-camera fallback can't resolve a pose.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_camera_modes.py`:

```python
from engine.appc.camera_modes import ZoomTargetMode


def test_zoom_target_mode_eye_at_source_looks_at_target():
    src = _FakeTarget((5.0, 0.0, 0.0))
    tgt = _FakeTarget((5.0, 10.0, 0.0))
    m = ZoomTargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", tgt)
    eye, fwd, up = m.Update()
    assert eye == (5.0, 0.0, 0.0)
    assert abs(fwd[1] - 1.0) < 1e-6                # looks +Y toward the target


def test_zoom_target_mode_source_none_uses_owner_camera():
    tgt = _FakeTarget((0.0, 100.0, 0.0))
    m = ZoomTargetMode()
    m._owner_camera = _FakeTarget((0.0, 0.0, 0.0))  # camera at origin
    m.SetAttrIDObject("Target", tgt)
    # Source left unset => falls back to the owning camera's pose.
    eye, fwd, up = m.Update()
    assert eye == (0.0, 0.0, 0.0)
    assert abs(fwd[1] - 1.0) < 1e-6


def test_zoom_target_mode_invalid_without_source_or_owner():
    m = ZoomTargetMode()
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 10.0, 0.0)))
    assert not m.IsValid()                          # no Source, no owner camera


def test_zoom_target_mode_invalid_when_target_dead():
    m = ZoomTargetMode()
    m.SetAttrIDObject("Source", _FakeTarget((0.0, 0.0, 0.0)))
    m.SetAttrIDObject("Target", _Dying())
    assert not m.IsValid()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_camera_modes.py::test_zoom_target_mode_eye_at_source_looks_at_target -v`
Expected: FAIL — `ImportError: cannot import name 'ZoomTargetMode'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/camera_modes.py`, in `CameraMode.__init__` (after `self._snap = False`) add:

```python
        # The camera this mode was built for (CameraObjectClass.GetNamedCameraMode
        # tags it). BC modes are owned by their camera; ZoomTargetMode uses it as
        # the eye when no Source object was wired.
        self._owner_camera = None
```

Append after `PlacementMode`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_camera_modes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/camera_modes.py tests/unit/test_camera_modes.py
git commit -m "feat(camera): ZoomTargetMode + CameraMode._owner_camera

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Mode factory wiring — `_MODE_FACTORY`, owner tagging, string `PopCameraMode`

**Files:**
- Modify: `engine/appc/bridge_set.py` (`CameraObjectClass._MODE_FACTORY`, `GetNamedCameraMode`, `PopCameraMode`)
- Test: `tests/unit/test_camera_mode_stack.py`

**Interfaces:**
- Consumes: `PlacementMode`, `ZoomTargetMode` (Task 2/3).
- Produces:
  - `GetNamedCameraMode("Placement")` → `PlacementMode`; `GetNamedCameraMode("ZoomTarget")` → `ZoomTargetMode`; every built mode has `._owner_camera is <the camera>`.
  - `PopCameraMode(name_string)` pops the top-most stack entry that is the camera's named mode of that name; `PopCameraMode(mode_obj)` and `PopCameraMode(None)` unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_camera_mode_stack.py`:

```python
from engine.appc.camera_modes import PlacementMode, ZoomTargetMode


def test_factory_builds_placement_and_zoomtarget():
    c = _cam()
    assert isinstance(c.GetNamedCameraMode("Placement"), PlacementMode)
    assert isinstance(c.GetNamedCameraMode("ZoomTarget"), ZoomTargetMode)


def test_get_named_mode_tags_owner_camera():
    c = _cam()
    m = c.GetNamedCameraMode("Placement")
    assert m._owner_camera is c


def test_pop_camera_mode_by_name_string():
    c = _cam()
    m = c.GetNamedCameraMode("Placement")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m
    popped = c.PopCameraMode("Placement")            # Camera.LowPop passes a str
    assert popped is m
    assert c.GetCurrentCameraMode() is None


def test_pop_camera_mode_unknown_name_is_none():
    c = _cam()
    c.PushCameraMode(c.GetNamedCameraMode("Placement"))
    assert c.PopCameraMode("NeverPushed") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_camera_mode_stack.py::test_factory_builds_placement_and_zoomtarget -v`
Expected: FAIL — `GetNamedCameraMode("Placement")` returns `None` (no factory entry).

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/bridge_set.py`, extend `_MODE_FACTORY`:

```python
    _MODE_FACTORY = {
        "Locked": ("LockedMode", {}),
        "Chase": ("ChaseMode", {}),
        "ReverseChase": ("ChaseMode", {"reverse": True}),
        "Target": ("TargetMode", {}),
        "Placement": ("PlacementMode", {}),
        "ZoomTarget": ("ZoomTargetMode", {}),
    }
```

In `GetNamedCameraMode`, tag the owner right after the mode is built:

```python
        cls = getattr(camera_modes, spec[0])
        mode = cls(**spec[1])
        mode._owner_camera = self
        self._named_modes[name] = mode
        return mode
```

In `PopCameraMode`, handle a mode-name string (insert the `str` branch after the `if mode is None:` pop-top branch, before the object-identity loop):

```python
    def PopCameraMode(self, mode=None):
        stack = self._ensure_stack()
        if not stack:
            return None
        if mode is None:
            return stack.pop()
        if isinstance(mode, str):
            # Camera.LowPop passes a mode-NAME string. Resolve it to the
            # camera's named mode and pop that instance wherever it sits.
            named = self._named_modes.get(mode) if "_named_modes" in self.__dict__ else None
            if named is None:
                return None
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] is named:
                    return stack.pop(i)
            return None
        # Named/object pop: remove the matching mode wherever it sits.
        for i in range(len(stack) - 1, -1, -1):
            if stack[i] is mode or (
                    hasattr(mode, "GetObjID") and stack[i].GetObjID() == mode.GetObjID()):
                return stack.pop(i)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_camera_mode_stack.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_camera_mode_stack.py
git commit -m "feat(camera): factory builds Placement/ZoomTarget + owner tag + str PopCameraMode

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `CameraMode_Create` dispatches on `kind` (Gap 1)

**Problem:** `CameraMode_Create` ignores its `kind` arg and always returns `PlaceByDirectionMode`. The bridge-captain path relies on `PlaceByDirection` → `PlaceByDirectionMode`, but the SDK also builds other kinds through this shim (`CameraModes.*`, `MakePlayerCamera`). Dispatch on `kind`; keep `PlaceByDirection` + unknown kinds mapping to `PlaceByDirectionMode` so the bridge path is unchanged.

**Files:**
- Modify: `engine/appc/camera_modes.py` (`CameraMode_Create`)
- Test: `tests/unit/test_camera_modes.py`

**Interfaces:**
- Produces: `CameraMode_Create(kind, pCamera=None)` → an instance of the class matching `kind` (`Locked`/`Chase`/`ReverseChase`/`Target`/`Placement`/`ZoomTarget`), else `PlaceByDirectionMode(kind)`. The returned mode has `._owner_camera = pCamera`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_camera_modes.py`:

```python
from engine.appc.camera_modes import (
    CameraMode_Create, ChaseMode, TargetMode, PlaceByDirectionMode,
)


def test_camera_mode_create_dispatches_on_kind():
    from engine.appc.camera_modes import LockedMode
    assert isinstance(CameraMode_Create("Locked"), LockedMode)
    assert isinstance(CameraMode_Create("Chase"), ChaseMode)
    assert isinstance(CameraMode_Create("Target"), TargetMode)
    assert isinstance(CameraMode_Create("Placement"), PlacementMode)
    assert isinstance(CameraMode_Create("ZoomTarget"), ZoomTargetMode)


def test_camera_mode_create_reverse_chase_is_reversed():
    m = CameraMode_Create("ReverseChase")
    assert isinstance(m, ChaseMode)
    assert m._reverse is True


def test_camera_mode_create_default_is_place_by_direction():
    assert isinstance(CameraMode_Create("PlaceByDirection"), PlaceByDirectionMode)
    assert isinstance(CameraMode_Create("Bogus"), PlaceByDirectionMode)


def test_camera_mode_create_tags_owner_camera():
    sentinel = object()
    assert CameraMode_Create("Chase", sentinel)._owner_camera is sentinel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_camera_modes.py::test_camera_mode_create_dispatches_on_kind -v`
Expected: FAIL — `CameraMode_Create("Locked")` returns a `PlaceByDirectionMode`.

- [ ] **Step 3: Write minimal implementation**

Replace `CameraMode_Create` in `engine/appc/camera_modes.py` (keep the existing docstring's first paragraph; the body changes):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_camera_modes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/camera_modes.py tests/unit/test_camera_modes.py
git commit -m "fix(camera): CameraMode_Create dispatches on kind (Gap 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: host_loop render override + drydock host test

**This task has three code edits and two test edits.** Do them in order; run tests only at the end of the step group as noted.

**Files:**
- Modify: `engine/host_loop.py` (add `_cutscene_pose`, `_apply_bridge_pass_state`; remove bridge-pass from `_apply_view_mode_side_effects`; wire the override into the render block)
- Modify: `tests/host/test_view_mode.py` (move bridge-pass assertions)
- Create: `tests/host/test_cutscene_camera_override.py`

**Interfaces:**
- Consumes: `_active_cutscene_camera()` (existing); `CameraMode.Update` returns `(eye, fwd_dir, up)`; `_apply_view_mode_side_effects(view_mode, h)` (existing, minus bridge-pass).
- Produces:
  - `_cutscene_pose(mode, dt) -> (eye, look_at_point, up)` — adds `eye` to the forward direction so the main camera consumes a look-at POINT.
  - `_apply_bridge_pass_state(effective_bridge, h, latch_owner) -> None` — idempotent driver of `h.bridge_pass_set_enabled`, latched on `latch_owner._last_synced_bridge_pass`; no-op when `h is None`.

### Code edits

- [ ] **Step 1: Add the two helpers**

In `engine/host_loop.py`, immediately after `_active_cutscene_camera()` (ends ~line 3881), add:

```python
def _cutscene_pose(mode, dt):
    """Convert a cutscene CameraMode's Update() result — (eye, forward_dir, up)
    in world game units — into the (eye, look_at_point, up) triple the main
    scene camera consumes. Update returns a forward DIRECTION; r.set_camera
    expects a look-at POINT, so add eye. (Fixes the direction-as-point seam the
    merged in-space controller (365207f7) shipped with.)"""
    eye, fwd, up = mode.Update(dt)
    look_at = (eye[0] + fwd[0], eye[1] + fwd[1], eye[2] + fwd[2])
    return (eye, look_at, up)
```

Immediately after `_apply_view_mode_side_effects` (ends ~line 1794, at `view_mode._last_synced_is_bridge = target`), add:

```python
def _apply_bridge_pass_state(effective_bridge, h, latch_owner):
    """Drive bridge_pass_set_enabled from the EFFECTIVE bridge-render state
    (view_mode.is_bridge AND no in-space cutscene camera owns the frame).
    Idempotent/latched on latch_owner._last_synced_bridge_pass.

    Split out of _apply_view_mode_side_effects so the bridge render PASS can
    turn off for an in-space cutscene while cursor lock / engine-rumble mute /
    bridge ambient stay keyed on the raw bridge flag — the player is still on
    the bridge in state; only what they SEE changes."""
    if h is None:
        return
    last = getattr(latch_owner, "_last_synced_bridge_pass", None)
    if last == effective_bridge:
        return
    h.bridge_pass_set_enabled(effective_bridge)
    latch_owner._last_synced_bridge_pass = effective_bridge
```

- [ ] **Step 2: Remove bridge-pass from `_apply_view_mode_side_effects`**

In `engine/host_loop.py`, delete the single line `h.bridge_pass_set_enabled(target)` (currently line ~1780) from `_apply_view_mode_side_effects`. Leave `set_cursor_locked`, `_rumble_set_muted`, `_bridge_ambient_set`, `camera_shake.reset`, `hit_feedback.reset_audio_throttle`, and the latch write intact. Update the function's docstring first line to note bridge-pass moved out:

```python
    """Mirror the view-mode flag into renderer-side state (cursor lock,
    engine-rumble mute, bridge ambient). Idempotent — only fires when the mode
    has changed since the last call. The bridge render PASS is driven
    separately by _apply_bridge_pass_state (it also folds in the cutscene
    override). `h` is the bindings module (or fake) exposing set_cursor_locked.
    """
```

- [ ] **Step 3: Wire the override into the render block**

In `engine/host_loop.py`, find the render camera block. Immediately **before** `if fixed_camera:` (currently line ~5929, after the `# Camera: orbit + zoom around the player ship (or origin fallback).` comment), insert (12-space indent, matching `if fixed_camera:`):

```python
                # In-space cutscene camera on the EXPLICITLY-rendered set: when a
                # live valid mode owns the frame, the bridge render pass turns
                # off and the main scene shows the exterior cutscene — even while
                # the bridge flag is set (the player is on the bridge in state
                # but sees the exterior; get_explicit_rendered_set() is the
                # render-target authority; bridge_flag()/GetRenderedSet() are
                # untouched). Reverts when CutsceneCameraEnd pops the mode.
                _cc = None if pause.is_open else _active_cutscene_camera()
                _apply_bridge_pass_state(
                    view_mode.is_bridge and _cc is None, _h, view_mode)
```

Then, inside the `elif player is not None:` branch, replace the existing gated cutscene block (currently lines ~5938-5946):

```python
                # In-space cutscene camera: if the rendered set has an active
                # cutscene camera with a live mode, drive the exterior view
                # from it instead of the player director (SDK CutsceneCamera*
                # + LockedView/ChaseCam/TargetWatch). Reverts automatically
                # when CutsceneCameraEnd removes the camera/mode.
                if not pause.is_open and not view_mode.is_bridge:
                    _cc = _active_cutscene_camera()
                    if _cc is not None:
                        eye, target, up_vec = _cc[1].Update(_player_dt)
```

with (16-space indent, using the `_cc` already computed above):

```python
                # Cutscene camera (computed above) drives the main-scene pose,
                # converting the mode's forward DIRECTION to a look-at POINT.
                if _cc is not None:
                    eye, target, up_vec = _cutscene_pose(_cc[1], _player_dt)
```

- [ ] **Step 4: Update `tests/host/test_view_mode.py`**

Replace `test_toggle_to_bridge_enables_pass_and_locks_cursor` and `test_toggle_to_exterior_disables_pass_and_releases_cursor` (lines ~345-366) with cursor-only assertions plus a dedicated bridge-pass-driver test:

```python
def test_toggle_to_bridge_locks_cursor():
    """Toggling exterior → bridge fires set_cursor_locked(True) exactly once.
    (The bridge render PASS is driven separately by _apply_bridge_pass_state.)"""
    from engine.host_loop import _apply_view_mode_side_effects
    vm = _exterior_vm()
    rr = _RecordingRenderer()
    vm.toggle()  # exterior → bridge
    _apply_view_mode_side_effects(vm, rr)
    assert rr.cursor_lock_calls == [True]
    assert rr.bridge_pass_calls == []               # applier no longer touches it


def test_toggle_to_exterior_releases_cursor():
    from engine.host_loop import _apply_view_mode_side_effects
    vm = _exterior_vm()
    vm.toggle()  # bridge
    rr = _RecordingRenderer()
    _apply_view_mode_side_effects(vm, rr)  # one true call
    vm.toggle()  # back to exterior
    _apply_view_mode_side_effects(vm, rr)
    assert rr.cursor_lock_calls == [True, False]
    assert rr.bridge_pass_calls == []


def test_apply_bridge_pass_state_drives_and_latches():
    """_apply_bridge_pass_state fires bridge_pass_set_enabled on change and is
    idempotent; effective_bridge=False (cutscene owns the frame) turns it off."""
    from engine.host_loop import _apply_bridge_pass_state

    class _Latch:
        pass

    rr = _RecordingRenderer()
    latch = _Latch()
    _apply_bridge_pass_state(True, rr, latch)       # bridge visible
    _apply_bridge_pass_state(True, rr, latch)       # no change → no re-fire
    _apply_bridge_pass_state(False, rr, latch)      # cutscene → pass off
    assert rr.bridge_pass_calls == [True, False]
```

Also update `test_apply_view_mode_side_effects_idempotent_within_a_mode` (lines ~369-383): drop the two `bridge_pass_calls` assertions (the applier no longer calls it), keeping the cursor assertion:

```python
def test_apply_view_mode_side_effects_idempotent_within_a_mode():
    """Calling _apply_view_mode_side_effects twice without toggling must not
    re-fire the cursor lock (it has visible side-effects we don't want to spam)."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _apply_view_mode_side_effects
    top_window.reset_for_tests()
    vm = _ViewModeController()
    rr = _RecordingRenderer()
    _apply_view_mode_side_effects(vm, rr)
    _apply_view_mode_side_effects(vm, rr)  # no toggle in between
    assert len(rr.cursor_lock_calls) <= 1
```

- [ ] **Step 5: Create the drydock host test**

Create `tests/host/test_cutscene_camera_override.py`:

```python
# tests/host/test_cutscene_camera_override.py
"""End-to-end: an in-space cutscene camera on the explicitly-rendered set
overrides the bridge render pass and drives the main-scene camera, without ever
mutating the bridge flag. Models the E1M1 drydock undock shot."""
import App
import Camera
from engine.appc.math import TGPoint3
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.top_window import bridge_flag
from engine.host_loop import (
    _active_cutscene_camera, _cutscene_pose, _apply_bridge_pass_state,
)


class _FakeBindings:
    def __init__(self):
        self.bridge_pass_calls = []

    def bridge_pass_set_enabled(self, enabled):
        self.bridge_pass_calls.append(enabled)


class _Latch:
    pass


def _drydock_scene():
    """DryDock space set: player ship at origin, "Cam Pos 1" placement 50 GU to
    port, and a CutsceneCam that is the set's active camera (CutsceneCameraBegin)."""
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "DryDock")
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    s.AddObjectToSet(ship, "player")
    wp = App.Waypoint_Create("Cam Pos 1", "DryDock", None)
    wp.SetTranslate(TGPoint3(-50.0, 0.0, 0.0))
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    App.g_kSetManager.MakeRenderedSet("DryDock")
    return s, cam, ship, wp


def test_placement_watch_produces_live_cutscene_camera_and_pose():
    before = bridge_flag()
    s, cam, ship, wp = _drydock_scene()
    # PlacementWatch("DryDock", "player", "Cam Pos 1") routes here (bSweep=0).
    Camera.Placement("Cam Pos 1", "player", "DryDock", 0, 1)
    cc = _active_cutscene_camera()
    assert cc is not None
    assert cc[0] is cam
    eye, look_at, up = _cutscene_pose(cc[1], 0.0)
    assert abs(eye[0] - (-50.0)) < 1e-6             # eye sits at the placement
    assert look_at[0] > eye[0]                      # looks +X toward the ship
    assert bridge_flag() == before                  # flag NEVER mutated
    App.g_kSetManager.DeleteSet("DryDock")


def test_bridge_pass_off_while_cutscene_active_then_on_after_end():
    s, cam, ship, wp = _drydock_scene()
    Camera.Placement("Cam Pos 1", "player", "DryDock", 0, 1)
    h = _FakeBindings()
    latch = _Latch()

    # During the shot: player is on the bridge in state (is_bridge=True) but a
    # cutscene camera owns the frame → effective_bridge False → pass OFF.
    cc = _active_cutscene_camera()
    _apply_bridge_pass_state(True and cc is None, h, latch)
    assert h.bridge_pass_calls == [False]

    # CutsceneCameraEnd: delete the cutscene camera → no live mode → pass ON.
    s.DeleteCameraFromSet("CutsceneCam")
    cc_after = _active_cutscene_camera()
    assert cc_after is None
    _apply_bridge_pass_state(True and cc_after is None, h, latch)
    assert h.bridge_pass_calls == [False, True]
    App.g_kSetManager.DeleteSet("DryDock")


def test_cutscene_pose_returns_lookat_point_not_direction():
    """Regression for the merged 365207f7 seam: mode.Update returns a forward
    DIRECTION; _cutscene_pose must return a look-at POINT (eye+fwd), else a
    far-from-origin chase looks at ~origin."""
    from engine.appc.camera_modes import ChaseMode
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(1000.0, 0.0, 0.0))
    m = ChaseMode()
    m.SetAttrIDObject("Target", ship)
    eye, look_at, up = _cutscene_pose(m, None)
    assert look_at[0] > 900.0                        # look-at is at the ship, not ~origin
```

- [ ] **Step 6: Run the touched tests**

Run:
```bash
uv run pytest tests/host/test_cutscene_camera_override.py tests/host/test_view_mode.py tests/host/test_cutscene_camera_selection.py -v
```
Expected: PASS (all). If `test_placement_watch_...` reports `cc is None`, the factory entry from Task 4 is missing — do not patch host_loop; fix the factory.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py tests/host/test_cutscene_camera_override.py
git commit -m "feat(camera): cutscene camera overrides bridge render on explicit rendered set

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (not a code task — run before declaring done)

- [ ] **Full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. It builds C++, runs pytest + ctest, and diffs failures against `tests/known_failures.txt`. If it names any failure not in that ledger, that failure is a regression this branch introduced — fix it (do not add to the ledger). No C++ changed here, so the ledger should be unaffected.

- [ ] **Live-verify the drydock shot**

Launch the game, start E1M1, and play through (or skip to) the "leaving drydock" undock beat (`E1M1.py:2524-2548`). Confirm:
1. The view switches from the bridge to the **exterior**, showing the Enterprise pulling out of spacedock from the "Cam Pos 1" placement.
2. Picard's "leaving drydock" VO plays (lip-sync runs invisibly on the bridge).
3. The tactical HUD / target reticle are **not** shown during the shot.
4. When `CutsceneCameraEnd` + `ChangeRenderedSet("bridge")` fire, the view returns to the bridge cleanly.
Per memory `no-desktop-interaction`: do not synthetic-click or full-screen-capture the live workstation — observe only.

---

## Self-review notes (author)

- **Spec coverage:** §1 modes → Tasks 2/3; §2 factory/owner/PopCameraMode → Task 4; §3 CameraMode_Create → Task 5; §4 render override (predicate, `_cutscene_pose`, `effective_bridge`, unchanged flag/audio/sim) → Task 6; `_target_alive` root cause 3 → Task 1; `Update` seam root cause 4 → Task 6 (`_cutscene_pose` + regression test); §5 testing → per-task tests + final gate + live-verify. ViewscreenZoomTarget is explicitly out of scope (follow-up spec).
- **Type consistency:** `_cutscene_pose` (host_loop) vs `mode.Update` (returns `(eye, fwd, up)`) — helper adds eye once, at the single consumption site. `_apply_bridge_pass_state(effective_bridge, h, latch_owner)` signature used identically in Task 6 code and tests. Factory keys `"Placement"`/`"ZoomTarget"` match `Camera.py`'s `NewMode` mode names.
- **No placeholders:** every code step shows complete code; every test step shows the assertions; the RED baseline for Task 6 was verified manually (`NewMode("Placement")` returns 0 today).

# Bridge Camera Walk-On Cutscene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When mission E1M1 loads, the bridge camera glides faithfully from the turbolift to the captain's chair along the baked NIF keyframes and the L1 lift door opens — replacing the `AttributeError: 'NoneType' object has no attribute 'UseAnimationPosition'` crash with the real cutscene.

**Architecture:** Native parses the camera-path NIF keyframes (expose the existing `assets::load_animation_clips` to Python); Python samples them (LERP/SLERP) and drives `_BridgeCamera` through a new `BridgeCutsceneController` that bridges the headless SDK action layer and the host/renderer. The camera move and the lift-door open are both `TGAnimAction(target.GetAnimNode(), clipName)`; the door animation is already baked into `DBridge.nif`'s `animations[0]` and plays via the existing `set_instance_animation`.

**Tech Stack:** C++17 / pybind11 (`native/src/host/host_bindings.cc`), Python 3 (engine/), pytest, CMake.

## Global Constraints

- One build tree at `<project-root>/build/`. Binary `build/dauntless`, module `build/python/_open_stbc_host.cpython-*.so`. Never build from inside `native/`.
- `host_bindings.cc` is compiled into BOTH `build/dauntless` and the `_dauntless_host` module — any change there requires a full `dauntless` rebuild (`cmake --build build -j`), not just the module.
- Python is reached via `import _dauntless_host as _h`, wrapped in `engine/renderer.py` (imported elsewhere as `r`). Add new bindings to the wrapper; callers use the wrapper, not `_h` directly.
- Rotation/þ math convention is column-vector (`v_world = R · v_body`); see CLAUDE.md. Quaternions serialized as `(x, y, z, w)`.
- Tests: unit in `tests/unit/`, integration (needs built module / game assets) in `tests/integration/`. Run one test: `uv run pytest <path>::<name> -v`. SDK importable in tests via `conftest._SDKFinder`.
- Game assets live under `game/` (gitignored); `data/...`-relative NIF paths resolve against the game working dir, same as existing model loads.

---

### Task 1: Expose `load_animation_clips` to Python

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add binding near the other `m.def(...)` animation bindings, ~line 684)
- Modify: `engine/renderer.py` (add wrapper near `set_instance_animation`, ~line 304)
- Test: `tests/integration/test_camera_path_clip.py`

**Interfaces:**
- Produces: `engine.renderer.load_animation_clips(path: str) -> list[dict]` where each clip = `{"name": str, "duration": float, "tracks": list[dict]}` and each track = `{"node": str, "translation": list[tuple[float,float,float,float]], "rotation": list[tuple[float,float,float,float,float]]}`. Translation tuples are `(time, x, y, z)`; rotation tuples are `(time, x, y, z, w)`.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_camera_path_clip.py
"""Native load_animation_clips must parse the bridge camera-path NIF.

Requires the built _dauntless_host module and the game install. Skips
cleanly when either is absent (CI without assets)."""
import os
import pytest

renderer = pytest.importorskip("engine.renderer")

CAMERA_NIF = "data/animations/db_camera_walk_capt.nif"


@pytest.mark.skipif(
    not os.path.exists("game/data/animations/DB_Camera_Walk_Capt.NIF"),
    reason="game install not present",
)
def test_camera_path_clip_has_motion():
    clips = renderer.load_animation_clips(CAMERA_NIF)
    assert len(clips) >= 1
    clip = clips[0]
    assert clip["duration"] > 0.0
    # At least one track must carry both translation and rotation keys —
    # the moving camera node.
    moving = [t for t in clip["tracks"]
              if t["translation"] and t["rotation"]]
    assert moving, "no track with translation+rotation keys"
    # Key tuples have the documented arity.
    assert len(moving[0]["translation"][0]) == 4   # (t, x, y, z)
    assert len(moving[0]["rotation"][0]) == 5       # (t, x, y, z, w)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_camera_path_clip.py -v`
Expected: FAIL — `AttributeError: module 'engine.renderer' has no attribute 'load_animation_clips'` (or the binding is missing).

- [ ] **Step 3: Add the native binding**

In `native/src/host/host_bindings.cc`, after the `set_instance_animation` binding block, add:

```cpp
    m.def("load_animation_clips",
          [](const std::string& path) {
              py::list clips_out;
              for (const auto& clip : assets::load_animation_clips(path)) {
                  py::dict d;
                  d["name"] = clip.name;
                  d["duration"] = clip.duration_seconds;
                  py::list tracks_out;
                  for (const auto& tr : clip.tracks) {
                      py::dict td;
                      td["node"] = tr.target_node_name;
                      py::list tl;
                      for (const auto& k : tr.translation)
                          tl.append(py::make_tuple(k.time, k.value.x,
                                                   k.value.y, k.value.z));
                      td["translation"] = tl;
                      py::list rl;
                      for (const auto& k : tr.rotation)
                          rl.append(py::make_tuple(k.time, k.value.x,
                                                   k.value.y, k.value.z,
                                                   k.value.w));
                      td["rotation"] = rl;
                      tracks_out.append(td);
                  }
                  d["tracks"] = tracks_out;
                  clips_out.append(d);
              }
              return clips_out;
          },
          py::arg("path"),
          "Parse a NIF's keyframe controllers into animation clips: "
          "[{name, duration, tracks:[{node, translation:[(t,x,y,z)], "
          "rotation:[(t,x,y,z,w)]}]}]. Quaternions are (x,y,z,w).");
```

`assets::load_animation_clips` is declared in `assets/animation.h`, already transitively included via `<renderer/pose_sampler.h>` at the top of the file. If the build complains it is not declared, add `#include <assets/animation.h>` near the other `assets/` includes.

- [ ] **Step 4: Add the Python wrapper**

In `engine/renderer.py`, after the `set_instance_animation` function:

```python
def load_animation_clips(path: str) -> list:
    """Parse a NIF's keyframe controllers into animation clips.

    Returns [{"name": str, "duration": float, "tracks": [...]}] where each
    track is {"node": str, "translation": [(t,x,y,z), ...],
    "rotation": [(t,x,y,z,w), ...]}. Used to drive the bridge camera
    walk-on cutscene (see engine/bridge_cutscene.py)."""
    return _h.load_animation_clips(path)
```

- [ ] **Step 5: Rebuild the native binary + module**

Run: `cmake --build build -j`
Expected: build succeeds; `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` updated.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_camera_path_clip.py -v`
Expected: PASS (or SKIP if the game install is absent — run locally where `game/` exists).

- [ ] **Step 7: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/integration/test_camera_path_clip.py
git commit -m "feat(spv): expose load_animation_clips to Python for camera-path sampling"
```

---

### Task 2: Recording `TGAnimNode`

**Files:**
- Create: `engine/appc/anim_node.py`
- Test: `tests/unit/test_anim_node.py`

**Interfaces:**
- Produces: `engine.appc.anim_node.TGAnimNode(owner=None, kind="object")`. Attributes: `owner`, `kind`, `position_clip` (str | None), `last_animation` (str | None). Methods: `UseAnimationPosition(name)`, `UseAnimation(name, *a)`, `SetExclusiveAnimation(name, *a)`, `SetNonExclusiveAnimation(name, *a)`, `StopNonExclusiveAnimation(*a)`, `SetExclusiveAnimationUseDefault(*a)`, `Stop(*a)`, `Copy(*a) -> self`, `IsAnimate() -> int`, `SetBlendTime(t)`, `GetBlendTime() -> float`, `SetRootNode(n)`, `GetRootNode() -> self`, `FindNode(name) -> self`. Truthy via `__bool__`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_anim_node.py
from engine.appc.anim_node import TGAnimNode


def test_records_use_animation_position():
    node = TGAnimNode(owner="cam", kind="camera")
    assert node.position_clip is None
    node.UseAnimationPosition("WalkCameraToCaptD")
    assert node.position_clip == "WalkCameraToCaptD"
    assert node.owner == "cam"
    assert node.kind == "camera"


def test_is_truthy_and_chainable():
    node = TGAnimNode()
    assert node                       # truthy guard (if pAnimNode:)
    assert node.Copy() is node
    assert node.GetRootNode() is node
    assert node.FindNode("x") is node


def test_records_animations_and_blend_time():
    node = TGAnimNode()
    node.UseAnimation("twitch")
    assert node.last_animation == "twitch"
    node.SetExclusiveAnimation("standing")
    assert node.last_animation == "standing"
    node.SetBlendTime(0.25)
    assert node.GetBlendTime() == 0.25
    # No-op surface must not raise.
    node.StopNonExclusiveAnimation()
    node.SetExclusiveAnimationUseDefault()
    node.Stop()
    assert node.IsAnimate() == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_anim_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.anim_node'`.

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/anim_node.py
"""TGAnimNode — the animation node returned by an object's GetAnimNode().

Real (recording) replacement for the per-class GetAnimNode stubs. The SDK
asks an object for its anim node and then either positions it
(UseAnimationPosition) or builds a TGAnimAction(node, clip) to play a clip
on it. Headless we cannot render, so this node RECORDS what it is told and
carries enough identity (owner + kind) for the cutscene controller to
discover what to play and where. See
docs/superpowers/specs/2026-06-17-bridge-camera-walkon-cutscene-design.md.

Surface mirrors sdk/Build/scripts/App.py:587-598 (TGAnimNode methods).
"""


class TGAnimNode:
    def __init__(self, owner=None, kind: str = "object"):
        self.owner = owner
        self.kind = str(kind)          # "camera" | "object"
        self.position_clip = None      # last UseAnimationPosition name
        self.last_animation = None     # last Use/SetExclusiveAnimation name
        self._blend_time = 0.0

    # ── recording surface ────────────────────────────────────────────────
    def UseAnimationPosition(self, name, *a):
        self.position_clip = str(name)

    def UseAnimation(self, name, *a):
        self.last_animation = str(name)

    def SetExclusiveAnimation(self, name, *a):
        self.last_animation = str(name)

    def SetNonExclusiveAnimation(self, name, *a):
        self.last_animation = str(name)

    def SetBlendTime(self, t, *a):
        self._blend_time = float(t)

    def GetBlendTime(self):
        return self._blend_time

    # ── chainable / no-op surface ────────────────────────────────────────
    def StopNonExclusiveAnimation(self, *a):
        pass

    def SetExclusiveAnimationUseDefault(self, *a):
        pass

    def Stop(self, *a):
        pass

    def IsAnimate(self, *a):
        return 0

    def Copy(self, *a):
        return self

    def SetRootNode(self, *a):
        pass

    def GetRootNode(self, *a):
        return self

    def FindNode(self, *a):
        return self

    def __bool__(self):
        return True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_anim_node.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/anim_node.py tests/unit/test_anim_node.py
git commit -m "feat(spv): recording TGAnimNode for camera/object animation"
```

---

### Task 3: Return the real `TGAnimNode` from `GetAnimNode`

**Files:**
- Modify: `engine/appc/bridge_set.py` (`ZoomCameraObjectClass`, ~line 99; `BridgeObjectClass.GetAnimNode`, ~line 63)
- Test: `tests/unit/test_bridge_set_stubs.py` (add cases)

**Interfaces:**
- Consumes: `engine.appc.anim_node.TGAnimNode` (Task 2).
- Produces: `ZoomCameraObjectClass.GetAnimNode() -> TGAnimNode(kind="camera", owner=self)` and `BridgeObjectClass.GetAnimNode() -> TGAnimNode(kind="object", owner=self)`, each returning the SAME persistent instance across calls.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_bridge_set_stubs.py
from engine.appc.anim_node import TGAnimNode
from engine.appc.actions import TGAnimPosition_Create


def test_camera_get_anim_node_is_real_and_does_not_crash():
    # Regression for the E1M1 Briefing() crash:
    # 'NoneType' object has no attribute 'UseAnimationPosition'.
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    node = cam.GetAnimNode()
    assert isinstance(node, TGAnimNode)
    assert node.kind == "camera"
    assert node.owner is cam
    assert cam.GetAnimNode() is node            # persistent
    node.UseAnimationPosition("WalkCameraToCaptD")   # must not raise
    assert node.position_clip == "WalkCameraToCaptD"


def test_bridge_object_get_anim_node_real_and_guest_chair_safe():
    obj = BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
    node = obj.GetAnimNode()
    assert isinstance(node, TGAnimNode)
    assert node.kind == "object"
    assert obj.GetAnimNode() is node            # persistent
    # PutGuestChairOut/In build a TGAnimPosition from the node — must work.
    pos = TGAnimPosition_Create(node, "db_guest_chair_out")
    assert pos.name == "db_guest_chair_out"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -k anim_node -v`
Expected: FAIL — `GetAnimNode()` returns `None`/a lambda result, not a `TGAnimNode`.

- [ ] **Step 3: Wire `ZoomCameraObjectClass.GetAnimNode`**

In `engine/appc/bridge_set.py`, add to `ZoomCameraObjectClass.__init__` (after the existing attribute assignments) and add the method:

```python
        self._anim_node = None   # lazily created TGAnimNode (kind="camera")
```

```python
    def GetAnimNode(self):
        # Real recording node (kind="camera"): the cutscene controller reads
        # the camera-path clip a TGAnimAction queues on it. Was previously a
        # _LoudStub no-op returning None, which crashed E1M1 Briefing().
        if self._anim_node is None:
            from engine.appc.anim_node import TGAnimNode
            self._anim_node = TGAnimNode(owner=self, kind="camera")
        return self._anim_node
```

- [ ] **Step 4: Wire `BridgeObjectClass.GetAnimNode`**

Replace the existing `BridgeObjectClass.GetAnimNode` (the one returning `None`) with:

```python
    def GetAnimNode(self):
        # Real recording node (kind="object"): the door TGAnimAction targets
        # this. PutGuestChairOut/In still only build a TGAnimPosition from it,
        # which is safe. Was previously None.
        if getattr(self, "_anim_node", None) is None:
            from engine.appc.anim_node import TGAnimNode
            self._anim_node = TGAnimNode(owner=self, kind="object")
        return self._anim_node
```

Add `self._anim_node = None` to `BridgeObjectClass.__init__` (after `self._property_set = _LoudStub()`).

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -v`
Expected: PASS (all existing cases still pass too).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py
git commit -m "fix(spv): GetAnimNode returns real TGAnimNode (fixes E1M1 Briefing crash)"
```

---

### Task 4: Keyframe sampling helpers

**Files:**
- Create: `engine/anim_sample.py`
- Test: `tests/unit/test_anim_sample.py`

**Interfaces:**
- Produces:
  - `sample_translation(keys, t) -> (x, y, z)` — `keys` = `[(time, x, y, z), ...]`, LERP, `t` clamped.
  - `sample_rotation(keys, t) -> (x, y, z, w)` — `keys` = `[(time, x, y, z, w), ...]`, SLERP, `t` clamped, result normalized.
  - `quat_rotate(q, v) -> (x, y, z)` — rotate 3-vector `v` by quaternion `q=(x,y,z,w)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_anim_sample.py
import math
from engine.anim_sample import sample_translation, sample_rotation, quat_rotate


def test_translation_lerp_and_clamp():
    keys = [(0.0, 0.0, 0.0, 0.0), (2.0, 10.0, -4.0, 2.0)]
    assert sample_translation(keys, -1.0) == (0.0, 0.0, 0.0)     # clamp low
    assert sample_translation(keys, 3.0) == (10.0, -4.0, 2.0)    # clamp high
    mid = sample_translation(keys, 1.0)
    assert mid == (5.0, -2.0, 1.0)                               # midpoint


def test_rotation_slerp_endpoints_and_midpoint():
    q0 = (0.0, 0.0, 0.0, 1.0)                       # identity
    # 90 deg about +Z
    q1 = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    keys = [(0.0, *q0), (1.0, *q1)]
    r0 = sample_rotation(keys, 0.0)
    assert all(abs(a - b) < 1e-6 for a, b in zip(r0, q0))
    # Midpoint = 45 deg about +Z.
    rm = sample_rotation(keys, 0.5)
    expected = (0.0, 0.0, math.sin(math.pi / 8), math.cos(math.pi / 8))
    assert all(abs(a - b) < 1e-6 for a, b in zip(rm, expected))


def test_quat_rotate_90_about_z():
    q = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))  # +90 Z
    x, y, z = quat_rotate(q, (1.0, 0.0, 0.0))
    assert abs(x - 0.0) < 1e-6 and abs(y - 1.0) < 1e-6 and abs(z) < 1e-6
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_anim_sample.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.anim_sample'`.

- [ ] **Step 3: Write the implementation**

```python
# engine/anim_sample.py
"""Keyframe sampling for the bridge camera walk-on cutscene.

Pure Python; mirrors the native pose_sampler's interpolation (translation
LERP, rotation SLERP, t clamped to the key range) so the camera glide
matches what the renderer would produce. Quaternions are (x, y, z, w).
"""
import math


def _bracket(keys, t):
    """Return (i0, i1, u) bracketing time t in a time-sorted key list, with
    u the [0,1] fraction between them. Clamps to the endpoints."""
    if not keys:
        return None
    if t <= keys[0][0]:
        return (0, 0, 0.0)
    if t >= keys[-1][0]:
        last = len(keys) - 1
        return (last, last, 0.0)
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, t1 = keys[lo][0], keys[hi][0]
    u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
    return (lo, hi, u)


def sample_translation(keys, t):
    """LERP keys = [(time, x, y, z), ...] at time t -> (x, y, z)."""
    br = _bracket(keys, t)
    if br is None:
        return (0.0, 0.0, 0.0)
    i0, i1, u = br
    a, b = keys[i0], keys[i1]
    return (a[1] + (b[1] - a[1]) * u,
            a[2] + (b[2] - a[2]) * u,
            a[3] + (b[3] - a[3]) * u)


def _slerp(q0, q1, u):
    dot = q0[0] * q1[0] + q0[1] * q1[1] + q0[2] * q1[2] + q0[3] * q1[3]
    if dot < 0.0:                      # shortest path
        q1 = (-q1[0], -q1[1], -q1[2], -q1[3])
        dot = -dot
    if dot > 0.9995:                   # near-parallel: nlerp
        res = tuple(q0[i] + (q1[i] - q0[i]) * u for i in range(4))
    else:
        theta = math.acos(max(-1.0, min(1.0, dot)))
        st = math.sin(theta)
        w0 = math.sin((1.0 - u) * theta) / st
        w1 = math.sin(u * theta) / st
        res = tuple(q0[i] * w0 + q1[i] * w1 for i in range(4))
    n = math.sqrt(sum(c * c for c in res)) or 1.0
    return (res[0] / n, res[1] / n, res[2] / n, res[3] / n)


def sample_rotation(keys, t):
    """SLERP keys = [(time, x, y, z, w), ...] at time t -> (x, y, z, w)."""
    br = _bracket(keys, t)
    if br is None:
        return (0.0, 0.0, 0.0, 1.0)
    i0, i1, u = br
    q0 = keys[i0][1:5]
    q1 = keys[i1][1:5]
    return _slerp(q0, q1, u)


def quat_rotate(q, v):
    """Rotate 3-vector v by quaternion q=(x,y,z,w): v + 2w(t) + 2(q.xyz x t)
    where t = q.xyz x v."""
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_anim_sample.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/anim_sample.py tests/unit/test_anim_sample.py
git commit -m "feat(spv): keyframe sampling helpers (LERP/SLERP/quat-rotate)"
```

---

### Task 5: `BridgeCutsceneController`

**Files:**
- Create: `engine/bridge_cutscene.py`
- Test: `tests/unit/test_bridge_cutscene.py`

**Interfaces:**
- Consumes: `engine.anim_sample` (Task 4); a `bridge_camera` with `set_anim_pose(eye, target, up)` / `clear_anim_pose()` (Task 6); a `view_mode` with `set_bridge()` (Task 6); a `renderer` with `load_animation_clips(path)` (Task 1) and `set_instance_animation(iid, clip_index, loop)` ; an `anim_mgr` with `path_for(name)`.
- Produces:
  - `BridgeCutsceneController()` with `request_camera_path(action, anim_node, clip_name)`, `request_object_anim(action, anim_node, clip_name)`, `update(dt, *, bridge_camera, view_mode, renderer, anim_mgr)`.
  - Module-level `get_controller() -> BridgeCutsceneController | None`, `set_controller(ctrl)`, `clear_controller()`.
  - Camera local basis constants `LOCAL_FORWARD = (0.0, 1.0, 0.0)`, `LOCAL_UP = (0.0, 0.0, 1.0)` (tuned during live verification).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_bridge_cutscene.py
from engine.bridge_cutscene import (
    BridgeCutsceneController, get_controller, set_controller, clear_controller,
)


class _FakeAction:
    def __init__(self):
        self.completed = False

    def Completed(self):
        self.completed = True


class _FakeCamera:
    def __init__(self):
        self.pose = None
        self.cleared = False

    def set_anim_pose(self, eye, target, up):
        self.pose = (eye, target, up)

    def clear_anim_pose(self):
        self.cleared = True
        self.pose = None


class _FakeViewMode:
    def __init__(self):
        self.bridge = False

    def set_bridge(self):
        self.bridge = True


class _FakeRenderer:
    def __init__(self):
        self.anim_calls = []

    def load_animation_clips(self, path):
        # Two-key straight slide on +X over 1 second, identity rotation.
        return [{
            "name": "cam", "duration": 1.0,
            "tracks": [{
                "node": "cam",
                "translation": [(0.0, 0.0, 0.0, 0.0), (1.0, 10.0, 0.0, 0.0)],
                "rotation": [(0.0, 0.0, 0.0, 0.0, 1.0),
                             (1.0, 0.0, 0.0, 0.0, 1.0)],
            }],
        }]

    def set_instance_animation(self, iid, clip_index, loop=False):
        self.anim_calls.append((iid, clip_index, loop))


class _FakeAnimMgr:
    def path_for(self, name):
        return "data/animations/db_camera_walk_capt.nif"


class _Owner:
    def __init__(self):
        self.render_instance = 77


class _FakeNode:
    def __init__(self, kind, owner=None):
        self.kind = kind
        self.owner = owner


def _ctx(cam, vm, rend, mgr):
    return dict(bridge_camera=cam, view_mode=vm, renderer=rend, anim_mgr=mgr)


def test_camera_path_drives_pose_and_completes_at_duration():
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    ctrl.request_camera_path(action, _FakeNode("camera"), "WalkCameraToCaptD")

    cam, vm, rend, mgr = _FakeCamera(), _FakeViewMode(), _FakeRenderer(), _FakeAnimMgr()
    # First update loads the clip, flips to bridge, samples t=0.
    ctrl.update(0.0, **_ctx(cam, vm, rend, mgr))
    assert vm.bridge is True
    assert cam.pose is not None
    eye0 = cam.pose[0]
    assert eye0 == (0.0, 0.0, 0.0)

    # Halfway: eye should be at +5 on X.
    ctrl.update(0.5, **_ctx(cam, vm, rend, mgr))
    assert abs(cam.pose[0][0] - 5.0) < 1e-6
    assert action.completed is False

    # Reaching duration completes the action and clears the pose.
    ctrl.update(0.5, **_ctx(cam, vm, rend, mgr))
    assert action.completed is True
    assert cam.cleared is True


def test_object_anim_plays_embedded_bridge_clip():
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    node = _FakeNode("object", owner=_Owner())
    ctrl.request_object_anim(action, node, "DB_Door_L1")

    cam, vm, rend, mgr = _FakeCamera(), _FakeViewMode(), _FakeRenderer(), _FakeAnimMgr()
    ctrl.update(0.0, **_ctx(cam, vm, rend, mgr))
    # Plays the bridge model's embedded clip 0 on the owner's render instance.
    assert rend.anim_calls == [(77, 0, False)]
    assert action.completed is True       # door is fire-and-forget


def test_object_anim_waits_for_render_instance():
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    owner = _Owner()
    owner.render_instance = None          # not realized yet
    node = _FakeNode("object", owner=owner)
    ctrl.request_object_anim(action, node, "DB_Door_L1")

    cam, vm, rend, mgr = _FakeCamera(), _FakeViewMode(), _FakeRenderer(), _FakeAnimMgr()
    ctrl.update(0.0, **_ctx(cam, vm, rend, mgr))
    assert rend.anim_calls == []          # deferred
    owner.render_instance = 99
    ctrl.update(0.0, **_ctx(cam, vm, rend, mgr))
    assert rend.anim_calls == [(99, 0, False)]


def test_module_level_registry():
    clear_controller()
    assert get_controller() is None
    ctrl = BridgeCutsceneController()
    set_controller(ctrl)
    assert get_controller() is ctrl
    clear_controller()
    assert get_controller() is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_cutscene.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.bridge_cutscene'`.

- [ ] **Step 3: Write the implementation**

```python
# engine/bridge_cutscene.py
"""BridgeCutsceneController — the seam between the headless SDK action layer
and the host/renderer for bridge animation cutscenes.

A camera TGAnimAction queues a camera-path request here and defers its own
completion; each host tick update() loads the clip (native), samples it, and
drives _BridgeCamera, completing the action when the clip ends so the SDK
sequence proceeds (firing ET_CAMERA_ANIMATION_DONE). A door TGAnimAction
queues an object request, which plays the bridge model's embedded clip 0
(the door keyframes baked into DBridge.nif) via set_instance_animation.

See docs/superpowers/specs/2026-06-17-bridge-camera-walkon-cutscene-design.md.
"""
from engine.anim_sample import sample_translation, sample_rotation, quat_rotate

# Camera node local basis the keyframe rotation orients. Tuned during live
# verification (the NIF camera node's authored forward/up convention).
LOCAL_FORWARD = (0.0, 1.0, 0.0)
LOCAL_UP = (0.0, 0.0, 1.0)


class BridgeCutsceneController:
    def __init__(self):
        # Pending camera request: (action, clip_name) before the clip loads.
        self._pending_camera = None
        # Active camera playback: dict(action, track, duration, t).
        self._active_camera = None
        # Pending door requests: list of (action, owner).
        self._pending_doors = []

    # ── requests (called from TGAnimAction._do_play, headless) ───────────
    def request_camera_path(self, action, anim_node, clip_name):
        self._pending_camera = (action, str(clip_name))

    def request_object_anim(self, action, anim_node, clip_name):
        self._pending_doors.append((action, getattr(anim_node, "owner", None)))

    def reset(self):
        """Clear all pending/active state (called on mission swap so a stale
        cutscene from the prior mission cannot leak into the next)."""
        self._pending_camera = None
        self._active_camera = None
        self._pending_doors = []

    # ── per-tick host pump ───────────────────────────────────────────────
    def update(self, dt, *, bridge_camera, view_mode, renderer, anim_mgr):
        self._update_doors(renderer)
        self._update_camera(dt, bridge_camera, view_mode, renderer, anim_mgr)

    def _update_doors(self, renderer):
        still_pending = []
        for action, owner in self._pending_doors:
            iid = getattr(owner, "render_instance", None)
            if iid is None:
                still_pending.append((action, owner))   # wait for realize
                continue
            # The door keyframes are baked into the bridge model's clip 0.
            renderer.set_instance_animation(iid, 0, False)
            action.Completed()                            # fire-and-forget
        self._pending_doors = still_pending

    def _update_camera(self, dt, bridge_camera, view_mode, renderer, anim_mgr):
        if self._active_camera is None and self._pending_camera is not None:
            action, clip_name = self._pending_camera
            path = anim_mgr.path_for(clip_name)
            track = self._load_camera_track(renderer, path)
            if track is None:
                # Nothing to play (missing clip / no motion): complete now so
                # the SDK sequence is not stuck waiting on this action.
                self._pending_camera = None
                action.Completed()
                return
            self._pending_camera = None
            view_mode.set_bridge()
            duration = max(track["translation"][-1][0],
                           track["rotation"][-1][0] if track["rotation"] else 0.0)
            self._active_camera = dict(action=action, track=track,
                                       duration=duration, t=0.0)

        if self._active_camera is None:
            return

        ac = self._active_camera
        ac["t"] += dt
        t = min(ac["t"], ac["duration"])
        track = ac["track"]
        eye = sample_translation(track["translation"], t)
        q = sample_rotation(track["rotation"], t) if track["rotation"] else (0.0, 0.0, 0.0, 1.0)
        fwd = quat_rotate(q, LOCAL_FORWARD)
        up = quat_rotate(q, LOCAL_UP)
        target = (eye[0] + fwd[0], eye[1] + fwd[1], eye[2] + fwd[2])
        bridge_camera.set_anim_pose(eye, target, up)

        if ac["t"] >= ac["duration"]:
            bridge_camera.clear_anim_pose()
            ac["action"].Completed()
            self._active_camera = None

    @staticmethod
    def _load_camera_track(renderer, path):
        if not path:
            return None
        clips = renderer.load_animation_clips(path)
        if not clips:
            return None
        # The moving camera node: the track with translation keys (prefer the
        # one with the most, in case the NIF has multiple animated nodes).
        moving = [t for t in clips[0]["tracks"] if t["translation"]]
        if not moving:
            return None
        return max(moving, key=lambda t: len(t["translation"]))


# ── module-level registry (host sets one; actions look it up) ────────────
_controller = None


def get_controller():
    return _controller


def set_controller(ctrl):
    global _controller
    _controller = ctrl


def clear_controller():
    global _controller
    _controller = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_cutscene.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_cutscene.py tests/unit/test_bridge_cutscene.py
git commit -m "feat(spv): BridgeCutsceneController drives camera path + door anim"
```

---

### Task 6: `_BridgeCamera` animation override + `view_mode.set_bridge()`

**Files:**
- Modify: `engine/host_loop.py` (`_BridgeCamera`, ~line 1324; `_ViewModeController`, ~line 1066)
- Test: `tests/unit/test_bridge_camera_anim.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_BridgeCamera.set_anim_pose(eye, target, up)`, `_BridgeCamera.clear_anim_pose()`; `_BridgeCamera.compute_camera()` returns the anim pose (plus base FOV) while one is set; `_BridgeCamera.apply(dx, dy)` is a no-op while an anim pose is set. `_ViewModeController.set_bridge()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_bridge_camera_anim.py
from engine.host_loop import _BridgeCamera, _ViewModeController


def test_anim_pose_overrides_compute_and_freezes_mouse_look():
    cam = _BridgeCamera()
    base_eye, _, _, _ = cam.compute_camera()
    cam.set_anim_pose((1.0, 2.0, 3.0), (1.0, 3.0, 3.0), (0.0, 0.0, 1.0))
    eye, target, up, fov = cam.compute_camera()
    assert eye == (1.0, 2.0, 3.0)
    assert target == (1.0, 3.0, 3.0)
    assert up == (0.0, 0.0, 1.0)
    assert fov > 0.0
    # Mouse-look frozen while the anim pose is active.
    before = (cam.yaw_rad, cam.pitch_rad)
    cam.apply(100.0, 100.0)
    assert (cam.yaw_rad, cam.pitch_rad) == before
    # Clearing restores normal mouse-look behaviour.
    cam.clear_anim_pose()
    restored_eye, _, _, _ = cam.compute_camera()
    assert restored_eye == base_eye
    cam.apply(100.0, 100.0)
    assert (cam.yaw_rad, cam.pitch_rad) != before


def test_view_mode_set_bridge():
    vm = _ViewModeController()
    vm.toggle()                # -> exterior (default is bridge)
    assert vm.is_exterior
    vm.set_bridge()
    assert vm.is_bridge
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_camera_anim.py -v`
Expected: FAIL — `_BridgeCamera` has no `set_anim_pose`; `_ViewModeController` has no `set_bridge`.

- [ ] **Step 3: Add the anim-pose state to `_BridgeCamera`**

In `_BridgeCamera.__init__`, after `self._zoom_target_world = None`:

```python
        # Cutscene animation override: when set, compute_camera returns this
        # (eye, target, up) verbatim and mouse-look is frozen. Driven by
        # BridgeCutsceneController.update (engine/bridge_cutscene.py).
        self._anim_pose = None
```

Add the two methods (after `set_zoom_target`):

```python
    def set_anim_pose(self, eye, target, up) -> None:
        """Override the camera with a cutscene-sampled pose (bridge-local)."""
        self._anim_pose = (tuple(eye), tuple(target), tuple(up))

    def clear_anim_pose(self) -> None:
        self._anim_pose = None
```

- [ ] **Step 4: Make `apply` and `compute_camera` honor the anim pose**

At the very top of `_BridgeCamera.apply`, before the existing zoom check:

```python
        if self._anim_pose is not None:
            return
```

At the very top of `_BridgeCamera.compute_camera`, before `local_fwd = (0.0, 1.0, 0.0)`:

```python
        if self._anim_pose is not None:
            eye, target, up = self._anim_pose
            return eye, target, up, self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX
```

- [ ] **Step 5: Add `set_bridge` to `_ViewModeController`**

After the `toggle` method:

```python
    def set_bridge(self) -> None:
        """Force bridge view (used to start a bridge cutscene)."""
        self._mode = self.BRIDGE
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_camera_anim.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_bridge_camera_anim.py
git commit -m "feat(spv): _BridgeCamera anim-pose override + view_mode.set_bridge"
```

---

### Task 7: Route camera/object `TGAnimAction` to the controller

**Files:**
- Modify: `engine/appc/actions.py` (`TGAnimAction`, `TGAnimAction_Create`, ~line 411)
- Test: `tests/unit/test_anim_action_routing.py`

**Interfaces:**
- Consumes: `engine.bridge_cutscene.get_controller` (Task 5); `TGAnimNode.kind` (Task 2).
- Produces: `TGAnimAction` stores `_anim_node` and `_clip`; `_do_play` routes `kind=="camera"`/`"object"` nodes (when a controller is registered) to the controller and defers completion; everything else completes instantly as before.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_anim_action_routing.py
from engine.appc.actions import TGAnimAction_Create
from engine.appc.anim_node import TGAnimNode
import engine.bridge_cutscene as bc


class _RecordingController:
    def __init__(self):
        self.camera = []
        self.door = []

    def request_camera_path(self, action, node, clip):
        self.camera.append((action, node, clip))

    def request_object_anim(self, action, node, clip):
        self.door.append((action, node, clip))


def teardown_function(_):
    bc.clear_controller()


def test_camera_action_defers_to_controller():
    ctrl = _RecordingController()
    bc.set_controller(ctrl)
    node = TGAnimNode(kind="camera")
    action = TGAnimAction_Create(node, "WalkCameraToCaptD", 1, 0, 0, 0)
    action.Play()
    assert ctrl.camera == [(action, node, "WalkCameraToCaptD")]
    assert action.IsPlaying() is True            # deferred, not completed


def test_object_action_defers_to_controller():
    ctrl = _RecordingController()
    bc.set_controller(ctrl)
    node = TGAnimNode(kind="object")
    action = TGAnimAction_Create(node, "DB_Door_L1", 0, 0)
    action.Play()
    assert ctrl.door == [(action, node, "DB_Door_L1")]


def test_character_gesture_action_completes_instantly():
    # A _NodeStub (no .kind) or no controller -> instant complete, no defer.
    bc.clear_controller()
    node = TGAnimNode(kind="camera")
    action = TGAnimAction_Create(node, "twitch", 0, 0)
    action.Play()
    assert action.IsPlaying() is False           # completed (no controller)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_anim_action_routing.py -v`
Expected: FAIL — `TGAnimAction_Create` ignores its args; no routing.

- [ ] **Step 3: Implement routing in `actions.py`**

Replace the existing `TGAnimAction` class and `TGAnimAction_Create` factory with:

```python
class TGAnimAction(TGAction):
    """Plays a named clip on a target's anim node.

    Camera (kind="camera") and bridge-object (kind="object") anim nodes route
    to the BridgeCutsceneController, which drives playback host-side and
    completes the action when the clip ends (deferred). Every other target
    (character gesture clips via a _NodeStub node, or no controller
    registered) keeps the Phase-1 instant-complete behaviour.
    """
    def __init__(self, anim_node=None, clip_name=""):
        super().__init__()
        self._anim_node = anim_node
        self._clip = str(clip_name)
        self._deferred = False

    def Play(self) -> None:
        self._playing = True
        self._deferred = False
        self._do_play()
        if not self._deferred:
            self.Completed()

    def _do_play(self) -> None:
        kind = getattr(self._anim_node, "kind", None)
        if kind not in ("camera", "object"):
            return
        from engine.bridge_cutscene import get_controller
        ctrl = get_controller()
        if ctrl is None:
            return
        if kind == "camera":
            ctrl.request_camera_path(self, self._anim_node, self._clip)
        else:
            ctrl.request_object_anim(self, self._anim_node, self._clip)
        self._deferred = True


def TGAnimAction_Create(*args) -> TGAnimAction:
    # SDK call shape: App.TGAnimAction_Create(pAnimNode, "ClipName", flags...).
    anim_node = args[0] if len(args) >= 1 else None
    clip_name = args[1] if len(args) >= 2 and isinstance(args[1], str) else ""
    return TGAnimAction(anim_node, clip_name)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_anim_action_routing.py -v`
Expected: PASS.

- [ ] **Step 5: Run the broader action + bridge suites for regressions**

Run: `uv run pytest tests/unit/test_anim_action_routing.py tests/unit/test_bridge_cutscene.py tests/unit/test_bridge_set_stubs.py tests/unit/test_anim_node.py -v`
Expected: PASS. (Confirms the camera/object routing didn't break the existing TGAnimAction users.)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_anim_action_routing.py
git commit -m "feat(spv): route camera/object TGAnimAction to cutscene controller"
```

---

### Task 8: Host-loop integration + live verification

**Files:**
- Modify: `engine/host_loop.py` (create + register controller near `bridge_camera = _BridgeCamera()` ~line 2630; pump `update` in the per-tick bridge branch ~line 3242; reset on mission swap)
- Test: live (the full unit suite has covered the units).

**Interfaces:**
- Consumes: `BridgeCutsceneController`, `set_controller`, `clear_controller` (Task 5); `App.g_kAnimationManager`; `r` (renderer wrapper, Task 1).

- [ ] **Step 1: Create and register the controller**

In `host_loop.run()`, immediately after `bridge_camera = _BridgeCamera()` (~line 2630):

```python
        from engine.bridge_cutscene import (
            BridgeCutsceneController, set_controller, clear_controller,
        )
        cutscene = BridgeCutsceneController()
        set_controller(cutscene)
```

- [ ] **Step 2: Pump the controller each tick (bridge branch)**

In the per-tick body, inside `if view_mode.is_bridge:` (the block around line 3242, before `bridge_camera.compute_camera()` is called), add the controller pump. It must run even while the rest of the bridge camera update is gated on `not pause.is_open` is fine — but the cutscene should advance with sim time, so pump it with `_player_dt` only when not paused:

```python
                if view_mode.is_bridge:
                    import App as _App
                    if not pause.is_open:
                        cutscene.update(
                            _player_dt,
                            bridge_camera=bridge_camera,
                            view_mode=view_mode,
                            renderer=r,
                            anim_mgr=_App.g_kAnimationManager,
                        )
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    # ... existing body unchanged ...
```

(Insert the `cutscene.update(...)` call; leave the existing mouse-delta and `compute_camera` lines as they are. While an anim pose is set, `bridge_camera.apply` is already a no-op and `compute_camera` returns the sampled pose — see Task 6.)

Note: a pending camera request will flip `view_mode` to bridge on its first `update`; but `update` is only reached inside `if view_mode.is_bridge`. Since the engine DEFAULTS to bridge view (`_ViewModeController.__init__` sets `BRIDGE`), the first E1M1 cutscene is reached. If the player has toggled to exterior, add the pre-check in Step 3.

- [ ] **Step 3: Ensure a queued cutscene forces bridge view even from exterior**

Just before the `if view_mode.is_bridge:` block, add an unconditional pump-arming check so a queued camera path pulls the view back to bridge:

```python
                if cutscene.has_pending_camera() and not pause.is_open:
                    view_mode.set_bridge()
```

Add the helper to `BridgeCutsceneController` (engine/bridge_cutscene.py):

```python
    def has_pending_camera(self):
        return self._pending_camera is not None or self._active_camera is not None
```

And add a unit test for it in `tests/unit/test_bridge_cutscene.py`:

```python
def test_has_pending_camera_flag():
    ctrl = BridgeCutsceneController()
    assert ctrl.has_pending_camera() is False
    ctrl.request_camera_path(_FakeAction(), _FakeNode("camera"), "X")
    assert ctrl.has_pending_camera() is True
```

Run: `uv run pytest tests/unit/test_bridge_cutscene.py -v` → PASS.

- [ ] **Step 4: Reset the controller on mission swap**

Find where a mission swap tears down per-mission state (search `_drain_pending_swap` / where `bridge_instance` is reset). After the new session loads, re-arm a fresh controller so a stale active cutscene from the prior mission cannot leak:

```python
        # After a successful swap (in the same place the new session is set):
        cutscene.reset()           # clear pending/active camera + doors
```

If the swap path does not have `cutscene` in lexical scope, call it via the
registry: `from engine.bridge_cutscene import get_controller`; then
`_c = get_controller()` and `if _c is not None: _c.reset()`.

- [ ] **Step 5: Build and run the game; verify E1M1 loads without the crash**

```bash
cmake --build build -j
./build/dauntless --developer
```

Then load mission E1M1 (dev "Load Mission…" picker → Maelstrom → Episode1 → E1M1).
Expected:
- The console no longer prints `AttributeError: 'NoneType' object has no attribute 'UseAnimationPosition'` / `mission swap to '...E1M1' failed`.
- In bridge view the camera glides from the lift toward the captain's chair; the L1 lift door animates.

- [ ] **Step 6: If the camera faces the wrong way, tune the local basis**

If the glide path is right but the camera looks the wrong direction, adjust `LOCAL_FORWARD` / `LOCAL_UP` in `engine/bridge_cutscene.py` (the NIF camera node's authored forward/up). Re-run `./build/dauntless` (no rebuild needed — pure Python). Document the final basis in a one-line comment.

- [ ] **Step 7: Run the full unit suite**

Run: `bash scripts/run_tests.sh` (watchdog-capped; see memory `feedback_pytest_memory`) or `uv run pytest tests/unit -q`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py engine/bridge_cutscene.py tests/unit/test_bridge_cutscene.py
git commit -m "feat(spv): wire bridge cutscene controller into host loop; E1M1 walk-on plays"
```

---

## Verification checklist (run after all tasks)

- [ ] `uv run pytest tests/unit/test_anim_node.py tests/unit/test_anim_sample.py tests/unit/test_bridge_cutscene.py tests/unit/test_bridge_set_stubs.py tests/unit/test_anim_action_routing.py tests/unit/test_bridge_camera_anim.py -v` — all PASS.
- [ ] `uv run pytest tests/integration/test_camera_path_clip.py -v` — PASS (with `game/` present).
- [ ] `./build/dauntless --developer` → load E1M1 → no `UseAnimationPosition` crash; camera walk-on plays; L1 door opens.
- [ ] `bash scripts/run_tests.sh` — full suite green, no regressions.

## Notes for the implementer

- **Door selectivity:** `set_instance_animation(iid, 0)` plays the bridge model's *entire* embedded clip (all doors at once), because `build_animations` collapses every keyframe controller into one clip. This is expected for v1. If non-L1 doors moving looks wrong during live verify, that is the documented follow-on (named-range or per-track native playback), NOT a bug in this plan — leave it and note it.
- **Completion coupling:** the camera action completes host-side when the clip ends (native owns duration). The controller force-completes if the clip can't be loaded (missing path / no motion) so the SDK sequence never hangs.
- **Path resolution:** `anim_mgr.path_for("WalkCameraToCaptD")` resolves to `data/animations/db_camera_walk_capt.nif` (the present file) because `CommonAnimations.WalkCameraToCaptOnD` re-registers the name over E1M1's earlier missing-file registration. Do not "fix" the missing-file `LoadAnimation` in E1M1 — the re-register is what the original relies on.
- **Controller registration timing:** the camera request is created when `Briefing()` calls `pSequence.Play()` during mission load. The controller must already be registered (`set_controller`) at that point, or the `TGAnimAction` sees no controller and instant-completes (cutscene silently skipped). The reported E1M1 case loads via a mid-loop mission *swap* (`_drain_pending_swap`), which happens after `set_controller` ran at loop start — so it is covered. If you later want the *initial* mission (loaded before the main loop) to also play its walk-on, move the `set_controller(cutscene)` call to before the initial mission load.

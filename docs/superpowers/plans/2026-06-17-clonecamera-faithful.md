# Faithful CloneCamera + comm-set render flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `App.g_kModelManager.CloneCamera` faithfully return the camera embedded in a set NIF (frustum + world transform), with a real Python `CameraObjectClass` surface, and loudly flag comm-set rendering as unimplemented under developer mode.

**Architecture:** A pure C++ NIF utility (`nif::find_first_camera`) extracts the first `NiCamera` and composes its world transform from the parent `NiNode` chain. A host binding (`parse_set_camera`) exposes it to Python. `CloneCamera` calls the binding (guarded) and wraps the result in `NiCameraData`; `CameraObjectClass_CreateFromNiCamera` / `CameraObjectClass_Create` build real camera objects consumed by `SetupBridgeSet`. A dev-mode one-shot warning fires in the host loop's viewscreen step when a comm set is requested.

**Tech Stack:** C++17 (nif static lib + pybind11 host bindings), Python 3.13 shim layer, gtest (native), pytest (Python).

## Global Constraints

- Spatial values stay in **game units** end-to-end (1 GU = 175 m); no display conversion in this code. Internal vars are `*_gu`, never `*_m`.
- Rotation matrices are **column-vector** convention: `R.GetCol(1)` is forward. `nif::Mat3x3.m` is **row-major** (`m[r*3+c]`); `TGMatrix3.Set(...)` takes row-major args — so 9 floats pass through directly with no transpose.
- Production render path must stay **byte-identical** when developer mode is off — the comm-render flag is gated by `dev_mode.is_enabled()`.
- Headless Python tests must never require the compiled `_dauntless_host` module — `CloneCamera` degrades to `None` (the existing SDK fallback branch) when it is absent.
- Build from the canonical tree only: `cmake -B build -S . && cmake --build build -j`. Binary at `build/dauntless`. Never build from inside `native/`.
- Edits to `native/src/host/host_bindings.cc` require rebuilding the `dauntless` target (the file is compiled into both the binary and the `_dauntless_host` module).

---

### Task 1: Python camera surface (value types + factories)

Build the real Python camera objects and the two SDK factory functions, wired into the `App` namespace. `CloneCamera` itself is untouched in this task (still returns `None`); the factories are exercised directly and through the real `MissionLib.SetupBridgeSet` by monkeypatching `CloneCamera`.

**Files:**
- Modify: `engine/appc/bridge_set.py`
- Modify: `App.py:73-87` (the `from engine.appc.bridge_set import (...)` block)
- Create: `tests/appc/__init__.py` (empty, if `tests/appc/` does not exist)
- Create: `tests/appc/test_camera_object.py`

**Interfaces:**
- Produces:
  - `class _NiFrustum` with attributes `m_fLeft, m_fRight, m_fTop, m_fBottom, m_fNear, m_fFar` (all `float`).
  - `class NiCameraData` with attributes `position: tuple[float,float,float]`, `rotation: tuple[float×9]` (row-major), `frustum: tuple[float,float,float,float]` (l,r,t,b), `near: float`, `far: float`, `source: str`.
  - `class CameraObjectClass` with `position: tuple`, `orientation: TGMatrix3`, methods `GetNiFrustum() -> _NiFrustum`, `SetNiFrustum(_NiFrustum) -> None`, `SetNearAndFarDistance(near, far) -> None`, `GetNearDistance() -> float`, `GetFarDistance() -> float`.
  - `CameraObjectClass_CreateFromNiCamera(niCamera: NiCameraData, name: str) -> CameraObjectClass`.
  - `CameraObjectClass_Create(x, y, z, a, ax, ay, az, name) -> CameraObjectClass`.

- [ ] **Step 1: Write the failing test**

Create `tests/appc/__init__.py` (empty) if missing, then create `tests/appc/test_camera_object.py`:

```python
"""Camera object surface that MissionLib.SetupBridgeSet drives."""
import App  # noqa: F401  (installs the SDK finder + shim namespace)
from engine.appc.bridge_set import (
    NiCameraData, CameraObjectClass_CreateFromNiCamera, CameraObjectClass_Create,
)


def test_create_from_nicamera_copies_frustum_and_placement():
    data = NiCameraData(
        position=(1.0, 2.0, 3.0),
        rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1),
        frustum=(-0.5, 0.5, 0.4, -0.4),
        near=1.0, far=800.0, source="x.nif",
    )
    cam = CameraObjectClass_CreateFromNiCamera(data, "maincamera")
    assert cam.position == (1.0, 2.0, 3.0)
    f = cam.GetNiFrustum()
    assert (f.m_fLeft, f.m_fRight, f.m_fTop, f.m_fBottom) == (-0.5, 0.5, 0.4, -0.4)
    assert cam.GetNearDistance() == 1.0 and cam.GetFarDistance() == 800.0
    # orientation is a column-vector matrix: identity -> forward is +Y col.
    assert cam.orientation.GetCol(1).y == 1.0


def test_frustum_halving_round_trips_through_setter():
    data = NiCameraData((0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1),
                        (-1.0, 1.0, 0.8, -0.8), 1.0, 800.0)
    cam = CameraObjectClass_CreateFromNiCamera(data, "maincamera")
    f = cam.GetNiFrustum()
    f.m_fLeft *= 0.5
    f.m_fRight *= 0.5
    f.m_fTop *= 0.5
    f.m_fBottom *= 0.5
    cam.SetNiFrustum(f)
    g = cam.GetNiFrustum()
    assert (g.m_fLeft, g.m_fRight, g.m_fTop, g.m_fBottom) == (-0.5, 0.5, 0.4, -0.4)


def test_create_from_coords_builds_real_camera():
    cam = CameraObjectClass_Create(0, 50, 47, -1.55, 0, 0, 1, "maincamera")
    assert cam.position == (0, 50, 47)
    # angle-axis (-1.55 rad about +Z) -> a real rotation matrix, not identity.
    assert cam.orientation.GetCol(0).x != 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_camera_object.py -q`
Expected: FAIL — `ImportError: cannot import name 'NiCameraData' from 'engine.appc.bridge_set'`.

- [ ] **Step 3: Add the camera classes and factories to `engine/appc/bridge_set.py`**

At the top of the file, after `from engine.appc.sets import SetClass`, add:

```python
from engine.appc.math import TGMatrix3, TGPoint3
```

Then add these classes and functions near the other camera types (after `ZoomCameraObjectClass_GetObject`, before `class ModelManager`):

```python
class _NiFrustum:
    """Mutable frustum bounds, mirroring the engine's NiFrustum struct.
    MissionLib.SetupBridgeSet reads these, scales each by 0.5, and writes
    them back via SetNiFrustum."""
    def __init__(self, left=0.0, right=0.0, top=0.0, bottom=0.0,
                 near=0.0, far=0.0):
        self.m_fLeft = left
        self.m_fRight = right
        self.m_fTop = top
        self.m_fBottom = bottom
        self.m_fNear = near
        self.m_fFar = far


class NiCameraData:
    """Opaque handle the SDK passes from CloneCamera to
    CameraObjectClass_CreateFromNiCamera. Holds the camera placement +
    frustum parsed out of a set NIF (game units; rotation row-major,
    column-vector convention)."""
    def __init__(self, position, rotation, frustum, near, far, source=""):
        self.position = tuple(position)      # (x, y, z) world, game units
        self.rotation = tuple(rotation)      # 9 floats, row-major storage
        self.frustum = tuple(frustum)        # (left, right, top, bottom)
        self.near = near
        self.far = far
        self.source = source


class CameraObjectClass:
    """A set camera. Built either from an embedded NiCamera
    (CameraObjectClass_CreateFromNiCamera) or from explicit coordinates
    (CameraObjectClass_Create). Real, stateful data: the viewscreen's
    SetRemoteCam consumes it. Comm-set rendering through it is not yet
    built (flagged loudly under developer mode)."""
    def __init__(self, name, position, orientation, frustum, near, far):
        self._name = name
        self.position = tuple(position)
        self.orientation = orientation       # TGMatrix3 (column-vector)
        self._frustum = frustum              # _NiFrustum
        self._near = near
        self._far = far

    def GetNiFrustum(self):
        return self._frustum

    def SetNiFrustum(self, frustum):
        self._frustum = frustum

    def SetNearAndFarDistance(self, near, far):
        self._near = near
        self._far = far

    def GetNearDistance(self):
        return self._near

    def GetFarDistance(self):
        return self._far


def CameraObjectClass_CreateFromNiCamera(niCamera, name):
    left, right, top, bottom = niCamera.frustum
    frustum = _NiFrustum(left, right, top, bottom, niCamera.near, niCamera.far)
    orientation = TGMatrix3()
    orientation.Set(*niCamera.rotation)      # row-major args
    return CameraObjectClass(name, niCamera.position, orientation,
                             frustum, niCamera.near, niCamera.far)


def CameraObjectClass_Create(x, y, z, a, ax, ay, az, name):
    """Fallback camera from explicit coords + angle-axis orientation. The SDK
    overrides near/far via SetNearAndFarDistance; frustum starts default."""
    orientation = TGMatrix3().MakeRotation(a, TGPoint3(ax, ay, az))
    return CameraObjectClass(name, (x, y, z), orientation,
                             _NiFrustum(), 1.0, 800.0)
```

- [ ] **Step 4: Wire the new symbols into the `App` namespace**

In `App.py`, extend the `from engine.appc.bridge_set import (...)` block (currently ending with `ModelManager,` around line 84) to also import:

```python
    CameraObjectClass,
    CameraObjectClass_Create,
    CameraObjectClass_CreateFromNiCamera,
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/appc/test_camera_object.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Write the SetupBridgeSet integration test**

Append to `tests/appc/test_camera_object.py`:

```python
def test_setupbridgeset_else_branch_with_embedded_camera(monkeypatch):
    import App
    import MissionLib
    from engine.appc import bridge_set

    data = NiCameraData((0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1),
                        (-1.0, 1.0, 0.8, -0.8), 1.0, 800.0, "starbase.nif")
    monkeypatch.setattr(bridge_set.ModelManager, "CloneCamera",
                        lambda self, path: data)
    App.g_kSetManager.RemoveSet("CamTestSet") if hasattr(
        App.g_kSetManager, "RemoveSet") else None

    pSet = MissionLib.SetupBridgeSet("CamTestSet", "starbase.nif", -35, 65, -1.55)
    cam = pSet.GetCamera("maincamera")
    assert cam is not None
    f = cam.GetNiFrustum()
    # SetupBridgeSet halves each frustum side for the embedded-camera path.
    assert (f.m_fLeft, f.m_fRight, f.m_fTop, f.m_fBottom) == (-0.5, 0.5, 0.4, -0.4)


def test_setupbridgeset_fallback_branch_when_no_camera(monkeypatch):
    import App
    import MissionLib
    from engine.appc import bridge_set

    monkeypatch.setattr(bridge_set.ModelManager, "CloneCamera",
                        lambda self, path: None)
    pSet = MissionLib.SetupBridgeSet("CamTestSet2", "nocam.nif", -35, 65, -1.55)
    assert pSet.GetCamera("maincamera") is not None
```

Note: if `SetupBridgeSet` returns an already-existing set on a re-run within one test session, use a unique set name per test (done above: `CamTestSet`, `CamTestSet2`).

- [ ] **Step 7: Run the integration test**

Run: `uv run pytest tests/appc/test_camera_object.py -q`
Expected: PASS (5 passed). If `test_setupbridgeset_else_branch...` fails on `GetCamera`, confirm `SetClass.AddCameraToSet`/`GetCamera` store/return by name (they already exist — see `engine/appc/sets.py:175`).

- [ ] **Step 8: Commit**

```bash
git add engine/appc/bridge_set.py App.py tests/appc/
git commit -m "feat(spv): real CameraObjectClass surface for set cameras

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: NIF camera-extraction utility (`nif::find_first_camera`)

A pure, GL-free utility on the `nif` static lib: given a parsed `nif::File`, find the first `NiCamera` and compose its world transform by walking the parent `NiNode` chain. Unit-tested against real BC NIFs with gtest.

**Files:**
- Create: `native/src/nif/include/nif/scene_camera.h`
- Create: `native/src/nif/src/scene_camera.cc`
- Modify: `native/src/nif/CMakeLists.txt:13` (add `src/scene_camera.cc` to the `nif` lib sources)
- Create: `native/tests/nif/scene_camera_test.cc`
- Modify: `native/tests/CMakeLists.txt` (add `nif/scene_camera_test.cc` to the `nif_tests` executable source list)

**Interfaces:**
- Consumes: `nif::File`, `nif::NiNode`, `nif::NiCamera`, `nif::Mat3x3`, `nif::Vec3` (from `nif/file.h`, `nif/block.h`, `nif/types.h`), and the link-id→index mapping idiom (`File::block_ids` parallel to `File::blocks`, see `native/tools/dump_nif_tree/dump_nif_tree.cc:25`).
- Produces:
  ```cpp
  namespace nif {
  struct SetCamera {
      std::array<float, 3> position;   // world translation, model frame
      std::array<float, 9> rotation;   // world rotation, row-major (m[r*3+c])
      std::array<float, 4> frustum;    // left, right, top, bottom
      float near_distance;
      float far_distance;
  };
  std::optional<SetCamera> find_first_camera(const File& f);
  }  // namespace nif
  ```

- [ ] **Step 1: Write the failing test**

Create `native/tests/nif/scene_camera_test.cc`:

```cpp
// native/tests/nif/scene_camera_test.cc — find_first_camera against real BC sets.
#include <gtest/gtest.h>

#include <nif/file.h>
#include <nif/scene_camera.h>

#include <filesystem>

namespace {
std::filesystem::path asset(const char* rel) {
    return std::filesystem::path(OPEN_STBC_PROJECT_ROOT) / rel;
}
}  // namespace

TEST(FindFirstCamera, StarbaseControlHasCamera) {
    auto path = asset("game/data/Models/Sets/StarbaseControl/starbasecontrolRM.NIF");
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    auto cam = nif::find_first_camera(f);
    ASSERT_TRUE(cam.has_value());
    // Frustum sides are non-degenerate (left<right, bottom<top).
    EXPECT_LT(cam->frustum[0], cam->frustum[1]);
    EXPECT_LT(cam->frustum[3], cam->frustum[2]);
    EXPECT_GT(cam->far_distance, cam->near_distance);
}

TEST(FindFirstCamera, DBridgeHasNoCamera) {
    auto path = asset("game/data/Models/Sets/DBridge/DBridge.NIF");
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    EXPECT_FALSE(nif::find_first_camera(f).has_value());
}

TEST(FindFirstCamera, EBridgeHasNoCamera) {
    auto path = asset("game/data/Models/Sets/EBridge/EBridge.NIF");
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    EXPECT_FALSE(nif::find_first_camera(f).has_value());
}
```

- [ ] **Step 2: Register the new source + test in CMake**

In `native/src/nif/CMakeLists.txt`, add to the `add_library(nif STATIC ...)` source list (after `src/blocks/scene.cc`):

```cmake
    src/scene_camera.cc
```

In `native/tests/CMakeLists.txt`, add to the `add_executable(nif_tests ...)` source list (after `nif/ni_node_test.cc`):

```cmake
    nif/scene_camera_test.cc
```

- [ ] **Step 3: Create the header `native/src/nif/include/nif/scene_camera.h`**

```cpp
// native/src/nif/include/nif/scene_camera.h
//
// Extract the first NiCamera from a parsed set NIF and compose its world
// transform from the parent NiNode chain. Used by the host's
// parse_set_camera binding to feed MissionLib.SetupBridgeSet's embedded-
// camera path. Pure: no GL, no asset cache.
#pragma once

#include <nif/file.h>

#include <array>
#include <optional>

namespace nif {

struct SetCamera {
    std::array<float, 3> position{0, 0, 0};   // world translation, model frame
    std::array<float, 9> rotation{1, 0, 0, 0, 1, 0, 0, 0, 1};  // row-major
    std::array<float, 4> frustum{0, 0, 0, 0}; // left, right, top, bottom
    float near_distance = 0.0f;
    float far_distance = 0.0f;
};

/// First NiCamera in the file with its world transform composed from the
/// root down its parent NiNode chain, or nullopt if the file has no camera.
std::optional<SetCamera> find_first_camera(const File& f);

}  // namespace nif
```

- [ ] **Step 4: Create the implementation `native/src/nif/src/scene_camera.cc`**

```cpp
// native/src/nif/src/scene_camera.cc
#include <nif/scene_camera.h>

#include <nif/block.h>

#include <array>
#include <cstdint>
#include <unordered_map>
#include <variant>
#include <vector>

namespace nif {
namespace {

// 3x3 row-major multiply: c = a * b.
std::array<float, 9> mat_mul(const std::array<float, 9>& a,
                             const std::array<float, 9>& b) {
    std::array<float, 9> c{};
    for (int r = 0; r < 3; ++r)
        for (int col = 0; col < 3; ++col)
            c[r * 3 + col] = a[r * 3 + 0] * b[0 * 3 + col]
                           + a[r * 3 + 1] * b[1 * 3 + col]
                           + a[r * 3 + 2] * b[2 * 3 + col];
    return c;
}

// world = parent_world applied to local: rotation composes, translation is
// parent_pos + parent_rot * (scale * local_translation).
struct Xform {
    std::array<float, 9> rot{1, 0, 0, 0, 1, 0, 0, 0, 1};
    std::array<float, 3> pos{0, 0, 0};
    float scale = 1.0f;
};

Xform local_of(const AvObjectBase& av) {
    Xform x;
    x.rot = av.rotation.m;
    x.pos = {av.translation.x, av.translation.y, av.translation.z};
    x.scale = av.scale;
    return x;
}

Xform compose(const Xform& parent, const Xform& local) {
    Xform w;
    w.rot = mat_mul(parent.rot, local.rot);
    std::array<float, 3> sl = {local.pos[0] * parent.scale,
                               local.pos[1] * parent.scale,
                               local.pos[2] * parent.scale};
    // parent.rot * sl
    for (int r = 0; r < 3; ++r) {
        w.pos[r] = parent.pos[r]
                 + parent.rot[r * 3 + 0] * sl[0]
                 + parent.rot[r * 3 + 1] * sl[1]
                 + parent.rot[r * 3 + 2] * sl[2];
    }
    w.scale = parent.scale * local.scale;
    return w;
}

std::unordered_map<std::uint32_t, std::size_t> link_map(const File& f) {
    std::unordered_map<std::uint32_t, std::size_t> m;
    m.reserve(f.block_ids.size());
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) m[f.block_ids[i]] = i;
    return m;
}

// DFS from `idx` accumulating world transform; when a NiCamera is reached,
// fill `out` and return true. NiCamera carries an AvObjectBase (c.av) so its
// own local transform composes on top of the chain.
bool walk(const File& f,
          const std::unordered_map<std::uint32_t, std::size_t>& links,
          std::size_t idx, const Xform& parent,
          std::vector<bool>& seen, SetCamera& out) {
    if (idx >= f.blocks.size() || seen[idx]) return false;
    seen[idx] = true;
    const Block& blk = f.blocks[idx];

    if (auto* cam = std::get_if<NiCamera>(&blk)) {
        Xform w = compose(parent, local_of(cam->av));
        out.rotation = w.rot;
        out.position = w.pos;
        out.frustum = {cam->frustum_left, cam->frustum_right,
                       cam->frustum_top, cam->frustum_bottom};
        out.near_distance = cam->frustum_near;
        out.far_distance = cam->frustum_far;
        return true;
    }
    if (auto* node = std::get_if<NiNode>(&blk)) {
        Xform w = compose(parent, local_of(node->av));
        for (auto link : node->child_links) {
            auto it = links.find(link);
            if (it != links.end() && walk(f, links, it->second, w, seen, out))
                return true;
        }
    }
    return false;
}

std::size_t root_index(const File& f) {
    // The root link maps through block_ids like any other; fall back to 0.
    auto links = link_map(f);
    auto it = links.find(f.root.id);
    return (it != links.end()) ? it->second : 0;
}

}  // namespace

std::optional<SetCamera> find_first_camera(const File& f) {
    if (f.blocks.empty()) return std::nullopt;
    auto links = link_map(f);
    std::vector<bool> seen(f.blocks.size(), false);
    SetCamera out;
    if (walk(f, links, root_index(f), Xform{}, seen, out)) return out;
    // Root walk may miss cameras not under the declared root; sweep any
    // unvisited NiCamera with identity-from-here as a fallback.
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        if (!seen[i]) {
            std::vector<bool> seen2(f.blocks.size(), false);
            if (walk(f, links, i, Xform{}, seen2, out)) return out;
        }
    }
    return std::nullopt;
}

}  // namespace nif
```

Note: `f.root` is a `BlockHandle`; use its raw id field to map to an index. If `BlockHandle`'s id accessor differs (check `native/src/nif/include/nif/block.h:473`), adapt `f.root.id` accordingly — the fallback sweep guarantees the camera is still found if the root mapping is off.

- [ ] **Step 5: Build and run the native test**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target nif_tests
./build/native/tests/nif_tests --gtest_filter='FindFirstCamera.*'
```
Expected: PASS (3 tests; any may `SKIP` if the game asset is absent, but on this workstation all three assets exist, so expect 3 PASS).

- [ ] **Step 6: Commit**

```bash
git add native/src/nif/include/nif/scene_camera.h native/src/nif/src/scene_camera.cc \
        native/src/nif/CMakeLists.txt native/tests/nif/scene_camera_test.cc \
        native/tests/CMakeLists.txt
git commit -m "feat(nif): find_first_camera — extract embedded set camera + world xform

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `parse_set_camera` host binding + `CloneCamera` wiring

Expose `find_first_camera` to Python via a parse-only host binding, and rewrite `CloneCamera` to resolve the SDK path to absolute, call the binding (guarded), and return a `NiCameraData` or `None`.

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add `parse_set_camera` + `m.def` near `load_model` at line 607)
- Modify: `engine/appc/bridge_set.py` (rewrite `ModelManager.CloneCamera`, add module-local game-root constant)
- Modify: `tests/appc/test_camera_object.py` (add CloneCamera guard tests)

**Interfaces:**
- Consumes: `nif::load`, `nif::find_first_camera`, `nif::SetCamera` (Task 2); `NiCameraData` (Task 1).
- Produces:
  - Host binding `parse_set_camera(nif_abs_path: str) -> dict | None` returning
    `{"position": (x,y,z), "rotation": (9 floats, row-major), "frustum": (l,r,t,b), "near": float, "far": float}` or `None`.
  - `ModelManager.CloneCamera(path) -> NiCameraData | None`.

- [ ] **Step 1: Write the failing CloneCamera guard tests**

Append to `tests/appc/test_camera_object.py`:

```python
def test_clonecamera_returns_none_without_host_module(monkeypatch):
    """Headless: the compiled host module is absent -> None (SDK fallback)."""
    import sys
    import App
    monkeypatch.setitem(sys.modules, "_dauntless_host", None)
    assert App.g_kModelManager.CloneCamera("data/Models/Sets/X/x.nif") is None


def test_clonecamera_wraps_binding_result(monkeypatch):
    import sys
    import types
    import App
    fake = types.ModuleType("_dauntless_host")
    fake.parse_set_camera = lambda p: {
        "position": (1.0, 2.0, 3.0),
        "rotation": (1, 0, 0, 0, 1, 0, 0, 0, 1),
        "frustum": (-0.5, 0.5, 0.4, -0.4),
        "near": 1.0, "far": 800.0,
    }
    monkeypatch.setitem(sys.modules, "_dauntless_host", fake)
    data = App.g_kModelManager.CloneCamera("data/Models/Sets/X/x.nif")
    assert data is not None
    assert data.position == (1.0, 2.0, 3.0)
    assert data.frustum == (-0.5, 0.5, 0.4, -0.4)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/appc/test_camera_object.py -k clonecamera -q`
Expected: FAIL — `test_clonecamera_wraps_binding_result` fails (current `CloneCamera` ignores the module and returns `None`).

- [ ] **Step 3: Rewrite `ModelManager.CloneCamera` in `engine/appc/bridge_set.py`**

Add the game-root constant near the top imports (after `from engine.appc.math import ...`):

```python
from pathlib import Path as _Path

# bridge_set.py lives at engine/appc/ -> project root is two parents up.
_GAME_ROOT = _Path(__file__).resolve().parent.parent.parent / "game"
```

Replace the current `CloneCamera` method (the interim `return None` version) with:

```python
    def CloneCamera(self, path):
        """Return the camera embedded in the set NIF, or None when the model
        has none / the renderer isn't present.

        Some set NIFs carry a camera (e.g. starbasecontrolRM.nif has
        'Camera01'); the player bridges do not (DBridge/EBridge), which is
        why MissionLib.SetupBridgeSet hardcodes their coords in the None
        branch. Parsing happens C++-side via the parse-only host binding; in
        headless tests (no compiled module) we return None and the SDK takes
        its fallback branch."""
        try:
            import _dauntless_host
        except ImportError:
            return None
        if _dauntless_host is None or not hasattr(_dauntless_host,
                                                  "parse_set_camera"):
            return None
        nif_abs = str(_GAME_ROOT / path)
        data = _dauntless_host.parse_set_camera(nif_abs)
        if data is None:
            return None
        return NiCameraData(
            position=data["position"],
            rotation=data["rotation"],
            frustum=data["frustum"],
            near=data["near"],
            far=data["far"],
            source=path,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/appc/test_camera_object.py -k clonecamera -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Add the `parse_set_camera` C++ binding**

In `native/src/host/host_bindings.cc`, add the include near the other nif/scenegraph includes (top of file, alongside `#include <scenegraph/camera.h>`):

```cpp
#include <nif/file.h>
#include <nif/scene_camera.h>
```

Add the implementation function near `load_model_impl` (before `PYBIND11_MODULE`):

```cpp
// Parse-only: extract the embedded set camera (frustum + world transform)
// from a NIF without any GL context or asset-cache entry. Feeds
// MissionLib.SetupBridgeSet's embedded-camera path via ModelManager.CloneCamera.
py::object parse_set_camera_impl(const std::string& nif_abs_path) {
    std::filesystem::path path = nif_abs_path;
    if (!std::filesystem::exists(path)) return py::none();
    nif::File f = nif::load(path);
    auto cam = nif::find_first_camera(f);
    if (!cam.has_value()) return py::none();
    py::dict d;
    d["position"] = py::make_tuple(cam->position[0], cam->position[1],
                                   cam->position[2]);
    d["rotation"] = py::make_tuple(
        cam->rotation[0], cam->rotation[1], cam->rotation[2],
        cam->rotation[3], cam->rotation[4], cam->rotation[5],
        cam->rotation[6], cam->rotation[7], cam->rotation[8]);
    d["frustum"] = py::make_tuple(cam->frustum[0], cam->frustum[1],
                                  cam->frustum[2], cam->frustum[3]);
    d["near"] = cam->near_distance;
    d["far"] = cam->far_distance;
    return d;
}
```

Register it inside `PYBIND11_MODULE(_dauntless_host, m)` (after the `m.def("load_model", ...)` at line 607):

```cpp
    m.def("parse_set_camera", &parse_set_camera_impl,
          "Extract the embedded camera (frustum + world transform) from a set "
          "NIF, or None. Parse-only; no GL context required.");
```

Wrap `nif::load(path)` in a `try { ... } catch (const std::exception&) { return py::none(); }` if `load` can throw on malformed input — check `nif::load`'s contract; if it returns a `File` with `eof_reached=false` on error rather than throwing, no try/catch is needed. Default to wrapping defensively:

```cpp
    nif::File f;
    try {
        f = nif::load(path);
    } catch (const std::exception&) {
        return py::none();
    }
```

(`nif::File` is move-only with a default constructor — declaring `f` then move-assigning from `nif::load` is valid.)

- [ ] **Step 6: Ensure the host links the `nif` lib**

The host target already depends on `nif` (it loads ship/bridge models). Confirm with:

Run: `grep -n "nif" native/src/host/CMakeLists.txt`
Expected: `nif` appears in the host target's `target_link_libraries`. If absent, add `nif` there.

- [ ] **Step 7: Rebuild the canonical binary + module**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` (and the `_dauntless_host` module) with no errors.

- [ ] **Step 8: Integration check — E1M1 loads without the crash**

Run:
```bash
timeout 60 ./build/dauntless --developer 2>&1 | tee /tmp/e1m1_run.log | grep -iE "CloneCamera|Traceback|AttributeError|mission swap" || echo "no camera/crash errors"
```
Then trigger the swap to E1M1 via the dev "Load Mission…" picker (or set E1M1 as the startup mission if a flag exists). Expected: no `CloneCamera`/`AttributeError`/`Traceback` lines referencing `SetupBridgeSet`.

Note: this step requires the live renderer and is a manual confirmation — the headless tests in Steps 1-4 already prove the Python contract. If the picker can't be driven non-interactively, confirm via the headless suite + native test and note the manual check as pending.

- [ ] **Step 9: Run the full camera test file**

Run: `uv run pytest tests/appc/test_camera_object.py -q`
Expected: PASS (7 passed).

- [ ] **Step 10: Commit**

```bash
git add native/src/host/host_bindings.cc engine/appc/bridge_set.py tests/appc/test_camera_object.py
git commit -m "feat(spv): CloneCamera returns the real embedded set camera

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Developer-mode comm-set render flag

When a viewscreen is turned on with a remote camera (a comm/remote set requested via `MissionLib.ViewscreenOn`), the RTT path currently ignores it and shows the forward view. Under developer mode, announce this once per activation so the unbuilt comm-render path is not silently forgotten.

**Files:**
- Create: `engine/appc/comm_render_flag.py`
- Modify: `engine/host_loop.py` (step-5c viewscreen drive, around lines 3341-3345)
- Create: `tests/appc/test_comm_render_flag.py`

**Interfaces:**
- Consumes: a viewscreen object exposing `IsOn() -> int` and `GetRemoteCam() -> object | None` (`engine/appc/bridge_set.py:80-90`); `engine.dev_mode.is_enabled()`.
- Produces:
  - `class CommRenderFlag` with `def notice(self, viewscreen_obj) -> bool` — returns `True` and logs a loud one-shot warning the first time it sees a given viewscreen turn on with a remote cam; resets when the viewscreen turns off or clears its remote cam, so the next activation announces again. No-op (returns `False`) when `dev_mode` is disabled.

- [ ] **Step 1: Write the failing test**

Create `tests/appc/test_comm_render_flag.py`:

```python
"""Dev-mode comm-set render flag: announce once per activation."""
import logging
import types

from engine.appc.comm_render_flag import CommRenderFlag


class _VS:
    def __init__(self, on, cam):
        self._on, self._cam = on, cam
    def IsOn(self):
        return self._on
    def GetRemoteCam(self):
        return self._cam


def _patch_dev(monkeypatch, enabled):
    import engine.appc.comm_render_flag as mod
    monkeypatch.setattr(mod.dev_mode, "is_enabled", lambda: enabled)


def test_announces_once_per_activation(monkeypatch, caplog):
    _patch_dev(monkeypatch, True)
    flag = CommRenderFlag()
    vs = _VS(1, object())
    with caplog.at_level(logging.WARNING):
        assert flag.notice(vs) is True       # first frame on -> announce
        assert flag.notice(vs) is False      # same activation -> silent
    assert sum("NOT IMPLEMENTED" in r.message for r in caplog.records) == 1


def test_reactivation_announces_again(monkeypatch):
    _patch_dev(monkeypatch, True)
    flag = CommRenderFlag()
    cam = object()
    assert flag.notice(_VS(1, cam)) is True
    assert flag.notice(_VS(0, cam)) is False   # off -> reset
    assert flag.notice(_VS(1, cam)) is True     # on again -> announce


def test_silent_when_no_remote_cam(monkeypatch):
    _patch_dev(monkeypatch, True)
    assert CommRenderFlag().notice(_VS(1, None)) is False


def test_silent_when_dev_mode_off(monkeypatch):
    _patch_dev(monkeypatch, False)
    assert CommRenderFlag().notice(_VS(1, object())) is False


def test_silent_when_viewscreen_none(monkeypatch):
    _patch_dev(monkeypatch, True)
    assert CommRenderFlag().notice(None) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/appc/test_comm_render_flag.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.comm_render_flag'`.

- [ ] **Step 3: Create `engine/appc/comm_render_flag.py`**

```python
"""Developer-mode flag for the unbuilt comm/remote-set render path.

MissionLib.ViewscreenOn sets a remote camera on the bridge viewscreen
(SetRemoteCam) to show a remote set (e.g. a starbase commander). The
viewscreen RTT currently renders the forward space view and ignores that
remote camera, so comm scenes do not appear. This flag loudly announces the
gap once per activation under developer mode; production (dev off) is a
silent no-op so the render path stays byte-identical.
"""
import logging

from engine import dev_mode

_log = logging.getLogger(__name__)

_BANNER = ("comm-set rendering requested (viewscreen remote maincamera) — "
           "NOT IMPLEMENTED; viewscreen shows forward view instead.")


class CommRenderFlag:
    def __init__(self):
        self._announced_for = None     # id of the remote cam last announced

    def notice(self, viewscreen_obj) -> bool:
        if not dev_mode.is_enabled():
            return False
        if viewscreen_obj is None:
            return False
        cam = (viewscreen_obj.GetRemoteCam()
               if viewscreen_obj.IsOn() else None)
        if cam is None:
            self._announced_for = None      # reset when off / no remote cam
            return False
        if id(cam) == self._announced_for:
            return False                     # same activation -> silent
        self._announced_for = id(cam)
        _log.warning("%s", _BANNER)
        return True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/appc/test_comm_render_flag.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Wire the flag into the host loop**

In `engine/host_loop.py`, near where the controller is set up (where other per-run state lives, e.g. alongside `controller.viewscreen_obj`), construct one flag instance. Add inside the run setup (a module-level singleton is fine since the loop is single-instance):

```python
    from engine.appc.comm_render_flag import CommRenderFlag
    _comm_render_flag = CommRenderFlag()
```

Then in step-5c (lines 3341-3345), after the existing
`r.set_viewscreen_enabled(_viewscreen_feed_on(_vs_obj))` line, add:

```python
            # Dev-only: the RTT shows the forward view; a comm/remote set
            # requested via ViewscreenOn is not yet rendered. Flag it loudly.
            _comm_render_flag.notice(_vs_obj)
```

Place the `_comm_render_flag` construction so it is in scope at line ~3345 (define it just before the main `while` loop, next to `bridge_camera = _BridgeCamera()` around line 2629). Use a name that does not shadow existing locals.

- [ ] **Step 6: Run the Python suite for the touched areas**

Run: `uv run pytest tests/appc/ -q`
Expected: PASS (all camera + comm-flag tests green).

- [ ] **Step 7: Integration check (manual, with the live engine)**

Run `./build/dauntless --developer`, load E1M1, and progress to Admiral Liu's viewscreen scene (`ViewscreenOn("StarbaseSet", "Liu")`). Expected: the `NOT IMPLEMENTED` warning appears once in the console when the viewscreen turns on. Without `--developer`, the warning never appears.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/comm_render_flag.py engine/host_loop.py tests/appc/test_comm_render_flag.py
git commit -m "feat(spv): dev-mode flag for unbuilt comm-set rendering

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Spec §Components 1 (C++ parse binding) → Task 2 (`find_first_camera`) + Task 3 (`parse_set_camera` host binding). ✓
- Spec §Components 2 (Python camera surface) → Task 1 + Task 3 (`CloneCamera` rewrite). ✓
- Spec §Components 3 (dev-mode comm flag) → Task 4. ✓
- Spec §Data flow → exercised end-to-end by Task 1 Step 6-7 (SetupBridgeSet) + Task 3 Step 8 (integration). ✓
- Spec §Error handling (module absent / bad NIF / no camera → None → fallback) → Task 3 Steps 1-3 + Task 2 fallback sweep + `parse_set_camera` exists check. ✓
- Spec §Testing (headless unit, native, integration) → Tasks 1-4 test steps. ✓
- Spec §Out of scope (comm rendering itself) → not built; flagged by Task 4. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases". Two explicit verify-against-codebase notes (Task 2 Step 4 `f.root.id` accessor; Task 3 Step 5 `nif::load` throw behaviour; Task 3 Step 6 host links `nif`) — each gives a concrete check command and a safe default, not a deferral.

**Type consistency:** `NiCameraData` fields (`position`, `rotation`, `frustum`, `near`, `far`, `source`) match between Task 1 (definition), Task 3 (construction from the binding dict), and the binding's returned dict keys. `nif::SetCamera` fields (`position`, `rotation`, `frustum`, `near_distance`, `far_distance`) are consistent between Task 2 header, impl, and Task 3 binding. `CameraObjectClass` orientation is a `TGMatrix3` in both factories. Rotation is row-major throughout (Mat3x3.m → dict → `TGMatrix3.Set`).

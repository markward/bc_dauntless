# Subsystem Target Reticle & Camera Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the player locks an off-centre subsystem, focus the tracking camera on it and draw BC's faithful two-element reticle (full-ship corner box + subsystem crosshair).

**Architecture:** A single pure-Python module (`engine/ui/target_reticle.py`) resolves both the camera look-at point and the reticle draw payload from one shared subsystem-world-position routine, so they can never disagree. The tracking camera gains an `aim_point` override; a new native GL billboard pass (`TargetReticlePass`, cloned from `SubsystemPinPass`) draws the `target.tga` corners and `subtarget.tga` crosshair. The unrotated `GetWorldLocation` bug is fixed and de-duplicated as part of the same work.

**Tech Stack:** Python 3 (engine + tests, pytest), C++17 + OpenGL 3.3 (renderer), pybind11 host bindings, CMake (embedded-shader headers), GLM.

**Spec:** `docs/superpowers/specs/2026-06-09-subsystem-target-reticle-and-camera-design.md`

---

## File Structure

**Create:**
- `engine/ui/target_reticle.py` — `target_aim_point()`, `build_target_reticle()`, `TargetReticlePayload`.
- `native/src/renderer/include/renderer/target_reticle_pass.h` — `TargetReticle` struct + `TargetReticlePass` class.
- `native/src/renderer/target_reticle_pass.cc` — the GL pass.
- `native/src/renderer/shaders/target_reticle.vert`, `target_reticle.frag` — billboard + texture sample with per-corner UV flip.
- `tests/unit/test_target_reticle.py` — pure-Python tests for the new module.

**Modify:**
- `engine/appc/subsystems.py` — add canonical `subsystem_world_position()`; fix `_ShipSubsystem.GetWorldLocation` to rotate through R.
- `engine/ui/ship_property_viewer.py:14` — `subsystem_world_position` becomes a thin re-export (keeps existing import sites working).
- `engine/cameras/tracking.py:128` — add `aim_point=None` to `compute()`.
- `engine/cameras/director.py:122,135` — pass `target_aim_point(player)` into both `tracking.compute(...)` calls.
- `engine/renderer.py:321` — add `set_target_reticle()` / `clear_target_reticle()` wrappers.
- `native/src/renderer/CMakeLists.txt` — embed the two new shaders; add the `.cc` to the renderer lib.
- `native/src/renderer/pipeline.cc`, `native/src/renderer/include/renderer/pipeline.h` — `target_reticle_shader()` accessor.
- `native/src/host/host_bindings.cc` — global + init/teardown/draw + `set_target_reticle`/`clear_target_reticle` bindings.
- `engine/host_loop.py:2680,2692,2695` — per-frame reticle feed + SPV-open hide.
- Combat/weapon tests (audit, Task 1).

---

## Task 1: Fix & de-duplicate subsystem world position

**Files:**
- Modify: `engine/appc/subsystems.py` (add module fn; `GetWorldLocation` ~line 743)
- Modify: `engine/ui/ship_property_viewer.py:14-40`
- Test: `tests/unit/test_subsystems.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_subsystems.py`:

```python
def test_subsystem_world_location_rotates_offset():
    """GetWorldLocation must rotate the local mount through the ship's
    world rotation (R · local), not add the raw body-frame offset."""
    import math
    from engine.appc.math import TGPoint3, TGMatrix3
    from engine.appc.subsystems import _ShipSubsystem, subsystem_world_position

    class _FakeShip:
        def __init__(self, loc, rot):
            self._loc, self._rot = loc, rot
        def GetWorldLocation(self):  return self._loc
        def GetWorldRotation(self):  return self._rot

    # 90° yaw about Z: ship-+X local maps to world +Y (column-vector R).
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    ship = _FakeShip(TGPoint3(100.0, 0.0, 0.0), R)

    sub = _ShipSubsystem("Port Nacelle")
    sub._position = TGPoint3(10.0, 0.0, 0.0)    # +10 along ship local X
    sub.SetParentShip(ship)

    w = sub.GetWorldLocation()
    # R·(10,0,0) for a +90° Z rotation = (0, 10, 0); plus ship loc (100,0,0).
    assert abs(w.x - 100.0) < 1e-5
    assert abs(w.y -  10.0) < 1e-5
    assert abs(w.z -   0.0) < 1e-5
    # The free function must agree with the method.
    w2 = subsystem_world_position(sub, ship)
    assert abs(w.x - w2.x) < 1e-9 and abs(w.y - w2.y) < 1e-9 and abs(w.z - w2.z) < 1e-9
```

(`_ShipSubsystem` has no `SetPosition` setter, so the test sets `sub._position` directly — it is initialised at subsystems.py:365. `SetParentShip` exists at subsystems.py:604.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystems.py::test_subsystem_world_location_rotates_offset -v`
Expected: FAIL — `assert abs(w.y - 10.0) < 1e-5` fails (current code returns the unrotated `(110, 0, 0)`), or ImportError on `subsystem_world_position`.

- [ ] **Step 3: Add the canonical function + fix the method**

In `engine/appc/subsystems.py`, add at module level (near the top, after imports):

```python
def subsystem_world_position(sub, ship=None):
    """World mount point of a subsystem: ship_loc + R · local_mount.

    Column-vector rotation convention (R · v); NO scale — BC stores mounts
    in world units relative to the ship centre. Returns the ship location if
    the subsystem has no 3D mount, and the origin if no ship is resolvable.

    ``ship`` may be passed explicitly (required for the Hull/root subsystem,
    whose ``_climb_to_ship()`` returns None).
    """
    from engine.appc.math import TGPoint3, TGMatrix3
    if ship is None:
        ship = sub._climb_to_ship() if hasattr(sub, "_climb_to_ship") else None
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return TGPoint3(0.0, 0.0, 0.0)
    ship_pos = ship.GetWorldLocation()
    local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
    if not isinstance(local, TGPoint3):
        return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
    offset = TGPoint3(local.x, local.y, local.z)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)   # R · offset (column-vector)
    return TGPoint3(ship_pos.x + offset.x,
                    ship_pos.y + offset.y,
                    ship_pos.z + offset.z)
```

Replace the body of `_ShipSubsystem.GetWorldLocation` (subsystems.py:743) with:

```python
    def GetWorldLocation(self) -> TGPoint3:
        if self._parent_ship is not None:
            return subsystem_world_position(self, self._parent_ship)
        return self.GetPositionTG()
```

- [ ] **Step 4: De-duplicate the UI helper**

Replace `engine/ui/ship_property_viewer.py:14-40` (the whole `def subsystem_world_position(...)` block) with a re-export so existing import sites keep working:

```python
# Canonical implementation lives in engine.appc.subsystems so the renderer,
# camera, and Ship Property Viewer all share one source of truth.
from engine.appc.subsystems import subsystem_world_position  # noqa: F401
```

Keep the `from engine.appc.math import TGPoint3, TGMatrix3` import already present below it (still used by the camera/projection code in that file).

- [ ] **Step 5: Run the new test + the UI helper's existing tests**

Run: `uv run pytest tests/unit/test_subsystems.py::test_subsystem_world_location_rotates_offset tests/ui/test_ship_property_viewer.py -v`
Expected: PASS. If a ship_property_viewer test asserted an *unrotated* pin position with a rotated ship, update it to the correct `R·local` value (the previous value was the bug).

- [ ] **Step 6: Audit weapon/combat tests for unrotated expectations**

Run: `uv run pytest tests/unit/test_combat_hit_resolution.py tests/unit/test_shield_face_from_hit_point.py tests/unit/test_phaser_fire_range_gate.py tests/unit/test_torpedo_tube_fire_dumb.py tests/unit/test_weapons_disabled_blocks_fire.py tests/unit/test_fire_script_choose_subsystem.py -v`
Expected: PASS. Tests using an identity ship rotation are unaffected (R·local == local). For any failure, confirm the new value equals `ship_loc + R·local` and update the expected constant; do not revert the fix.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/subsystems.py engine/ui/ship_property_viewer.py tests/unit/test_subsystems.py
git add -u tests/
git commit -m "fix(subsystems): rotate subsystem world position through ship R

GetWorldLocation added the body-frame mount offset without rotating it,
so off-centre subsystems mislocated on any pitched/rolled ship (weapon
aim leaned on this). Extract one canonical subsystem_world_position and
share it between the method and the Ship Property Viewer helper.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `engine/ui/target_reticle.py` — shared decision module

**Files:**
- Create: `engine/ui/target_reticle.py`
- Test: `tests/unit/test_target_reticle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_target_reticle.py`:

```python
import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import _ShipSubsystem
from engine.ui.target_reticle import target_aim_point, build_target_reticle


class _Sub(_ShipSubsystem):
    pass


def _ship(loc, rot, radius=5.0):
    class _Ship:
        def __init__(self):
            self._t = None
            self._sub = None
        def GetWorldLocation(self): return loc
        def GetWorldRotation(self): return rot
        def GetRadius(self): return radius
        def GetTarget(self): return self._t
        def GetTargetSubsystem(self): return self._sub
    return _Ship()


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def test_aim_point_no_target_is_none():
    p = _ship(TGPoint3(0, 0, 0), _identity())
    assert target_aim_point(p) is None


def test_aim_point_target_no_subsystem_is_hull_centre():
    tgt = _ship(TGPoint3(200, 0, 0), _identity())
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    a = target_aim_point(p)
    assert (abs(a.x - 200) < 1e-6 and abs(a.y) < 1e-6 and abs(a.z) < 1e-6)


def test_aim_point_subsystem_uses_rotated_world_pos():
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    tgt = _ship(TGPoint3(200, 0, 0), R)
    sub = _Sub("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt)
    tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    a = target_aim_point(p)
    # ship (200,0,0) + R·(10,0,0) = (200, 10, 0)
    assert abs(a.x - 200) < 1e-5 and abs(a.y - 10) < 1e-5 and abs(a.z) < 1e-5


def test_aim_point_destroyed_subsystem_falls_back_to_hull():
    tgt = _ship(TGPoint3(200, 0, 0), _identity())
    sub = _Sub("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt); sub.SetDestroyed(True)
    tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    a = target_aim_point(p)
    assert abs(a.x - 200) < 1e-6 and abs(a.y) < 1e-6


def test_build_reticle_invisible_without_target():
    p = _ship(TGPoint3(0, 0, 0), _identity())
    r = build_target_reticle(p)
    assert r.visible is False


def test_build_reticle_box_only_when_no_subsystem():
    tgt = _ship(TGPoint3(200, 0, 0), _identity(), radius=7.0)
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    r = build_target_reticle(p)
    assert r.visible is True
    assert abs(r.ship_radius - 7.0) < 1e-6
    assert r.subtarget_pos is None


def test_build_reticle_subtarget_agrees_with_aim_point():
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    tgt = _ship(TGPoint3(200, 0, 0), R)
    sub = _Sub("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt); tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    r = build_target_reticle(p)
    a = target_aim_point(p)
    assert r.subtarget_pos is not None
    assert abs(r.subtarget_pos[0] - a.x) < 1e-9
    assert abs(r.subtarget_pos[1] - a.y) < 1e-9
    assert abs(r.subtarget_pos[2] - a.z) < 1e-9
```

Confirm `_ShipSubsystem` has `SetDestroyed` (subsystems.py ~427 mentions `SetDestroyed`/`SetDamaged`). If the method differs, set `sub._destroyed = True` directly (initialised at subsystems.py:433) and check `IsDestroyed()` in Step 3.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_reticle.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.ui.target_reticle`.

- [ ] **Step 3: Implement the module**

Create `engine/ui/target_reticle.py`:

```python
"""Single source of truth for subsystem-target focus: the tracking-camera
look-at point and the on-screen reticle payload. Pure Python (no GL/CEF).

See docs/superpowers/specs/2026-06-09-subsystem-target-reticle-and-camera-design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from engine.appc.subsystems import subsystem_world_position


@dataclass
class TargetReticlePayload:
    visible: bool = False
    ship_center: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    ship_radius: float = 0.0
    subtarget_pos: Optional[Tuple[float, float, float]] = None


def _valid_target(player):
    """The player's current target if it is a real, non-self object."""
    get = getattr(player, "GetTarget", None)
    if get is None:
        return None
    tgt = get()
    if tgt is None or tgt is player:
        return None
    return tgt


def _valid_subsystem(target):
    """The locked subsystem if present and not destroyed, else None."""
    get = getattr(target, "GetTargetSubsystem", None)
    if get is None:
        return None
    sub = get()
    if sub is None:
        return None
    is_destroyed = getattr(sub, "IsDestroyed", None)
    if is_destroyed is not None and is_destroyed():
        return None
    return sub


def target_aim_point(player):
    """World point the tracking camera should orbit, or None if no valid
    target. Subsystem world position when a valid subsystem is locked,
    otherwise the target's hull centre."""
    target = _valid_target(player)
    if target is None:
        return None
    sub = _valid_subsystem(target)
    if sub is not None:
        return subsystem_world_position(sub, target)
    return target.GetWorldLocation()


def build_target_reticle(player) -> TargetReticlePayload:
    """Describe what the reticle pass should draw this frame."""
    target = _valid_target(player)
    if target is None:
        return TargetReticlePayload(visible=False)
    centre = target.GetWorldLocation()
    radius = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    sub = _valid_subsystem(target)
    subtarget = None
    if sub is not None:
        w = subsystem_world_position(sub, target)
        subtarget = (w.x, w.y, w.z)
    return TargetReticlePayload(
        visible=True,
        ship_center=(centre.x, centre.y, centre.z),
        ship_radius=float(radius or 0.0),
        subtarget_pos=subtarget,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_reticle.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_reticle.py tests/unit/test_target_reticle.py
git commit -m "feat(targeting): target_reticle module (camera aim + reticle payload)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Tracking camera `aim_point` override

**Files:**
- Modify: `engine/cameras/tracking.py:128`
- Modify: `engine/cameras/director.py:122,135`
- Test: `tests/unit/test_tracking_aim_point.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tracking_aim_point.py`:

```python
import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.cameras.tracking import _TrackingCamera


class _Obj:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def test_aim_point_overrides_target_world_location():
    cam = _TrackingCamera()
    cam.set_ship_radius(5.0)
    player = _Obj(TGPoint3(0, 0, 0), _identity())
    target = _Obj(TGPoint3(200, 0, 0), _identity())
    aim = TGPoint3(200, 10, 0)   # an off-centre subsystem on the target

    # dt=None → solver geometry only (deterministic, no springs).
    eye_h, look_h, up_h = cam.compute(player=player, target=target, dt=None)
    eye_a, look_a, up_a = cam.compute(player=player, target=target, dt=None,
                                      aim_point=aim)
    # The look-at must shift toward the aim point's +Y (it did not before).
    assert look_a[1] > look_h[1] + 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tracking_aim_point.py -v`
Expected: FAIL — `compute() got an unexpected keyword argument 'aim_point'`.

- [ ] **Step 3: Add the `aim_point` parameter**

In `engine/cameras/tracking.py`, change the signature at line 128 and the `T` assignment at line 146:

```python
    def compute(self, player, target, dt, aim_point=None):
```

```python
        S = player.GetWorldLocation()
        T = aim_point if aim_point is not None else target.GetWorldLocation()
```

Leave the rest of the method unchanged (the docstring may note: "When `aim_point` is given, it replaces the target hull centre as the framed point T.").

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tracking_aim_point.py -v`
Expected: PASS.

- [ ] **Step 5: Wire the director**

In `engine/cameras/director.py`, add the import near the top:

```python
from engine.ui.target_reticle import target_aim_point
```

In `compute(self, *, player, dt)`, both `return self.tracking.compute(player=player, target=tgt, dt=dt)` sites (lines 122 and 135) become:

```python
                return self.tracking.compute(player=player, target=tgt, dt=dt,
                                             aim_point=target_aim_point(player))
```

(`target_aim_point` returns the subsystem world pos when one is locked, else the hull centre — identical to the old behaviour when there is no subsystem.)

- [ ] **Step 6: Run the camera test suite**

Run: `uv run pytest tests/unit/test_tracking_aim_point.py tests/ -k "tracking or director" -v`
Expected: PASS. (Existing tracking/director geometry tests still pass — with no subsystem locked, `aim_point` equals the hull centre.)

- [ ] **Step 7: Commit**

```bash
git add engine/cameras/tracking.py engine/cameras/director.py tests/unit/test_tracking_aim_point.py
git commit -m "feat(camera): re-centre tracking camera on locked subsystem

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Native `TargetReticlePass` (GL billboard pass)

No unit test (consistent with the other renderer passes); verified by build + Task 7 manual check.

**Files:**
- Create: `native/src/renderer/include/renderer/target_reticle_pass.h`
- Create: `native/src/renderer/target_reticle_pass.cc`
- Create: `native/src/renderer/shaders/target_reticle.vert`, `target_reticle.frag`
- Modify: `native/src/renderer/CMakeLists.txt`
- Modify: `native/src/renderer/pipeline.cc`, `native/src/renderer/include/renderer/pipeline.h`

- [ ] **Step 1: Write the shaders**

Create `native/src/renderer/shaders/target_reticle.vert`:

```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // unit quad corner in [-0.5, 0.5]
uniform mat4  u_view_proj;
uniform vec3  u_center_world;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform float u_size_world;
uniform vec2  u_uv_flip;                  // (+1/-1) per axis to mirror art
out vec2 v_uv;
void main() {
    vec3 offset = (u_camera_right * a_corner.x + u_camera_up * a_corner.y) * u_size_world;
    v_uv = vec2(0.5) + a_corner * u_uv_flip;   // mirror by flipping about centre
    gl_Position = u_view_proj * vec4(u_center_world + offset, 1.0);
}
```

Create `native/src/renderer/shaders/target_reticle.frag`:

```glsl
#version 330 core
in vec2 v_uv;
uniform sampler2D u_tex;   // reticle art (target corner / subtarget crosshair)
out vec4 frag;
void main() {
    vec4 t = texture(u_tex, v_uv);
    if (t.a < 0.01) discard;
    frag = t;
}
```

- [ ] **Step 2: Write the pass header**

Create `native/src/renderer/include/renderer/target_reticle_pass.h`:

```cpp
// native/src/renderer/include/renderer/target_reticle_pass.h
#pragma once

#include <assets/texture.h>

#include <memory>

#include <glm/glm.hpp>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Faithful BC two-element target reticle:
///   - four target.tga corner billboards boxing the whole target ship
///     (sized from the target's bounding-sphere radius), and
///   - one subtarget.tga crosshair on the locked subsystem (optional).
/// Drawn depth-test OFF so the reticle is always visible over the hull.
struct TargetReticle {
    bool      visible       = false;
    glm::vec3 ship_center   {0.0f};
    float     ship_radius   = 0.0f;
    bool      has_subtarget = false;
    glm::vec3 subtarget_pos {0.0f};
};

class TargetReticlePass {
public:
    TargetReticlePass();
    ~TargetReticlePass();
    TargetReticlePass(const TargetReticlePass&)            = delete;
    TargetReticlePass& operator=(const TargetReticlePass&) = delete;

    void render(const TargetReticle& reticle,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    void ensure_quad();
    void ensure_textures();

    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    std::unique_ptr<assets::Texture> corner_tex_;     // game/data/target.tga
    std::unique_ptr<assets::Texture> crosshair_tex_;  // game/data/subtarget.tga
    bool textures_loaded_ = false;
};

}  // namespace renderer
```

- [ ] **Step 3: Write the pass implementation**

Create `native/src/renderer/target_reticle_pass.cc`:

```cpp
// native/src/renderer/target_reticle_pass.cc
#include "renderer/target_reticle_pass.h"
#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdio>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <vector>

namespace renderer {

namespace {

constexpr const char* kCornerFile    = "game/data/target.tga";
constexpr const char* kCrosshairFile = "game/data/subtarget.tga";

// Constant on-screen size (pixels) for each corner glyph and the crosshair.
constexpr float kCornerSizePx    = 24.0f;
constexpr float kCrosshairSizePx = 20.0f;

std::unique_ptr<assets::Texture> load_tga(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[target_reticle] failed to open '%s'\n", path);
        return std::make_unique<assets::Texture>();
    }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        return std::make_unique<assets::Texture>(std::move(tex));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[target_reticle] decode/upload '%s' failed: %s\n",
                     path, e.what());
        return std::make_unique<assets::Texture>();
    }
}

}  // namespace

TargetReticlePass::TargetReticlePass()  = default;
TargetReticlePass::~TargetReticlePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void TargetReticlePass::ensure_quad() {
    if (quad_vao_) return;
    const float corners[12] = {
        -0.5f, -0.5f,   0.5f, -0.5f,   0.5f,  0.5f,
        -0.5f, -0.5f,   0.5f,  0.5f,  -0.5f,  0.5f,
    };
    glGenVertexArrays(1, &quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindVertexArray(quad_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(corners), corners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void TargetReticlePass::ensure_textures() {
    if (textures_loaded_) return;
    textures_loaded_ = true;
    corner_tex_    = load_tga(kCornerFile);
    crosshair_tex_ = load_tga(kCrosshairFile);
}

void TargetReticlePass::render(const TargetReticle& reticle,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline) {
    if (!reticle.visible) return;
    ensure_quad();
    ensure_textures();

    auto& shader = pipeline.target_reticle_shader();
    shader.use();

    const glm::mat4 view = camera.view_matrix();
    const glm::mat4 vp   = camera.proj_matrix() * view;
    shader.set_mat4("u_view_proj", vp);

    // World-space camera basis = rows of the view rotation (see pin pass).
    const glm::vec3 cam_right(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up   (view[0][1], view[1][1], view[2][1]);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_tex", 0);

    // px → world conversion at a given distance (constant on-screen size).
    const glm::mat4 proj = camera.proj_matrix();
    const float tan_half = (proj[1][1] != 0.0f) ? (1.0f / proj[1][1]) : 1.0f;
    GLint vp_rect[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp_rect);
    const float viewport_h = (vp_rect[3] > 0) ? static_cast<float>(vp_rect[3]) : 1.0f;
    const glm::vec3 eye = camera.eye;
    auto world_for_px = [&](const glm::vec3& at, float px) {
        return glm::length(at - eye) * (2.0f * px * tan_half / viewport_h);
    };

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    // --- Full-ship corner box (target.tga) ---
    glBindTexture(GL_TEXTURE_2D, corner_tex_ ? corner_tex_->id() : 0);
    const float r = reticle.ship_radius;
    const float corner_size = world_for_px(reticle.ship_center, kCornerSizePx);
    // (sign_right, sign_up, uv_flip_x, uv_flip_y) — UL, UR, LL, LR.
    const float corners[4][4] = {
        {-1.0f,  1.0f,  1.0f,  1.0f},   // upper-left  (art as authored)
        { 1.0f,  1.0f, -1.0f,  1.0f},   // upper-right (mirror H)
        {-1.0f, -1.0f,  1.0f, -1.0f},   // lower-left  (mirror V)
        { 1.0f, -1.0f, -1.0f, -1.0f},   // lower-right (mirror H+V)
    };
    for (const auto& c : corners) {
        const glm::vec3 centre = reticle.ship_center
                               + cam_right * (c[0] * r)
                               + cam_up    * (c[1] * r);
        shader.set_vec3 ("u_center_world", centre);
        shader.set_float("u_size_world",   corner_size);
        shader.set_vec2 ("u_uv_flip", glm::vec2(c[2], c[3]));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // --- Subtarget crosshair (subtarget.tga) ---
    if (reticle.has_subtarget) {
        glBindTexture(GL_TEXTURE_2D, crosshair_tex_ ? crosshair_tex_->id() : 0);
        shader.set_vec3 ("u_center_world", reticle.subtarget_pos);
        shader.set_float("u_size_world",
                         world_for_px(reticle.subtarget_pos, kCrosshairSizePx));
        shader.set_vec2 ("u_uv_flip", glm::vec2(1.0f, 1.0f));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glBindVertexArray(0);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

Confirm `Shader` exposes `set_vec2` (the pin pass uses `set_vec3`/`set_float`/`set_int`/`set_mat4`). If `set_vec2` is absent, add it next to `set_vec3` in `native/src/renderer/shader.{h,cc}` mirroring the `set_vec3` body (`glUniform2f`).

- [ ] **Step 4: Register the shader in the pipeline**

In `native/src/renderer/include/renderer/pipeline.h`, add the accessor after `subsystem_pin_shader()` (line 25):

```cpp
    Shader& target_reticle_shader() noexcept  { return *target_reticle_; }
```

and the member after `subsystem_pin_` (line 41):

```cpp
    std::unique_ptr<Shader> target_reticle_;
```

In `native/src/renderer/pipeline.cc`, add the includes near line 29:

```cpp
#include "embedded_target_reticle_vs.h"
#include "embedded_target_reticle_fs.h"
```

and the construction after line 49:

```cpp
    target_reticle_ = std::make_unique<Shader>(shader_src::target_reticle_vs, shader_src::target_reticle_fs);
```

- [ ] **Step 5: Embed shaders + add the source in CMake**

In `native/src/renderer/CMakeLists.txt`, after line 37 (the subsystem_pin embeds):

```cmake
embed_shader(SHADER_TARGET_RETICLE_VS shaders/target_reticle.vert target_reticle_vs)
embed_shader(SHADER_TARGET_RETICLE_FS shaders/target_reticle.frag target_reticle_fs)
```

and add to the `add_library(renderer STATIC ...)` list after `subsystem_pin_pass.cc` (line 74):

```cmake
    target_reticle_pass.cc
```

- [ ] **Step 6: Reconfigure + build (shaders changed → reconfigure required)**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: builds `build/dauntless` with no errors. (Per project rule, `.vert`/`.frag` changes need the `cmake -B build -S .` reconfigure to regenerate embedded headers.)

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/target_reticle_pass.cc \
        native/src/renderer/include/renderer/target_reticle_pass.h \
        native/src/renderer/shaders/target_reticle.vert \
        native/src/renderer/shaders/target_reticle.frag \
        native/src/renderer/pipeline.cc \
        native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): TargetReticlePass (full-ship box + subtarget crosshair)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Host binding + `renderer.py` wrappers

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py:332`

- [ ] **Step 1: Add the global + lifecycle in host_bindings.cc**

Add the include near host_bindings.cc:32:

```cpp
#include <renderer/target_reticle_pass.h>
```

Add globals near host_bindings.cc:101 (after `g_subsystem_pin_pass`):

```cpp
renderer::TargetReticle                     g_target_reticle;
std::unique_ptr<renderer::TargetReticlePass> g_target_reticle_pass;
```

In the init block, after host_bindings.cc:218:

```cpp
    g_target_reticle_pass = std::make_unique<renderer::TargetReticlePass>();
```

In `shutdown()`, after host_bindings.cc:258:

```cpp
    g_target_reticle = renderer::TargetReticle{};
    g_target_reticle_pass.reset();
```

In the per-frame draw block, after host_bindings.cc:343 (the subsystem-pin render):

```cpp
    if (g_target_reticle_pass && g_target_reticle.visible)
        g_target_reticle_pass->render(g_target_reticle, g_camera, *g_pipeline);
```

- [ ] **Step 2: Add the pybind bindings**

After the `clear_subsystem_pins` binding (host_bindings.cc:842):

```cpp
    m.def("set_target_reticle",
          [](bool visible,
             std::array<float, 3> ship_center, float ship_radius,
             py::object subtarget_pos) {
              g_target_reticle.visible     = visible;
              g_target_reticle.ship_center = {ship_center[0], ship_center[1], ship_center[2]};
              g_target_reticle.ship_radius = ship_radius;
              if (subtarget_pos.is_none()) {
                  g_target_reticle.has_subtarget = false;
              } else {
                  auto s = subtarget_pos.cast<std::array<float, 3>>();
                  g_target_reticle.has_subtarget = true;
                  g_target_reticle.subtarget_pos = {s[0], s[1], s[2]};
              }
          },
          py::arg("visible"), py::arg("ship_center"), py::arg("ship_radius"),
          py::arg("subtarget_pos"),
          "Set the target reticle: full-ship corner box at ship_center sized "
          "by ship_radius (GU), plus an optional subtarget crosshair at "
          "subtarget_pos (x,y,z) or None. Applied each frame().");
    m.def("clear_target_reticle",
          []() { g_target_reticle = renderer::TargetReticle{}; },
          "Hide the target reticle. Takes effect next frame().");
```

- [ ] **Step 3: Add the Python wrappers**

In `engine/renderer.py`, after `clear_subsystem_pins` (line 332):

```python
def set_target_reticle(payload) -> None:
    """Feed the target reticle pass from a target_reticle.TargetReticlePayload.

    No-ops silently if the host binding is unavailable (headless tests).
    """
    fn = getattr(_h, "set_target_reticle", None)
    if fn is None:
        return
    fn(payload.visible, payload.ship_center, payload.ship_radius,
       payload.subtarget_pos)


def clear_target_reticle() -> None:
    """Hide the target reticle. Takes effect next frame()."""
    fn = getattr(_h, "clear_target_reticle", None)
    if fn is not None:
        fn()
```

- [ ] **Step 4: Rebuild the host module**

Run:
```bash
cmake --build build -j
```
Expected: builds with no errors (no shader change this task, so no reconfigure needed).

- [ ] **Step 5: Smoke-check the binding exists**

Run:
```bash
./build/dauntless --help >/dev/null 2>&1; echo "binary ok"
```
Expected: prints `binary ok` (the binary loads; the binding is registered at import).

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(host): set_target_reticle / clear_target_reticle bindings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Per-frame feed in host_loop

**Files:**
- Modify: `engine/host_loop.py` (camera apply block, ~2680–2697)

- [ ] **Step 1: Add the import**

Near the other `engine.ui` imports at the top of `engine/host_loop.py`, add:

```python
from engine.ui.target_reticle import build_target_reticle
```

- [ ] **Step 2: Hide the reticle while the Ship Property Viewer is open**

In the `if _spv_open:` branch, after the `r.set_subsystem_pins([...])` call (host_loop.py:2680-2684), add:

```python
                r.clear_target_reticle()
```

- [ ] **Step 3: Feed the reticle in the normal gameplay path**

In the `else:` branch, after the `r.set_camera(eye=eye, ...)` call (host_loop.py:2695-2697), add:

```python
                if player is not None:
                    r.set_target_reticle(build_target_reticle(player))
                else:
                    r.clear_target_reticle()
```

- [ ] **Step 4: Build (no shader change)**

Run: `cmake --build build -j`
Expected: builds clean. (Python-only edit, but confirm nothing else broke.)

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): feed target reticle each frame; hide during SPV

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Build, focused test sweep, manual verification

**Files:** none (verification only)

- [ ] **Step 1: Reconfigure + full build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `build/dauntless` builds with no errors.

- [ ] **Step 2: Focused Python test sweep (NEVER the full suite — it OOMs the machine)**

Run:
```bash
uv run pytest tests/unit/test_target_reticle.py \
              tests/unit/test_tracking_aim_point.py \
              tests/unit/test_subsystems.py \
              tests/ui/test_ship_property_viewer.py -v
```
Expected: all PASS.

- [ ] **Step 3: Manual verification in the developer build**

Run: `./build/dauntless --developer`

Confirm against the spec's acceptance list:
1. Lock a Galaxy and confirm the four corner brackets box the whole ship and scale as you change range.
2. Lock the **Port Warp** (or Star Warp) nacelle: the `subtarget.tga` crosshair sits on the nacelle, not the hull centre.
3. The tracking camera eases to centre the nacelle (no hard snap; springs carry it).
4. Switch between subsystems (impulse pods, bridge): crosshair and camera move smoothly together.
5. Destroy the locked subsystem: the crosshair disappears and the camera recentres on the hull; the full-ship box remains.
6. Clear the subsystem (target ship only): box shows, no crosshair; works in chase view too.
7. Open the Ship Property Viewer (dev pause menu): the gameplay reticle is hidden; on close it returns.

- [ ] **Step 4: Final commit (only if any verification tweak was needed)**

If Step 3 required tuning `kCornerSizePx` / `kCrosshairSizePx` or the `ship_screen_radius` factor:

```bash
git add native/src/renderer/target_reticle_pass.cc
git commit -m "tune(renderer): target reticle on-screen sizing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review notes

- **Spec coverage:** §Architecture→Task 2; §Camera→Task 3; §Reticle pass→Task 4; §Host wiring→Tasks 5–6; §Folded-in fix→Task 1; §Testing→Tasks 1–3,7; §box-visible-any-view→Task 6 (fed every frame regardless of camera mode). All covered.
- **Validity/edge cases:** `_valid_subsystem` (destroyed→fallback), `_valid_target` (none/self→hidden), no-mount (helper returns ship centre) — Task 2 tests.
- **Camera rules:** body-up unchanged (`R.GetCol(2)`); only the look-at point moves; billboards use camera-space right/up — no world-Z introduced.
- **Type consistency:** `TargetReticlePayload` fields (`visible`, `ship_center`, `ship_radius`, `subtarget_pos`) match the `set_target_reticle` wrapper (Task 5) and the binding args; C++ `TargetReticle` mirrors them.

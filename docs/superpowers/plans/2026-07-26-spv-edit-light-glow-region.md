# SPV Edit Light — Glow-Region Shape & Size Editing (with real Box glow) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real Box glow-region shape to the renderer, then let the Ship Property Viewer edit a light-bearing subsystem's glow region (shape + size) and persist it into the machine-owned `hardpoint_overrides.py`, staged behind an explicit Save.

**Architecture:** Phase 0 makes Box a genuine third renderable glow shape (shader box branch via a 5th uniform, native box primitive + upload + binding, Python resolve/register, debug wireframe box). Phase 1 adds the Edit Light UI on top of the merged radius editor: a `set_region` writer op, a mixed-edit routing target, a descriptor `light` flag, panel staging, live-preview wiring, and a mouse-only shape-picker modal. All three shapes preview live.

**Tech Stack:** Python 3 (engine + pytest), C++/GLSL (native renderer, host bindings, GLFW/OpenGL), CEF (HTML/CSS/JS).

## Global Constraints

- **Design:** `docs/superpowers/specs/2026-07-26-spv-edit-light-glow-region-design.md`.
- **Dev-only:** the SPV is constructed only under `--developer`; production render/logic stays byte-identical. Capsule/sphere glow leaves the new `u_glow_region_e` uniform zeroed → the box branch is never taken.
- **Machine-owned file:** `hardpoint_overrides.py` is 100% emitter output; `emit(read_models(module)) == source` must hold. Never hand-edit it.
- **Crash-safe writes:** emitted text must `ast.parse`; write atomically (`os.replace`); a failure aborts without touching the file.
- **Build:** single tree at `build/`. Shader/`.frag`/`.vert` edits need `cmake -B build -S .` (reconfigure) before `cmake --build build -j`. `host_bindings.cc`/`frame.cc`/renderer edits need `cmake --build build -j`. CEF JS/HTML/CSS is runtime-loaded from source — no rebuild.
- **Test gate:** `scripts/check_tests.sh` green. `tests/known_failures.txt` is the authority — it currently expects the C++ suite **fully green** (no baselined failures).
- **Rotation convention:** column-vector, right-handed. World-forward = `GetCol(1)`. Body→world direction = `v.MultMatrixLeft(R)` (= `R·v`). No renderer reflection.
- **Game units:** everything spatial is GU; only convert at display. Never name a var `*_m`/`*_mps`.
- **Shared checkout:** stage commits with EXPLICIT pathspecs only. NEVER `git add -A`/`git add .`/`git checkout`/`git restore`/`git stash`/`git reset --hard`/`git clean`. (A concurrent session's `docs/stub_heatmap.md` edit is uncommitted in this tree — do not touch it.)
- **host_io façade:** in tests, patch `engine.host_io._h` / inject a fake renderer; never call `_dauntless_host` directly in engine code paths under test.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Phase 0 (real Box glow):**
- `engine/appc/subsystem_glow.py` — `resolve_baked_region` box op; `_register_baked` box dispatch.
- `engine/renderer.py` — `add_box_region`, `set_debug_boxes`, `clear_debug_boxes` wrappers.
- `native/src/scenegraph/include/scenegraph/instance.h` — `GlowRegion` gains `shape`, `half_extents`.
- `native/src/renderer/frame.cc` — pack `u_glow_region_e`.
- `native/src/renderer/shaders/opaque.frag` — box inside-test branch + `u_glow_region_e` uniform.
- `native/src/host/host_bindings.cc` — `add_box_region`, `set_debug_boxes`, `clear_debug_boxes` bindings; debug-box frame draw.
- `native/src/renderer/include/renderer/debug_volume_pass.h` + `debug_volume_pass.cc` — `DebugBox` + `render(boxes, camera)`.
- `engine/ui/glow_region_overlay.py` — box emission; returns `(cylinders, boxes)`.
- `engine/host_loop.py` — push `set_debug_cylinders` + `set_debug_boxes`.
- Tests: `tests/unit/test_subsystem_glow.py`, `tests/unit/test_glow_region_overlay.py`, `tests/host/test_box_glow_region.py`.

**Phase 1 (Edit Light UI):**
- `engine/appc/hardpoint_override_writer.py` — `set_region`.
- `engine/appc/override_routing.py` — mixed-edit `write`.
- `engine/ui/ship_property_viewer.py` — descriptor `light`/`light_region`; `region_spec_to_calls`.
- `engine/ui/ship_property_viewer_panel.py` — `_pending_light`, `set_light`/`save`, dirty/tally, `pending_light_specs`.
- `native/assets/ui-cef/{index.html,js/ship_property_viewer.js,css/ship_property_viewer.css}` — Edit Light menu + modal.
- Tests: `tests/unit/test_hardpoint_override_writer.py`, `tests/unit/test_override_routing.py`, `tests/unit/test_subsystem_glow.py`, `tests/ui/test_ship_property_viewer_panel.py`.

---

# Phase 0 — Real Box glow rendering

## Task 1: Python — resolve + register the box op

**Files:**
- Modify: `engine/appc/subsystem_glow.py` (`resolve_baked_region`, `_register_baked`)
- Modify: `engine/renderer.py` (`add_box_region` wrapper + `_REQUIRED_BINDINGS`)
- Test: `tests/unit/test_subsystem_glow.py`

**Interfaces:**
- Consumes: existing `baked_glow_regions`, `read_indexed_setter_args`.
- Produces:
  - `resolve_baked_region(raw, default_pos)` returns `("box", center_tuple3, half_extents_tuple3)` for a `Box` shape (else unchanged).
  - `ShipGlowController._register_baked` dispatches a `box` op to `self._r.add_box_region(iid, center, half_extents)`.
  - `engine.renderer.add_box_region(instance_id, center, half_extents) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_subsystem_glow.py
from engine.appc import subsystem_glow as sg


def test_resolve_box_region_returns_box_op():
    raw = {"shape": "Box", "position": (1.0, 2.0, 3.0),
           "scale": (0.5, 0.6, 0.7), "axis": None, "radius": None, "extent": None}
    op = sg.resolve_baked_region(raw, default_pos=(0.0, 0.0, 0.0))
    assert op == ("box", (1.0, 2.0, 3.0), (0.5, 0.6, 0.7))


def test_resolve_box_defaults_position_to_hardpoint():
    raw = {"shape": "Box", "position": None, "scale": (0.5, 0.5, 0.5)}
    op = sg.resolve_baked_region(raw, default_pos=(4.0, 0.0, 0.0))
    assert op == ("box", (4.0, 0.0, 0.0), (0.5, 0.5, 0.5))


def test_resolve_box_rejects_nonpositive_scale():
    raw = {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.5, 0.0, 0.5)}
    assert sg.resolve_baked_region(raw, default_pos=(0.0, 0.0, 0.0)) is None


class _RecRenderer:
    def __init__(self): self.calls = []
    def add_box_region(self, iid, center, half):
        self.calls.append((iid, center, half)); return 0
    def add_sphere_region(self, *a): return -1
    def add_cylinder_region(self, *a): return -1
    def set_glow_region_dim(self, *a, **k): pass
    def set_glow_region_gain(self, *a, **k): pass


def test_register_baked_dispatches_box(monkeypatch):
    rr = _RecRenderer()
    monkeypatch.setattr(sg, "baked_region_ops",
                        lambda prop, pos, name="": [("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0))])
    monkeypatch.setattr(sg, "_position_tuple", lambda pod: (0.0, 0.0, 0.0))

    class _Pod:
        def GetProperty(self): return object()
        def GetName(self): return "Box Pod"
    ctrl = sg.ShipGlowController.__new__(sg.ShipGlowController)
    ctrl._r = rr; ctrl._iid = 7; ctrl._regions = []
    ctrl._register_baked(_Pod(), boost=False)
    assert rr.calls == [(7, (0.0, 0.0, 0.0), (1.0, 2.0, 3.0))]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_subsystem_glow.py -q -k box`
Expected: FAIL (`resolve_baked_region` returns None for Box; `add_box_region` missing).

- [ ] **Step 3: Implement the box op in `resolve_baked_region`**

In `engine/appc/subsystem_glow.py`, in `resolve_baked_region`, insert before the
final `return None`:

```python
    if shape == "box":
        scale = raw.get("scale")
        if scale is None or len(scale) != 3:
            return None
        try:
            hx, hy, hz = (float(scale[0]), float(scale[1]), float(scale[2]))
        except (TypeError, ValueError):
            return None
        if hx <= 0.0 or hy <= 0.0 or hz <= 0.0:
            return None
        return ("box", tuple(pos), (hx, hy, hz))
```

(`pos` and the case-insensitive `shape` are already computed at the top of the
function, exactly like the sphere/cylinder branches.)

- [ ] **Step 4: Implement the box dispatch in `_register_baked`**

In `ShipGlowController._register_baked`, extend the op dispatch:

```python
            if op[0] == "sphere":
                idx = self._r.add_sphere_region(self._iid, op[1], op[2])
            elif op[0] == "box":
                idx = self._r.add_box_region(self._iid, op[1], op[2])
            else:  # cylinder
                idx = self._r.add_cylinder_region(
                    self._iid, op[1], op[2], op[3], op[4])
```

- [ ] **Step 5: Add the `add_box_region` renderer wrapper**

In `engine/renderer.py`, next to `add_sphere_region` (~L483):

```python
def add_box_region(instance_id: InstanceId, center, half_extents) -> int:
    """Store a body-axis-aligned box glow region at a hardpoint. center and
    half_extents are 3-tuples in game units. Returns the region index, or -1."""
    return _h.add_box_region(instance_id, tuple(center), tuple(half_extents))
```

Add `"add_box_region"` to the `_REQUIRED_BINDINGS` set/list (alphabetical, next
to `"add_cylinder_region"`, `"add_sphere_region"` ~L33).

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/unit/test_subsystem_glow.py -q`
Expected: PASS. (`add_box_region` wrapper is not exercised by these tests — it's
covered by the host test in Task 2 — but importing `engine.renderer` must not
fail; a missing binding on the real `_h` only matters at call time.)

- [ ] **Step 7: Commit**

```bash
git add engine/appc/subsystem_glow.py engine/renderer.py tests/unit/test_subsystem_glow.py
git commit -m "feat(glow): resolve + register a Box glow region op (Python)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: C++ — Box glow rendering (storage, upload, binding, shader)

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (`GlowRegion`)
- Modify: `native/src/renderer/frame.cc` (pack `u_glow_region_e`)
- Modify: `native/src/renderer/shaders/opaque.frag` (box branch + uniform)
- Modify: `native/src/host/host_bindings.cc` (`add_box_region` binding)
- Test: `tests/host/test_box_glow_region.py`

**Interfaces:**
- Consumes: `engine.renderer.add_box_region` (Task 1), existing `set_glow_region_gain`.
- Produces: `_dauntless_host.add_box_region(instance_id, center, half_extents) -> int`; a box region dims/brightens the hull inside a body-axis-aligned box; capsule/sphere path unchanged.

- [ ] **Step 1: Write the failing host test**

```python
# tests/host/test_box_glow_region.py
"""A Box glow region brightens the hull's glow inside a body-axis-aligned box.

Adds a box covering the whole ship with gain>1; the box inside-test must match
so the gain applies and the sampled glow gets brighter than the unlit baseline.
Guards the shader box branch + the native upload path against regression.
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _max_glow(host, cx, cy):
    m = 0
    for dx in range(-60, 61, 2):
        for dy in range(-40, 41, 2):
            r, g, b, _ = host.read_pixel(cx + dx, cy + dy)
            m = max(m, r + g + b)
    return m


def test_box_region_gain_brightens_inside():
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as H
    H.init(640, 360, "test_box_glow")
    try:
        h = H.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = H.create_instance(h)
        H.set_world_transform(iid, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        H.set_camera(eye=(0.0, 0.0, 1500.0), target=(0.0, 0.0, 0.0),
                     up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=1.0, far=100000.0)
        H.set_lighting((0.0, 0.0, 0.0), [])
        H.frame()
        fw, fh = H.framebuffer_size()
        cx, cy = fw // 2, fh // 2
        baseline = _max_glow(H, cx, cy)

        idx = H.add_box_region(iid, (0.0, 0.0, 0.0), (5000.0, 5000.0, 5000.0))
        assert idx >= 0
        H.set_glow_region_gain(iid, idx, 2.5, (0.0, 0.0, 0.0))
        H.frame()
        boosted = _max_glow(H, cx, cy)

        assert boosted > baseline, (
            f"box gain did not brighten glow inside the box "
            f"(baseline={baseline}, boosted={boosted}) — box inside-test broken?")
    finally:
        H.destroy_instance(iid)
        H.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/host/test_box_glow_region.py -q`
Expected: FAIL (`_dauntless_host has no attribute add_box_region`). (If BC assets
are absent it SKIPS — that is not a pass; you must have `game/` for this task.)

- [ ] **Step 3: Add `shape` + `half_extents` to the instance GlowRegion**

In `native/src/scenegraph/include/scenegraph/instance.h`, inside `struct GlowRegion`
(after `gain_axis`):

```cpp
        float     shape = 0.0f;          // 0 = capsule/sphere, 1 = body-axis box
        glm::vec3 half_extents{0.0f};    // box half-extents (model units); box only
```

- [ ] **Step 4: Pack the 5th uniform in frame.cc**

In `native/src/renderer/frame.cc`, in the glow-region block (~L334-353): add a
fifth array and upload it.

```cpp
        glm::vec4 na[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 nb[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 nc[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 nd[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 ne[scenegraph::Instance::kMaxGlowRegions];   // shape, half_extents.xyz
        int nn = 0;
        for (const auto& n : glow_regions) {
            if (!n.active) continue;
            na[nn] = glm::vec4(n.center, n.radius);
            nb[nn] = glm::vec4(n.axis, n.aft);
            nc[nn] = glm::vec4(n.fore, n.dim_target, n.disable_time, n.flicker);
            nd[nn] = glm::vec4(n.gain, n.gain_axis.x, n.gain_axis.y, n.gain_axis.z);
            ne[nn] = glm::vec4(n.shape, n.half_extents.x, n.half_extents.y, n.half_extents.z);
            ++nn;
        }
        prog.set_int("u_glow_region_count", nn);
        if (nn > 0) {
            prog.set_vec4_array("u_glow_region_a", na, nn);
            prog.set_vec4_array("u_glow_region_b", nb, nn);
            prog.set_vec4_array("u_glow_region_c", nc, nn);
            prog.set_vec4_array("u_glow_region_d", nd, nn);
            prog.set_vec4_array("u_glow_region_e", ne, nn);
            prog.set_mat4("u_ship_world_inv", glm::inverse(world));
            prog.set_float("u_decal_time", decal_time);
        }
```

- [ ] **Step 5: Add the box branch to the shader**

In `native/src/renderer/shaders/opaque.frag`, after the existing region uniforms
(~L145) add:

```glsl
uniform vec4 u_glow_region_e[MAX_GLOW_REGIONS];  // shape_flag, half_extent.xyz
```

In `glow_region_mult`, replace the capsule inside-test (the block computing
`d`, `t`, `perp` and the two `continue`s, ~L222-227) with a shape-branched test:

```glsl
        vec3 d = p_body - center;
        if (u_glow_region_e[i].x > 0.5) {          // body-axis-aligned box
            vec3 h = u_glow_region_e[i].yzw;
            vec3 a = abs(d);
            if (a.x > h.x || a.y > h.y || a.z > h.z) continue;
        } else {                                   // capsule / sphere (unchanged)
            float t = dot(d, axis);
            vec3  perp = d - t * axis;
            if (dot(perp, perp) > radius * radius) continue;
            if (t < aft || t > fore) continue;
        }
```

Everything after (gain gate, dim/flicker/destroy state, `mult = min(...)`) is
unchanged and shape-agnostic. `axis`/`radius`/`aft`/`fore` are still read above
for the capsule branch; leave those local reads in place.

- [ ] **Step 6: Add the `add_box_region` host binding**

In `native/src/host/host_bindings.cc`, after `add_cylinder_region` (~L3144), add
(mirrors `add_sphere_region`'s slot loop + game-unit→model conversion):

```cpp
    m.def("add_box_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center,
             std::tuple<float, float, float> half) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              const glm::vec3 he(std::get<0>(half) * inv,
                                 std::get<1>(half) * inv,
                                 std::get<2>(half) * inv);
              for (std::size_t i = 0; i < inst->glow_regions.size(); ++i) {
                  if (inst->glow_regions[i].active) continue;
                  auto& n = inst->glow_regions[i];
                  n = scenegraph::Instance::GlowRegion{};   // reset to defaults
                  n.center = c;
                  n.shape = 1.0f;
                  n.half_extents = he;
                  n.dim_target = 1.0f;
                  n.disable_time = -1.0f;
                  n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("half_extents"),
          "Store a body-axis-aligned box glow region (game units / body frame). "
          "Returns the region index, or -1 on failure (stale id, no slot).");
```

- [ ] **Step 7: Reconfigure (shader changed), build, run the host test**

```bash
cmake -B build -S .            # shader edit → reconfigure
cmake --build build -j
uv run pytest tests/host/test_box_glow_region.py -q
```
Expected: PASS.

- [ ] **Step 8: Run the gate**

```bash
scripts/check_tests.sh
```
Expected: green (capsule/sphere path unchanged; existing FrameTests + glow tests pass).

- [ ] **Step 9: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/src/renderer/frame.cc native/src/renderer/shaders/opaque.frag native/src/host/host_bindings.cc tests/host/test_box_glow_region.py
git commit -m "feat(glow): real Box glow region — shader box test + native primitive

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: C++ — Debug wireframe box in the debug-volume pass

**Files:**
- Modify: `native/src/renderer/include/renderer/debug_volume_pass.h` (`DebugBox` + overload)
- Modify: `native/src/renderer/debug_volume_pass.cc` (unit-cube mesh + `render(boxes)`)
- Modify: `native/src/host/host_bindings.cc` (`set_debug_boxes`/`clear_debug_boxes` + frame draw)

**Interfaces:**
- Produces:
  - `renderer::DebugBox { glm::vec3 center, ex, ey, ez, color; }` — `ex/ey/ez` are world-space half-extent edge vectors (already rotated).
  - `DebugVolumePass::render(const std::vector<DebugBox>&, const scenegraph::Camera&)`.
  - `_dauntless_host.set_debug_boxes(list[dict])` / `clear_debug_boxes()`; each dict: `center, ex, ey, ez, color`.

- [ ] **Step 1: Declare `DebugBox` + the render overload**

In `native/src/renderer/include/renderer/debug_volume_pass.h`, after `DebugCylinder`:

```cpp
/// One wireframe box to draw, expressed in WORLD space. ex/ey/ez are the box's
/// three half-extent edge vectors (already rotated), so the drawn box is
/// center +/- ex +/- ey +/- ez.
struct DebugBox {
    glm::vec3 center{0.0f};
    glm::vec3 ex{1.0f, 0.0f, 0.0f};
    glm::vec3 ey{0.0f, 1.0f, 0.0f};
    glm::vec3 ez{0.0f, 0.0f, 1.0f};
    glm::vec3 color{0.0f, 1.0f, 0.0f};
};
```

In `class DebugVolumePass`, add next to the cylinder `render`:

```cpp
    void render(const std::vector<DebugBox>& boxes,
                const scenegraph::Camera& camera);
```

and add box mesh members next to `vao_`/`vbo_`:

```cpp
    unsigned int box_vao_ = 0;
    unsigned int box_vbo_ = 0;
    int box_vertex_count_ = 0;
    void ensure_box_resources();
```

- [ ] **Step 2: Implement the box mesh + render in `debug_volume_pass.cc`**

Delete the box VAO/VBO in the destructor alongside the cylinder ones:

```cpp
DebugVolumePass::~DebugVolumePass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
    if (box_vbo_) glDeleteBuffers(1, &box_vbo_);
    if (box_vao_) glDeleteVertexArrays(1, &box_vao_);
}
```

Add (after `ensure_resources`), a unit-cube (corners at +/-1) triangle mesh —
wireframe via `GL_LINE` outlines every edge:

```cpp
void DebugVolumePass::ensure_box_resources() {
    if (box_vao_) return;
    if (!shader_) shader_ = std::make_unique<Shader>(kVs, kFs);

    // 12 triangles (2 per face) of the [-1,1]^3 cube.
    const float c[8][3] = {
        {-1,-1,-1}, { 1,-1,-1}, { 1, 1,-1}, {-1, 1,-1},
        {-1,-1, 1}, { 1,-1, 1}, { 1, 1, 1}, {-1, 1, 1},
    };
    const int faces[6][4] = {
        {0,1,2,3}, {4,5,6,7}, {0,1,5,4}, {2,3,7,6}, {1,2,6,5}, {0,3,7,4},
    };
    std::vector<float> verts;
    for (auto& f : faces) {
        const int tri[6] = {f[0], f[1], f[2], f[0], f[2], f[3]};
        for (int idx : tri) {
            verts.push_back(c[idx][0]); verts.push_back(c[idx][1]); verts.push_back(c[idx][2]);
        }
    }
    box_vertex_count_ = static_cast<int>(verts.size() / 3);

    glGenVertexArrays(1, &box_vao_);
    glGenBuffers(1, &box_vbo_);
    glBindVertexArray(box_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, box_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(float)),
                 verts.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void DebugVolumePass::render(const std::vector<DebugBox>& boxes,
                             const scenegraph::Camera& camera) {
    if (boxes.empty()) return;
    ensure_box_resources();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader_->use();

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE);
    glLineWidth(1.5f);
    glBindVertexArray(box_vao_);

    for (const auto& b : boxes) {
        glm::mat4 M(1.0f);
        M[0] = glm::vec4(b.ex, 0.0f);      // unit-cube X (+/-1) -> +/- ex
        M[1] = glm::vec4(b.ey, 0.0f);
        M[2] = glm::vec4(b.ez, 0.0f);
        M[3] = glm::vec4(b.center, 1.0f);
        shader_->set_vec3("u_color", b.color);
        shader_->set_mat4("u_mvp", vp * M);
        glDrawArrays(GL_TRIANGLES, 0, box_vertex_count_);
    }

    glBindVertexArray(0);
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}
```

- [ ] **Step 3: Add the host bindings + global + frame draw**

In `native/src/host/host_bindings.cc`: add a box list next to `g_debug_cylinders`
(~L231):

```cpp
std::vector<renderer::DebugBox>              g_debug_boxes;
```

Clear it in shutdown next to `g_debug_cylinders.clear();` (~L546):

```cpp
    g_debug_boxes.clear();
```

Add the frame draw next to the cylinder draw (~L905):

```cpp
    if (viewer_mode && g_debug_volume_pass && !g_debug_cylinders.empty())
        g_debug_volume_pass->render(g_debug_cylinders, g_camera);
    if (viewer_mode && g_debug_volume_pass && !g_debug_boxes.empty())
        g_debug_volume_pass->render(g_debug_boxes, g_camera);
```

Add the bindings next to `set_debug_cylinders`/`clear_debug_cylinders` (~L2440):

```cpp
    m.def("set_debug_boxes",
          [](const std::vector<py::dict>& descs) {
              g_debug_boxes.clear();
              g_debug_boxes.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::DebugBox b;
                  auto v3 = [&](const char* k, glm::vec3& out) {
                      if (d.contains(k)) {
                          auto v = d[k].cast<std::array<float, 3>>();
                          out = {v[0], v[1], v[2]};
                      }
                  };
                  v3("center", b.center); v3("ex", b.ex); v3("ey", b.ey);
                  v3("ez", b.ez); v3("color", b.color);
                  g_debug_boxes.push_back(b);
              }
          },
          py::arg("boxes"),
          "Set the world-space debug wireframe boxes (SPV glow-region overlay; "
          "viewer_mode only). Each dict: center, ex, ey, ez, color.");

    m.def("clear_debug_boxes",
          []() { g_debug_boxes.clear(); },
          "Clear the debug wireframe boxes. Takes effect next frame().");
```

- [ ] **Step 4: Build**

```bash
cmake --build build -j       # no shader change here → no reconfigure needed
```
Expected: clean build.

- [ ] **Step 5: Gate**

```bash
scripts/check_tests.sh
```
Expected: green (no behavior change until Python pushes boxes in Task 4).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/debug_volume_pass.h native/src/renderer/debug_volume_pass.cc native/src/host/host_bindings.cc
git commit -m "feat(spv): wireframe DebugBox in the debug-volume pass + host bindings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Python — overlay box emission + wire boxes into host_loop

**Files:**
- Modify: `engine/ui/glow_region_overlay.py` (`build_glow_region_overlay` → `(cylinders, boxes)`)
- Modify: `engine/renderer.py` (`set_debug_boxes`/`clear_debug_boxes` wrappers)
- Modify: `engine/host_loop.py` (push both lists)
- Test: `tests/unit/test_glow_region_overlay.py`

**Interfaces:**
- Consumes: `resolve_baked_region` (now with box), `baked_region_ops`, `_position_tuple`.
- Produces:
  - `build_glow_region_overlay(ship, selected_name=None, show_all=True) -> (list, list)` — `(cylinders, boxes)`.
  - `engine.renderer.set_debug_boxes(boxes)` / `clear_debug_boxes()`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_glow_region_overlay.py
from engine.ui import glow_region_overlay as gro


class _Rot:   # identity rotation: MultMatrixLeft leaves the point unchanged
    pass


class _Sub:
    def __init__(self, name, prop): self._n = name; self._p = prop
    def GetName(self): return self._n
    def GetProperty(self): return self._p


class _Ship:
    def __init__(self, subs): self._subs = subs
    def GetWorldLocation(self):
        class P: x = 10.0; y = 0.0; z = 0.0
        return P()
    def GetWorldRotation(self): return None   # None rot => body == world
    def __iter__(self): return iter(self._subs)


def test_overlay_returns_cylinders_and_boxes_tuple(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0))])
    ship = _Ship([_Sub("Box Pod", object())])
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True)
    assert cyls == []
    assert len(boxes) == 1
    b = boxes[0]
    # center = ship_pos + region center (None rot => identity): (10,0,0)
    assert b["center"] == (10.0, 0.0, 0.0)
    # edge vectors carry the half-extents along body axes (identity rot).
    assert b["ex"] == (1.0, 0.0, 0.0)
    assert b["ey"] == (0.0, 2.0, 0.0)
    assert b["ez"] == (0.0, 0.0, 3.0)
    assert b["color"] == gro.GLOW_COLOR
```

(Adjust the monkeypatch target names — `_iter_subsystems`, `_position_tuple`,
`baked_region_ops` — to whatever the existing tests in this file already patch;
keep the existing cylinder/sphere tests, updating them to unpack the tuple.)

- [ ] **Step 2: Update existing tests to unpack the tuple**

Every existing assertion of the form `result = build_glow_region_overlay(...)`
followed by `assert result == [...]` (cylinders) becomes:

```python
    cyls, boxes = build_glow_region_overlay(...)
    assert cyls == [...]
    assert boxes == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_glow_region_overlay.py -q`
Expected: FAIL (function returns a list, not a tuple; no box emission).

- [ ] **Step 4: Implement box emission + tuple return**

In `engine/ui/glow_region_overlay.py`:

Add a non-normalizing rotate + a box builder near `_rotate_dir`/`_cylinder`:

```python
def _rotate_vec(v: Vec3, rot) -> Vec3:
    """R · v for a vector, preserving magnitude (no normalize)."""
    from engine.appc.math import TGPoint3
    p = TGPoint3(v[0], v[1], v[2])
    if rot is not None:
        p.MultMatrixLeft(rot)
    return (p.x, p.y, p.z)


def _box(center: Vec3, ex: Vec3, ey: Vec3, ez: Vec3) -> dict:
    return {"center": center, "ex": ex, "ey": ey, "ez": ez, "color": GLOW_COLOR}
```

Import the box resolver at the top (it already imports `baked_region_ops`,
`_position_tuple`):

```python
from engine.appc.subsystem_glow import baked_region_ops, _position_tuple
```

Rewrite the body of `build_glow_region_overlay` to collect two lists and handle
the `box` op:

```python
    out: List[dict] = []
    boxes: List[dict] = []
    for sub in _iter_subsystems(ship):
        name = sub.GetName() if hasattr(sub, "GetName") else ""
        if not show_all and name != selected_name:
            continue
        pos = _position_tuple(sub)
        prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
        for op in baked_region_ops(prop, pos, name):
            if op[0] == "cylinder":
                _kind, center, axis, radius, length = op
                out.append(_cylinder(
                    _body_to_world(center, ship_pos, rot),
                    _rotate_dir(axis, rot), radius, length))
            elif op[0] == "box":
                _kind, center, half = op
                boxes.append(_box(
                    _body_to_world(center, ship_pos, rot),
                    _rotate_vec((half[0], 0.0, 0.0), rot),
                    _rotate_vec((0.0, half[1], 0.0), rot),
                    _rotate_vec((0.0, 0.0, half[2]), rot)))
            else:  # sphere
                _kind, center, radius = op
                up = _rotate_dir((0.0, 0.0, 1.0), rot)
                world_c = _body_to_world(center, ship_pos, rot)
                base = (world_c[0] - up[0] * radius,
                        world_c[1] - up[1] * radius,
                        world_c[2] - up[2] * radius)
                out.append(_cylinder(base, up, radius, 2.0 * radius))
    return out, boxes
```

Update the two early-return guards to return the tuple shape:

```python
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return [], []
    if not show_all and not selected_name:
        return [], []
```

- [ ] **Step 5: Add the renderer wrappers**

In `engine/renderer.py`, near `set_debug_cylinders`/`clear_debug_cylinders` (~L926):

```python
def set_debug_boxes(boxes: list) -> None:
    fn = getattr(_h, "set_debug_boxes", None)
    if fn is not None:
        fn(boxes)


def clear_debug_boxes() -> None:
    fn = getattr(_h, "clear_debug_boxes", None)
    if fn is not None:
        fn()
```

Add `"set_debug_boxes"` and `"clear_debug_boxes"` to `_REQUIRED_BINDINGS` (next
to the `clear_debug_cylinders`/`set_debug_cylinders` entries ~L78/82).

- [ ] **Step 6: Wire host_loop to push both**

In `engine/host_loop.py` at the `set_debug_cylinders(build_glow_region_overlay(...))`
call (~L7272), replace with:

```python
                _cyls, _boxes = build_glow_region_overlay(
                    player,
                    selected_name=ship_property_viewer.selected_name(),
                    show_all=ship_property_viewer.show_glow_regions)
                r.set_debug_cylinders(_cyls)
                r.set_debug_boxes(_boxes)
```

- [ ] **Step 7: Run overlay tests + gate**

```bash
uv run pytest tests/unit/test_glow_region_overlay.py -q
scripts/check_tests.sh
```
Expected: PASS / green.

- [ ] **Step 8: Commit**

```bash
git add engine/ui/glow_region_overlay.py engine/renderer.py engine/host_loop.py tests/unit/test_glow_region_overlay.py
git commit -m "feat(spv): overlay emits wireframe boxes for Box glow regions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# Phase 1 — Edit Light UI

## Task 5: Writer — `set_region` (replace a region's glow setters)

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py`
- Test: `tests/unit/test_hardpoint_override_writer.py`

**Interfaces:**
- Consumes: existing `read_models`, `emit`, `_INDEXED_PREFIX`.
- Produces: `set_region(models, leaf, subsystem, index, calls) -> None` — removes every `SetGlowRegion*(index, …)` for the subsystem, appends `calls` (ordered `[(setter, args), …]`); leaves `SetRadius`/other-index setters intact; creates the leaf/subsystem entry if absent.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_hardpoint_override_writer.py
def test_set_region_replaces_glow_setters_for_index():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetRadius(0.5)
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [
        ("SetGlowRegionShape", (0, "Box")),
        ("SetGlowRegionPosition", (0, 1.0, 0.0, 0.0)),
        ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)),
    ])
    calls = models["x"]["A"]
    # SetRadius (non-glow) preserved; old cylinder glow setters gone.
    assert ("SetRadius", (0.5,)) in calls
    assert not any(s == "SetGlowRegionAxis" for s, a in calls)
    assert not any(s == "SetGlowRegionExtent" for s, a in calls)
    assert ("SetGlowRegionShape", (0, "Box")) in calls
    assert ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)) in calls


def test_set_region_leaves_other_indices_intact():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionShape(1, "Sphere")
        p.SetGlowRegionRadius(1, 0.4)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [("SetGlowRegionShape", (0, "Box")),
                                       ("SetGlowRegionScale", (0, 1.0, 1.0, 1.0))])
    calls = models["x"]["A"]
    assert ("SetGlowRegionShape", (1, "Sphere")) in calls   # index 1 untouched
    assert ("SetGlowRegionRadius", (1, 0.4)) in calls
    assert ("SetGlowRegionRadius", (0, 0.25)) not in calls   # index 0 replaced


def test_set_region_creates_absent_subsystem():
    m = _module('def _x(find):\n    return\nOVERRIDES = {"x": _x}\n')
    models = w.read_models(m)
    w.set_region(models, "x", "New", 0, [("SetGlowRegionShape", (0, "Sphere")),
                                         ("SetGlowRegionRadius", (0, 0.3))])
    assert models["x"]["New"] == [("SetGlowRegionShape", (0, "Sphere")),
                                  ("SetGlowRegionRadius", (0, 0.3))]


def test_set_region_result_round_trips():
    m = _module('def _x(find):\n    return\nOVERRIDES = {"x": _x}\n')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [("SetGlowRegionShape", (0, "Box")),
                                       ("SetGlowRegionScale", (0, 1.0, 2.0, 3.0))])
    text = w.emit(models)
    m2 = _module(text)
    assert w.read_models(m2) == models
    assert w.emit(w.read_models(m2)) == text
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q -k region`
Expected: FAIL (`set_region` not defined).

- [ ] **Step 3: Implement `set_region`**

In `engine/appc/hardpoint_override_writer.py`, after `set_setter`:

```python
def set_region(models, leaf, subsystem, index, calls) -> None:
    """Replace all SetGlowRegion*(index, ...) calls for a subsystem with `calls`
    (ordered [(setter, args), ...], each args starting with `index`). Non-glow
    setters (e.g. SetRadius) and other region indices are left intact."""
    per_sub = models.setdefault(leaf, {})
    existing = per_sub.setdefault(subsystem, [])
    kept = [(s, a) for (s, a) in existing
            if not (s.startswith(_INDEXED_PREFIX) and a and a[0] == index)]
    kept.extend((s, tuple(a)) for (s, a) in calls)
    per_sub[subsystem] = kept
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer.py
git commit -m "feat(overrides): set_region — replace a subsystem's glow setters at an index

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Target — accept mixed setter + region edits

**Files:**
- Modify: `engine/appc/override_routing.py` (`HardpointOverridesFileTarget.write`)
- Test: `tests/unit/test_override_routing.py`

**Interfaces:**
- Consumes: `read_models`, `set_setter`, `set_region`, `emit` (Task 5).
- Produces: `HardpointOverridesFileTarget.write(leaf, edits)` where each edit is either a 3-tuple `(subsystem, setter, args)` → `set_setter`, or a 4-tuple `(subsystem, "__region__", index, calls)` → `set_region`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_override_routing.py
def test_write_applies_region_edit(tmp_path):
    f = tmp_path / "hardpoint_overrides.py"
    f.write_text(w.emit({"galaxy": {"Center Impulse": [("SetRadius", (0.25,))]}}))
    target = r.HardpointOverridesFileTarget(str(f))
    target.write("galaxy", [("Center Impulse", "__region__", 0, [
        ("SetGlowRegionShape", (0, "Box")),
        ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)),
    ])])
    import types
    m = types.ModuleType("x"); exec(f.read_text(), m.__dict__)  # noqa: S102
    calls = w.read_models(m)["galaxy"]["Center Impulse"]
    assert ("SetRadius", (0.25,)) in calls              # untouched
    assert ("SetGlowRegionShape", (0, "Box")) in calls
    assert ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)) in calls


def test_write_applies_mixed_setter_and_region(tmp_path):
    f = tmp_path / "hardpoint_overrides.py"
    f.write_text(w.emit({"galaxy": {"Center Impulse": [("SetRadius", (0.25,))]}}))
    target = r.HardpointOverridesFileTarget(str(f))
    target.write("galaxy", [
        ("Center Impulse", "SetRadius", (0.9,)),
        ("Center Impulse", "__region__", 0, [("SetGlowRegionShape", (0, "Sphere")),
                                             ("SetGlowRegionRadius", (0, 0.3))]),
    ])
    import types
    m = types.ModuleType("x"); exec(f.read_text(), m.__dict__)  # noqa: S102
    calls = w.read_models(m)["galaxy"]["Center Impulse"]
    assert ("SetRadius", (0.9,)) in calls
    assert ("SetGlowRegionShape", (0, "Sphere")) in calls
```

(The existing `test_file_target_persists_radius_edit` — a 3-tuple radius edit —
must still pass unchanged.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_override_routing.py -q -k "region or mixed"`
Expected: FAIL (`write` unpacks a 3-tuple; the 4-tuple raises).

- [ ] **Step 3: Implement the mixed-edit dispatch**

In `engine/appc/override_routing.py`, replace the edit loop inside `write`:

```python
        models = _writer.read_models(module)
        for edit in edits:
            if len(edit) == 4:
                subsystem, tag, index, calls = edit
                _writer.set_region(models, leaf, subsystem, index, calls)
            else:
                subsystem, setter, args = edit
                _writer.set_setter(models, leaf, subsystem, setter, args)
        text = _writer.emit(models)          # raises on a bad emit
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_override_routing.py -q`
Expected: PASS (radius, region, mixed all green).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/override_routing.py tests/unit/test_override_routing.py
git commit -m "feat(overrides): file target applies mixed setter + region edits

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Descriptors — light flag, light_region, region_spec_to_calls

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (post-pass + `region_spec_to_calls`)
- Modify: `engine/appc/subsystem_glow.py` (`glow_bearing_subsystem_ids`)
- Test: `tests/unit/test_subsystem_glow.py`, `tests/ui/test_ship_property_viewer.py` (create if absent)

**Interfaces:**
- Consumes: `warp_pods`, `impulse_engines`, `baked_glow_regions`, `_position_tuple`.
- Produces:
  - `subsystem_glow.glow_bearing_subsystem_ids(ship) -> set` — `id()` of warp pods, impulse pods, sensor; None-safe.
  - `build_descriptors` marks light-bearing descriptors: `"light": True`, `"light_region": {shape, position, axis, radius, extent, scale}` (baked-shaped tuples; radius=(r,), extent=(aft,fore), etc.).
  - `ship_property_viewer.region_spec_to_calls(index, spec) -> [(setter, args), ...]`.

- [ ] **Step 1: Write the failing tests (helper + spec_to_calls)**

```python
# append to tests/unit/test_subsystem_glow.py
def test_glow_bearing_ids_covers_warp_impulse_sensor(monkeypatch):
    warp = [object(), object()]; imp = [object()]; sensor = object()

    class _Ship:
        def GetWarpEngineSubsystem(self): return "w"
        def GetImpulseEngineSubsystem(self): return "i"
        def GetSensorSubsystem(self): return sensor
    monkeypatch.setattr(sg, "warp_pods", lambda s: warp if s == "w" else [])
    monkeypatch.setattr(sg, "impulse_engines", lambda s: imp if s == "i" else [])
    ids = sg.glow_bearing_subsystem_ids(_Ship())
    assert ids == {id(warp[0]), id(warp[1]), id(imp[0]), id(sensor)}


def test_glow_bearing_ids_none_safe():
    assert sg.glow_bearing_subsystem_ids(object()) == set()
```

```python
# tests/ui/test_ship_property_viewer.py  (create if it doesn't exist)
from engine.ui.ship_property_viewer import region_spec_to_calls


def test_region_spec_to_calls_cylinder():
    spec = {"shape": "Cylinder", "position": (1.0, 0.0, 0.0),
            "axis": (0.0, -1.0, 0.0), "radius": (0.25,), "extent": (0.0, 2.0),
            "scale": (0.25, 0.25, 0.25)}
    assert region_spec_to_calls(0, spec) == [
        ("SetGlowRegionShape", (0, "Cylinder")),
        ("SetGlowRegionPosition", (0, 1.0, 0.0, 0.0)),
        ("SetGlowRegionAxis", (0, 0.0, -1.0, 0.0)),
        ("SetGlowRegionRadius", (0, 0.25)),
        ("SetGlowRegionExtent", (0, 0.0, 2.0)),
    ]


def test_region_spec_to_calls_box():
    spec = {"shape": "Box", "position": (0.0, 0.0, 0.0), "axis": (0.0, -1.0, 0.0),
            "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.5, 0.6, 0.7)}
    assert region_spec_to_calls(0, spec) == [
        ("SetGlowRegionShape", (0, "Box")),
        ("SetGlowRegionPosition", (0, 0.0, 0.0, 0.0)),
        ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)),
    ]


def test_region_spec_to_calls_sphere():
    spec = {"shape": "Sphere", "position": (0.0, 0.0, 0.0), "axis": (0.0, -1.0, 0.0),
            "radius": (0.3,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    assert region_spec_to_calls(0, spec) == [
        ("SetGlowRegionShape", (0, "Sphere")),
        ("SetGlowRegionPosition", (0, 0.0, 0.0, 0.0)),
        ("SetGlowRegionRadius", (0, 0.3)),
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_subsystem_glow.py tests/ui/test_ship_property_viewer.py -q -k "glow_bearing or spec_to_calls"`
Expected: FAIL (`glow_bearing_subsystem_ids`/`region_spec_to_calls` undefined).

- [ ] **Step 3: Implement `glow_bearing_subsystem_ids`**

In `engine/appc/subsystem_glow.py` (module level):

```python
def glow_bearing_subsystem_ids(ship) -> set:
    """id() of every subsystem that can carry a glow region: warp pods, impulse
    engine pods, and the sensor array. None-safe; never raises."""
    ids: set = set()
    try:
        for pod in warp_pods(ship.GetWarpEngineSubsystem()):
            ids.add(id(pod))
        for pod in impulse_engines(ship.GetImpulseEngineSubsystem()):
            ids.add(id(pod))
        sensor = ship.GetSensorSubsystem()
        if sensor is not None:
            ids.add(id(sensor))
    except Exception:   # noqa: BLE001 - stub ships may miss getters
        pass
    return ids
```

- [ ] **Step 4: Implement `region_spec_to_calls` + the descriptor post-pass**

In `engine/ui/ship_property_viewer.py`, add module-level:

```python
def region_spec_to_calls(index, spec):
    """Full ordered SetGlowRegion* call list for a region spec (baked-shaped:
    radius=(r,), extent=(aft,fore), scale=(sx,sy,sz), position/axis 3-tuples)."""
    shape = spec["shape"]
    px, py, pz = spec["position"]
    calls = [("SetGlowRegionShape", (index, shape)),
             ("SetGlowRegionPosition", (index, px, py, pz))]
    if shape == "Cylinder":
        ax, ay, az = spec["axis"]
        calls.append(("SetGlowRegionAxis", (index, ax, ay, az)))
        calls.append(("SetGlowRegionRadius", (index, spec["radius"][0])))
        aft, fore = spec["extent"]
        calls.append(("SetGlowRegionExtent", (index, aft, fore)))
    elif shape == "Box":
        sx, sy, sz = spec["scale"]
        calls.append(("SetGlowRegionScale", (index, sx, sy, sz)))
    else:  # Sphere
        calls.append(("SetGlowRegionRadius", (index, spec["radius"][0])))
    return calls


def _light_region_spec(sub):
    """Region-0 spec (baked-shaped) for the modal pre-fill; from-scratch default
    when the subsystem has no baked region."""
    from engine.appc.subsystem_glow import baked_glow_regions, _position_tuple
    prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
    pos = _position_tuple(sub) or (0.0, 0.0, 0.0)
    regions = baked_glow_regions(prop)
    if regions:
        r = regions[0]
        return {"shape": r["shape"],
                "position": r["position"] or pos,
                "axis": r["axis"] or (0.0, -1.0, 0.0),
                "radius": r["radius"] or (0.25,),
                "extent": r["extent"] or (0.0, 2.0),
                "scale": r["scale"] or (0.25, 0.25, 0.25)}
    return {"shape": "Sphere", "position": pos, "axis": (0.0, -1.0, 0.0),
            "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
```

In `build_descriptors`, after the subsystem loop builds `out` (before the
object-emitter loop), annotate light-bearing descriptors. Re-walk in the same
order so indices line up:

```python
    from engine.appc.subsystem_glow import glow_bearing_subsystem_ids
    light_ids = glow_bearing_subsystem_ids(ship)
    di = 0
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue                      # skipped in the build loop too
        if id(sub) in light_ids:
            out[di]["light"] = True
            out[di]["light_region"] = _light_region_spec(sub)
        di += 1
```

(Every descriptor without `light` is treated as non-light — the CEF layer reads
`row.light === true`.)

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/unit/test_subsystem_glow.py tests/ui/test_ship_property_viewer.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/appc/subsystem_glow.py tests/unit/test_subsystem_glow.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(spv): light-bearing descriptor flag + region_spec_to_calls

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Panel — stage light edits, save, dirty/tally, pending_light_specs

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py`

**Interfaces:**
- Consumes: `resolve_override_target`, `hardpoint_leaf_for_ship` (already imported); `region_spec_to_calls` (Task 7).
- Produces:
  - `self._pending_light: dict[int, dict]` (descriptor index → baked-shaped region spec); reset in open/close; in the render snapshot.
  - `dispatch_event("set_light:<json>")`, `save` including light 4-tuples.
  - `pending_count`/`dirty`/`_pending_edits()` count light+radius; `pending_light_specs() -> {name: spec}`.

- [ ] **Step 1: Write the failing panel tests**

```python
# append to tests/ui/test_ship_property_viewer_panel.py
import json as _json


def _light_descriptor(name):
    return {"name": name, "icon_id": 0, "world_pos": (0, 0, 0),
            "state": "healthy", "targetable": True, "condition_pct": 100,
            "parent_index": None, "light": True,
            "light_region": {"shape": "Cylinder", "position": (1.0, 0.0, 0.0),
                             "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                             "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)},
            "properties": {"name": name, "radius": 0.25}}


class _LightShip:
    def GetScript(self): return "ships.Galaxy"


def test_set_light_stages_and_marks_dirty(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    ok = p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Cylinder", "radius": 0.4, "aft": 0.0, "fore": 3.0}))
    assert ok is True
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["subsystems"][0]["dirty"] is True
    spec = p.pending_light_specs()["Center Impulse"]
    assert spec["shape"] == "Cylinder"
    assert spec["radius"] == (0.4,)
    assert spec["extent"] == (0.0, 3.0)
    assert spec["position"] == (1.0, 0.0, 0.0)   # carried from light_region


def test_set_light_rejects_fore_le_aft(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    ok = p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Cylinder", "radius": 0.4, "aft": 2.0, "fore": 2.0}))
    assert ok is False
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_set_light_box_rejects_nonpositive_scale(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    ok = p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Box", "sx": 0.5, "sy": 0.0, "sz": 0.5}))
    assert ok is False


def test_save_routes_light_region_edit(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits): calls.append((leaf, edits))
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Box", "sx": 0.5, "sy": 0.6, "sz": 0.7}))
    p.dispatch_event("save")
    assert len(calls) == 1
    leaf, edits = calls[0]
    assert leaf == "galaxy"
    assert edits[0][0] == "Center Impulse"
    assert edits[0][1] == "__region__"
    assert edits[0][2] == 0
    assert ("SetGlowRegionShape", (0, "Box")) in edits[0][3]
    assert ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)) in edits[0][3]
    assert _payload_data(p.render_payload())["pending_count"] == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q -k light`
Expected: FAIL (`set_light` unhandled; no `pending_light_specs`).

- [ ] **Step 3: Implement the panel changes**

Import `region_spec_to_calls` at the top of
`engine/ui/ship_property_viewer_panel.py` (it lives in `ship_property_viewer`):

```python
from engine.ui.ship_property_viewer import (
    build_descriptors, OrbitCamera, pick_pin, region_spec_to_calls,
)
```

In `__init__`, next to `self._pending_radius = {}`:

```python
        # Staged glow/light edits: descriptor index -> baked-shaped region spec.
        self._pending_light: dict = {}
```

Reset it in `open()` and `close()` next to `self._pending_radius = {}`:

```python
        self._pending_light = {}
```

Add the snapshot term in `render_payload` (extend the tuple):

```python
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    tuple(sorted(self._pending_radius.items())),
                    tuple(sorted((i, tuple(sorted(s.items())))
                                 for i, s in self._pending_light.items())
                          if False else ()),   # see note below
                    tuple(sorted(self._expanded_groups)))
```

(Region specs contain nested tuples, which are hashable, but to keep the snapshot
simple and always-correct, instead bump `_last_pushed = None` on every light
edit and include only the count in the snapshot. Replace the term above with the
count form:)

```python
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    tuple(sorted(self._pending_radius.items())),
                    tuple(sorted(self._pending_light)),   # indices with a staged light
                    tuple(sorted(self._expanded_groups)))
```

Change `pending_count` and dirty to count both dicts. In `render_payload`'s
payload dict:

```python
            "pending_count": len(set(self._pending_radius) | set(self._pending_light)),
```

In `_subsystem_rows`, change the dirty line:

```python
            row["dirty"] = (i in self._pending_radius) or (i in self._pending_light)
```

In `_pending_edits`, count light edits too:

```python
    def _pending_edits(self):
        counts: dict = {}
        order: list = []
        for i in sorted(set(self._pending_radius) | set(self._pending_light)):
            name = self._descriptors[i]["name"]
            if name not in counts:
                counts[name] = 0
                order.append(name)
            counts[name] += (1 if i in self._pending_radius else 0)
            counts[name] += (1 if i in self._pending_light else 0)
        return [{"name": n, "count": counts[n]} for n in order]
```

Add `pending_light_specs`:

```python
    def pending_light_specs(self) -> dict:
        """{subsystem_name: baked-shaped region spec} for the live overlay."""
        return {self._descriptors[i]["name"]: spec
                for i, spec in self._pending_light.items()
                if 0 <= i < len(self._descriptors)}
```

Add the `set_light` handler in `dispatch_event` (before `if action == "save":`):

```python
        if action.startswith("set_light:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                idx = int(arg["i"]); shape = str(arg["shape"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            base = dict(self._descriptors[idx].get("light_region") or {})
            pos = base.get("position") or (0.0, 0.0, 0.0)
            axis = base.get("axis") or (0.0, -1.0, 0.0)
            spec = {"shape": shape, "position": tuple(pos), "axis": tuple(axis),
                    "radius": base.get("radius") or (0.25,),
                    "extent": base.get("extent") or (0.0, 2.0),
                    "scale": base.get("scale") or (0.25, 0.25, 0.25)}
            try:
                if shape == "Sphere":
                    r = float(arg["radius"])
                    if r <= 0.0:
                        return False
                    spec["radius"] = (r,)
                elif shape == "Cylinder":
                    r = float(arg["radius"]); aft = float(arg["aft"]); fore = float(arg["fore"])
                    if r <= 0.0 or fore <= aft:
                        return False
                    spec["radius"] = (r,); spec["extent"] = (aft, fore)
                elif shape == "Box":
                    sx = float(arg["sx"]); sy = float(arg["sy"]); sz = float(arg["sz"])
                    if sx <= 0.0 or sy <= 0.0 or sz <= 0.0:
                        return False
                    spec["scale"] = (sx, sy, sz)
                else:
                    return False
            except (KeyError, TypeError, ValueError):
                return False
            self._pending_light[idx] = spec
            self._last_pushed = None
            return True
```

In the `save` handler, build BOTH radius and light edits. Replace the `edits`
construction and the empty-guard:

```python
        if action == "save":
            if not self._pending_radius and not self._pending_light:
                return True
            ship = self._ship_getter()
            leaf = hardpoint_leaf_for_ship(ship)
            if not leaf:
                self._last_pushed = None
                return True
            edits = [(self._descriptors[i]["name"], "SetRadius", (v,))
                     for i, v in sorted(self._pending_radius.items())]
            edits += [(self._descriptors[i]["name"], "__region__", 0,
                       region_spec_to_calls(0, spec))
                      for i, spec in sorted(self._pending_light.items())]
            try:
                resolve_override_target(ship).write(leaf, edits)
            except Exception as e:
                from engine import dev_mode
                dev_mode.log_swallowed("spv light/radius save", e)
                self._last_pushed = None
                return True
            self._pending_radius = {}
            self._pending_light = {}
            self._last_pushed = None
            return True
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: PASS (new + existing radius/close/overlay tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel.py
git commit -m "feat(spv): stage glow/light region edits + route __region__ Save

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Live preview — pending spec overrides the baked overlay

**Files:**
- Modify: `engine/ui/glow_region_overlay.py` (`pending` param)
- Modify: `engine/host_loop.py` (pass `pending_light_specs()`)
- Test: `tests/unit/test_glow_region_overlay.py`

**Interfaces:**
- Consumes: `resolve_baked_region` (box-aware), `pending_light_specs()` (Task 8).
- Produces: `build_glow_region_overlay(ship, selected_name=None, show_all=True, pending=None) -> (cylinders, boxes)` — a subsystem with a pending spec resolves that spec instead of its baked ops.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_glow_region_overlay.py
def test_pending_cylinder_overrides_baked(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("sphere", (0.0, 0.0, 0.0), 0.9)])
    ship = _Ship([_Sub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, 0.0, 1.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.1, 0.1, 0.1)}}
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True, pending=pending)
    assert boxes == []
    assert len(cyls) == 1
    assert abs(cyls[0]["radius"] - 0.2) < 1e-9   # pending radius, not the baked 0.9 sphere
    assert abs(cyls[0]["length"] - 2.0) < 1e-9   # pending extent fore-aft


def test_pending_box_yields_a_box(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops", lambda prop, pos, name: [])
    ship = _Ship([_Sub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Box", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, -1.0, 0.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.5, 0.6, 0.7)}}
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True, pending=pending)
    assert cyls == []
    assert len(boxes) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_glow_region_overlay.py -q -k pending`
Expected: FAIL (`pending` kwarg unknown).

- [ ] **Step 3: Implement the pending override**

In `engine/ui/glow_region_overlay.py`, import the resolver and add the param:

```python
from engine.appc.subsystem_glow import (
    baked_region_ops, resolve_baked_region, _position_tuple,
)
```

Change the signature and the per-subsystem op source:

```python
def build_glow_region_overlay(ship, selected_name: str = None,
                              show_all: bool = True, pending: dict = None) -> tuple:
    ...
    pending = pending or {}
    ...
    for sub in _iter_subsystems(ship):
        name = sub.GetName() if hasattr(sub, "GetName") else ""
        if not show_all and name != selected_name:
            continue
        pos = _position_tuple(sub)
        if name in pending:
            op = resolve_baked_region(pending[name], pos)
            ops = [op] if op is not None else []
        else:
            prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
            ops = baked_region_ops(prop, pos, name)
        for op in ops:
            ...  # (unchanged cylinder / box / sphere dispatch from Task 4)
```

(Keep the docstring's mention that Box → box wire, Sphere/Cylinder → cylinder
wire; a pending Box with no renderer op is impossible now that box resolves.)

- [ ] **Step 4: Pass pending from host_loop**

In `engine/host_loop.py`, at the overlay call (updated in Task 4), add `pending`:

```python
                _cyls, _boxes = build_glow_region_overlay(
                    player,
                    selected_name=ship_property_viewer.selected_name(),
                    show_all=ship_property_viewer.show_glow_regions,
                    pending=ship_property_viewer.pending_light_specs())
                r.set_debug_cylinders(_cyls)
                r.set_debug_boxes(_boxes)
```

- [ ] **Step 5: Run overlay tests + gate**

```bash
uv run pytest tests/unit/test_glow_region_overlay.py -q
scripts/check_tests.sh
```
Expected: PASS / green.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/glow_region_overlay.py engine/host_loop.py tests/unit/test_glow_region_overlay.py
git commit -m "feat(spv): staged light edit overrides the live glow wireframe

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: CEF — Edit Light context item + mouse-only shape/size modal

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`

**Interfaces:**
- Consumes: `setShipPropertyViewer(data)` — rows now carry `light` (bool) and
  `light_region` (spec); `dauntlessEvent('ship-property-viewer/set_light:<json>')`.
- Produces: no Python interface. Verified by the gate build + a live `--developer` check. (CEF JS is not unit-tested here.)

- [ ] **Step 1: DOM — context item + light modal (index.html)**

In the `#spv-ctxmenu` block, add the Edit Light item (hidden by default; JS shows
it for light rows):

```html
        <div id="spv-ctx-light" class="spv-ctxmenu__item" style="display:none;"
             onclick="shipPropertyViewerCtxLight()">Edit Light…</div>
```

After `#spv-radius`, add the light modal (mouse-only: shape buttons + steppers):

```html
      <div id="spv-light" class="spv-modal-backdrop" style="display:none;">
        <div class="spv-modal">
          <div class="spv-modal__title">Edit Light</div>
          <div class="spv-shape-row">
            <button id="spv-shape-Sphere" class="spv-shape-btn"
                    onclick="shipPropertyViewerLightShape('Sphere')">Sphere</button>
            <button id="spv-shape-Cylinder" class="spv-shape-btn"
                    onclick="shipPropertyViewerLightShape('Cylinder')">Cylinder</button>
            <button id="spv-shape-Box" class="spv-shape-btn"
                    onclick="shipPropertyViewerLightShape('Box')">Box</button>
          </div>
          <div id="spv-light-fields"></div>
          <div class="spv-modal__row">
            <button class="spv-modal__btn" onclick="shipPropertyViewerLightCancel()">Cancel</button>
            <button class="spv-modal__btn spv-modal__btn--primary" onclick="shipPropertyViewerLightApply()">Apply</button>
          </div>
        </div>
      </div>
```

- [ ] **Step 2: JS — state, menu gating, shape/stepper rendering, apply (ship_property_viewer.js)**

Extend `spvHideOverlaysNoEvent` id list to include `'spv-light'`:

```javascript
    ['spv-ctxmenu', 'spv-radius', 'spv-light', 'spv-confirm'].forEach(function (id) {
```

Add module state + a per-row light map (seed like `spvRowRadii`):

```javascript
var spvRowLight = {};   // index -> light_region spec (or true) for light rows
var spvLight = null;    // working spec while the modal is open
```

In `spvSeedRowRadius`, also seed light:

```javascript
function spvSeedRowRadius(row) {
    if (row.radius != null) spvRowRadii[row.index] = row.radius;
    if (row.light === true) spvRowLight[row.index] = row.light_region || true;
    else delete spvRowLight[row.index];
}
```

In `shipPropertyViewerRowMenu`, show/hide the Edit Light item for the row:

```javascript
    var lightItem = document.getElementById('spv-ctx-light');
    if (lightItem) lightItem.style.display = spvRowLight[index] ? 'block' : 'none';
```

Add the light handlers:

```javascript
// Default sizes when a field isn't pre-seeded from light_region.
function spvLightDefaults() {
    return {shape: 'Sphere', radius: 0.25, aft: 0.0, fore: 2.0,
            sx: 0.25, sy: 0.25, sz: 0.25};
}

window.shipPropertyViewerCtxLight = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvLight = spvLightDefaults();
    var seed = spvRowLight[spvCtxIndex];
    if (seed && typeof seed === 'object') {
        // light_region is baked-shaped: radius=[r], extent=[aft,fore], scale=[sx,sy,sz]
        spvLight.shape = seed.shape || 'Sphere';
        if (seed.radius && seed.radius.length) spvLight.radius = seed.radius[0];
        if (seed.extent && seed.extent.length === 2) {
            spvLight.aft = seed.extent[0]; spvLight.fore = seed.extent[1];
        }
        if (seed.scale && seed.scale.length === 3) {
            spvLight.sx = seed.scale[0]; spvLight.sy = seed.scale[1]; spvLight.sz = seed.scale[2];
        }
    }
    shipPropertyViewerLightShape(spvLight.shape);
    document.getElementById('spv-light').style.display = 'flex';
};

function spvStepperHtml(label, field, step) {
    return '<div class="spv-stepper">'
         +   '<span class="spv-stepper__label">' + label + '</span>'
         +   '<button class="spv-step-btn" onclick="shipPropertyViewerLightStep(\'' + field + '\',' + (-step) + ')">&minus;</button>'
         +   '<span class="spv-stepper__val" id="spv-lv-' + field + '">' + spvLight[field].toFixed(2) + '</span>'
         +   '<button class="spv-step-btn" onclick="shipPropertyViewerLightStep(\'' + field + '\',' + step + ')">+</button>'
         + '</div>';
}

window.shipPropertyViewerLightShape = function (shape) {
    spvLight.shape = shape;
    ['Sphere', 'Cylinder', 'Box'].forEach(function (s) {
        var b = document.getElementById('spv-shape-' + s);
        if (b) b.classList.toggle('active', s === shape);
    });
    var html = '';
    if (shape === 'Sphere') {
        html = spvStepperHtml('Radius', 'radius', 0.05);
    } else if (shape === 'Cylinder') {
        html = spvStepperHtml('Radius', 'radius', 0.05)
             + spvStepperHtml('Aft', 'aft', 0.25)
             + spvStepperHtml('Fore', 'fore', 0.25);
    } else {   // Box
        html = spvStepperHtml('Size X', 'sx', 0.05)
             + spvStepperHtml('Size Y', 'sy', 0.05)
             + spvStepperHtml('Size Z', 'sz', 0.05);
    }
    document.getElementById('spv-light-fields').innerHTML = html;
};

window.shipPropertyViewerLightStep = function (field, delta) {
    var floor = (field === 'aft') ? -100.0 : 0.01;   // aft may be <=0; others > 0
    spvLight[field] = Math.round((spvLight[field] + delta) * 100) / 100;
    if (spvLight[field] < floor) spvLight[field] = floor;
    var el = document.getElementById('spv-lv-' + field);
    if (el) el.textContent = spvLight[field].toFixed(2);
};

window.shipPropertyViewerLightApply = function () {
    var msg = {i: spvCtxIndex, shape: spvLight.shape};
    if (spvLight.shape === 'Sphere') {
        msg.radius = spvLight.radius;
    } else if (spvLight.shape === 'Cylinder') {
        msg.radius = spvLight.radius; msg.aft = spvLight.aft; msg.fore = spvLight.fore;
    } else {
        msg.sx = spvLight.sx; msg.sy = spvLight.sy; msg.sz = spvLight.sz;
    }
    dauntlessEvent('ship-property-viewer/set_light:' + JSON.stringify(msg));
    spvHideOverlays();
};

window.shipPropertyViewerLightCancel = function () { spvHideOverlays(); };
```

- [ ] **Step 3: CSS — shape buttons + steppers (ship_property_viewer.css)**

```css
.spv-shape-row { display: flex; gap: 6px; padding: 12px 14px 4px; }
.spv-shape-btn {
    flex: 1; background: rgba(0, 0, 0, 0.35);
    border: 1px solid rgba(255, 230, 160, 0.4); color: #ffd;
    padding: 5px 0; cursor: pointer; font-family: inherit; font-size: 12px;
}
.spv-shape-btn.active { background: rgba(255, 214, 90, 0.85); color: rgb(40, 24, 8); }
.spv-stepper { display: flex; align-items: center; gap: 8px; padding: 6px 14px; }
.spv-stepper__label { color: #cdd3dc; font-size: 12px; min-width: 56px; }
.spv-stepper__val { color: #ffd; font-size: 14px; min-width: 52px; text-align: center; }
.spv-step-btn {
    width: 26px; height: 26px; background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(255, 230, 160, 0.4); color: #ffd; cursor: pointer;
    font-family: inherit; font-size: 15px; line-height: 1;
}
.spv-step-btn:hover { background: rgba(255, 214, 90, 0.25); }
```

- [ ] **Step 4: Build (host untouched, but run the gate) + live-verify**

CEF assets are runtime-loaded — no rebuild needed for the JS/HTML/CSS. Run the
gate to confirm nothing else regressed:

```bash
scripts/check_tests.sh
```
Expected: green.

Live-verify under `--developer` on the Galaxy:
1. Open the Ship Property Viewer; enable **Glow Regions** (orange wireframes appear).
2. Right-click **Center Impulse** → **Edit Light…** appears (right-click a phaser
   bank → it does NOT).
3. Modal pre-filled as Cylinder r0.25 [0,2]. Step **Radius**/**Fore** → **Apply**
   → the orange cylinder wireframe resizes live; row shows the dirty accent; the
   Save bar reads "Save changes (1)".
4. Right-click again → Edit Light → switch to **Box**, step **Size X/Y/Z** →
   **Apply** → a real orange **box** wireframe appears (and the in-scene glow, if
   the region is powered, is a box).
5. **Save changes** → confirm modal lists "Center Impulse (1)" → **Save**.
6. Inspect `engine/appc/hardpoint_overrides.py`: `_galaxy`'s `Center Impulse`
   block now has the new `SetGlowRegion*` calls, cleanly (no orphan setters from
   the previous shape).
7. Reload the mission → the glow persists at the saved shape/size.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/ship_property_viewer.css
git commit -m "feat(spv): Edit Light context item + mouse-only shape/size modal

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Phase 0 shader box branch + `u_glow_region_e` → Task 2.
- Native box primitive/storage/upload/binding → Task 2.
- `resolve_baked_region`/`_register_baked` box → Task 1.
- Debug wireframe box → Task 3 (C++) + Task 4 (Python emission/wiring).
- `set_region` writer → Task 5. Mixed-edit target → Task 6.
- Glow-category helper + descriptor `light`/`light_region` + `region_spec_to_calls` → Task 7.
- Panel staging/save/dirty/tally/`pending_light_specs` → Task 8.
- Live preview via pending override → Task 9.
- Edit Light menu + mouse-only shape/size modal → Task 10.
- Menu gated to impulse/warp/sensor → Task 7 (`glow_bearing_subsystem_ids`) + Task 10 (`row.light`).
- Box body-axis-aligned, no orientation editor → Task 2 (shader `abs(d)`), Task 8 (no axis field for Box).
- Index 0 only → every `set_light`/`region_spec_to_calls`/save uses index 0.
- Staged, explicit Save/confirm, keep-on-failure → Task 8 (`save` clears only on success; confirm modal is existing UI).

**Placeholder scan:** none — every step carries real code or exact commands. The
snapshot-tuple note in Task 8 resolves to the count form explicitly.

**Type consistency:** region spec is baked-shaped everywhere (`radius=(r,)`,
`extent=(aft,fore)`, `scale=(sx,sy,sz)`, `position`/`axis` 3-tuples) — produced by
`_light_region_spec`/`set_light` (Task 7/8), consumed by `region_spec_to_calls`
(Task 7) and `resolve_baked_region` (Task 1/9). Edit tuples: radius 3-tuple
`(name,"SetRadius",(v,))`; light 4-tuple `(name,"__region__",0,calls)` — produced
in Task 8, consumed in Task 6. Overlay returns `(cylinders, boxes)` from Task 4
on; every caller (host_loop, tests) unpacks the pair. `add_box_region(iid, center,
half_extents)` signature identical in Task 1 (wrapper), Task 2 (binding), Task 4
(unused there). `DebugBox` fields `center/ex/ey/ez/color` identical in Task 3
(struct + binding) and Task 4 (emission).

**Out-of-scope confirmed absent:** no position/axis editor; no region index > 0;
no live-while-you-step (Apply then preview); no modded-ship target.

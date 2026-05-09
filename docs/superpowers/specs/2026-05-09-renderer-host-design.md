# Renderer Host — Design Spec

**Date:** 2026-05-09
**Status:** Approved (pending implementation)
**Phase:** 2 (Full C++ engine), third sub-project

## Goal

Bring up a C++ host binary `open_stbc_host` that embeds CPython 3.x, runs the
existing Phase 1 engine inside its process, and renders the running game to a
window in lock-step with the 60 Hz tick. The v1 ship gate is the simplest BC
mission rendering — player ship plus NPC ships at their real game-loop
positions, BC skybox, hard-coded lighting, fixed third-person camera.

This sub-project intentionally bundles four items from the renderer breakdown
that the brainstorming process scoped together:

- **Item 3** — scene-graph runtime (transform propagation, instance management;
  frustum culling deferred to v2 — see "Deferred / future work")
- **Item 4 (minimal)** — render pipeline (GLFW window + GL 3.3 core context,
  forward shader, draw submission)
- **Item 5** — Python ↔ C++ glue, in the Phase 2 end-state form (C++ host
  embedding CPython, *not* a temporary bridge)
- **Item 6 (partial)** — BC-specific extension for skybox rendering as a
  dedicated pass

The bundling decision is on the record; each section below is bounded so the
implementation plan can be staged and course-corrected mid-flight.

## Non-goals

- No animation playback, no skinned-mesh rendering (data is in `Model` already
  via the asset pipeline; runtime evaluation deferred)
- No frustum culling. The asset pipeline does not currently produce per-`Mesh`
  or per-`Model` bounding volumes, and M1 Basic-class scenes have ~10 ships
  — culling has no v1 payoff. The scene-graph submits every visible instance
  each frame
- No interpretation of BC's per-mission/system skybox lookup config (v1 uses a
  single hard-coded default skybox NIF)
- No interpretation of BC's `NiAmbientLight` / `NiDirectionalLight` blocks
  (v1 uses hard-coded ambient + single directional)
- No LOD selection (asset pipeline doesn't populate `lod_chain` yet)
- No decoupled render thread, no inter-tick interpolation
- No render targets, framebuffers, or post-processing
- No HUD, UI, tactical view, bridge view, or any in-game camera mode
- No procedural FX (explosions, weapon fire, warp trails) — gap analysis
  confirms these are runtime-procedural, not asset-pipeline-driven
- No hardpoint-marker or damage-node interpretation (item 6 in full)
- No mod / asset-overlay support
- No save/load coverage for render state (Phase 1 concern; render state is
  rebuilt at load from Python ship state)
- No BC input system integration; v1 has no debug fly-around camera, only a
  fixed third-person offset behind the player ship
- No replacement of the existing headless test harness; `gameloop_harness.py`
  and the pytest suite continue to run via `uv run` unchanged

## Success criteria (v1 ship gate)

1. `cmake --build build --target open_stbc_host` produces
   `build/bin/open_stbc_host` on macOS and Linux.

2. Running `./build/bin/open_stbc_host <mission_name>`:
   - Opens a 1280×720 window titled "open_stbc"
   - Boots the existing Phase 1 engine inside the embedded interpreter
   - Initializes the named mission via the same path `gameloop_harness` uses
   - Renders 60 frames per second, lock-step with the tick
   - Shows the player ship and any NPC ships the mission spawns at their
     actual game-loop world positions and orientations
   - Shows the hard-coded default BC skybox behind everything
   - Closes cleanly when the window's close button is pressed (no leaked GL
     handles, no leaked Python references, exit code 0)

3. The mission used for the visible ship gate is selected by ranking
   `sdk/Build/scripts/Missions/` candidates by Python source-line count and
   spawn count, picking the smallest-sum candidate; this scan is a discrete
   task in the implementation plan, not a decision baked into the spec.

4. The existing `pytest` suite continues to pass via `uv run pytest` with no
   changes to its invocation.

5. New `pytest` cases drive `_open_stbc_host` against an offscreen GLFW
   context and verify import, init, a few frames of synthetic transforms,
   shutdown — no crashes, state queries return expected values.

6. New `ctest` cases cover scene-graph transform propagation, frustum-cull
   math, and camera matrix construction (pure C++, no GL); plus
   shader-compile/link and minimal-draw smoke tests under the existing
   offscreen GL fixture pattern.

---

## Architecture

### Where it lives

Three new top-level subtrees under `native/src/`:

- `native/src/host/` — host binary entry point and pybind11 module source
- `native/src/renderer/` — window, GL context, shader pipeline, draw submission
- `native/src/scenegraph/` — instance registry, transform propagation, culling,
  camera

One new Python module under `engine/`:

- `engine/host_loop.py` — bridges existing mission-init / tick logic to the
  renderer
- `engine/renderer.py` — Pythonic wrapper around the `_open_stbc_host` C++
  bindings module

### Dependency graph

```
nif (existing)
  ↑
assets (existing)
  ↑
scenegraph ──→ renderer ──→ host
                              ↑
                          pybind11 (new third_party), Python::Python (FindPython3),
                          GLFW (existing in tests, promoted to runtime dep)

engine/host_loop.py  ──imports──→  _open_stbc_host (built by host target)
engine/renderer.py   ──imports──→  _open_stbc_host
```

`scenegraph` and `renderer` are sibling libraries; both are linked by `host`.
`scenegraph` does not link any GL — it operates on plain math types and
hands draw lists to `renderer`.

### Threading and frame model

Single thread, lock-step at 60 Hz, mirroring BC's measured loop (60 Hz fixed,
single-threaded from Python's perspective per `docs/gap_analysis.md`).

Per-iteration shape:

```
acquire GIL (already held — single thread)
  → call engine.host_loop.tick()         # existing GameLoop.tick under the hood
  → for each tracked ship: pull transform, push via set_world_transform
  → set_camera (fixed third-person offset behind player ship in v1)
  → frame()
      → propagate scene-graph transforms (no-op pass-through in v1; reserved
        for item 6 hardpoint attachment)
      → skybox pass (depth-write off, projection translation removed)
      → opaque pass (depth-test on, depth-write on; iterate every visible
        instance — no culling in v1)
      → glfwSwapBuffers (vsync gates the loop to ~60 Hz)
      → glfwPollEvents
  → if should_close(): break
```

Vsync provides the timing gate; if vsync is off (offscreen tests), the loop
does not sleep — tests drive a fixed tick count and exit.

---

## Components

### `native/src/host/`

| File | Purpose |
|---|---|
| `host_main.cc` | `main()`. Parses CLI args (mission name, optional window flags). Calls `Py_InitializeEx`, configures `sys.path` to include the project root and `engine/`, imports `engine.host_loop`, calls `run(mission_name)`. On return, finalizes the interpreter and exits. |
| `host_bindings.cc` | pybind11 `PYBIND11_MODULE(_open_stbc_host, m)` definition. Wraps `Renderer`, `SceneGraph`, and `AssetCache` operations into a single flat module surface (see API below). |
| `CMakeLists.txt` | Defines `open_stbc_host` executable target and `_open_stbc_host` module library; both consume the same `host_bindings.cc` source. |

### `native/src/renderer/`

| File | Purpose |
|---|---|
| `window.h/cc` | `Window` RAII type. Constructor calls `glfwInit`, `glfwCreateWindow`, `glfwMakeContextCurrent`, `glfwSwapInterval(1)`. Exposes `should_close()`, `swap_buffers()`, `poll_events()`, `framebuffer_size()`. Destructor tears down GLFW. |
| `shader.h/cc` | `Shader` RAII type. Compiles + links a vertex/fragment pair from `shaders/*.glsl` (path-relative to binary). Exposes uniform setters for `mat4`, `vec3`, `int`. |
| `pipeline.h/cc` | `Pipeline` owns the opaque-pass `Shader` and the skybox-pass `Shader`. Owns the GL state setup helpers (`glEnable(GL_DEPTH_TEST)`, `glCullFace`, etc.) called once at init. |
| `frame.h/cc` | `FrameSubmitter::submit(world: const SceneGraph&, camera: const Camera&)` issues all draw calls for one frame. Iterates visible instances from the scene graph, sets per-draw uniforms, binds VAO/textures from `assets::Mesh`/`assets::Texture`, calls `glDrawElements`. Skybox pass first, opaque pass second. |
| `shaders/opaque.vert`, `shaders/opaque.frag` | Single forward pass: vertex transforms by `model * view * proj`; fragment uses ambient + N·L diffuse from the per-mesh `Material` diffuse colour and base-colour texture. |
| `shaders/skybox.vert`, `shaders/skybox.frag` | Skybox: vertex shader strips translation from view matrix; fragment samples base-colour texture. |
| `CMakeLists.txt` | `renderer` library; depends on `assets`, GLFW, GLAD. |

### `native/src/scenegraph/`

| File | Purpose |
|---|---|
| `instance.h` | `struct Instance { ModelHandle model; glm::mat4 world; bool visible = true; bool dirty = true; }`. `using InstanceId = uint32_t;` |
| `world.h/cc` | `class World`. Owns `std::vector<Instance>` keyed by `InstanceId` (a generational handle to support reuse-after-destroy). Provides `create_instance`, `destroy_instance`, `set_world_transform`, `set_visible`, `set_skybox`. Per-frame `propagate()` is currently a pass-through (Phase 1 ships have no parent/child hierarchy *between* ships; intra-model node hierarchy is already baked into `Model::nodes` by the asset pipeline). The hook is reserved so item 6 work — hardpoints attached to ship instances — can attach later without an API break. |
| `camera.h/cc` | `class Camera`. Fields: eye, target, up, fov_y, near, far, aspect. `view_matrix()` returns a `glm::lookAt`. `proj_matrix()` returns `glm::perspective`. |
| `CMakeLists.txt` | `scenegraph` library; depends on `assets`, `glm`. No GL link. |

### `engine/host_loop.py`

```python
def run(mission_name: str, *, max_ticks: int | None = None) -> int:
    """Boot the renderer, init the named mission, run until window closes
    or max_ticks reached. Returns 0 on clean exit."""
```

Internally:
1. `_open_stbc_host.init(1280, 720, "open_stbc")`
2. Calls existing Phase 1 mission init (same path as `gameloop_harness`):
   `Initialize(pMission)`, `ET_MISSION_START` event fired
3. Walks the current ship registry, calls `_open_stbc_host.load_model` for
   each unique ship NIF, `create_instance` per ship; stores `(ship_id →
   instance_id)` map
4. Sets the default skybox via `set_skybox`
5. Tick loop:
   - `GameLoop.tick()`
   - For each tracked ship: convert position/orientation to a flat 16-float
     row-major matrix, call `set_world_transform`
   - Compute fixed third-person camera offset behind player ship; call
     `set_camera`
   - `_open_stbc_host.frame()`
   - if `should_close()` or tick count exceeded: break
6. Destroy instances; `_open_stbc_host.shutdown()`

### `engine/renderer.py`

Thin wrapper that re-exports `_open_stbc_host` symbols with type hints and
docstrings. No logic. Exists so call sites import `engine.renderer`, not
`_open_stbc_host` directly.

---

## Python bindings surface (`_open_stbc_host`)

```python
init(width: int, height: int, title: str) -> None
shutdown() -> None
should_close() -> bool

load_model(nif_path: str, texture_search_path: str) -> ModelHandle

create_instance(model: ModelHandle) -> InstanceId
destroy_instance(id: InstanceId) -> None
set_world_transform(id: InstanceId, mat4: list[float]) -> None  # 16 floats, row-major
set_visible(id: InstanceId, visible: bool) -> None

set_camera(eye: tuple[float, float, float],
           target: tuple[float, float, float],
           up: tuple[float, float, float],
           fov_y_rad: float, near: float, far: float) -> None

set_skybox(model: ModelHandle | None) -> None

frame() -> None  # propagate, cull, skybox pass, opaque pass, swap, poll
```

`ModelHandle` and `InstanceId` are opaque pybind11-bound types. `mat4` crosses
the boundary as a `list[float]` of length 16 (row-major) — chosen over numpy
to keep numpy out of the binding surface; Python callers can format from
whatever they have.

No event callbacks or Python-side subscriptions in v1. Python pulls; doesn't
subscribe.

---

## Skybox & lighting

### Skybox

Treat the BC skybox NIF as a normal `Model` loaded via `AssetCache::load`. The
asset pipeline already produces correct geometry, textures, and materials
from the NIF. The renderer renders it with a dedicated pass *before* the
opaque pass:

- Bind skybox `Shader`
- Set `view_no_translation = mat4(mat3(camera.view_matrix()))`
- Set `proj = camera.proj_matrix()`
- `glDepthMask(GL_FALSE)`, `glDepthFunc(GL_LEQUAL)`
- Draw the skybox model
- Restore `glDepthMask(GL_TRUE)`, `glDepthFunc(GL_LESS)` for the opaque pass

The "which skybox NIF for which mission" lookup is non-trivial — BC stores
this in per-system or per-mission Python config. In v1, the skybox path is a
single hard-coded constant in `engine/host_loop.py`, picked from a known
location in `game/data`. **Deferred-work item:** "Skybox path lookup from
mission/system config."

### Lighting

Hard-coded in the opaque shader:

- Ambient: `vec3(0.1, 0.1, 0.1)`
- Single directional light: direction `normalize(vec3(-0.3, -1.0, -0.2))`,
  colour `vec3(1.0, 1.0, 1.0)`

Per-mesh material values *are* used — diffuse colour and base-colour texture
flow through from the asset pipeline's `Material`. What's hard-coded is only
the *light source*, not the *surface response*. This means materials that
the asset pipeline already builds (item 2 ship gate already validated this)
render with their real BC values; only the lighting environment is faked.

**Deferred-work item:** "BC light data interpretation from `NiAmbientLight` /
`NiDirectionalLight` blocks in scene NIFs."

---

## Build system

- New CMake target `open_stbc_host` (executable) and `_open_stbc_host`
  (Python module shared library), both defined in
  `native/src/host/CMakeLists.txt`. Both consume `host_bindings.cc`; the
  executable additionally has `host_main.cc`.
- New CMake `find_package(Python3 COMPONENTS Development Embed)` for the
  embedded interpreter and module build.
- pybind11 vendored under `native/third_party/pybind11/` (or fetched via
  CMake `FetchContent` — to be decided in the implementation plan based on
  what's least intrusive on offline builds).
- GLFW promoted from "test-only dep" to "runtime dep"; same source either
  way (existing `gl_fixture.h` keeps using it for offscreen tests).
- The binary is invoked directly as `./build/bin/open_stbc_host <mission>`.
  The embedded interpreter sets `PYTHONHOME` / `PYTHONPATH` at startup from
  the active `uv`-managed venv (resolved via `VIRTUAL_ENV` env var; falls
  back to the system Python config if unset). Tighter `uv run` integration
  (e.g., a Python wrapper script registered in `[project.scripts]`) is a
  plan-time decision, not a spec-time decision.

---

## Tests & verification

| Layer | Test type | Coverage |
|---|---|---|
| Scene-graph math | C++ gtest, no GL | `Camera::view_matrix` / `proj_matrix` correctness against hand-computed reference; `World::create_instance` / `destroy_instance` generational-handle reuse; `World::propagate` is a no-op pass-through in v1 but covered by a regression test so the seam stays intact |
| Renderer (offscreen) | C++ gtest using the existing `gl_fixture.h` pattern | `Shader` compile + link succeeds for both opaque and skybox shaders; `Pipeline::init` configures GL state without errors; minimal one-mesh draw produces a non-clear-coloured framebuffer; skybox pass leaves depth buffer untouched |
| Bindings | pytest, offscreen GLFW context | Import `_open_stbc_host`; `init`/`shutdown` round-trip; `load_model` returns valid handle on a sample NIF; `create_instance`/`set_world_transform`/`destroy_instance` cycle; `frame()` runs without exception |
| Integration | pytest end-to-end | Boot `engine.host_loop.run` against a *synthetic* 1-tick "mission" stub: init → instance create → set transforms → 1 frame → shutdown all clean |
| Visible ship gate | Manual run | `./build/bin/open_stbc_host <picked-mission>`; player ship and NPCs render at correct positions; skybox visible; close cleanly |

The headless `pytest` suite continues to run via `uv run pytest` and stays
untouched. The host adds a separate run mode; it does not replace any
existing harness.

---

## Deferred / future work

The following items are mirrored to a deferred-work tracker at
`native/src/host/docs/deferred_work.md`, following the asset-pipeline
precedent (its tracker lives at `native/src/assets/docs/deferred_work.md`):

1. **Skybox path lookup from mission/system config** — replaces the v1
   hard-coded default skybox.
2. **BC light data interpretation** — read `NiAmbientLight` /
   `NiDirectionalLight` blocks from scene NIFs and feed real values to the
   shaders.
3. **Animation playback** — evaluate `AnimationClip` data already present in
   `Model` and apply to scene-graph instance transforms or sub-node
   transforms. (Asset pipeline deferred-work item #14 points here.)
4. **Skinned-mesh rendering** — bone palette uniform, vertex skinning in the
   vertex shader, evaluation against `Skeleton` data already in `Model`.
5. **LOD selection** — depends on asset pipeline populating `Mesh::lod_chain`
   first (asset pipeline deferred-work item #1).
6. **Frustum culling** — sphere-in-frustum test once scene-instance count
   grows beyond a few dozen. Requires the asset pipeline to produce per-`Model`
   bounding volumes; cross-cutting work into the asset pipeline. The
   `Camera::view_matrix` / `proj_matrix` infrastructure in v1 is already
   sufficient to derive frustum planes when needed.
7. **Decoupled render thread / interpolation** — option B from the
   brainstorming question; off-table for v1, available if profiling later
   shows headroom problems.
8. **Render targets / framebuffers / post-processing** — required for
   bloom, motion blur, etc.; none of these are v1 surface.
9. **Debug fly-around camera** — mouse + WASD; needs an input-binding
   layer.
10. **In-game camera modes** — tactical, bridge, external orbit, cinematic;
    each needs its own camera-state machine and BC-config interpretation.
11. **HUD and UI** — separate sub-project entirely; not part of any item in
    the renderer breakdown.
12. **Procedural FX** (explosions, weapon fire, warp trails) — gap analysis
    confirms runtime-procedural; will need its own renderer pass and
    particle system.
13. **Hardpoint-marker / damage-node interpretation** — the rest of item 6
    in the renderer breakdown.
14. **Mod / asset-overlay support** — depends on asset pipeline gaining the
    same (asset pipeline deferred-work item #6).
15. **Save/load coverage of render state** — Phase 1 concern; render state
    is rebuilt at load from Python ship state, but the seam needs to be
    formalized once Phase 1 save/load lands.
16. **BC input system integration** — keyboard/mouse/joystick mapping
    matching BC's input scheme, distinct from the v1 fixed third-person
    camera.

---

## Update protocol

When a deferred-work item is added, removed, or moves on/off the list, update
both this spec's "Deferred / future work" section and the matching
`docs/architecture/sub_project_status.md` row for this sub-project. When the
v1 ship gate is met, update the status doc's headline status and date.

# Sun Rendering — Design

**Status:** Approved, pre-implementation.
**Sub-project:** Renderer host — Sun rendering (procedural sphere body + corona shell).
**Related specs:**
- [2026-05-10-skybox-backdrops-design.md](2026-05-10-skybox-backdrops-design.md) — structural template for this work
- [2026-05-10-bc-light-data-design.md](2026-05-10-bc-light-data-design.md) — three-layer architecture reference

## Why this scope

BC's Sun is not a NIF mesh — it is a procedural 3D sphere textured with one of five
`SunBase`/`SunRed`/`SunYellow`/`SunBlueWhite`/`SunRedOrange` TGA files (confirmed
sphere UV maps). Survey of `sdk/Build/scripts/Systems/`:

- **Every** space system that contains a star calls `App.Sun_Create(radius,
  atmosphere_thickness, damage_per_sec[, base_texture[, flare_texture]])`.
- Many calls omit texture args (e.g. Biranu1_S.py passes only the three numeric args);
  the original engine presumably fell back to a default.
- `atmosphere_thickness` is always equal to or greater than `radius` in stock content
  (typical: `Sun_Create(4000, 4000, 500)`, `Sun_Create(1000, 1000, 500)`).
- Sun textures live at `data/Textures/Sun*.tga`; all five variants are present in
  `game/data/Textures/`.

Phase 1 today has `Sun_Create` storing the data but `host_loop.run()` skips Sun objects
in `_iter_planets`. This sub-project wires the full path.

Lens flares (`Tactical.LensFlares.YellowLensFlare`) are out of scope — they require a
screen-space sprite pass and are tracked as a follow-up in `deferred_work.md`.

## Goals

1. Render each Sun as an opaque UV-sphere at its world-space position, scaled to its
   radius, textured with `base_texture`.
2. Render a corona shell (additive-blended outer sphere at `radius + atmosphere_thickness`)
   as the secondary deliverable of this sub-project.
3. Draw order: backdrop pass → sun pass → opaque pass, so ships/planets correctly
   occlude sun geometry at close range.
4. Use the existing `build_uv_sphere()` infrastructure; no new geometry primitives.
5. Follow the same spec → TDD → implement → verify pattern as the backdrop sub-project.

## Non-goals

- **Lens flares.** `Tactical.LensFlares.*` calls are scoped as a separate follow-up;
  tracked in `native/src/host/docs/deferred_work.md`.
- **Animated corona / corona texture.** Stock content uses no animated corona; the
  corona is a tinted additive shell driven purely by the latitude-fade formula.
- **NIF-based sun meshes.** BC ships no sun NIFs; procedural sphere is the correct path.
- **Sunlight source.** The sun object is not wired to the lighting system; that's a
  separate concern and BC's ambient/directional lights are already driven from
  script-side `LightPlacement` objects.

## Architecture

Three layers, three responsibilities (mirroring lighting and backdrop sub-projects):

```
SDK script (e.g. Biranu1_S.py, Cebalrai3_S.py)
   │  Initialize() / LoadPlacements()
   ▼
App.Sun_Create(radius, atmosphere_thickness, damage_per_sec,
               base_texture="", flare_texture="")
pSet.AddObjectToSet(pSun, "Sun")
pSun.PlaceObjectByName("Sun")    ← copies world position from waypoint registry
   │
   ▼
Sun object (Planet subclass, engine/appc/planet.py)
  .GetRadius()           → body sphere radius
  .GetAtmosphereRadius() → corona shell thickness
  .GetModelPath()        → base_texture path (stored as _model_path by Sun_Create)
  .GetWorldLocation()    → world-space position (set by PlaceObjectByName)
   │
   │  (each tick, host_loop.run)
   ▼
_aggregate_suns(project_root, sets) → list[dict]:
  {
    "position":          (x, y, z),
    "radius":            float,
    "base_texture_path": str,        # absolute, pre-validated
    "corona_radius":     float,      # radius + atmosphere_thickness
  }
r.set_suns([...])
   │
   ▼
host_bindings.cc: g_suns: std::vector<SunDescriptor>
frame(): backdrop_pass → sun_pass → opaque_pass
   │
   ▼
SunPass::render(suns, camera, pipeline)
  per sun:
    1. body sphere  — opaque, full MVP (translate to position, scale by radius), unlit
    2. corona sphere — additive (GL_SRC_ALPHA, GL_ONE), same center, corona_radius
                       alpha tapered by sin(v_uv.y * π) in fragment shader
```

**Render order in `frame()`:**
- `g_backdrop_pass->render(...)` — backdrops at far plane (z = w)
- `g_sun_pass->render(...)` — suns at real world-space depth
- `g_submitter->submit_opaque(...)` — ships, planets with depth test

## Phase-1 Appc changes

### `engine/appc/planet.py` — new `aggregate_suns_for_renderer`

No changes to the `Sun` class or `Sun_Create` factory — they already store all
required data. A new module-level function handles aggregation:

```python
def aggregate_suns_for_renderer(project_root, pSets):
    """Return list[dict] for all Sun objects across pSets.

    Suns with empty base_texture are dropped with a once-per-object warning
    (suppressed after the first fire via a _sun_warned flag on the instance).
    Suns with unresolvable texture paths are dropped with the same once-per-object
    warning. Suns with radius <= 0 are dropped silently.
    Returns [] when pSets is empty or contains no Sun objects.
    """
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            if not isinstance(obj, Sun):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            loc = obj.GetWorldLocation()
            tex_rel = obj.GetModelPath()
            if not tex_rel:
                if not getattr(obj, "_sun_warned", False):
                    print(f"[suns] no texture for Sun at "
                          f"({loc.x:.0f},{loc.y:.0f},{loc.z:.0f}); skipping",
                          flush=True)
                    obj._sun_warned = True
                continue
            abs_path = (project_root / "game" / tex_rel).resolve()
            if not abs_path.is_file():
                if not getattr(obj, "_sun_warned", False):
                    print(f"[suns] texture not found: {tex_rel!r}; skipping",
                          flush=True)
                    obj._sun_warned = True
                continue
            out.append({
                "position":          (loc.x, loc.y, loc.z),
                "radius":            radius,
                "base_texture_path": str(abs_path),
                "corona_radius":     radius + obj.GetAtmosphereRadius(),
            })
    return out
```

### `engine/host_loop.py` additions

```python
def _iter_suns():
    """Walk every Sun in every active set."""
    import App
    from engine.appc.planet import Sun
    for pSet in App.g_kSetManager._sets.values():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Sun):
                yield obj


def _aggregate_suns():
    """Thin wrapper supplying PROJECT_ROOT and all sets."""
    from engine.appc.planet import aggregate_suns_for_renderer
    import App
    return aggregate_suns_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))
```

In `run()`, after `r.set_backdrops(backdrops)`:

```python
suns = _aggregate_suns()
r.set_suns(suns)

if verbose and ticks == 0:
    print(f"[host_loop] tick 0 suns: {len(suns)} sun(s)", flush=True)
```

### `engine/renderer.py` addition

```python
def set_suns(suns: list) -> None:
    """Configure the renderer's sun list. Each entry is a dict:
        {
            "position":          (x, y, z),
            "radius":            float,
            "base_texture_path": str (absolute),
            "corona_radius":     float,
        }
    """
    _h.set_suns(suns)
```

## Renderer changes (C++)

### `renderer/frame.h` — new `SunDescriptor` struct

Added alongside `Backdrop` and `Lighting`:

```cpp
struct SunDescriptor {
    glm::vec3   position;                  // world-space center
    float       radius        = 1.0f;      // body sphere radius (BC units)
    std::string base_texture_path;
    float       corona_radius = 0.0f;      // 0 = no corona; draw when > radius
};
```

### New files: `renderer/include/renderer/sun_pass.h`

```cpp
#pragma once

#include <renderer/frame.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

class SunPass {
public:
    SunPass() = default;
    ~SunPass();
    SunPass(const SunPass&) = delete;
    SunPass& operator=(const SunPass&) = delete;

    void render(const std::vector<SunDescriptor>& suns,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    std::unordered_map<int, std::unique_ptr<assets::Mesh>>    sphere_cache_;
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>> texture_cache_;

    assets::Mesh*    ensure_sphere(int target_tris = 256);
    assets::Texture* ensure_texture(const std::string& path);
};

}  // namespace renderer
```

### `renderer/sun_pass.cc`

`ensure_sphere` and `ensure_texture` are identical in structure to
`BackdropPass`'s implementations (lazy-allocate, sentinel cache entries for
failed loads, `build_uv_sphere` for geometry, `decode_tga` + `upload_image`
for textures).

`render` logic:

```cpp
void SunPass::render(const std::vector<SunDescriptor>& suns,
                     const scenegraph::Camera& camera,
                     Pipeline& pipeline) {
    if (suns.empty()) return;

    auto& shader = pipeline.sun_shader();
    shader.use();
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_mat4("u_view", camera.view_matrix());  // full view — no translation strip

    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
    glCullFace(GL_FRONT);  // render inside of sphere

    for (const auto& s : suns) {
        assets::Mesh*    sphere = ensure_sphere();
        assets::Texture* tex    = ensure_texture(s.base_texture_path);
        if (!sphere || !tex) continue;

        // Body: opaque, full MVP
        glm::mat4 model = glm::translate(glm::mat4(1.0f), s.position)
                        * glm::scale(glm::mat4(1.0f), glm::vec3(s.radius));
        shader.set_mat4("u_model", model);
        shader.set_int("u_corona", 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, tex->id());
        shader.set_int("u_texture", 0);
        glBindVertexArray(sphere->vao());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);

        // Corona: additive shell
        if (s.corona_radius > s.radius) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            glm::mat4 corona_model =
                glm::translate(glm::mat4(1.0f), s.position)
                * glm::scale(glm::mat4(1.0f), glm::vec3(s.corona_radius));
            shader.set_mat4("u_model", corona_model);
            shader.set_int("u_corona", 1);
            glDrawElements(GL_TRIANGLES,
                           static_cast<GLsizei>(sphere->index_count()),
                           GL_UNSIGNED_INT, nullptr);
            glDisable(GL_BLEND);
        }
    }

    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}
```

### New shaders

**`renderer/shaders/sun.vert`** — full MVP, no translation stripping, no z=w idiom:

```glsl
#version 330 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_normal;   // unused; VAO layout compatibility
layout(location=2) in vec2 a_uv;

uniform mat4 u_proj;
uniform mat4 u_view;
uniform mat4 u_model;

out vec2 v_uv;

void main() {
    gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
    v_uv = a_uv;
}
```

**`renderer/shaders/sun.frag`** — unlit body; latitude-faded corona:

```glsl
#version 330 core

in vec2 v_uv;

uniform sampler2D u_texture;
uniform int       u_corona;   // 0 = body draw, 1 = corona draw

out vec4 frag_color;

void main() {
    vec4 tex = texture(u_texture, v_uv);
    if (u_corona == 0) {
        frag_color = vec4(tex.rgb, 1.0);
    } else {
        // v_uv.y ∈ [0,1]: poles = 0 and 1, equator ≈ 0.5
        // sin maps to 0 at poles, 1 at equator → atmospheric halo tapers off
        float fade = sin(v_uv.y * 3.14159265);
        frag_color = vec4(tex.rgb, tex.a * fade * 0.6);
    }
}
```

### `renderer/include/renderer/pipeline.h` and `pipeline.cc`

Add `sun_shader()` accessor, loaded from `sun.vert` / `sun.frag`, exactly parallel
to `backdrop_shader()`. Shader compiled and cached on first call.

### `host_bindings.cc` changes

File-scope additions alongside `g_backdrops` / `g_backdrop_pass`:

```cpp
std::vector<renderer::SunDescriptor>   g_suns;
std::unique_ptr<renderer::SunPass>     g_sun_pass;
```

`init()`: `g_sun_pass = std::make_unique<renderer::SunPass>();`

`shutdown()`: `g_sun_pass.reset();` before `g_window.reset()`, same order as
`g_backdrop_pass`.

`frame()` call order (between `g_backdrop_pass->render` and `submit_opaque`):

```cpp
g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);
g_sun_pass->render(g_suns, g_camera, *g_pipeline);
g_submitter->submit_opaque(g_world, g_camera, *g_pipeline, lookup, g_lighting);
```

`set_suns` binding:

```cpp
m.def("set_suns",
      [](const std::vector<py::dict>& descs) {
          g_suns.clear();
          g_suns.reserve(descs.size());
          for (const auto& d : descs) {
              renderer::SunDescriptor s;
              auto pos = d["position"].cast<std::tuple<float,float,float>>();
              s.position        = {std::get<0>(pos),
                                   std::get<1>(pos),
                                   std::get<2>(pos)};
              s.radius          = d["radius"].cast<float>();
              s.base_texture_path = d["base_texture_path"].cast<std::string>();
              s.corona_radius   = d["corona_radius"].cast<float>();
              g_suns.push_back(std::move(s));
          }
      },
      py::arg("suns"),
      "Set the active sun list, applied each frame().");
```

`g_suns` cleared in both `init()` and `shutdown()` for symmetry with `g_backdrops`.

## Defaults and edge cases

| Case | Handling |
|---|---|
| `base_texture` empty (e.g. Biranu1 sun) | Aggregator drops with `[suns] no texture for Sun at (...)` warning; suppressed after first fire via `obj._sun_warned` flag |
| Texture file missing from `game/` | Same once-per-object warning + drop: `[suns] texture not found: ...` |
| Texture decode failure in C++ | `stderr` once, sentinel cache entry prevents per-frame retries |
| `corona_radius <= radius` | Corona draw skipped (`if (s.corona_radius > s.radius)`) |
| `radius <= 0` | Dropped silently in aggregator |
| Sun position at origin | Valid — `PlaceObjectByName` is a no-op when the waypoint is absent |
| `set_suns([])` | `SunPass::render` returns immediately |
| `shutdown()` / `init()` cycle | `g_sun_pass.reset()` + `g_suns.clear()` in shutdown; fresh state in init |

## Testing strategy

### Pytest unit (no GL) — `tests/unit/test_appc_suns.py`

- `Sun_Create(4000, 4000, 500)` stores radius, atmosphere, damage correctly
- `Sun_Create(1000, 1000, 500, "data/Textures/SunRed.tga", ...)` stores texture via `GetModelPath()`
- `aggregate_suns_for_renderer(root, [])` → `[]`
- Sun with empty texture → dropped with warning (capsys); second call is silent
- Sun with unresolvable texture path → dropped with warning; second call is silent
- Sun with valid texture → descriptor has correct `position`, `radius`,
  `base_texture_path`, `corona_radius = radius + atmosphere`
- `corona_radius` = radius + atmosphere_thickness (not just atmosphere)
- `radius <= 0` → dropped silently

### Pytest unit — `tests/unit/test_host_loop_suns.py`

- `_iter_suns` yields Sun objects from a set
- `_iter_suns` skips plain Planet objects
- `_iter_suns` skips ship-like objects
- `_aggregate_suns` returns descriptors for suns with valid textures
- `_aggregate_suns` returns `[]` when no suns in any set

### Pytest with GL — `tests/host/test_sun_bindings.py`

- `r.set_suns([])` doesn't raise
- `set_suns` with one valid descriptor dict doesn't raise
- `frame()` after `set_suns([valid_desc])` completes without error

### Pytest with GL — `tests/host/test_sun_integration.py`

- End-to-end: load a system with a textured sun, run 5 ticks, `rc == 0`
- Existing backdrop + lighting tests still pass (regression)

### Native C++ — `native/tests/renderer/sun_pass_test.cc`

- Empty sun list produces no GL errors
- Single sun descriptor renders without GL error
- Texture cache: same path twice returns same `GLuint`
- Sphere cache: single entry after first render
- Corona draw triggered when `corona_radius > radius`; no GL error

## Files changed

| File | Change |
|---|---|
| `engine/appc/planet.py` | Add `aggregate_suns_for_renderer` |
| `engine/host_loop.py` | Add `_iter_suns`, `_aggregate_suns`; wire `r.set_suns` into `run()` |
| `engine/renderer.py` | Add `set_suns` |
| `native/src/renderer/include/renderer/frame.h` | Add `SunDescriptor` struct |
| `native/src/renderer/include/renderer/sun_pass.h` | New |
| `native/src/renderer/sun_pass.cc` | New |
| `native/src/renderer/shaders/sun.vert` | New |
| `native/src/renderer/shaders/sun.frag` | New |
| `native/src/renderer/include/renderer/pipeline.h` | Add `sun_shader()` |
| `native/src/renderer/pipeline.cc` | Load and cache `sun.vert`/`sun.frag` |
| `native/src/renderer/CMakeLists.txt` | Add `sun_pass.cc`, embed shaders |
| `native/src/host/host_bindings.cc` | Add `g_suns`, `g_sun_pass`, `set_suns`, wire `frame()` |
| `tests/unit/test_appc_suns.py` | New |
| `tests/unit/test_host_loop_suns.py` | New |
| `tests/host/test_sun_bindings.py` | New |
| `tests/host/test_sun_integration.py` | New |
| `native/tests/renderer/sun_pass_test.cc` | New |

## Deferred work

These items are explicitly out of scope and tracked in
`native/src/host/docs/deferred_work.md`:

- **Lens-flare rendering.** `Tactical.LensFlares.YellowLensFlare(pSet, pSun)` and
  variants need a screen-space sprite pass. Already listed under the backdrop
  sub-project's follow-up backlog; this spec confirms the deferral.
- **Sun as a light source.** BC's directional lights come from `LightPlacement`
  objects, not from the Sun object. Wiring Sun position → a directional light
  is a future quality-of-life improvement, not needed for Phase 1 correctness.
- **Animated corona.** No stock content uses animated corona effects.
- **Corona texture.** The corona reuses the body texture with a fade. A dedicated
  corona texture (e.g. `SunFlaresOrange.tga`) could produce a better look; the
  flare-texture arg to `Sun_Create` is already stored as `_flare_texture` for
  when this is revisited.

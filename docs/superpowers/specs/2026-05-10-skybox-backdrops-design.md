# Star-Sphere Skybox + Backdrop Layers — Design

**Status:** Draft, pre-implementation.
**Sub-project:** Renderer host deferred-work item #1 ("Skybox path lookup
from mission/system config") — re-scoped from a single-NIF skybox slot to
BC's actual procedural multi-layer backdrop system.

## Why this scope

Stock BC uses runtime-procedural backdrops, not scene NIFs. Survey of
`sdk/Build/scripts/Systems/`:

- **101 different system files** call `App.StarSphere_Create()` (every
  space scene has one).
- **425 total** `StarSphere_Create()` + `BackdropSphere_Create()` calls
  across the SDK; most systems layer 1–4 nebula overlays on the
  starfield.
- The standard pattern in `Systems/Biranu/Biranu1.LoadBackdrops`:
  `App.StarSphere_Create()` → set texture (`data/stars.tga`),
  radius (300), tiling (22×11), spans (1.0×1.0) → `pSet.AddBackdropToSet`.
- `data/stars.tga` is a 256×256 24-bit RGB tile designed to repeat 22×11
  across the sphere (≈242 tiles in azimuth × ≈11 in elevation).

Phase-1 currently has nothing for `StarSphere_Create` /
`BackdropSphere_Create` / `pSet.AddBackdropToSet`; all routes through
`_NamedStub` and silently no-ops. The renderer's existing
`g_world.skybox_model` slot is a no-op (no NIF skybox in BC's content)
and is removed in this sub-project.

## Goals

1. Wire BC's runtime backdrops (StarSphere + BackdropSphere) through to a
   new C++ render pass that draws an ordered list of textured spheres.
2. Multi-layer support: a StarSphere base plus alpha-blended overlays
   (nebula clouds), drawn in registration order.
3. Camera-anchored position, world-locked orientation: as the ship
   rotates, stars sweep across screen space (rotation reference); as the
   ship translates, the sphere translates with the camera so distance
   stays "infinite" (no parallax). Standard skybox view-matrix idiom.
4. Honor `AlignToVectors` per-backdrop so each system's intended
   starfield rotation is preserved.
5. Replace the legacy `set_skybox` API entirely (resolves
   deferred-work item #1).

## Non-goals

- **Parallax with a finite-radius origin-fixed sphere.** BC's actual
  setup uses radius 300 at origin, which produces parallax inside that
  region, but the user's stated need is rotation reference, not
  translation parallax — and the conventional translation-stripped
  skybox is simpler and avoids "ship can fly through the stars" edge
  cases.
- **Lens flares.** `Tactical.LensFlares.YellowLensFlare` decorates the
  Sun; that's sub-project #3's territory (sun + planet rendering).
- **Backdrop animation.** No stock content uses rotating nebulae;
  cosmetic future option.
- **Cubemap path.** BC uses tiled UV-spheres; mod-driven cubemap
  starfields are out of scope.

## Architecture

Three layers, three responsibilities (mirroring the lighting
sub-project):

```
SDK script (e.g. Biranu1.LoadBackdrops)
   │  Initialize() / LoadBackdrops()
   ▼
App.StarSphere_Create()       # opaque starfield
App.BackdropSphere_Create()   # alpha-blended overlay
kThis.SetName(name)
kThis.SetTextureFileName("data/stars.tga")
kThis.SetSphereRadius(300)
kThis.SetTextureHTile(22) / SetTextureVTile(11)
kThis.SetHorizontalSpan(1.0) / SetVerticalSpan(1.0)
kThis.AlignToVectors(forward, up)              # world orientation
kThis.Rebuild()                                # no-op; eval at submit
   │
   ▼   pSet.AddBackdropToSet(kThis, name)
SetClass._backdrops : list[Backdrop]   (insertion order = draw order)
   │
   │  (each tick, host_loop.run, after _resolve_active_set)
   ▼
backdrops = aggregate_for_renderer(active_set, project_root)
r.set_backdrops([{texture_path, kind, h_tile, v_tile, h_span, v_span,
                  world_rotation: list[9], target_poly_count}])
   │
   ▼
_open_stbc_host caches the descriptor list. submit_backdrops() walks
the list each frame: lazy-uploads textures + tessellates UV-spheres,
strips view-matrix translation, draws each backdrop with appropriate
blend state.
```

**Render order:** backdrops → opaque ships → (future passes). Each
backdrop draws with depth-test LEQUAL, depth-write off, front-face
culling reversed (we render the inside of the sphere). StarSphere uses
opaque blending; BackdropSphere uses
`GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA`.

## Phase-1 Appc shim additions

### New module: `engine/appc/backdrops.py`

```python
"""Phase-1 backdrop objects: StarSphere + BackdropSphere."""
from engine.appc.objects import ObjectClass


class Backdrop(ObjectClass):
    """Common storage. Subclasses differ only in their `kind`
    discriminator; the rendering blend mode is selected from kind."""
    KIND_STAR = "star"
    KIND_BACKDROP = "backdrop"

    def __init__(self, kind):
        super().__init__()
        self._kind = kind
        self._texture_path: str = ""
        self._target_poly_count: int = 256
        self._horizontal_span: float = 1.0
        self._vertical_span: float = 1.0
        self._sphere_radius: float = 300.0
        self._texture_h_tile: float = 1.0
        self._texture_v_tile: float = 1.0

    def SetTextureFileName(self, path):  self._texture_path = str(path)
    def SetTargetPolyCount(self, n):     self._target_poly_count = int(n)
    def SetHorizontalSpan(self, h):      self._horizontal_span = float(h)
    def SetVerticalSpan(self, v):        self._vertical_span = float(v)
    def SetSphereRadius(self, r):        self._sphere_radius = float(r)
    def SetTextureHTile(self, h):        self._texture_h_tile = float(h)
    def SetTextureVTile(self, v):        self._texture_v_tile = float(v)

    def Rebuild(self):
        # In real BC this regenerates the sphere mesh with the configured
        # poly count and UV mapping. We defer geometry to the renderer
        # (cached & shared per-poly_count across all backdrops), so this
        # is a no-op.
        return None


class StarSphere(Backdrop):
    def __init__(self):
        super().__init__(Backdrop.KIND_STAR)


class BackdropSphere(Backdrop):
    def __init__(self):
        super().__init__(Backdrop.KIND_BACKDROP)


def StarSphere_Create() -> StarSphere:
    return StarSphere()


def BackdropSphere_Create() -> BackdropSphere:
    return BackdropSphere()


def aggregate_for_renderer(pSet, project_root):
    """Return list[dict] in draw order with absolute texture paths and
    flattened world rotation. See Section 4 for details."""
    ...
```

### `SetClass` additions (`engine/appc/sets.py`)

```python
def __init__(self):
    ...  # existing _lights / _lights_by_name / _cameras / etc.
    self._backdrops: 'list["Backdrop"]' = []

def AddBackdropToSet(self, backdrop, name):
    """SDK signature: pSet.AddBackdropToSet(obj, name).

    Appended to _backdrops in registration order. Draw order matches
    insertion order (StarSphere first, nebula overlays after).
    """
    if hasattr(backdrop, "SetName"):
        backdrop.SetName(name)
    self._backdrops.append(backdrop)
    return None
```

The existing `_RendererStub` catch-all stops intercepting
`AddBackdropToSet`; all other unknown method names still chain through
the stub unchanged.

### `App.py` exports

Add to the existing import block alongside `engine.appc.lights`:

```python
from engine.appc.backdrops import (
    Backdrop, StarSphere, BackdropSphere,
    StarSphere_Create, BackdropSphere_Create,
)
```

## Renderer changes (C++)

### Files removed

- `native/src/renderer/shaders/skybox.vert`
- `native/src/renderer/shaders/skybox.frag`
- `Pipeline::skybox_shader()` (replaced by `backdrop_shader()`)
- `FrameSubmitter::submit_skybox`
- `World::skybox_model` / `World::set_skybox` / `World::skybox_model_`
- `_open_stbc_host.set_skybox` binding
- `engine.renderer.set_skybox`
- `host_loop.DEFAULT_SKYBOX_NIF` and the related `r.load_model` /
  `r.set_skybox` boot-time calls
- `tools/pick_default_skybox.py` (dead post-spec)

### Files added

- `native/src/renderer/shaders/backdrop.vert`
- `native/src/renderer/shaders/backdrop.frag`
- `native/src/renderer/include/renderer/backdrop_pass.h`
- `native/src/renderer/backdrop_pass.cc`

### `renderer::Backdrop` struct (`renderer/frame.h`)

```cpp
enum class BackdropKind { Star, Backdrop };

struct Backdrop {
    /// Source descriptor; matched against the renderer's per-texture
    /// cache. The renderer uploads on first sight and reuses thereafter.
    std::string texture_path;
    BackdropKind kind = BackdropKind::Star;
    float h_tile = 1.0f;        // texture HTile multiplier
    float v_tile = 1.0f;        // texture VTile multiplier
    float h_span = 1.0f;        // [0,1] coverage for partial overlays
    float v_span = 1.0f;        // [0,1] coverage for partial overlays
    glm::mat3 world_rotation = glm::mat3(1.0f);
    int target_poly_count = 256;
};
```

### `BackdropPass` (`renderer/backdrop_pass.h`)

```cpp
class BackdropPass {
public:
    BackdropPass() = default;
    ~BackdropPass();
    BackdropPass(const BackdropPass&) = delete;
    BackdropPass& operator=(const BackdropPass&) = delete;

    void render(const std::vector<Backdrop>& backdrops,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::filesystem::path& texture_search_dir);

private:
    /// Lazy-tessellated UV sphere keyed by target_poly_count. Most BC
    /// systems use 256; cache grows on demand.
    std::unordered_map<int, MeshHandle> sphere_cache_;
    /// Texture cache keyed by absolute path.
    std::unordered_map<std::string, GLuint> texture_cache_;

    MeshHandle ensure_sphere(int target_poly_count);
    GLuint     ensure_texture(const std::string& path,
                              const std::filesystem::path& search_dir);
};
```

### Sphere geometry generator

UV-sphere by latitude × longitude segments; target poly count splits
2:1 (lat:lon) so `target=256` → 8 lat × 16 lon = 128 quads = 256 tris.
Inside-facing winding (clockwise from outside; CCW from inside given
our `glFrontFace(GL_CW)` choice from earlier work) so back-face culling
reveals the textured interior.

UV layout: `u = lon / (2π)` ∈ [0,1], `v = (lat + π/2) / π` ∈ [0,1]. The
top and bottom of the sphere converge at v=0 and v=1; texture stretching
at the poles is acceptable for BC's stars.tga and stock backdrops.

### Backdrop fragment shader (`backdrop.frag`)

```glsl
#version 330 core

in vec3 v_pos_local;
in vec2 v_uv;

uniform sampler2D u_texture;
uniform vec2  u_tile;
uniform vec2  u_span;
uniform int   u_use_alpha;

out vec4 frag_color;

void main() {
    if (v_uv.x > u_span.x || v_uv.y > u_span.y) {
        if (u_use_alpha == 1) discard;
    }
    vec2 uv = vec2(v_uv.x * u_tile.x, v_uv.y * u_tile.y);
    vec4 tex = texture(u_texture, uv);
    if (u_use_alpha == 1) {
        frag_color = vec4(tex.rgb, tex.a);
    } else {
        frag_color = vec4(tex.rgb, 1.0);
    }
}
```

### Backdrop vertex shader (`backdrop.vert`)

```glsl
#version 330 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec2 a_uv;

uniform mat4 u_view_no_translation;
uniform mat4 u_proj;
uniform mat3 u_world_rotation;

out vec3 v_pos_local;
out vec2 v_uv;

void main() {
    vec3 rotated = u_world_rotation * a_pos;
    v_pos_local = rotated;
    v_uv = a_uv;
    vec4 clip = u_proj * u_view_no_translation * vec4(rotated, 1.0);
    // Skybox-depth idiom: force fragment to the far plane so any
    // subsequently-drawn opaque geometry always wins LEQUAL depth tests.
    clip.z = clip.w;
    gl_Position = clip;
}
```

### GL state per backdrop in `BackdropPass::render`

```cpp
glDepthMask(GL_FALSE);
glDepthFunc(GL_LEQUAL);
glCullFace(GL_FRONT);     // we're inside the sphere; cull front faces
for (const auto& b : backdrops) {
    if (b.kind == BackdropKind::Backdrop) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    } else {
        glDisable(GL_BLEND);
    }
    // bind texture, set uniforms, bind sphere VAO, draw indexed
}
glDisable(GL_BLEND);
glCullFace(GL_BACK);
glDepthMask(GL_TRUE);
glDepthFunc(GL_LESS);
```

### `host_bindings.cc` changes

- Drop `set_skybox`, `g_world.skybox_model()` access in `frame()`, the
  `submit_skybox` call.
- Add file-scope `std::vector<renderer::Backdrop> g_backdrops;` and a
  `BackdropPass g_backdrop_pass;` (the latter owns sphere + texture
  caches; reset on `init()` and `shutdown()` like `g_lighting`).
- Add `set_backdrops` binding (see Section 4).
- `frame()` calls `g_backdrop_pass.render(g_backdrops, g_camera,
  *g_pipeline, project_root_textures)` before the opaque pass.

## Host loop integration

### `_resolve_active_set` (renamed from `_resolve_active_lighting_set`)

```python
def _resolve_active_set(player):
    """Return the SetClass whose lights & backdrops apply. Order:
      1. g_kSetManager.GetRenderedSet() — explicit (MakeRenderedSet).
      2. The set containing the player ship — fallback.
      3. None — caller falls back to defaults.
    """
    import App
    rendered = App.g_kSetManager.GetRenderedSet()
    if rendered is not None and (
        getattr(rendered, "_lights", None) or
        getattr(rendered, "_backdrops", None)
    ):
        return rendered
    if player is not None:
        for s in App.g_kSetManager._sets.values():
            if any(o is player for o in getattr(s, "_objects", {}).values()):
                if (getattr(s, "_lights", None) or
                    getattr(s, "_backdrops", None)):
                    return s
    return None
```

The old `_resolve_active_lighting_set` becomes a thin alias that
delegates to `_resolve_active_set` so the existing lighting tests don't
have to be touched in the same commit.

### `aggregate_for_renderer` in `engine/appc/backdrops.py`

```python
def aggregate_for_renderer(pSet, project_root):
    """Return list[dict] in draw order. See Section 4 entries.

    Backdrops with empty texture paths are dropped silently. Backdrops
    with paths that don't resolve under `project_root/game/` are
    dropped with a once-per-set warning (pSet._backdrop_warned flag).
    Returns [] when pSet is None or has no backdrops.
    """
    if pSet is None or not getattr(pSet, "_backdrops", None):
        return []

    out = []
    missing_paths = []
    for b in pSet._backdrops:
        if not b._texture_path:
            continue  # silent: script-author bug
        abs_path = (project_root / "game" / b._texture_path).resolve()
        if not abs_path.is_file():
            missing_paths.append(b._texture_path)
            continue
        rot = b.GetWorldRotation()  # live; AlignToVectors flows through
        m9 = [
            rot._m[0][0], rot._m[0][1], rot._m[0][2],
            rot._m[1][0], rot._m[1][1], rot._m[1][2],
            rot._m[2][0], rot._m[2][1], rot._m[2][2],
        ]
        out.append({
            "texture_path": str(abs_path),
            "kind": b._kind,
            "h_tile": b._texture_h_tile,
            "v_tile": b._texture_v_tile,
            "h_span": b._horizontal_span,
            "v_span": b._vertical_span,
            "world_rotation": m9,
            "target_poly_count": max(int(b._target_poly_count), 64),
        })
    if missing_paths and not getattr(pSet, "_backdrop_warned", False):
        print(f"[backdrops] dropped {len(missing_paths)} backdrop(s) with "
              f"unresolvable textures from set {pSet.GetName()!r}: "
              f"{missing_paths!r}", flush=True)
        pSet._backdrop_warned = True
    return out
```

### `host_loop.run()` integration

```python
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=100000.0)

            active_set = _resolve_active_set(player)
            ambient, directionals = _aggregate_lights(active_set)
            r.set_lighting(ambient, directionals)

            backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 lighting ambient={ambient} "
                      f"directionals={directionals}", flush=True)
                print(f"[host_loop] tick 0 backdrops: "
                      f"{len(backdrops)} layer(s)", flush=True)

            r.frame()
```

`DEFAULT_SKYBOX_NIF` and the boot-time `r.load_model(SKYBOX_NIF) →
r.set_skybox(handle)` are removed.

`_aggregate_backdrops` is a thin private wrapper in `host_loop.py` that
supplies `PROJECT_ROOT` to `engine.appc.backdrops.aggregate_for_renderer`
(same pattern as `_aggregate_lights` wrapping `aggregate_for_renderer`
in lights.py with `DEFAULT_AMBIENT` / `DEFAULT_DIRECTIONALS`):

```python
def _aggregate_backdrops(pSet):
    from engine.appc.backdrops import aggregate_for_renderer
    return aggregate_for_renderer(pSet, PROJECT_ROOT)
```

### `_open_stbc_host.set_backdrops` binding

```cpp
m.def("set_backdrops",
      [](const std::vector<py::dict>& descriptors) {
          g_backdrops.clear();
          g_backdrops.reserve(descriptors.size());
          for (const auto& d : descriptors) {
              renderer::Backdrop b;
              b.texture_path      = d["texture_path"].cast<std::string>();
              std::string kind    = d["kind"].cast<std::string>();
              b.kind = (kind == "star") ? renderer::BackdropKind::Star
                                        : renderer::BackdropKind::Backdrop;
              b.h_tile            = d["h_tile"].cast<float>();
              b.v_tile            = d["v_tile"].cast<float>();
              b.h_span            = d["h_span"].cast<float>();
              b.v_span            = d["v_span"].cast<float>();
              b.target_poly_count = d["target_poly_count"].cast<int>();
              auto m9 = d["world_rotation"].cast<std::vector<float>>();
              if (m9.size() == 9) {
                  b.world_rotation = glm::mat3(
                      m9[0], m9[1], m9[2],
                      m9[3], m9[4], m9[5],
                      m9[6], m9[7], m9[8]);
              }
              g_backdrops.push_back(std::move(b));
          }
      },
      py::arg("backdrops"),
      "Set the active set's ordered backdrop list, applied each frame().");
```

`g_backdrops` and `g_backdrop_pass` are reset on both `init()` and
`shutdown()` for symmetry with `g_lighting`.

## Defaults, edge cases

- **No fallback skybox.** Empty backdrop list = void. The
  `glClearColor(0.05, 0.07, 0.10, 1.0)` already provides a defensible
  visual state for boot tick 0 / missions without `LoadBackdrops()`.
- **Texture not found.** `aggregate_for_renderer` resolves against
  `project_root/game/`; misses dropped with a once-per-set warning.
  Renderer never sees a path it can't load.
- **Empty texture_path.** Dropped silently.
- **Texture decode failure.** Renderer-side: log to stderr once
  (sentinel cache entry prevents per-frame retries), drop from draw
  list.
- **`target_poly_count ≤ 0`.** `max(value, 64)` in aggregation; the
  renderer's `ensure_sphere` further snaps to 64 if it sees ≤ 0.
- **Many backdrops in one set.** No hard cap. Stock max is 4. Texture
  cache prevents re-uploads; per-tick draw cost is ≈ N × small mesh.
- **NaN / zero rotation.** Same once-per-set warning + drop pattern.
- **GL handle lifetime.** `BackdropPass` destructor releases sphere VAOs
  and texture handles; reset before `g_window` destruction in
  `shutdown()`.

## Testing strategy

### Pytest unit (no GL)

`tests/unit/test_appc_backdrops.py`:
- `StarSphere_Create()` returns `StarSphere` with `kind == KIND_STAR`.
- `BackdropSphere_Create()` returns `BackdropSphere` with
  `kind == KIND_BACKDROP`.
- Setters round-trip: `SetTextureFileName`, `SetTextureHTile`,
  `SetSphereRadius`, `SetHorizontalSpan`, `SetTargetPolyCount`.
- `Rebuild()` is a no-op (returns None).
- `pSet.AddBackdropToSet(b, "name")` appends to `_backdrops` in order;
  sets backdrop name.
- `Backdrop` inherits `ObjectClass`: `AlignToVectors` works against a
  backdrop instance (rotation matrix retrievable via
  `GetWorldRotation`).

`tests/unit/test_aggregate_backdrops.py`:
- `aggregate_for_renderer(None, ...)` → `[]`.
- Two backdrops in registration order produce a 2-element list with
  correct `kind` discriminators.
- Texture path resolved against `game/` prefix; `data/stars.tga`
  resolves to absolute path.
- Missing file dropped with once-per-set warning (capsys capture).
- `world_rotation` reflects post-`AlignToVectors` matrix elements.
- `target_poly_count=0` snaps to 64.
- Empty `texture_path` dropped silently (no warning).
- Same-set repeat-aggregate after a missing-texture warning is silent
  (warning fires once).

`tests/unit/test_set.py` extension:
- `_backdrops` initially empty.
- `AddBackdropToSet` appends and assigns name.
- Existing renderer-only stub regression test still passes (verifies
  `__getattr__` catch-all still handles non-backdrop unknown names).

`tests/host/test_host_loop_unit.py` extension:
- `_resolve_active_set` returns the active set when only lights are
  configured.
- Returns same set when only backdrops are configured.
- Returns same set when both are configured.
- Falls through to None when neither is configured.

### Pytest with GL (host suite)

`tests/host/test_backdrops_bindings.py`:
- `_open_stbc_host.set_backdrops([])` doesn't raise.
- `set_backdrops` with one valid star descriptor doesn't raise.
- 10 backdrops in a single call doesn't raise.
- `set_backdrops([…stars…])` then `frame()`: pixel sampled at corner of
  viewport (away from any opaque geometry) is non-clear-color value
  `(13, 18, 26, 255)`.

`tests/host/test_backdrops_integration.py`:
- End-to-end: load M1Basic, run 5 ticks, sample pixel away from ship —
  not the clear color.
- Camera-rotation test: render frame, rotate 30° about Z, render second
  frame, sample same pixel; channels differ (rotation reference works).
- Camera-translation test: render frame, translate camera +1000 units
  along forward, render; same pixel within float tolerance (no
  parallax).
- Lighting still works after backdrops added: existing
  `test_set_lighting_changes_rendered_pixel` still passes.

### Native (C++)

`native/tests/renderer/backdrop_pass_test.cc`:
- Empty backdrop list produces no GL errors.
- Single star backdrop renders without GL error.
- `target_poly_count=64` and `=1024` both produce valid meshes (cache
  populated).
- Texture cache: same path twice = same GLuint.
- Sphere mesh interior winding: front-face culling enabled, sphere
  still visible (i.e. inside-facing geometry).

### Removed/migrated tests

- `tests/host/test_scene_setup.py::test_set_skybox_does_not_crash_in_frame`
  — migrated to backdrop equivalent.
- `tests/host/test_scene_bindings.py::test_set_skybox_does_not_raise`
  — migrated to backdrop equivalent.
- `tools/pick_default_skybox.py` — removed.

## Deferred-work updates

`native/src/host/docs/deferred_work.md`:

- Item #1 (skybox path lookup) → ✅ implemented; replaced with this
  spec. Add a note: NIF-skybox path is intentionally not part of this
  work — BC ships no skybox NIFs (`tools/pick_default_skybox.py`'s
  scan returned only starbase NIFs matching "star" — false positives).
- Add new follow-ups:
  - **Lens-flare rendering.** Used by
    `Tactical.LensFlares.YellowLensFlare(pSet, pSun)`; scoped into
    sub-project #3.
  - **Backdrop animation.** No stock content uses rotating nebulae;
    cosmetic.
  - **Cubemap path.** Higher-detail starfields via cubemaps; mod
    territory, not BC native.

## Cross-references

Mirror the same change in
`docs/superpowers/specs/2026-05-09-renderer-host-design.md` deferred-work
list and `docs/architecture/sub_project_status.md` index.

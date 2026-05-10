# BC Light Data Interpretation — Design

**Status:** Draft, pre-implementation.
**Sub-project:** Renderer host deferred-work item #2 (was: "BC light data
interpretation — read `NiAmbientLight` / `NiDirectionalLight` blocks from
scene NIFs").

## Why this item is being re-scoped

The deferred-work item, as previously written, asked us to read
`NiAmbientLight` / `NiDirectionalLight` blocks from scene NIFs. Pre-design
investigation found the literal premise to be unsupported by the asset
corpus and the SDK script base:

- A binary scan across **all 93 NIFs in the repo** (`game/data/` plus
  `sdk/Art/`) for the byte signatures `NiAmbientLight`, `NiDirectionalLight`,
  `NiPointLight`, `NiSpotLight` returned **zero** matches in any file.
  Stock BC ships no light blocks inside its scene NIFs.
- BC's actual lighting comes from runtime **Python script** calls. Per-system
  files (e.g. `Systems/Biranu/Biranu2.py`) call
  `App.LightPlacement_Create(name, sSetName, parent)` then
  `kThis.AlignToVectors(forward, up)` then
  `kThis.ConfigAmbientLight(r, g, b, dimmer)` /
  `kThis.ConfigDirectionalLight(r, g, b, dimmer)`. Per-set helpers
  (`MissionLib.CreateBridgeSet`, `LoadBridge.py`) call
  `pSet.CreateAmbientLight(r, g, b, dimmer, name)`.
- Across the SDK, **243** runtime light-creation calls exist:
  104 `ConfigAmbientLight`, 135 `ConfigDirectionalLight`, plus the
  `pSet.Create*Light` shortcut variants. **Zero** `ConfigPointLight` or
  `ConfigSpotLight` calls exist anywhere in stock content.
- Phase-1 today swallows these calls: `engine/appc/sets.py:_RendererStub` is
  a chainable no-op. The renderer falls back to hardcoded values in
  `frame.cc:135-137` (ambient 0.1, one directional from above).

The right work is therefore "wire the Python-script lighting path through
to the renderer's lighting uniforms," not "parse light blocks out of NIFs."
This spec describes that work.

## Goals

1. Replace `frame.cc`'s hardcoded ambient + directional with values driven
   by SDK script calls.
2. Support 1 ambient + up to 4 directional lights per scene — covers all
   stock content (max observed: 3 directionals, in Federation systems
   like Serris1–3 and Starbase12).
3. Honour `g_kSetManager.GetRenderedSet()` so set transitions
   (space ↔ bridge ↔ cinematic) automatically pick up the right lights.
4. Keep the v1 ship gate working: missing or missing lighting must fall
   back to the existing hardcoded values, not produce a black scene.

## Non-goals

- NIF-block light parsing. (Block-type parsers already exist in
  `native/src/nif/src/blocks/scene.cc` for forward compatibility, but no
  code path reaches them today and we don't add one.)
- Point or spot lights. No stock content uses them; out of scope for v1.
- Per-object light filtering via `pLight.AddIlluminatedObject(obj)`. Phase 1
  treats every light as affecting every object in its set.
- Bridge / character / cinematic scene rendering. The 4th-arg
  ambiguity in `SetClass.CreateAmbientLight` (range vs dimmer; `LoadBridge.py`
  passes 0.7 but `MissionLib.py` passes 19.0) is documented as a follow-up
  for when bridge rendering lands.

## Architecture

Three layers, three responsibilities:

```
SDK script (e.g. Biranu2.py)
   │  Initialize() / LoadPlacements()
   ▼
App.LightPlacement_Create(...)
kThis.SetTranslateXYZ(...)             # ignored for ambient/directional
kThis.AlignToVectors(forward, up)      # captured: forward = light direction
kThis.ConfigAmbientLight(r,g,b,dimmer) # stored as (color * dimmer)
kThis.ConfigDirectionalLight(...)
   │
   ▼   (also: pSet.CreateAmbientLight / CreateDirectionalLight bypass paths)
SetClass._lights : list[Light]
   │
   │   (each tick, host_loop.run)
   ▼
active_set = g_kSetManager.GetRenderedSet() or player's set
ambient, directionals = aggregate_lights(active_set._lights)
   │
   ▼
r.set_lighting(ambient_rgb, [(dir_xyz, color_rgb)] x ≤ 4)
   │
   ▼
_open_stbc_host C++ stores in renderer::Lighting struct;
frame() pushes uniforms to opaque shader.
```

The choice of **pull, not push** — host_loop reads from the active SetClass
each tick rather than the shim invoking a callback into the renderer on
each Config call — keeps the Phase-1 shim free of any renderer dependency
and matches how camera and ship transforms already flow.

## Phase-1 Appc shim additions

### New module: `engine/appc/lights.py`

```python
class Light(ObjectClass):
    """Phase-1 light object stored in SetClass._lights and returned by GetLight().

    Holds the configured RGB + dimmer + (for directional) world-space direction.
    AddIlluminatedObject is a no-op — Phase 1 doesn't filter per-object
    lighting; every light affects everything in its set.
    """
    KIND_AMBIENT = "ambient"
    KIND_DIRECTIONAL = "directional"

    def __init__(self, kind, name, r, g, b, dimmer):
        super().__init__()
        self.SetName(name)
        self._kind = kind
        self._color = (float(r), float(g), float(b))
        self._dimmer = float(dimmer)
        self._direction_world = (0.0, 1.0, 0.0)  # placeholder; set by placement

    def AddIlluminatedObject(self, _obj):
        return None  # SDK no-op


class LightPlacement(PlacementObject):
    """Result of App.LightPlacement_Create. Inherits position + orientation
    from PlacementObject (via ObjectClass). On the first Config*Light call,
    materialises a Light into the containing SetClass.
    """
    def ConfigAmbientLight(self, r, g, b, dimmer):
        self._make_light(Light.KIND_AMBIENT, r, g, b, dimmer)

    def ConfigDirectionalLight(self, r, g, b, dimmer):
        light = self._make_light(Light.KIND_DIRECTIONAL, r, g, b, dimmer)
        # ObjectClass.GetWorldRotation() reflects post-AlignToVectors state;
        # row 1 is the placement's "forward" axis = direction the light shines.
        rot = self.GetWorldRotation()
        fwd = rot.GetRow(1)
        light._direction_world = (fwd.x, fwd.y, fwd.z)

    def _make_light(self, kind, r, g, b, dimmer):
        light = Light(kind, self.GetName(), r, g, b, dimmer)
        if self._containing_set is not None:
            self._containing_set._lights.append(light)
            self._containing_set._lights_by_name[self.GetName()] = light
        return light


def LightPlacement_Create(name, set_name, parent=None):
    p = LightPlacement()
    p.SetName(name)
    import App
    s = App.g_kSetManager.GetSet(set_name)
    if s is not None:
        s.AddObjectToSet(p, name)  # populates _containing_set
    return p
```

### `SetClass` additions (`engine/appc/sets.py`)

Real implementations of methods currently caught by the `_RendererStub`
chain:

```python
def __init__(self):
    ...
    self._lights: list[Light] = []
    self._lights_by_name: dict[str, Light] = {}

def CreateAmbientLight(self, r, g, b, range_or_dimmer, name):
    # SDK signature: pSet.CreateAmbientLight(r, g, b, range, name).
    # 4th arg is "range" in some calls, "dimmer" in others; for ambient
    # range is meaningless (no falloff) so we treat it as dimmer
    # uniformly. Bridge interiors pass values up to 19.0 — flagged as a
    # bridge-rendering follow-up.
    from engine.appc.lights import Light
    light = Light(Light.KIND_AMBIENT, name, r, g, b, range_or_dimmer)
    self._lights.append(light)
    self._lights_by_name[name] = light
    return light

def CreateDirectionalLight(self, r, g, b, dimmer, dx, dy, dz, name):
    # SDK signature observed in DeepSpace.py:
    #   pSet.CreateDirectionalLight(1, 1, 1, 1, 1, 0, 0, "light1")
    from engine.appc.lights import Light
    light = Light(Light.KIND_DIRECTIONAL, name, r, g, b, dimmer)
    light._direction_world = (float(dx), float(dy), float(dz))
    self._lights.append(light)
    self._lights_by_name[name] = light
    return light

def GetLight(self, name):
    return self._lights_by_name.get(name)
```

Real methods shadow `__getattr__`; the existing `_RendererStub` catch-all
keeps handling everything else (`SetBackgroundModel`, etc.) unchanged.

### `App.py` exports

Add `LightPlacement_Create` to the existing `from engine.appc.lights ...`
import block alongside `Waypoint_Create` etc.

## Renderer changes

### Shader — `native/src/renderer/shaders/opaque.frag`

```glsl
#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;
uniform vec3 u_ambient_light;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 lit_dir = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        float ndotl = max(dot(n, normalize(u_dir_light_dir_ws[i])), 0.0);
        lit_dir += ndotl * u_dir_light_color[i];
    }
    vec4 tex = texture(u_base_color, v_uv);
    vec3 lit = (u_ambient_light + lit_dir) * u_diffuse_color * tex.rgb;
    frag_color = vec4(lit, 1.0);
}
```

`u_dir_light_count = 0` produces ambient-only output — legitimate for
nebula-style scenes that only configure ambient.

### `renderer::Lighting` (header `renderer/frame.h`)

```cpp
struct Lighting {
    static constexpr int MaxDirectionals = 4;
    glm::vec3 ambient = glm::vec3(0.1f);  // boot fallback
    int directional_count = 1;
    glm::vec3 directional_dir_ws[MaxDirectionals] = {
        glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f))
    };
    glm::vec3 directional_color[MaxDirectionals] = { glm::vec3(1.0f) };
};
```

### `FrameSubmitter::submit_opaque` signature change

Takes a `const Lighting&` argument; the existing literal float values move
into a default `Lighting{}` instance owned by `host_bindings.cc`. Shader
uniforms are pushed inside `submit_opaque` from the struct.

### New pybind binding `set_lighting` in `host_bindings.cc`

```cpp
static renderer::Lighting g_lighting;  // file-scope; reset on init()

m.def("set_lighting",
      [](std::tuple<float,float,float> ambient,
         const std::vector<std::tuple<
             std::tuple<float,float,float>,    // direction_world
             std::tuple<float,float,float>>>&  // color
             directionals) {
          g_lighting.ambient = {std::get<0>(ambient),
                                std::get<1>(ambient),
                                std::get<2>(ambient)};
          int n = std::min(static_cast<int>(directionals.size()),
                           renderer::Lighting::MaxDirectionals);
          g_lighting.directional_count = n;
          for (int i = 0; i < n; ++i) {
              auto& [dir, col] = directionals[i];
              g_lighting.directional_dir_ws[i] = glm::normalize(glm::vec3(
                  std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)));
              g_lighting.directional_color[i] = {
                  std::get<0>(col), std::get<1>(col), std::get<2>(col)};
          }
      });
```

### Direction sign convention

BC's directional light shines **in the +forward direction** of the
LightPlacement's orientation (forward = "where the light is pointing").
The shader's `u_dir_light_dir_ws` is "direction toward the light." So
host_loop converts: `dir_to_light = -placement_forward` before calling
`set_lighting`.

### Python wrapper (`engine/renderer.py`)

```python
def set_lighting(
    ambient: Tuple[float, float, float],
    directionals: List[Tuple[Tuple[float,float,float],
                             Tuple[float,float,float]]],
) -> None:
    _h.set_lighting(ambient, directionals)
```

## Host loop integration (`engine/host_loop.py`)

Two helpers + a single call inserted before `r.frame()`:

```python
def _resolve_active_lighting_set(player):
    """Order: GetRenderedSet -> player's set -> None."""
    import App
    rendered = App.g_kSetManager.GetRenderedSet()
    if rendered is not None and getattr(rendered, "_lights", None):
        return rendered
    if player is not None:
        for s in App.g_kSetManager._sets.values():
            if any(o is player for o in getattr(s, "_objects", {}).values()):
                if getattr(s, "_lights", None):
                    return s
    return None


def _aggregate_lights(pSet):
    """Collapse a SetClass._lights list into (ambient_rgb, directionals).

    Ambient: last-wins across configured ambients, color × dimmer.
    Directionals: up to 4, in insertion order, each as
        (dir_TOWARD_light_xyz, color_rgb_with_dimmer).
    Returns DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS when pSet is None.
    """
```

In `run()`, after `r.set_camera(...)`, before `r.frame()`:

```python
ambient, directionals = _aggregate_lights(
    _resolve_active_lighting_set(player))
r.set_lighting(ambient, directionals)
```

## Defaults, fallbacks, edge cases

- **Boot fallback** — file-scope `g_lighting` in `host_bindings.cc` is
  default-constructed to the existing hardcoded values (ambient 0.1; one
  directional, generic top-down). Tests that boot the renderer without a
  mission keep producing a lit Galaxy.
- **No active set / no lights** — `_aggregate_lights(None)` returns
  `(DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS)` so calls to `set_lighting` always
  produce a usable scene. Constants live in Python; the C++ default
  mirrors them and is documented.
- **Only ambient configured** — directionals list is empty; shader gets
  `u_dir_light_count = 0`. Scene is uniformly lit (correct for nebulas).
- **Only directionals configured** — ambient is 0,0,0 (script's explicit
  choice; do not inject baseline ambient).
- **Capacity overflow** — Stock max is 3; if a mod exceeds 4, host_loop
  logs once (`"[host_loop] dropped N directional lights from set X (>4)"`)
  and takes the first 4 in insertion order.
- **Direction zero-vector guard** — host_loop filters directionals with
  `‖dir‖ < 1e-6` before reaching `set_lighting`.
- **LightPlacement without Config** — placement still acts as a regular
  PlacementObject; no `Light` enters the set. Script-author error; not
  guarded.

## Testing strategy

### Pytest (no GL needed)

`tests/test_appc_lights.py`:
- `LightPlacement_Create` registers the placement in the named set.
- `ConfigAmbientLight` materialises an ambient Light with color × dimmer
  applied; appears in `pSet._lights` and `pSet.GetLight(name)`.
- `ConfigDirectionalLight` after `AlignToVectors(forward, up)` produces a
  Light whose `_direction_world` matches the forward.
- `pSet.CreateAmbientLight(r, g, b, dimmer, name)` 4-arg form produces
  equivalent state.
- `pSet.CreateDirectionalLight(r, g, b, dimmer, dx, dy, dz, name)` 8-arg
  form populates direction directly.
- `pSet.GetLight("nonexistent")` returns None (not a stub).
- Existing renderer-only stubs (`SetBackgroundModel`, etc.) still chain
  through `_RendererStub` (no regression in catch-all).

`tests/test_host_loop_lighting.py`:
- `_resolve_active_lighting_set` priority order: GetRenderedSet > player's
  set > None.
- `_aggregate_lights(None)` returns the documented fallback.
- 5 directionals truncate to 4; warning is logged once.
- Zero-vector direction is filtered.
- Multiple ambients: last-wins.
- Direction sign: `forward = (0, 1, 0)` → renderer gets `dir_to_light =
  (0, -1, 0)`.

### C++ (`native/src/host/tests/`)

`set_lighting_round_trip_test.cc`: call `set_lighting`, render one frame,
read pixel; assert it differs from the default-lit baseline. Validates
the binding marshalling and shader uniform path.

### Integration (extending the existing 5-tick smoke)

After `_init_mission("Custom.Tutorial.Episode.M1Basic.M1Basic")`, the active
set's `_lights` list is non-empty. Pixel sampled at the Galaxy hull centre
is brighter than the same scene with `set_lighting((0,0,0), [])`.

### Negative

- A mission script that only configures ambient produces
  `u_dir_light_count = 0`.
- A mission with no light configuration falls through to defaults — the
  existing 5-tick smoke is the witness; lighting must remain non-zero.

## Deferred-work updates

Update both `native/src/host/docs/deferred_work.md` and the renderer-host
design spec's "Deferred / future work" section:

1. **Item #2 ("BC light data interpretation")** — rewrite to "Phase-1 light
   wiring (Python-script lighting)" and mark implemented. Add a note:
   *"NIF-block light parsing is intentionally not part of this work — a
   binary survey of all 93 NIFs in the repo found zero `NiAmbient*` /
   `NiDirectional*` blocks."*
2. **New: Bridge & cinematic light rendering.** When bridge rendering
   arrives, revisit `SetClass.CreateAmbientLight`'s 4th-arg semantics
   (range vs dimmer) — bridges pass values up to 19.0 which is treated as
   dimmer today.
3. **New: `AddIlluminatedObject` per-object filtering.** Phase-1 ignores
   it; lights affect every object in the set. Becomes relevant when
   characters render.
4. **New: Save/load coverage of `Light` and `SetClass._lights`.** Tracked
   under the existing "Save/load coverage of render state" item;
   cross-referenced.
5. **New: Point/spot light support.** No stock content uses
   `ConfigPointLight` / `ConfigSpotLight`. `NiPointLight` / `NiSpotLight`
   parsers already exist for forward compatibility.
6. **New: Per-set lighting persistence across set transitions.** The
   pull-each-tick model re-aggregates every frame; cache by `_lights`
   identity if profiling later shows it matters.

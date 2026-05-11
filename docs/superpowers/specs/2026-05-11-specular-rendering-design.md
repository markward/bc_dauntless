# Specular (`_spec` / `_specular`) Rendering — Design Spec

Date: 2026-05-11

## Problem

BC ship scripts pass a 9th positional arg to `pLODModel.AddLOD(...)` naming a
texture-filename suffix — typically `"_specular"` — that tells the engine to
treat NIF images whose basename ends in that suffix as per-texel specular
masks. The `Material::specular`, `Material::glossiness`, and
`Material::StageSlot::Gloss` fields are already parsed but the renderer
ignores all three. Ships authored with `_specular.tga` (Keldon, Vorcha,
CardStarbase, RanKuf, BiranuStation, CardHybrid, BombFreighter, and several
Marauder/Card variants) render matte where they should highlight.

## Goal

Add a Blinn-Phong specular term to the opaque pass, modulated by a
`_specular`/`_spec` per-texel mask when the corresponding NIF image is
present. No new render pass. No post-process. Ships without a `_specular`
texture render byte-identically to today.

## Asset corpus findings

Verified against the BC corpus before designing:

- `_specular.tga`: 169 files. `_spec.tga`: 0 files in stock content.
- Mod packs are known to ship `_spec.tga`; both suffixes must be accepted.
- All seven `_specular.tga` files spot-checked are 24-bit RGB, zero alpha
  bits. Rules out encoding glossiness in the texture alpha channel.
- `NiMaterialProperty.glossiness` values across the corpus form a small
  discrete set: `{0.000, 0.120, 0.250, 0.300, 4.000}` — clearly authored in
  a normalized [0,1] range (with one 4.0 outlier), not as Phong exponents.
- `NiMaterialProperty.specular` is essentially uniform: `(0.9, 0.9, 0.9)`
  or `(1.0, 1.0, 1.0)` on nearly every block, including ships without a
  `_specular.tga`.

The corpus-dump tool used to gather these values is preserved at
`/tmp/dump_material.cc`; it links against the existing `libnif.a` and can
be promoted to `native/tools/` if we need it for follow-on investigations.

## Scope decision

Specular contribution is **gated on presence of a `_specular`/`_spec`
texture**. When absent, a black 1×1 fallback is bound and the contribution
multiplies to zero. This matches the goal ("support _spec specular
textures") and avoids shifting the visual baseline of every ship in one
commit. The alternative — applying `Material::specular × NdotH^exp`
uniformly to every NIF — was considered and rejected because (a) all stock
ships have non-zero specular/glossiness in their NIFs, so enabling it
globally would change Akira, Sovereign, Galaxy, Defiant, and every other
hero ship in a single change; and (b) the gated approach can be expanded
to "always on" later by swapping the fallback from black to white in one
line.

## Final color formula

```
N        = normalize(v_normal_ws)
V        = normalize(u_camera_pos_ws - v_position_ws)
spec_acc = vec3(0)
for each directional light i:
    L     = normalize(u_dir_light_dir_ws[i])
    H     = normalize(L + V)
    nl    = max(dot(N, L), 0.0)
    s     = pow(max(dot(N, H), 0.0), u_specular_power) * step(0.0, nl)
    spec_acc += s * u_dir_light_color[i]

lit  = (u_ambient_light + Σ ndotl·color) × u_diffuse_color × base_tex.rgb
glow = glow_tex.rgb × glow_tex.a
spec = spec_acc × u_specular_color × spec_tex.rgb       // black fallback ⇒ 0
out  = lit + u_emissive_color + glow + spec
```

`step(0.0, nl)` zeros the highlight on fragments facing away from the
light, preventing a wraparound ring on the dark side. Specular is not
modulated by `base_tex` or `u_diffuse_color` — it is a surface property,
not an albedo property.

## Glossiness mapping

BC's normalized [0,1] glossiness is remapped to a Blinn-Phong exponent by a
single inline function so the curve is trivially swappable for A/B
comparison.

`native/src/renderer/include/renderer/lighting.h` (new):

```cpp
namespace renderer {
// Map normalized BC glossiness [0,1] → Blinn-Phong exponent.
// Chosen mapping: linear remap into [4, 128].
//   gloss=0.12 → 19   gloss=0.25 → 35   gloss=0.30 → 41   gloss=1.0 → 128
// Outlier gloss=4.0 clamps to 128.
inline float glossiness_to_specular_power(float g) {
    return 4.0f + 124.0f * std::clamp(g, 0.0f, 1.0f);
    // Alt (D3D era):  return 2.0f + 254.0f * std::clamp(g, 0.0f, 1.0f);
    // Alt (exp2):     return std::pow(2.0f, std::clamp(g, 0.0f, 1.0f) * 10.0f);
}
}  // namespace renderer
```

Swapping the curve = edit one line, rebuild. A pinned-value test in
`lighting_test.cc` trips CI if the curve changes accidentally, but is
intentionally easy to update for deliberate retunes.

## Files changed

### `native/src/assets/src/model_build.cc`

Add a `filename_is_specular` classifier next to the existing
`filename_is_glow`:

```cpp
bool filename_is_specular(std::string_view fname) {
    auto stem = strip_extension(fname);
    return stem.ends_with("_specular") || stem.ends_with("_spec");
}
```

Both classifiers run independently on every NiImage in
`load_all_textures`. A model can have either, both, or neither.

### `native/src/assets/src/material_build.cc`

Extend `apply_texture_property` to detect `is_specular` alongside the
existing `is_glow` path. When the property's base image is classified as
specular, bind its texture index to `StageSlot::Gloss` only — unlike
`_glow` (which dual-binds to Base + Glow because BC's `_glow` convention
encodes both hull color in RGB and emissive mask in alpha), `_specular` is
a standalone mask image and does not co-occupy Base.

Update the docstring on `Material::StageSlot::Gloss` in
`native/src/assets/include/assets/material.h` to clarify that the slot is
populated at runtime by the `_specular`/`_spec` filename classifier, not
by a NIF stage linkage.

### `native/src/renderer/include/renderer/lighting.h`

New header containing `glossiness_to_specular_power` (see above).

### `native/src/renderer/shaders/opaque.vert`

Emit a world-space position varying so the fragment shader can compute
view direction. `u_model` is already a per-mesh uniform.

```glsl
out vec3 v_position_ws;
// inside main(), after computing ws:
v_position_ws = ws.xyz;
```

### `native/src/renderer/shaders/opaque.frag`

New uniforms:

```glsl
uniform vec3 u_camera_pos_ws;
uniform sampler2D u_specular_map;    // tex unit 2
uniform vec3 u_specular_color;
uniform float u_specular_power;

in vec3 v_position_ws;
```

Specular accumulation loop runs in the same loop as the diffuse term to
avoid two normalizes of the light direction:

```glsl
vec3 V = normalize(u_camera_pos_ws - v_position_ws);
vec3 lit_dir = vec3(0.0);
vec3 spec_acc = vec3(0.0);
for (int i = 0; i < u_dir_light_count; ++i) {
    vec3 L = normalize(u_dir_light_dir_ws[i]);
    float nl = max(dot(n, L), 0.0);
    lit_dir += nl * u_dir_light_color[i];
    vec3 H = normalize(L + V);
    float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
    spec_acc += s * u_dir_light_color[i];
}
vec3 spec = spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb;
frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a + spec, 1.0);
```

### `native/src/renderer/frame.cc`

`ensure_black_texture()` already exists from the glow work — reused as the
spec fallback. No new texture members in `frame.h`.

In `draw_model()` per-mesh loop, add (after the existing glow binding):

```cpp
const int spec_tex = mat.stages[
    static_cast<std::size_t>(assets::Material::StageSlot::Gloss)
].texture_index;
glActiveTexture(GL_TEXTURE2);
if (spec_tex >= 0) {
    glBindTexture(GL_TEXTURE_2D, model.textures[spec_tex].id());
} else {
    glBindTexture(GL_TEXTURE_2D, black_fallback);
}
shader.set_int  ("u_specular_map",   2);
shader.set_vec3 ("u_specular_color", mat.specular);
shader.set_float("u_specular_power",
    renderer::glossiness_to_specular_power(mat.glossiness));
```

In `submit_opaque()`, derive the camera position once and set
`u_camera_pos_ws`:

```cpp
glm::vec3 cam_ws = glm::vec3(glm::inverse(view)[3]);
shader.set_vec3("u_camera_pos_ws", cam_ws);
```

Add a one-line comment near the texture-unit bindings stating the
opaque-pass convention: units 0 = base, 1 = glow, 2 = spec.

## Tests

### Python — `tests/host/test_specular_pass.py` (new)

Pattern: `OPEN_STBC_HOST_HEADLESS=1` + `_open_stbc_host`, matching
`test_glow_pass.py`.

- Skip when Keldon NIF/texture dir absent (missing prerequisite, not
  platform).
- Lighting: small ambient + one directional from `+Z`.
- Render Keldon, scan a 7×7 grid around the screen center, assert at
  least one sampled pixel is non-zero.
- Smoke test only — does not isolate the specular contribution
  numerically. The binding correctness lives in `material_build_test.cc`
  and the math correctness lives in `lighting_test.cc`; combining them
  with a successful render is a sufficient signal.

A true differential ("brighter with spec than without") would require
either mutating an `AssetCache`-owned model post-load or adding a
host-side "disable spec" debug knob. Both are out of scope; reconsider
if visual regressions slip past the smoke + unit tests.

### C++ — `native/tests/renderer/frame_test.cc`

New `TEST_F(FrameTest, SpecularShipRendersWithDirectionalLight)`.
- Load Keldon (a `_specular`-using ship) via the asset cache.
- Render with ambient + one directional light.
- Assert `glGetError() == GL_NO_ERROR` (the spec uniforms wired up
  correctly) and that a 5×5 grid around screen center has at least one
  non-zero pixel.
- Same smoke-test rationale as the Python test; pairs with the
  deterministic binding + mapping tests below.

### C++ — `native/tests/assets/cpu/material_build_test.cc`

New `TEST(MaterialBuild, SpecularImageBindsToGlossSlot)`:
- Synthesize a `NiTexturingProperty` whose base image filename is
  `Ship_specular.tga`.
- Call `apply_texture_property`.
- Assert `Material::stages[StageSlot::Gloss].texture_index >= 0`.
- Assert `Material::stages[StageSlot::Base].texture_index < 0` (specular
  does NOT dual-bind, unlike glow).
- Second sub-test confirms `Ship_spec.tga` (the mod suffix) also binds to
  Gloss and not to Base.

### C++ — `native/tests/renderer/lighting_test.cc` (new)

Pins the gloss → exponent mapping:
- `glossiness_to_specular_power(0.0f) == 4.0f`
- `glossiness_to_specular_power(0.25f) == 35.0f`
- `glossiness_to_specular_power(1.0f) == 128.0f`
- `glossiness_to_specular_power(4.0f) == 128.0f`  (clamp check)

Trips CI on accidental curve changes; trivially updated for intentional
retunes.

## Risks

1. **Highlight intensity may not match BC's original engine.** The
   `[4, 128]` mapping is a defensible guess; BC's exact curve is
   unknown without instrumentation. The mapping function is one inline
   call site — A/B against the D3D-era `[2, 256]` or `pow(2, g·10)` is a
   one-line edit. The pinned-value test exists to catch *accidental*
   changes, not to lock the curve.

   *Test gap:* the renderer-level tests are smoke tests, not
   differentials. A subtle bug — for example, the spec uniform set but
   the math accidentally additive-zero — would slip past them. Mitigated
   by manual visual inspection on first integration and by adding a
   debug "disable spec" host knob if regressions ever surface.

2. **Camera-position derivation must agree with existing passes.**
   `glm::inverse(view)[3].xyz` is correct for an affine view matrix.
   Verification: the C++ test renders the same scene from two camera
   positions and confirms the highlight moves with the camera, not the
   geometry.

3. **Texture-unit convention.** Opaque pass now owns units 0 (base), 1
   (glow), 2 (spec). Sun/backdrop/dust passes use independent shader
   programs with their own assignments, so no conflict, but the
   convention deserves a one-line comment in `frame.cc`.

## Deferred / nice-to-have

- Runtime A/B hotkey for cycling gloss-mapping curves. The C++ function
  is structured for this; UI hookup is deferred until needed.
- Threading the actual `AddLOD` suffix arg from Python through the asset
  loader. Glow already deferred this; spec inherits the same deferral so
  both can be de-hardcoded together.
- PBR shader variant activated when `_normal` / `_rough` / `_metal` maps
  are present. Viable once mod content ships those maps; stock BC has
  none. `StageSlot` enum has room.
- Specular contribution from non-directional lights. BC's lighting model
  is directional-only; no change here.
- Per-texel glossiness from spec-alpha. Ruled out by data — all 169
  stock `_specular.tga` files are 24-bit RGB with zero alpha bits.

## Out of scope

- Post-process bloom (tracked as item #24 in
  [`native/src/host/docs/deferred_work.md`](../../../native/src/host/docs/deferred_work.md)).
- Environment reflections / cubemap-based specular.
- Modifying the `_glow` path to de-hardcode its suffix.
- Any change to lighting for ships without a `_specular`/`_spec` texture
  — the gated design keeps stock visuals unchanged.

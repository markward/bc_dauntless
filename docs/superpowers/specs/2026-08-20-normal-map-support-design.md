# Normal-map support for ship hulls — design

**Date:** 2026-08-20
**Status:** approved, pre-implementation

## Summary

Tangent-space normal maps on ship hulls, discovered by filename convention.
Dropping `Warbird_normal.tga` beside `Warbird.tga` in a ship's texture
directory makes the renderer load it and light the hull with the perturbed
normal — no NIF change, no script change, no per-ship registration.

The tangent frame is reconstructed **per-pixel in the fragment shader** from
screen-space derivatives, so no vertex attribute is added and no mesh data
changes. A hull with no `_normal` sibling renders byte-identically to today.

BC has no normal-map concept anywhere — no `AddLOD` slot, no NIF block, no
stock asset. This is an enhancement in the same family as the HDR and
Fresnel-rim work, not a reimplementation of engine behaviour. Because stock BC
ships zero `_normal` files, the feature is inert on stock assets and fidelity
is preserved by construction rather than by a toggle.

## Context

The pieces this builds on, all of which already exist:

- **The `_specular` sibling shim** (`native/src/assets/src/model_build.cc:82-131`).
  BC's engine, given an `AddLOD` `_specular` suffix argument, pairs each
  `NiImage` with a sibling spec map at load time. Our load path bypasses
  `AddLOD`, so `load_all_textures` replicates it: for every external `NiImage`
  that isn't itself a `_specular` file, it derives a sibling filename, probes
  the texture search path, and registers the hit as an extra texture keyed back
  to the original image's link ID. Misses are silently skipped. This is the
  exact shape the `_normal` discovery needs, and the reason this project is
  small.
- **`Material::StageSlot::Bump`** (`native/src/assets/include/assets/material.h`)
  — already declared in the stage enum, currently never populated and never
  sampled. No enum change is required.
- **Texture units in the opaque pass** — 0 base, 1 glow, 2 specular, 3 damage
  decal, 5 sun shadow map (`native/src/renderer/frame.cc:455-490`,
  `:520-565`). **Unit 4 is free.**
- **Linear texture upload** (`native/src/assets/src/texture_upload.cc`) —
  images upload as `GL_RGB8`/`GL_RGBA8` with no sRGB internal format, so a
  normal map's texels arrive unmodified. No separate linear path is needed.
- **TGA decode via stb_image** (`native/src/assets/src/texture_decode.cc`),
  gated to `STBI_ONLY_TGA`. RLE TGAs already decode. Indexed and 16bpp TGAs
  throw `UnsupportedTga`.
- **`opaque.frag`'s lighting terms** — directional lights with a PCF sun
  shadow (`:63`), dynamic segment lights, a per-texel specular mask, and the
  Fresnel rim (`:25-31`).

### Why the tangent frame is not a vertex attribute

BC NIFs carry no tangents, so a baked tangent basis would have to be generated
at mesh build and stored on the vertex. That was considered and rejected:

- `MeshCpu::Vertex` (`native/src/assets/include/assets/mesh.h`) is 52 bytes.
  A `vec4` tangent makes it 68 — **+31% vertex memory across all geometry in
  the game**, including every bridge set and character that will never carry a
  normal map.
- Five files copy or interpolate vertices — `tessellate.cc` (Phong subdivision
  on officers), `skin_weights.cc`, `model_compose.cc`, `skin_shield.cc`, and
  `model_build.cc`. Each would need to interpolate-and-renormalise or transform
  a tangent. Vertices are built by named-field assignment, not aggregate
  initialisation, so **missing one produces silently wrong lighting rather than
  a compile error or a test failure.**
- A baked basis' only real advantage is exact agreement with a map baked from a
  high-poly sculpt through a specific tangent convention. Maps here are
  hand-authored over existing BC hull textures, so there is no reference basis
  to disagree with.

Derivative reconstruction (Mikkelsen's method) is the standard approach for
meshes carrying no tangents. It costs a few ALU on normal-mapped materials
only, changes no mesh data, and makes two future extensions nearly free: it
needs no tangent skinning for dynamically-lit characters, and it is the same
code path procedurally-generated asteroid normals will use.

Adding a real attribute later remains additive — the shader would take a
tangent from an attribute instead of derivatives, and nothing in the loader
half changes.

## Non-goals

- **Bridge sets and bridge characters.** `bridge.vert` does not read
  `a_normal` and emits no normal varying; `bridge.frag` is
  `base × lightmap × max(ambient, emissive)` with no light direction and no
  view vector. There is no lighting term for a normal map to perturb.
  Supporting bridges is blocked behind giving bridge sets a dynamic lighting
  model — a separate project, deferred deliberately.
- **Dynamically-lit characters** (`skinned.vert`, which pairs with
  `opaque.frag`). A cheap follow-on, but out of scope here.
- A baked tangent vertex attribute.
- Parallax / height / displacement mapping.
- Auto-deriving normal maps from diffuse luminance.
- PNG decode (one `#define` away if ever wanted, but not now).

## Architecture

Five units. The first three are the asset half and are pass-agnostic; the last
two are the render half.

### 1. Filename predicates — `model_build.cc`

Two free functions beside the existing `filename_is_glow` /
`filename_is_specular`, following their structure exactly:

```
bool filename_is_normal(std::string_view fname);       // stem ends "_normal" or "_norm"
std::string sibling_normal_filename(std::string_view); // strip trailing "_glow", append "_normal"
```

Both case-insensitive. `_normal` is the primary form; `_norm` is accepted as a
short form, mirroring the `_specular`/`_spec` precedent (there both forms are
ours, since BC authored no normal maps at all).

`sibling_normal_filename` strips a trailing `_glow` before appending, so a
hull's diffuse and its glow map resolve to the **same** normal map — identical
to `sibling_specular_filename`'s behaviour and for the same reason.

### 2. Discovery plumbing — `TextureLoadResult` in `model_build.cc`

Two new members alongside the specular ones:

```
std::unordered_set<std::uint32_t>      normal_image_links;
std::unordered_map<std::uint32_t, int> sibling_normal_for_image;
```

`load_all_textures` gains a probe block mirroring the `_specular` one: for each
external `NiImage`, derive the sibling name, resolve it against
`ctx.texture_search_paths`, decode, upload, register the index against the
image's link ID. A miss is silently skipped — most ships will never have one.

One condition the specular path does not need: **skip probing entirely when the
image is itself a `_specular` or `_normal` file.** Without it, every load hits
disk looking for `Hull_specular_normal.tga`.

### 3. Material binding — `material_build.cc`

`apply_stage` populates `StageSlot::Bump` from `sibling_normal_for_image`,
alongside the existing `Gloss` population at `:130-137`.

`Bump` is **standalone** — it does not dual-bind with `Base`, the same rule
`Gloss` follows. A directly-referenced `_normal` `NiImage` (should a modded NIF
ever carry one) binds to `Bump` and is excluded from `Base`.

The slot's contract is *"a texture in this material's bump stage"*, not *"a
file found on disk"*. File discovery is one producer feeding it. This keeps the
path open for procedurally-generated maps to be attached without touching this
file.

### 4. Renderer binding — `frame.cc`

In the material-binding block beside base/glow/specular, on **unit 4**:

```
u_normal_map       sampler2D  — the Bump-stage texture
u_normal_enabled   int        — 1 when the material has a Bump texture
u_normal_strength  float      — global tunable, default 1.0
u_normal_flip_g    int        — global green-channel flip, default 1
```

The sampler is always assigned its unit even when disabled, matching the
shadow-map comment's reasoning at `:476` (an unassigned sampler colliding on
unit 0 is a `GL_INVALID_OPERATION` risk).

### 5. Shading — `opaque.frag`

A cotangent-frame helper and a perturbed normal:

```glsl
mat3 cotangent_frame(vec3 N, vec3 p, vec2 uv);  // dFdx/dFdy of p and uv
vec3 perturb_normal(vec3 N, vec3 p, vec2 uv);   // sample, decode, scale, transform
```

The sample decodes as `xyz * 2.0 - 1.0`; `xy` is scaled by `u_normal_strength`
before renormalising, so strength 0 collapses to the geometric normal and
values above 1 exaggerate. `u_normal_flip_g` negates `y`.

**The perturbed normal does not replace the geometric normal everywhere.** It
feeds the diffuse term, the specular term, and the dynamic segment lights. It
is deliberately **not** used for:

- **The sun shadow's normal-offset bias** (`opaque.frag:63`). That bias exists
  to push the sample point off the surface along real geometry to suppress
  self-shadow acne. Offsetting along a texture-perturbed normal reintroduces
  exactly the acne it prevents.
- **The Fresnel rim** (`:25-31`). The rim is a silhouette effect keyed to
  `N·V`. Perturbing it makes the rim crawl and sparkle across greeble detail
  instead of reading as a clean edge — and its `RIM_POWER`/`RIM_GAIN` are
  already hand-calibrated against the Galaxy.

`u_normal_enabled == 0` early-outs to the geometric normal, so a hull with no
`_normal` file takes the pre-existing code path and its output is
byte-identical to today.

## Data flow

```
Warbird_normal.tga on disk (ship texture dir)
  → load_all_textures: sibling probe resolves + decodes + uploads
  → TextureLoadResult::sibling_normal_for_image[link_id] = texture index
  → apply_stage: Material::stages[Bump].texture_index = that index
  → frame.cc: bind to unit 4, u_normal_enabled = 1
  → opaque.frag: cotangent frame from derivatives, perturb N,
                 feed diffuse + specular + dynamic lights
```

## Conventions and tunables

- **Author normal maps to the OpenGL convention (+Y up).** That is what the
  engine expects out of the box. A map authored for the DirectX convention
  (−Y) will read inverted — lighting appears to come from the opposite side.
- **How the engine achieves that:** texture row 0 (`v == 0`) is always the
  image's TOP row (`stb_image` normalises the TGA origin bit on load), so `v`
  runs **downward** in image space. Flipping green internally is therefore
  what makes a standard OpenGL-convention (+Y up) authored map render
  correctly — so `u_normal_flip_g` **defaults to 1 (on)**. It exists as a
  **global** switch, rather than a per-file heuristic, so there is one
  documented answer at authoring time and no filename magic to remember; turn
  it off only for a map authored to the DirectX convention.
- **Known authoring wrinkle:** maps generated by
  https://wizard.texturewiz.com/ additionally need their **red (X) channel
  inverted at export**. Measured (`.superpowers/sdd/2026-08-20-normal-map-support/tangent-basis-report.md`)
  to originate upstream of the engine — this engine's tangent basis is
  correct in both axes — so it is handled in the authoring workflow, not with
  an engine switch.
- **Strength** defaults to 1.0. Both strength and the green flip are exposed as
  developer tunables under Developer Options → Lighting, following the
  precedent in `2026-08-05-dev-forced-glow-state-toggles-design.md`. Neither is
  persisted across launches.

## Error handling

- **Missing sibling** — silently skipped; the material's Bump stage stays `-1`
  and the hull renders as today. This is the overwhelmingly common case.
- **Unreadable or undecodable `_normal.tga`** — the existing
  `load_all_textures` catch already substitutes a magenta checkerboard for
  failed *base* textures so geometry always renders. A failed **bump** texture
  must instead be **skipped**, leaving Bump unpopulated: a checkerboard bound
  as a normal map produces violent garbage lighting rather than an obvious
  visual error. Log to stderr with the filename, as the base path does.
- **Indexed or 16bpp TGA** — `decode_tga` throws `UnsupportedTga`; handled by
  the same skip-and-log path.

## Testing

- **Unit** (`native/tests/assets/cpu/`) — `filename_is_normal` across
  `_normal` / `_norm` / `_NORMAL` / non-matches, and `sibling_normal_filename`
  including the `_glow`-stripping case and extension preservation.
- **Material build** (`material_build_test.cc`, the existing precedent for the
  specular sibling) — Bump populates when a sibling is registered, stays `-1`
  when it isn't, and a decode failure leaves it `-1` rather than binding a
  checkerboard.
- **Discovery** — a `_specular` or `_normal` source image does not trigger a
  sibling probe.
- **Frame** (`native/tests/renderer/frame_test.cc`) — a draw with no Bump
  texture is unchanged against the current baseline (the byte-identical
  guarantee), and a draw with one differs. Strength 0 must match the unmapped
  draw.

Both suites via `scripts/check_tests.sh`, per the project test gate.

## Risks

- **Derivative frames are per-triangle-flat in UV space.** On geometry with
  very low-frequency UVs or degenerate/zero-area UV triangles, the
  reconstructed frame degenerates. The helper must guard against a zero-length
  tangent and fall back to the geometric normal rather than emitting NaN. A NaN
  reaching the HDR path propagates into the bloom amplifier and surfaces as
  black squares on screen — this tree has shipped that bug once already, from
  an unguarded `pow` in the rim term.
- **Mirrored UVs** are handled correctly by derivative reconstruction (the
  frame flips with the UV winding), which is one thing this approach gets right
  for free that a baked basis needs a handedness sign to encode.
- **Authoring-side surprise**: a normal map is invisible until a light hits the
  surface at a grazing enough angle. Judge results in-mission with a sun, not
  in a flat-lit viewer.

## Future work

Each is independent and additive, in rough order of cheapness:

1. **Dynamically-lit characters** — `skinned.vert` already pairs with
   `opaque.frag`; the derivative frame needs no skinning, so this is close to
   free once hulls are proven.
2. **Generated maps for procedural asteroids** — attaches to the same Bump
   slot through the source-agnostic contract.
3. **Baked tangent attribute** — only if an authored map ever demonstrates
   visible basis disagreement on a real hull.
4. **Bridge sets** — blocked on bridge dynamic lighting, a separate project.

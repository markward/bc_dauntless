# Planet geosphere — design

**Status:** approved in conversation 2026-10-06 · branch `feat/planet-geosphere`
**Programme:** sub-project 1 of 3. SP2 is high-resolution planet textures
(4096², streaming only if measured to be needed). SP3 is atmospheric scattering
plus a Fresnel limb, driven by a catalogue keyed on planet name. Neither SP2
nor SP3 is in scope here; this design only keeps their doors open.

## 1. Problem

System-map planets are about 20× BC's authored size: `radius_gu` runs from 140
to 7200, mostly 1600–3600 (`tools/gen_system_maps.py:136`
`planet_radius_scale`). At that size BC's planet mesh is visibly faceted, both
along the silhouette and in the Gouraud shading, from orbit (about 150 GU above
the surface).

## 2. Measured facts this design rests on

Each one was measured on the installed BC content on 2026-10-06, using
throwaway probes linked against `libnif`.

- **All 31 planet NIFs** in `data/Models/Environment` share one vertex set:
  673 vertices, 1280 triangles, one UV set, bound radius 90.0099, centred on
  the shape origin. Only the texture differs.
- **Tree:** `NiNode → NiNode → 'Scene Root' → 'planet' → NiTriShape 'Editable
  Mesh'`. Every rotation is identity and every scale is 1. The `planet` node
  carries a translation of **(−0.736648, 0.368324, 0)**, so in the model
  (body) frame the sphere centre is not at the origin. `earth.NIF` adds two
  light nodes and no extra shapes.
- **UV mapping is exact equirectangular, Z-up**, in the shape frame, with
  `lon = atan2(y, x)` and `lat = asin(z / |p|)`:
  - `u = fract(lon / 2π + 0.75)` (the seam is at lon = +90°, the +Y side)
  - `v = 0.5 − lat / π`

  The residual for v is 0.0000. For u, every equator vertex matches the formula
  to 4 decimal places. Near the poles BC's own u values leave [0, 1] (minimum
  −0.15), which is a fan artefact of BC's mesh, not part of the mapping.
- **No planet NIF has an atmosphere shell, cloud layer, glow, alpha or a
  second texture stage.**
- **Depth precision is not a problem at orbital range.** On the 24-bit,
  standard-Z buffer with near = 1 GU, a depth step is about 0.06 GU at 1,000 GU
  and about 6 GU at 10,000 GU. It is out of scope.

## 3. What stays the same

A planet remains an ordinary `scenegraph::Instance` in `Pass::Space`, drawn by
`FrameSubmitter::submit_opaque_in_pass` with the opaque program. Everything
that depends on that keeps working unchanged:

- depth writes, which classic lens-flare occlusion, volumetric nebula and DoF
  read;
- the `Lighting` struct, sun shadow and dynamic lights;
- the three realize paths and their teardowns;
- warp-blackout visibility;
- the `GetRadius() <= 0` radius fallback from the NIF extent.

No gameplay code reads the planet mesh. Picking, reticle, collisions, sensors
and dust all use `GetRadius()`.

## 4. Design

### 4.1 Geosphere mesh (native, pure)

`assets::build_geosphere(int level, float radius) -> MeshCpu`:

- an icosphere with `20·4^level` triangles, wound CCW when viewed from
  outside;
- every vertex exactly at `radius`;
- normal = unit position;
- UV = the §2 formula evaluated per vertex. These UVs are a fallback for any
  program that ignores the sphere-map flag. The opaque program never reads
  them for a sphere-mapped draw (§4.4).

Levels **3, 4, 5, 6** give 1,280 / 5,120 / 20,480 / 81,920 triangles. Level 3
matches BC's triangle count, so the coarsest LOD is never worse than today.
The builder may reuse the midpoint-cached subdivision from
`native/src/rockgen/src/shape.cc` `icosphere`, but it lives in `assets` with
no dependency on rockgen.

### 4.2 Geosphere model variant (native, at load)

`Texture` and `Mesh` are move-only because they own GL objects, so a `Model`
cannot be copied. The geosphere is therefore a **load variant** of the NIF
model, not a copy of it.

**Loading.** `load_model(..., geosphere=True)` adds `|geosphere` to the
`g_loaded_models` dedupe key and to the `AssetCache` key, so a geosphere load
never shares a handle with a plain load of the same NIF. It builds the NIF
model through the normal path, with its own textures and material, and then
runs `assets::apply_geosphere(Model&, mesh_uploader)` before the model is
published. That is the same construction-time window `tessellate_model_in_place`
and mesh fixes use, which is what keeps `Model::trace_accel` sound (see
`model.h`).

**Gate.** `apply_geosphere` acts only when the model has exactly one mesh,
every vertex of that mesh is within 0.5% of the mean vertex distance **from
the mesh's NODE-LOCAL ORIGIN** (not the vertex-position mean), and the mesh
has a UV set. Two further checks pin the mapping the shader reproduces: the
composed node chain's linear part (node-local → body) must be a **pure
rotation** — every column of unit length and the columns mutually orthogonal,
both within 1e-4 — and for every vertex whose body-frame direction
(rotation · normalize(node-local position)) has |z| ≤ 0.98 and whose stored u
is not within 1e-3 of 0 or 1, the stored UV must equal `sphere_uv` of that
direction within 1e-3 (the excluded vertices are BC's pole fan, whose u leaves
[0, 1], and the seam column, where 0 and 1 are both right). All 31 stock planet
NIFs pass. The node-local origin, not the vertex mean, is the measuring
point because on IcePlanet.NIF the vertex mean showed 2.25% radial spread —
BC's UV sphere duplicates seam-column and pole-fan vertices lopsidedly, which
biases a naive average — versus ~9e-6 about the node-local origin. Anything
else leaves the model untouched (`sphere_map` empty), so the variant renders
exactly like the plain NIF. That covers a modded ringed planet, a multi-shape
planet, a non-sphere, or a modded sphere whose mesh is not centred on its node
origin — it fails the gate and renders as its own NIF, unchanged from today.
The gate is geometric, not a file hash, so a retextured mod sphere still gets
the geosphere.

**Construction.** When the gate passes, it sets
`Model::sphere_map = SphereMap{mesh_index, center_body, radius, lods}`:

- `lods` is `std::array<Mesh, 4>`, holding `build_geosphere(level, r)` for
  levels 3–6. Each is centred on the mesh's **node-local origin** (not
  translated to the original mesh's shape-local centroid), so it sits under
  the same node as the original mesh and inherits every node transform, the
  material and the textures. `r` is the mesh's mean vertex distance from that
  origin.
- `center_body` is the mesh's node-local origin carried through the composed
  node chain (node-local → body). For stock planets it is (−0.736648, 0.368324, 0), with
  r = 90.0099.
- `meshes[mesh_index]` keeps BC's original geometry, so the AABB,
  `model_aabb`, ray tracing and every pass that is not sphere-aware see
  exactly what they see today. `natural_scale = radius / sphere_radius` in
  `host_loop` is therefore unchanged.

### 4.3 LOD selection (native renderer)

- **Pick.** In `submit_opaque_in_pass`, for a model with `sphere_map`, the
  submitter computes a level with `pick_geosphere_level(...)` and passes it to
  `draw_model`. `draw_model` then draws `sphere_map.lods[level]` in place of
  `meshes[mesh_index]`, with the same node transform and material. The pick
  runs per camera, inside the submitter, because the bridge viewscreen RTT is
  a different camera from the main view. There is no new `Instance` field and
  no per-instance binding.
- **Pure function `pick_geosphere_level(R, d, focal_px, max_err_px = 0.5)`.**
  It returns the coarsest level index whose silhouette error stays under
  `max_err_px`. Here `R` is the world radius, `d` the camera-to-centre
  distance and `focal_px = proj[1][1] · viewport_h / 2`.
  - Error: `R·θ_L²/8 / max(√(d² − R²), ε) · focal_px`, where `θ_L` is level
    L's mean edge angle (63.43° / 2^L).
  - Inside the sphere (`d ≤ R`), or when no level meets the threshold, it
    returns the finest level.
  - Worked check: R = 3600, 150 GU altitude, focal 935 px → level 5 (index 2)
    gives 0.49 px and level 6 (index 3) gives 0.12 px.
  - `R` is the world radius: `sphere_map.radius` × the instance's world scale,
    read from the length of `inst.world`'s first column.

### 4.4 Shading (`opaque.frag` / `opaque.vert`)

New uniforms `u_sphere_map` (int), `u_sphere_center_body` (vec3). `draw_model`
sets `u_sphere_map = 1` only while drawing a `sphere_map.lods[level]` mesh,
and 0 for every other mesh draw. A sphere-mapped model drawn without a level
(any pass other than the opaque submitter) draws BC's mesh with the flag off,
exactly as today.

When `u_sphere_map != 0`:

- `dir = normalize(p_body − u_sphere_center_body)`, using the `p_body`
  `opaque.frag` already reconstructs.
- **Shading normal** = `normalize(mat3(u_model) · dir)`. This replaces the
  interpolated `n` before normal perturbation and lighting, so shading is
  smooth at any LOD.
- **Albedo UV** = the §2 formula of `dir`. It is sampled with `textureGrad`,
  using gradients taken from a seam-free parameterisation outside any branch,
  so the seam column does not drop to the smallest mip. The same UV feeds
  every texture stage that uses `v_uv` (glow, gloss, bump), which are absent
  on stock planets anyway.

When `u_sphere_map == 0`, every current program path is byte-identical in its
output. The sphere-map math (a mat4 multiply, normalize, atan, asin and six
derivatives) still runs on every opaque-program fragment even then, because the
derivatives must sit outside any branch; its cost is unmeasured, since GPU
timing is unavailable on the dev Mac. Both
the static and skinned programs must declare the uniforms; only the static
one is exercised.

### 4.5 Python realize paths (`engine/host_loop.py`)

All three realize paths (mission load, `realize_set_objects`, and
`_reconcile_celestial_instances`) already share `_load_planet_model`. That
function passes `geosphere=engine.planet_geosphere.enabled()` to
`r_.load_model`. The flag also joins the HostController model cache key
(`nif_to_handle` / `nif_to_extent` / `nif_to_sphere_radius`), so a toggle never
serves a stale handle.

`engine/planet_geosphere.py` holds a developer toggle in the
`engine.rocks.catalogue` mould (`enabled()` / `set_enabled()`, default
**on**). It appears in Developer Options → Environments as "Geosphere Planets
(off = BC mesh; applies to planets realized after toggling)". It exists for
live A/B comparison only.

`load_model`'s new keyword argument defaults to `False`, so every other caller
is unchanged.

## 5. Out of scope

Terrain relief, atmosphere, clouds, high-resolution or streamed textures,
planet spin, depth precision, suns (they have their own pass), and
non-sphere modded planets (they fall back to their NIF).

## 6. Testing

**C++ (gtest, run by the gate):**

- `build_geosphere`: triangle counts per level, every vertex at radius ±1e-5,
  outward CCW winding on every triangle, per-vertex UVs equal the §2 formula.
- `pick_geosphere_level`: the worked check above; far away gives level 0;
  inside the sphere gives the finest level; output is monotonic in distance.
- Sphere UV function, **asset-backed** (content root via
  `native/tests/support/content_root.h`): load `IcePlanet.NIF` and assert that
  the analytic UV equals BC's stored UV for every vertex not within 1 vertex
  ring of a pole or the seam (|u − 0| or |u − 1| > 1e-3), to 1e-4.
- `apply_geosphere` (mesh uploader injected, as `AssetCache::Config`
  allows):
  - accepts the stock planet, with `sphere_map.center_body` equal to the
    measured centre, radius 90.0099, and BC's original mesh left in
    `meshes[mesh_index]`;
  - leaves a two-mesh model and a non-spherical mesh (for example a ship NIF)
    untouched.
- `draw_model` with a sphere level draws the LOD mesh's index count, not the
  original mesh's.
- Render (`FrameTest`): draw a sphere-mapped planet with a known two-colour
  texture and assert no seam discontinuity in a pixel row across the seam;
  then draw with the flag off and assert it matches the current output.

**Python (pytest):** `_load_planet_model` passes `geosphere=True` when
enabled and `False` when disabled, and the cache key separates the two.

**Live (Mark, main checkout):** orbit a large planet (for example Haven or
Chambana 1) with the toggle on and off. Check that the silhouette is round,
the shading is smooth, the texture shows no seam or pole artefact, and the
texture placement matches the BC mesh.

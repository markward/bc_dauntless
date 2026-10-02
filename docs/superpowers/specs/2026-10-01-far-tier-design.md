# Far tier — design (modern asteroids, sub-project 3b)

**Date:** 2026-10-01
**Status:** built, awaiting live check
**Branch:** `feat/far-tier` (worktree `.claude/worktrees/far-tier`), forked from
local `main` at `6f8f4f14` (sub-projects 1, 2 and 3 merged and live-verified).
**Roadmap:** `2026-09-30-modern-asteroids-roadmap.md`, "Sub-project 3b: far
tier" and "Sub-project 4: profile seeding". The standing decisions there are
not repeated here.
**Builds on:** `2026-09-30-rock-catalogue-design.md` (impostors, average albedo),
`2026-09-30-rock-class-design.md` (`RockClass`) and
`2026-10-01-minor-rocks-design.md` (`MinorField`, `MinorPass`, the pixel cull).

## Intent

Rocks should not vanish with distance. Today a minor is culled below 1.5 px,
majors draw as full meshes at any distance (sub-pixel and aliasing), and a
field seen from outside is mostly empty: in Beol 4 the player starts about
800 GU outside a 1,000 GU-radius tile field whose largest minors (0.7 GU) fall
under the cull at about 800 GU, so most of the field draws nothing.

The far tier continues every rock down the size ladder: mesh, then impostor,
then a lit speck, then (for density-field populations) an analytic haze. It
also draws **belts**: the radial profile's `asteroids` column becomes a flat
disc in the system plane, seen as a band across the sky. It is render-only.
Nothing here is simulated, targetable or an event source.

## Decisions (Mark, 2026-10-01)

| # | Decision |
|---|---|
| F1 | **Look: specks, then haze.** Beyond resolved rocks, a field reads as lit specks that merge into a faint haze at the far edge. |
| F2 | **Belts are pulled into 3b (render only).** The profile's `asteroids` column drives a belt source now. No seeded real rocks; that stays sub-project 4. |
| F3 | **A belt is a flat disc** in the system plane, with a vertical falloff. Not a spherical shell. |
| F4 | **Approach A.** A per-camera size ladder plus a disc density source; a native no-GL `FarField` and a `FarPass`; impostors linked with `opaque.frag`; a deterministic cell generator that sub-project 4 can promote rocks out of. |
| F5 | **3b defines the minimal density-field interface** (one primitive, the disc source). Sub-project 4 extends it. |
| — | Design sections 1–4 approved as presented. |

## Facts this design rests on (checked 2026-10-01)

- **Camera.** Exterior vertical FOV 35° (`engine/cameras/__init__.py:17`), user
  setting and a ±4° speed boost on top (`director.py:73-77`). Near 1 GU, far
  1,800,000 GU (`cameras/__init__.py:45-46`). Forward Z, `GL_LESS`, 24-bit depth;
  no reversed or log depth. The viewscreen RTT is 640×360
  (`host_bindings.cc:1447`); its zoom feed uses the director FOV without the
  boost (`host_loop.py:11748`).
- **No culling or LOD in the opaque path.** `submit_opaque_in_pass` draws every
  visible Space instance (`host_bindings.cc:1178-1185`, `frame.cc:1163-1185`).
  The only gate is `Instance::visible` (`world.h:64-85`). Ships load
  `FilenameHigh` only.
- **Minors** already cull and pick LOD per drawn camera:
  `MinorField::build_bins` (`minor_field.cc:238-307`), re-binned in
  `render_space_geometry` against the camera and height actually drawn
  (`host_bindings.cc:1188-1207`; `kViewscreenRttH` for the RTT).
- **Frame passes.** `render_space_geometry` (MSAA, depth write) draws backdrop,
  suns, `space.opaque`, `space.minors.draw`, carve stencil, breach, shield.
  `render_space_vfx` (single-sample, `target.depth_texture()` readable) draws
  dust, then the nebula branch (`host_bindings.cc:1240-1300`). The viewscreen
  RTT calls both.
- **Floating origin.** View space = the viewed set's coordinates; render space =
  view minus `render_origin` (the camera eye, double)
  (`engine/systems/frames.py:83-138`, `host_bindings.cc:1085`). A mapped
  region's view space is system space minus its `anchor_gu`
  (`frames.py:34-45`, `system_position` at `:194-199`).
- **Systems are flat.** In every map the bodies lie near the system XY plane:
  |z| ≤ 36,000 GU against XY spans of 230,000–860,000 GU. The star is the
  body with `orbits is None` (`profile.py:78-91`).
- **`asteroids` is read by nothing** (`profile.py:11,21,37`). Only Vesuvi
  authors it: 0.05 from 0 to 340,000 GU, and 0.5 from 226,000 GU (Geki) to
  330,000 GU (Haven); the last row is at 340,000 GU.
- **Impostors** (`native/src/rockgen/src/impostor.cc`): 512² atlas, 4×4 cells of
  128², 16 Fibonacci view directions in the **glTF frame** (the direction the
  camera looks *from*; `catalogue.json` `impostor_view_dirs`). Each view's basis
  is `make_basis(dir)`: `up_ref` = +Y (or +X near the poles),
  `right = normalize(cross(up_ref, −dir))`, `up = cross(−dir, right)`. Albedo is
  **unlit** base colour, alpha 255 inside the silhouette and 0 outside (hard
  coverage, no edge AA); the normal atlas stores the view-space normal
  `(n·right, n·up, n·dir) · 0.5 + 0.5`. Atlas pixel y grows downward
  (`screen.y = half − sy`). Every catalogue rock has one, fragments included.
- **`opaque.frag`** builds its tangent frame from screen derivatives of the
  position and UV (`perturb_normal`, `opaque.frag:778`) and honours
  `u_normal_flip_g`. It has **no alpha cutout**, and base alpha is the
  **emissive mask** (`opaque.frag:1406`, `:1504`). `minor.vert` is already
  linked with it (`pipeline.cc`).
- **Shader sources have no include mechanism** besides `smaa_lib.glsl`.
- **Dust** is camera-anchored, ±40 GU, density from the profile `dust` column
  (`dust_pass.h:103`, `host_loop.py:4944-4952`), and is off on the viewscreen
  except while warp-streaking.
- **Dials.** `dev_dial_groups.register_group(name, order, get_dials, step)`
  (`engine/dev_dial_groups.py:31-38`); nebula and minors are registered.
- **Frame profiler.** `DAUNTLESS_FRAME_SCOPE("name")` is RAII and nests
  (`frame_timer.h:191`). The GPU column is dead on this Mac; CPU only.

## Evidence gaps

- **stbc-reference was unreachable** (connect timeout, 2026-10-01). BC's
  `AsteroidField` exposes `Get/SetInnerFieldRadius`, `Get/SetOuterFieldRadius`
  and `GetTileSize` (SWIG tier, `App.py:4150-4160`), which hints that BC tiled
  its fields around the camera. That is not recovered behaviour, and nothing
  here depends on it.
- **The density anchors** (Beol 4 for minors at 1.0, Vesuvi 4 for majors at
  1.0) are roadmap standing decisions, not BC behaviour.
- **The far tier as a whole is a deliberate departure from BC**, which drew
  tile fields of ship-class rocks and nothing at a distance.

## Amended during execution (2026-10-01/02)

This design was built, not just reviewed; a handful of numbers and ordering
rules changed on contact with the implementation and its tests. The sections
below carry the corrected value in place; this is the index.

- **R5/R8 — generator defaults.** `cells_per_range` is **4**, not the 8 first
  proposed (§2 Generator); `cell_cache_max` is **32,768**, not 4,096 (§2
  Generator).
- **R7 — telephoto guard.** A new native dial, `max_cells_per_axis` (default
  **17**), caps each class's cell enumeration at ≤17 cells per axis (§2
  Generator): without it a telephoto camera (viewscreen zoom raises `k`) could
  enumerate on the order of 530,000 cells for one class.
- **R9 — discard ordering in `opaque.frag`.** The coverage-cutout discard sits
  at the **top** of `main()`, beside the dither discard, not after the base
  colour sample as first drafted (§3 `opaque.frag` uniforms): placed later it
  measurably broke an existing NaN guard on this driver, cutout on or off.
- **R12/R13 — speck coverage.** The speck cross-fades a floor()-aligned 2×2
  square (p ≤ 1) to a flux-normalised AA disc (p ≥ 2), quad half-size
  `max(p + 0.5, 1.5)` (§3 Speck shading): measured flux within 0.3% of π p²
  and sub-pixel shimmer ≤ 4.6% across the whole band.
- **R11 — ambient_scale on the far passes.** `render_specks` and `render_haze`
  both take `ambient_scale`, exactly as the rock passes do (§3 `FarPass`).
- **R6 — unplaceable flagged rock.** A flagged rock `build` cannot place this
  frame gets `far_fade` **0** (mesh visible), never a stale hide (§3 Instance
  fade).
- **Python — unmatched population dropped.** `density.to_native` drops, with
  one warning, a population whose family matches no catalogue rock, instead of
  sending it empty (§4 Python integration).
- **R14 — `haze_gain` default.** Corrected from the originally drafted
  **143** to **270** (§2 Haze): the derivation now uses half the band chord.
- **Tile-field haze (2026-10-02).** Every `AsteroidField` gets a view-space
  sphere haze source, `tile_haze_gain` 26,860 (§2 Haze, "Tile-field haze").
- **Measured, not designed.** Bench mean **0.015 ms** static / **0.10 ms** at
  100,000 GU/s; the Vesuvi band (a = 0.5) enumerates only **~220** speck-tier
  minors per camera — the haze carries the band, not speck density (§5
  Performance).

## Design

### 1. The tier ladder

Every rock is in exactly **one** tier per drawn camera, chosen by its on-screen
radius

```
p = r · k / d,    k = (H / 2) / tan(fov_y / 2)
```

where r is the rock's radius (GU), d its distance from the eye (GU) and H the
target's framebuffer height in pixels (the convention `MinorField` uses). Every
threshold is a dial (§5).

| p (px) | Explicit major (mission or breakup rock) | Explicit minor (halo, tile, debris) | Procedural (disc source) |
|---|---|---|---|
| ≥ `imp_hi` 16 | mesh (opaque path, unchanged) | lod0 ≥ 24, lod1 below (unchanged) | not drawn |
| `imp_lo` 12 – 16 | mesh → impostor, **dithered crossfade** | lod1 | — |
| `speck_hi` 2 – 12 | impostor | lod1 | impostor (majors only) |
| `speck_lo` 1.5 – 2 | impostor → speck, alpha crossfade | lod1 → speck, **hard switch** at 1.5 | speck |
| `p_min` 0.25 – 1.5 | speck | speck (today: culled) | speck |
| < 0.25 | culled | culled | **haze** (§2) |

Distances at 1080p and the default 35° FOV (k ≈ 1,713):

| Rock | Mesh until | Impostor from | Speck from | Gone at |
|---|---|---|---|---|
| r 5 GU (large major) | 535 GU | 714 GU | 4,282–5,709 GU | 34,254 GU |
| r 2 GU (Vesuvi 4 rock) | 214 GU | 285 GU | 1,713–2,284 GU | 13,700 GU |
| r 0.7 GU (largest tile minor) | — | — | 799 GU | 4,796 GU |
| r 0.05 GU (gravel) | — | — | 57 GU | 343 GU |

The viewscreen RTT (360 px) divides every distance by 3. A Retina framebuffer
doubles them; thresholds are in framebuffer pixels, as for minors.

**Procedural rocks** use the same weights minus the mesh: a procedural major's
impostor fades in over 16 → 12 px, and a procedural minor's speck fades out
over 1.5 → 2 px (there is no lod1 for it). Until sub-project 4 seeds real
rocks, that leaves an empty zone around the eye inside a belt, which is
expected.

**Hand-offs**
- **Mesh → impostor (majors):** a screen-door fade. The mesh draw discards by a
  4×4 Bayer mask at `far_fade`; the impostor draws with the inverse mask, so
  every pixel is covered exactly once.
- **Impostor → speck:** the impostor fades with the same mask; the speck's
  alpha rises over the same band. Their flux is matched (§3, tested).
- **Minor lod1 → speck:** a hard switch at `speck_lo`. A 3 px mesh and a 3 px
  speck of the same flux are close, and it avoids widening the minor instance
  format. If it reads as a pop live, a per-instance fade is the fallback.
- **Speck → haze:** a size cut, not a fade. The haze integrates exactly the
  population below `p_min` at each depth (§2), so each (size, distance) pair is
  drawn once. Explicit rocks below `p_min` are simply culled: their combined
  light is negligible for every formation that exists.
- **Impostor view choice:** the nearest of the 16 baked views to the eye
  direction in the rock's own frame. No blending between views; a tumbling rock
  under 12 px may visibly flip view (Risks).
- **Stock-BC rocks** (catalogue toggle off) have no impostor. They keep the
  mesh down to `speck_hi`, then go to speck.

### 2. The density source and the generator

**Interface (`engine/rocks/density.py`).** 3b defines it; sub-project 4 extends
it. One primitive:

```
DiscSource{
    id, frame_key,                 # the system frame the source lives in
    centre_gu,                     # system coordinates
    normal,                        # unit
    table: [(r_gu, a)],            # a in [0,1], the `asteroids` meaning
    outer_fade_gu,                 # beyond the last row, a falls to 0 over this
    scale_height_frac, scale_height_min_gu,
    families: {family: weight},
    seed,
    explicit_regions: [(centre_gu, radius_gu)],   # empty in 3b; sub-project 4
}

a(x) = table(ρ) · exp(−z² / 2H²),   H = max(scale_height_frac · ρ, scale_height_min_gu)
```

ρ is the distance from the centre in the disc plane and z the height above it.
Starting defaults (dials): `scale_height_frac` 0.03 (H ≈ 8,400 GU at the middle
of Vesuvi's band), `scale_height_min_gu` 1,000, `outer_fade_gu` 20,000.
`table` interpolates linearly between rows (as `profile.evaluate` does); below
the first row it holds the first value; past the last row it falls linearly to
0 over `outer_fade_gu`.

- **Profile belt** (`density.profile_belt(system)`): one source per mapped
  system with `asteroids` > 0 in any row. Centre = the star's `position_gu`,
  normal = system +Z, table = the `asteroids` column. Today that is Vesuvi only:
  a 0.05 floor across the system plane and the 0.5 band from Geki to Haven.
- **A ring** later is the same primitive with a planet's centre and its own
  normal and table.
- **Explicit regions** are empty in 3b. Sub-project 4 fills them with its
  working volume, and the generator skips any rock whose position lies inside
  one (per rock, so the boundary is exact).

**Populations (`engine/rocks/field_table.py`).** One table, shared with
sub-project 4 (the roadmap's "one data table"):

| Population | Density at a | Radius | Shape | Mesh |
|---|---|---|---|---|
| Minors | a × 9.67×10⁻⁸ /GU³ (Beol 4 at 1.0: 405 in a 1,000 GU sphere) | 0.05–0.7 GU | power law, exponent 2.5 | catalogue fragments |
| Majors | ramp(a; 0.5 → 1.0) × 1 / 1.2×10⁹ GU³ (Vesuvi 4 at 1.0) | 1–5 GU | power law, exponent 2.5 | catalogue majors |

`ramp` is 0 at or below 0.5 and rises linearly to 1 at 1.0. Vesuvi's 0.5 band
therefore has procedural minors and no procedural majors, which follows from
the roadmap's threshold.

**Generator (C++, deterministic).**
- Each population is split into `size_classes` (default 4) log-spaced radius
  bins. Class c matters only out to `D_c = k_ref · r_max,c / p_min`, with
  `k_ref` the main view's k (a smaller k, as on the RTT, needs less), **capped**
  at `0.5 · max_cells_per_axis · L_c` (default **17** cells per axis, added
  2026-10-02 — ruling R7, §5): a telephoto camera (viewscreen zoom raises k)
  otherwise enumerates up to ~530k cells for one class.
- Class c's rocks live in cubic cells of edge `L_c = D_c / cells_per_range`
  (default **4**, amended 2026-10-02 — ruling R5, §5), indexed by integer
  `ijk` in **system coordinates**.
- A cell's contents are a pure function of `(source seed, population, class,
  ijk)`: a Poisson count from the density at the cell centre times L³ times the
  class's share of the size distribution (with `a` taken at the cell's
  maximum), then candidate positions accepted against `a(x)` so density
  gradients stay smooth, plus radius, catalogue rock, tumble axis, rate and
  phase. A belt looks the same when you come back.
- Per drawn camera: enumerate the cells within `D_c` of the eye that intersect
  the frustum and the disc's ±`slab_sigmas` · H slab (default 4), nearest
  first, until `max_far_rocks` (60,000) rocks are generated. A rock inside an
  explicit region is skipped. Each survivor goes through the §1 ladder.
- An LRU cache of generated cells (`cell_cache_max`, default **32,768** cells,
  amended 2026-10-02 — ruling R8, §5), keyed on `(source, population, class,
  ijk)`, is shared by the main view and the viewscreen.
- **Sub-project 4's promotion contract:** a seeded real rock is exactly a
  generator rock (same cell, same index, same position, size and mesh), so a
  rock crossing an explicit region's edge keeps its identity.

**Haze.**
- Per source, a march along the eye ray over its intersection with the disc's
  slab and outer radius, at most `haze_steps` (24), stopped at scene depth.
- At each sample, the emission adds, per population, the **cross-section of
  the rocks below** `r_cut(d) = p_min · d / k`:
  `n(a) · ∫ π r² f(r) dr` over `[r_min, min(r_cut, r_max)]`, in closed form for
  the truncated power law. This is the exact complement of the per-rock cull.
- Single scattering: the population's average albedo (the mean `avg_albedo` of
  its family's catalogue rocks) × the Lambert-sphere phase function of the
  sun–rock–eye angle × sun colour, plus the ambient term.
- One dial, **`haze_gain`**, scales the optical depth: per step
  `Δτ = haze_gain · Σ n·σ_below · ds`, colour += `T · (1 − e^(−Δτ)) · albedo ·
  light`, `T *= e^(−Δτ)`, alpha = `1 − T`. Colour and alpha therefore stay
  consistent (premultiplied).
- Physically, τ across a belt is about 10⁻⁵, which is invisible, so
  `haze_gain` is an explicit art dial, tuned live. **Default 270**, derived
  (amended 2026-10-01, ruling R14 during execution) from one target: from
  mid-band (ρ = 278,000 GU) looking tangentially forward along the plane,
  alpha ≈ 0.15. Minors only (a = 0.5 has no majors): n = 4.84×10⁻⁸ /GU³, mean
  cross-section 0.0659 GU². The eye sees HALF the 355,600 GU band chord
  (plus the 330k–360k fade tail); the CPU reference measures alpha 0.0825 at
  gain 143, so 270 = 143·ln(0.85)/ln(1 − 0.0825). (An earlier draft used the
  full chord and gave 143.)
- The haze ignores explicit regions: real rocks below `p_min` are culled, so
  the haze still stands in for them.

**Tile-field haze (added 2026-10-02).** From outside, a BC tile field (Beol 4:
405 minors of 0.05–0.7 GU in a 1,000 GU sphere) showed ~20–30 sub-pixel
specks, so every `AsteroidField` in the viewed set now gets a **sphere**
haze source as well.
- `DiscSource` gains `shape` (Disc | Sphere), `procedural` (false: `build`
  generates no rocks — the field already has real minors), `view_space`
  (centre in the viewed set's view space, active whenever pushed, frame key
  or not, so unmapped sets like Multi7 haze too; `refresh_active` puts it in
  system coordinates as centre + anchor), `sphere_radius_gu`,
  `sphere_edge_frac` and `gain_scale` (× `haze_gain`). A disc is unchanged.
- Sphere density: a = 1 within R(1 − edge_frac), a linear ramp to 0 at R.
  The interval is the ray's chord through the sphere, clipped to [0, scene
  depth]; the march (midpoint, `r_cut`, accumulation) is the disc's.
  `haze_column` and `far_haze.frag` stay twins, pinned by
  `FarPassGLTest.SphereHazeShaderMatchesTheCpuReference`.
- Population: one minor population built FROM `minors.tile_spec` (the
  field's own tile cloud): `density_at_1` = count / (4/3·π·R³), its r_min,
  r_max and exponent, silicate (`density.tile_field_source`).
- **Gain.** Python dial `tile_haze_gain` (sent as `gain_scale = tile_haze_gain
  / haze_gain`), **default 26,860**, derived by
  `FarHazeSphere.DefaultTileGainHitsTheStatedTarget`: from Beol 4's
  "Player Start" (−593.7, 840.9, −269.3) looking at the field centre
  (797.7, 977.2, 1268.9), k = 1713, p_min 0.25, edge 0.2, the CPU reference
  measures τ = 6.05×10⁻⁶ per unit gain; alpha = 1 − e^(−gain·τ) exactly, so
  gain = −ln 0.85 / τ = 26,862 → 26,860, alpha **0.150**. (At the belt's 270 it
  would be ~0.0016.) `tile_haze_edge_frac` 0.2.

**Frames.**
- Python pushes the view→system offset (the viewed frame's `anchor_gu`) once a
  frame. Native places a cell at `system − anchor − render_origin`, computed in
  double.
- Sources belong to a frame key. Only sources of the viewed frame are active.
  One-set frames (Multi*) have none; their explicit rocks still use the
  impostor and speck tiers.
- The far tier is off in the `"warp"` set, as dust is.

### 3. Rendering (native)

**`FarField`** (`native/src/renderer/far_field.{h,cc}`): no GL, built like
`MinorField`.
- Holds the catalogue table (per rock: index, avg albedo, impostor present),
  the sources, the generator and its cell cache, and the flagged explicit rock
  instances `{instance key, catalogue index, radius_gu}`.
- `build(view, proj, eye_render, target_h, out)` puts every candidate in its
  tier for that camera and fills `out`: impostor bins (one per catalogue rock in
  use), the speck list, and a `far_fade` per flagged instance. Explicit minors'
  specks come from `MinorField::build_bins`, which gains a speck output for
  the band below `speck_lo` that it culls today.

**Instance fade.** `scenegraph::Instance` gains `far_fade` (0 = mesh only). The
host writes it from `build` before each camera's `space.opaque`.
`submit_opaque_in_pass` skips an instance at 1 and sets `u_dither_fade` between.
The shadow pass ignores it, so a far rock still casts. A flagged rock `build`
cannot place yet (no world transform) gets fade **0** — mesh visible — rather
than keeping whatever fade was last written, so a late-realised rock is never
left hidden (amended 2026-10-02 — ruling R6, §5).

**`FarPass`** (`native/src/renderer/far_pass.{h,cc}`):

| Draw | Where | How |
|---|---|---|
| **Impostors** | `render_space_geometry`, right after `space.minors.draw` (MSAA, depth write) | New `impostor.vert` **linked with `opaque.frag`**. One `glDrawArraysInstanced` (a unit quad) per catalogue rock in use, with that rock's albedo and normal atlases bound as ordinary 2D textures. |
| **Specks** | `render_space_geometry`, after the breach pass and before the shield bubble | Premultiplied point sprites, depth test, no depth write. `speck.vert/.frag`. |
| **Haze** | `render_space_vfx`, after dust and before the nebula branch (single-sample, depth readable) | Fullscreen pass, one march per active source (at most `max_sources` 4). `far_haze.frag`. |

**Impostor geometry.**
- The quad is perpendicular to the chosen baked view direction carried into
  world space by the rock's rotation (`R · M_gltf→BC · dir`), centred on the
  rock, with half-size = rock radius × the bake's `1.02` margin. Its in-plane
  axes are the baked view's `right` and `up` carried the same way, so the
  atlas normal is exactly a tangent-space normal for this quad.
- `impostor.vert` writes the varyings `opaque.vert` writes: `v_position_ws` on
  the quad, `v_normal_ws` = the carried view direction, `v_uv` into the atlas
  cell. The plan's first impostor task pins the UV-y and `u_normal_flip_g`
  convention against the atlas's downward y with a render test.
- The pass sets the same lighting, shadow and rim uniforms as `MinorPass`,
  with every ship-only feature off (decals, carve, hull field, glow regions,
  dynamic lights, hull-name decals), and glow off.
- `FarPass::render_specks` and `render_haze` both take an `ambient_scale`
  parameter and apply it to the ambient term exactly as the rock passes do
  (filmic exterior tone, amended 2026-10-02 — ruling R11, §5), so a speck or
  the haze doesn't read as mis-lit against the same scene's ships and rocks.

**`opaque.frag` gains two uniforms, both off by default:**
- `u_dither_fade` (float, 0 = off): discard where the Bayer threshold is below
  it; with `u_dither_invert`, the complement.
- `u_coverage_cutout` (int, 0 = off): discard where base alpha < 0.5. Needed
  because base alpha is otherwise the emissive mask.

Both discards sit at the **top of `main()`**, beside each other, before the
base/normal sample and the dFdx/dFdy block (amended 2026-10-02 — ruling R9,
§5): a `u_coverage_cutout` discard placed *after* that block, where it reads
more naturally next to the base-colour sample, measurably broke the
`amb_d` NaN guard on this driver even with the cutout off
(`HullFieldClipTest.DegenerateNormalWithGradientOnStaysFinite`).

With both off, a draw is byte-identical to one that never touched
`u_dither_fade` (`FarDitherGLTest.ZeroFadeIsByteIdentical`: the same draw
before and after a fade-0.5 draw). That test does not compare against the
pre-branch `opaque.frag`; production identity rests on it plus the existing
pixel suites (FrameTest, hull-clip) passing unchanged.

**Atlases.**
- Loaded once, lazily per catalogue rock, from `paths.project_asset_root()`
  (resolved at use). They are not mission content and survive a swap.
- At load, colour is dilated into the transparent texels (a few passes), so
  mipmaps do not fringe the silhouette dark. The committed catalogue is
  unchanged.

**Speck shading.** Colour = `avg_albedo · (sun_rgb · Φ(α) + ambient)`, with Φ
the Lambert-sphere phase function of the phase angle α. The sprite quad's
half-size is `max(p + 0.5, 1.5)` px. Coverage cross-fades between two kernels,
each of total flux exactly π p² (amended 2026-10-02 — rulings R12/R13, §5):
below p = 1 a floor()-aligned 2×2 square (always exactly 4 texels, each
`π p² / 4` — no sub-pixel shimmer at all); above p = 2 a flux-normalised AA
disc (`clamp(p + 0.5 − r, 0, 1)` scaled by `p² / (p² + 1/12)`); between 1 and 2
the two mix linearly. Measured: flux within 0.3% of π p² at every tested p
(including p = 1, the square/disc seam), and sub-pixel-offset shimmer ≤ 4.6%
across the whole band (the disc alone shimmers ~11% at p = 1 sampled at pixel
centres — the reason for the cross-fade). `speck_gain` (default 1.0) is a
dial. A flux-continuity test (§5) pins the speck to the lit mesh and the
impostor at the hand-off.

**Viewscreen RTT.** Every draw is rebuilt for the RTT's own camera and height,
as minors are. The cell cache is shared.

**Mission swap.** `reset_frame_state` clears the sources, the flagged instances
and the cell cache. The atlases and catalogue table stay.

**Profiling.** `DAUNTLESS_FRAME_SCOPE` scopes `space.far.build`,
`space.far.impostors`, `space.far.specks` and `space.far.haze`.

### 4. Python integration

- **`engine/rocks/density.py`:** `DiscSource`, `evaluate(source, point)`,
  `profile_belt(system)`.
- **`engine/rocks/field_table.py`:** the population table (§2). Built into a
  native source by `density.to_native`, which drops (rather than sends empty)
  any population whose `kind` + `families` matches no catalogue rock, with one
  deduped stderr warning per `(system, kind)` (amended 2026-10-02 — ruling
  rows "Python", §5): an empty-but-present population would otherwise render
  every generated rock of it as catalogue index 0 regardless of kind/family.
- **`engine/rocks/far_tier.py`:** the registry.
  - Pushes the catalogue table to native once (`far_set_catalogue`).
  - Pushes the viewed system's sources when the viewed frame changes, at the
    same seam as `_push_system_nebula` (`far_set_sources`).
  - Inside `_reconcile_scene`, flags every realised `RockClass` whose model is
    a catalogue rock, with `effective_radius`, and sends changes only
    (`far_set_rocks`).
  - Pushes the view→system offset once a frame (`far_set_frame`).
  - Clears on mission swap (the `_drain_pending_swap` reset list).
- **`engine/rocks/far_dials.py`:** every number in §1–3 in one `DEFAULTS`
  dict. Native-owned values go to native as one `far_set_dials(dict)` call;
  Python-owned values (populations, scale height, outer fade) are read at use
  and re-push the sources. Registered as the third dial group, `"far"`, on the
  shared `/ L O` keys. Not persisted; the conftest autouse reset restores the
  defaults.
- **Developer toggle:** Developer Options → Lighting → "Far tier", default on,
  not persisted. Off skips `build` and all three draws, and every `far_fade`
  is 0.
- Nothing here runs in `render_payload`, and nothing changes game state.

### 5. Testing

Everything runs under `scripts/check_tests.sh`, which must exit 0. GL tests are
run with the sandbox disabled (they SKIP inside it).

- **C++ `FarField` (no GL, ctest):**
  - **partition:** a sweep over (r, d) gives exactly one tier per rock; the
    thresholds land at the §1 distances; a 360 px target scales them by 1/3
  - **determinism:** a cell's contents depend only on `(seed, population,
    class, ijk)`, not on camera position or visit order
  - **counts:** the mean count over many cells matches n·V within a statistical
    tolerance, and the density gradient is honoured
  - **explicit regions:** no rock inside one is generated
  - **budget:** nearest cells first; only slab- and frustum-intersecting cells
    are enumerated
  - **haze integral:** the closed-form cross-section below `r_cut` matches
    numeric integration, and haze + specks conserve the total cross-section
    across the cut
  - **fade:** `far_fade` is written per camera for flagged instances
  - **minors:** the speck output of `MinorField::build_bins` covers exactly the
    band it used to cull
- **C++ render (headless GL, minor-pass test style):**
  - an impostor drawn through `opaque.frag` at a baked view direction matches a
    render of the same rock's lod1 mesh at that view and lighting, within a
    tolerance
  - **flux continuity:** the summed radiance of a mesh, an impostor and a speck
    of the same rock at p = 2 px agree within 25%
  - `opaque.frag` with `u_dither_fade = 0` and `u_coverage_cutout = 0` is
    byte-identical to a draw that never set them (not a cross-revision
    golden; the existing pixel suites cover the pre-branch output)
  - the dithered mesh and the inverse-dithered impostor together cover every
    pixel of the silhouette once
  - draw count = non-empty impostor bins + 1 speck draw + 1 per haze source
- **Bindings:** the `far_*` calls in the `host_io` manifest
  (`test_host_io_binding_manifest.py`); their reset pinned in
  `test_init_resets_frame_state.py`.
- **Python:**
  - `profile_belt` builds Vesuvi's disc and builds nothing for a system with no
    `asteroids`; the outer fade applies past the last row
  - populations follow the anchors; no majors at or below 0.5
  - the registry flags only catalogue rocks, sends changes only, clears on swap
  - the dial group registers without new keys (`test_dev_key_collisions.py`)
  - `test_path_indirection.py` stays green
- **E2E through the mission harness (entry at the mission):**
  - E1M2 at Vesuvi registers the belt source and flags its rocks
  - E2M1 at Beol 4 registers no source, and its tile minors reach the speck
    band
- **Performance:** a ctest benchmark of `FarField::build` at the 60,000 budget,
  from inside the Vesuvi band and while dashing at 100,000 GU/s, *reports* its
  time and asserts nothing. Acceptance numbers are live, from the frame
  profiler (`space.far.*`). Measured (amended 2026-10-02): mean **0.015 ms**
  static in the band, **0.10 ms** while dashing at 100,000 GU/s; the Vesuvi
  band at a = 0.5 enumerates only **~220** speck-tier minors per camera (no
  procedural majors there, §2) — it is the haze, not speck count, that carries
  the band visually.

## Live check (Mark)

`./build/dauntless --developer` from the worktree, then:

- **E2M1 / Beol 4:** the tile field is visible as specks from the start
  position.
- **E1M2 at Vesuvi:** the belt band across the sky; the swarm rocks go mesh →
  impostor → speck as you pull away, with no visible pop; the bridge viewscreen
  shows the same.
- **Dash** along the band: no shimmer, no stalls. Read `space.far.*` in the
  profiler (`` ` ``).
- Expect tuning rounds on `/ L O` (group "far") for the thresholds,
  `haze_gain`, `speck_gain` and the scale height.

## Out of scope

- Seeded real rocks, and filling `explicit_regions` (sub-project 4).
- Vesuvi's 0.5 → 0.4 band edit (sub-project 4).
- Planetary rings as sources (the primitive supports them).
- Impostors for minors (minors go lod1 → speck).
- Blending between impostor views.
- Haze extinction of ships, sensor occlusion, haze in the warp tunnel.
- Shadow casting by impostors or specks.

## Risks

- **Impostor view flips.** 16 views are about 50° apart; a tumbling rock between
  2 and 12 px may visibly change silhouette. `imp_lo` / `imp_hi` are the lever.
- **GPU cost is unmeasurable here.** The haze pass is fullscreen at full
  resolution; specks and impostors are cheap per item but can number tens of
  thousands. CPU scopes expose the build; the budget bounds the counts.
- **Belts are faint by physics.** Specks and haze are tuned by gain dials, so
  the first live run may show almost nothing or too much.
- **The 0.05 floor makes Vesuvi's whole plane a faint disc.** It is authored
  data; sub-project 4 may revise it.
- **Shared `opaque.frag` changes.** Both uniforms default off and a
  byte-identity test pins the production path.

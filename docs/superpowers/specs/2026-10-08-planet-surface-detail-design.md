# Planet surface detail — design

**Status:** approved in conversation 2026-10-07/08 · branch `feat/planet-surface-detail` (worktree `.claude/worktrees/planet-surface-detail`, cut from local main `6811cbf8`)
**Programme:** sub-project 2 of the planet rendering programme.
- SP1 geosphere: `2026-10-06-planet-geosphere-design.md` (merged, live-verified).
- SP3 atmosphere: `2026-10-07-planet-atmosphere-design.md` (merged, live-verified). This design extends its catalogue with the `surface` key it reserved.

## 1. Goal and success test

From orbit (150–1100 GU up) a planet should read as a natural surface, not a magnified 256² texture. BC's texture stays the low-frequency truth — Haven still looks like Haven — and procedural high-frequency detail fades in with closeness: relief and albedo variation on land, crisp coastlines and sun glint on water, crack lines on ice, slow turbulence on gas giants. **Render-only**: no gameplay, SDK or `GetRadius()` behaviour changes.

**The success test is Mark's eye in a live calibrate-by-eye loop**, not green tests. Procedural relief has failed here before (collision scuffs: eight live passes read as a stencil or a grid). Tests guard correctness, cost and non-regression; they cannot say the result looks natural. §9 defines the loop.

## 2. Facts this design rests on

Measured 2026-10-07/08 on the installed BC content and this Mac (M3 Pro, GL "4.1 Metal - 90.5").

- **Textures are 256×256** (not 256×128): ~88 GU/texel in longitude, ~44 in latitude at R = 3600. Even 4096² would be ~5.5 GU/texel, so resolution alone cannot reach the bar.
- **~10 of 31 stock planets mix land and ocean in one texture** (Aqua, BlueGray, BlueTan, BrownBlue, GreenPurple — Haven —, PurpleWhite, Ice, earth, planet, dry). Many maps are tiled photos, not projections. `SlimeGreenPlanet.NIF` references `GreenPlanet.tga`. `LavenderPlanet.tga` and `RedSwirlPlanet.tga` are not in the Environment folder.
- **Per-pixel procedural noise is too expensive at full screen** (spike 1, `GL_TIME_ELAPSED`, wall clock agreeing within 0.15 ms): ~0.15 ms per Mpx per analytic-derivative octave; finite-difference bump ~0.26. A full-screen planet at 4.6 Mpx (Mark's 3840×1200 @ 120 Hz display) costs ~4 ms with 6 analytic octaves, ~6.5 ms with domain warp — half or more of an 8.3 ms frame. The footprint fade saves little at the nadir: 0.1 GU pixels from 270 GU up need ~9 octaves.
- **A budgeted toroidal clipmap is flat and cheap** (spike 2, 3840×1200, 5 × 1024² RGBA16F, 64k texels/frame): bake p95 0.18–0.31 ms and max ≤ 0.52 ms across still / orbit 6 GU/s / 60 GU/s / dash 400 GU/s / hard cut; extra sampling +0.2–0.27 ms over the 0.43 ms baseline; cold fill ~80 frames. At dash speed the finest level starves and the shader falls back to coarser ones — cost stays flat. The spike exposed three defects this design fixes: hard seams at level fallback (§5.4 transition bands), a diagonal lattice in the noise (§4 hash), and texel budgeting that is not cost-flat (§5.3 cost units).
- **GPU timing works** since `a244f966`: the profiler times top-level passes with `GL_TIME_ELAPSED` (nested scopes report CPU only).
- `opaque.frag` is optimizer-fragile on this driver (`sampler3D` miscompiles even unreachable; a discard after the derivative block broke a NaN guard). `sampler2D` is proven safe. `pipeline.cc` already compiles a variant of it with `with_define(opaque_fs, "IMPOSTOR_VIEWS")`.

## 3. Architecture

```
atmospheres.json ─▶ engine/planets/surface.py ─▶ _apply_planet_atmosphere ─▶ set_instance_surface(iid, params|None)
                                                                                   │
                                          scenegraph::Instance::Surface ◀──────────┘
                                                   │
frame():  … shadow ─▶ [planet_detail]  PlanetDetailPass picks the target planet, PlanetClipmap::update(budget)
                       ─▶ space / viewscreen RTT ─▶ submit_opaque_in_pass: target planet's sphere-LOD draw uses planet_ program
```

Units, each with one job:

| Unit | Kind | Job |
|---|---|---|
| `engine/planets/surface.py` | Python | `Surface` dataclass, validation of the nested `surface` object, `resolve_surface(set, name, nif)` |
| `engine/planet_surface.py` | Python | developer toggle `enabled()` / `set_enabled()`, default on (geosphere/atmosphere mould) |
| `engine/planets/surface_dials.py` | Python | `"surface"` dial group, reload action |
| `native/src/renderer/planet_detail_noise.{h,cc}` | C++, GL-free | hash, analytic-derivative noise, per-type field functions, the per-type default table — the CPU twin the bake shader mirrors |
| `native/src/renderer/planet_clipmap.{h,cc}` | C++ | one planet's 5-level toroidal clipmap in a single `sampler2D` atlas: anchor frame, valid/target rects, strip scheduling under a cost budget, re-anchor. The scheduling core is GL-free and unit-tested; a thin GL layer bakes strips |
| `native/src/renderer/planet_detail_pass.{h,cc}` | C++ | per frame: choose the target planet, call `update`, expose the sampling uniforms |
| `shaders/planet_bake.frag` | GLSL | bakes one strip piece of one level |
| `opaque.frag` `#ifdef PLANET_SURFACE` | GLSL | sampling + shading, compiled only into the new `planet_` program |

**What stays byte-identical:** `opaque_`, `skinned_`, `minor_` and `impostor_` compile from unchanged source text (the new code is entirely inside `#ifdef PLANET_SURFACE`), and every draw that is not the target planet's sphere-LOD draw goes through them exactly as today. With the toggle off, or no planet close enough, the bake pass does nothing and no draw uses `planet_`.

## 4. Noise

- **Hash:** pcg3d (integer, 3 rounds) on the integer lattice cell, replacing the spike's xor-multiply hash, whose correlation produced a visible diagonal lattice. Lattice coordinates are taken from **body-frame** positions, so detail is fixed to the planet.
- **Noise:** gradient noise with analytic derivatives (value + ∂/∂x,y,z from one evaluation, quintic fade), plus a per-octave rotation to break axis alignment.
- **Seed:** a 32-bit hash of the resolved catalogue key, added to the lattice coordinates, so two planets sharing a type do not share terrain but a planet always gets the same terrain.
- **Field functions** (one per type, §6) are written once in C++ (`planet_detail_noise`) and once in GLSL (`planet_bake.frag`); a test pins the GLSL bake against the C++ twin at sample points.

## 5. The clipmap

### 5.1 Parameterisation

Each level is a square on the plane tangent to the planet at an **anchor** direction `A` (the camera's nadir when the clipmap is (re)built), with in-plane axes `E` (east, `normalize(cross(Z_body, A))`, falling back to `X_body` within 1e-3 of a pole) and `N = cross(A, E)`. A sphere point maps to the plane gnomonically, `P = p · R / dot(p, A)`, `(x, y) = (dot(P,E), dot(P,N))`; a plane point maps back by `normalize(A·R + E·x + N·y)·R`. All in the planet's body frame, centred on `sphere_map.center_body`.

**Re-anchor** (a cold refill) when the camera nadir's plane distance from the anchor exceeds `0.5·R` (~27°; gnomonic stretch < 1.3×), or when the target planet changes.

### 5.2 Levels

- Level 0 texel `ts0 = 0.1 GU`; level L texel `ts0·2^L`; each level 1024². At the closest allowed altitude (150 GU) a nadir pixel is ~0.06–0.12 GU.
- Level count is 5, capped so the outermost level's half-extent (`512·ts0·2^L`) is ≤ R — a 140 GU moon gets fewer levels.
- Atlas: one `sampler2D`, levels stacked vertically, `GL_RGBA16F`, linear filtering, no mips (~40 MB for 5 levels). **Horizontal** toroidal wrap uses `GL_REPEAT` on S (the atlas is exactly 1024 wide). **Vertical** wrap cannot repeat inside a band, so each band is 1026 rows: toroidal rows 0–1023 at band rows 1–1024, plus two guard rows — band row 0 mirrors toroidal row 1023 and band row 1025 mirrors toroidal row 0 (same absolute texels, so same content). The scheduler emits the guard row as an extra `BakeRect` whenever a strip covers toroidal row 0 or 1023. The shader maps `fract(y)` into the band's rows 1–1024 and clamps T, so the bilinear footprint at a band edge reads a guard row, never the neighbouring level. Atlas size 1024 × (1026·levels).
- Texel: R = height, G/B = gradient on the plane (`dot(∇h, E)`, `dot(∇h, N)`), A = per-type secondary field (§6).
- Each level holds the type's full octave stack from its base wavelength down to 2 texels of that level (coarser levels hold fewer octaves).

### 5.3 Bake scheduling

- `PlanetClipmap::update(nadir_plane_xy, budget_cost)` — coarse levels first. Each level's valid rect `B` is clipped to its target rect `D` (1024² centred on the nadir in that level's texels), then grown toward `D` by strips (columns while its height > 0, else rows; seeded as a zero-height full-width band when empty).
- **Cost unit:** `texels × octaves(level)`. Budget dial default `65536 × 8` units/frame (≈ the spike's 64k texels at level 0, ~0.3 ms). A strip's width is chosen so a strip never exceeds the remaining budget by more than one row/column.
- **Cold-start boost:** while any level is incomplete after a reset, the budget is ×2 (still a cap).
- Strips are drawn as scissored full-screen triangles into the level's atlas band, split into ≤ 4 pieces where they wrap. The scheduling core (rects, strips, wrap split, cost accounting) is GL-free and unit-tested; it emits a list of `BakeRect{level, abs_x, abs_y, tor_x, tor_y, w, h}` that the GL layer draws.

### 5.4 Sampling (in `opaque.frag` under `PLANET_SURFACE`)

- Derivatives (`dFdx/dFdy` of the body-frame position) are taken **unconditionally, alongside the existing sphere-map derivative block**, never inside a branch.
- Pixel footprint `fp` (GU) → fractional level `lf = clamp(log2(fp/ts0), 0, levels−1)`. Sample levels `floor(lf)` and `floor(lf)+1`, blend by `fract(lf)`.
- **Transition band:** within the last 10% of a level's valid rect (per axis, measured from its edge), blend toward the next coarser level by the band fraction; if a level is not valid at the point, use the next coarser valid one. This removes the hard seam the spike showed.
- Outside the outermost level, or with no valid level, the detail weight is 0.
- 2 atlas fetches (4 for gas, two phases), all `textureLod(..., 0)`.

### 5.5 Target planet and lifetime (`PlanetDetailPass`)

- Runs once per frame in `frame()` as its own top-level `DAUNTLESS_FRAME_SCOPE("planet_detail")`, after `shadow` and before the viewscreen RTT / `space`, using `g_camera`. Top-level ⇒ the profiler times it on the GPU.
- Target: among visible `Pass::Space` instances with `surface.type != 0` and a `sphere_map`, the one nearest the camera by surface distance, **if** detail would be visible: a BC texel at the nadir spans ≥ 2 px for the main camera. Otherwise no target, and the pass does nothing. Switching to a different candidate requires it to be ≥ 10% nearer (hysteresis).
- The clipmap is reset when the target changes, when the target instance is destroyed, or when the planet's surface params change shape (type, scale, seed).
- Other cameras (bridge viewscreen RTT) sample the same clipmap where valid and fall back to no detail elsewhere; they never trigger a bake.

## 6. Shading

Everything is inside `#ifdef PLANET_SURFACE`, after the BC albedo fetch and before lighting. **Detail weight** `w = smoothstep(2, 8, px_per_BC_texel) × coverage_fade`; `px_per_BC_texel` comes from the existing Tarini UV gradients and the texture size. At `w = 0` the output equals the plain sphere-map path.

**Water mask** (entries with `ocean`): `m = 1 − smoothstep(0.5·tol, 1.5·tol, |base_lin − ocean_lin|)`. **Coast sharpening:** `m_s = smoothstep(0.5 − k, 0.5 + k, m + a·h)`; where `m_s > m` the albedo is pulled toward the ocean colour. `type: ocean` sets `m_s = 1`.

**Land** (weight `(1 − m_s)·w`):
- Bump: `n_shade = normalize(n_shade − s·(g.x·E_ws + g.y·N_ws))`, falling back to `n_shade` when the length is degenerate. `n` stays geometric — the atmosphere limb/terminator and shadow bias are unchanged.
- Albedo: `base *= exp(c·(h − h̄))` — zero-mean in log-luminance, correlated with the relief; `c` defaults to ~±10% and dials to 0.

**Water** (weight `m_s·w`): no wave geometry (waves are far below 1 GU = 175 m). A GGX sun specular, Schlick f0 = 0.02, sun colour, roughness modulated by A (wind patches). No bump, no albedo change.

| Type | Bake: height (R,G,B) | Bake: A |
|---|---|---|
| `rocky` | ridged multifractal, ~40 GU base, strong bump | wind roughness |
| `desert` | soft fBm, low amplitude, + a dune octave stretched along a fixed per-planet wind axis | wind roughness |
| `ice` | low-amplitude fBm, lower roughness (sheen) | crack mask (thin ridged lines; darken + blue-shift albedo) |
| `gas` | domain-warped fBm, 4× stretched east–west, ~200 GU base; **no bump**, albedo only | second decorrelated field (phase 2) |
| `ocean` | unused | wind roughness |

**Gas animation:** sample positions advect east by a per-latitude flow (seeded sine series ⇒ shear between bands) × `u_decal_time` (game time: pause freezes it, time scale applies). Two phases crossfade over a period (default 40 s) so the offset stays bounded; rate 0 = static.

**NaN safety:** every `normalize` guarded; outputs clamped and finite. The `planet_` program gets its own finite-output probe test (§8).

## 7. Catalogue and developer tuning

```json
"greenpurpleplanet": {"color": "#9FB0FF", "thickness": 0.035, "density": 1.0, "limb": 1.0,
                      "surface": {"type": "rocky", "ocean": "#B4A8D0"}},
"moon":              {"atmosphere": false, "surface": {"type": "rocky"}},
"pinkgasplanet":     {"color": "#FF9A96", "thickness": 0.06, "density": 1.4, "limb": 1.0,
                      "surface": {"type": "gas"}}
```

| Field | Meaning | Range / default |
|---|---|---|
| `type` | `rocky` / `desert` / `ice` / `gas` / `ocean` / `none` | required |
| `ocean` | water key colour, `#RRGGBB` sRGB | optional |
| `ocean_tolerance` | mask width, linear-RGB distance | (0, 1], 0.15 |
| `strength` | relief/bump multiplier | [0, 4], 1 |
| `albedo` | albedo-variation multiplier | [0, 4], 1 |
| `scale` | base-wavelength multiplier | [0.25, 4], 1 |

- Unknown fields inside `surface` are rejected; `type` is a closed enum.
- **`atmosphere: false` no longer swallows `surface`** — it disables only the air. Today's "any other fields are ignored" rule changes to "air fields are ignored".
- `surface` resolves **independently**: a `"<set>/<name>"` override that has no `surface` inherits the stem's, and vice versa.
- A malformed `surface` warns once per key and drops only the detail; the atmosphere is unaffected.
- `ocean` only drives the mask; it never tints. Glint takes the sun colour.
- Per-type defaults (base wavelength, octave shape, roughness, gas flow…) live in **one table in `planet_detail_noise`**; the JSON only scales them per planet.

**Seed content** (stems; `ocean` keys sampled from each texture's sea colour, then tuned live):

| Type | Stems |
|---|---|
| `rocky` | moon, grayplanet, rockyplanet, tanplanet, redplanet, brownplanet, greenplanet, slimegreenplanet, rootbeerplanet; + `ocean`: aquaplanet, bluegrayplanet, greenpurpleplanet, purplewhiteplanet, earth, planet |
| `desert` | sulfurplanet; + `ocean`: dryplanet, bluetanplanet, brownblueplanet |
| `ice` | snowplanet; + `ocean`: iceplanet |
| `gas` | pinkgasplanet, bluewhitegasplanet, tangasplanet, gasgiant, redswirlplanet |
| `ocean` | purpleplanet, brightgreenplanet, turquoiseplanet, bluerockyplanet |
| `rocky` (texture not seen) | lavenderplanet — revisit live |

**Developer tuning** (developer-only, atmosphere pattern):
- Developer Options → Environments: "Planet Surface Detail (off = BC texture only; applies to planets realized after toggling)" and "Surface Detail Debug" (tints by clipmap level).
- Dial group `"surface"` on the targeted planet's **type table entry**: `strength`, `albedo`, `scale`, `ocean_tolerance`, coast sharpness, roughness, gas rate, gas period, bake budget. Shape changes (scale, octave shape) reset the clipmap (bounded cold refill); sample-time values apply instantly.
- No save action. "Reload Planet Surfaces" re-reads the JSON; tuned type-table numbers are copied into `planet_detail_noise` by hand.

## 8. Testing and performance

**Python (pytest):**
- `surface` validation: each type accepted; unknown field rejected; bad enum rejected; ranges enforced; hex → linear.
- `atmosphere: false` + `surface` ⇒ no atmosphere, surface resolved.
- Independent resolution: override without `surface` inherits the stem's; override with `surface` wins; malformed `surface` warns once and leaves the atmosphere intact.
- Every stock stem has a `surface` entry (stem list in the test).
- Hook: each realize path pushes `set_instance_surface` with resolved params when enabled, `None` when disabled; fakes mirror the real binding signature.
- Developer Options rows and render snapshot; dial group registers and re-pushes.

**C++ GL-free (gtest):**
- `planet_detail_noise`: pcg3d determinism; analytic gradient matches central differences within tolerance; per-type fields finite and bounded over a sample grid; seed changes the field.
- `planet_clipmap` scheduling: cold fill completes in the expected number of frames for a budget; per-frame cost never exceeds budget + one strip; strips cover `D` exactly once with no gaps or overlap (pixel-set check); wrap split produces ≤ 4 pieces that tile the strip; moving one texel bakes exactly one column per level; re-anchor threshold; level-count cap for small R.
- Gnomonic round trip (plane → sphere → plane) within 1e-4 relative.

**C++ GL (gtest, `FrameTest` style):**
- Bake twin: bake a small region and read back; matches `planet_detail_noise` at sample texels within fp16 tolerance.
- `planet_` program finite-output probe over a full-screen planet (camera outside, at the limb, at a pole, on the seam): no NaN/Inf.
- With no target / toggle off: frame matches today pixel for pixel.
- Seam test: render across a level transition band and assert no step in a pixel row above a threshold.
- **Every pre-existing renderer test passes, run as the FULL binaries** (the `sampler3D` lesson: filtering to `HullClipTest` once hid 16 failures).

**Performance (bench, gated):** a ctest bench (rock-bench pattern) renders a full-screen planet at 3840×1200 through the real `planet_` program and `PlanetClipmap`, timing with `GL_TIME_ELAPSED`, over still / orbit / dash / cut. **Budgets:** bake p95 ≤ 0.35 ms and max ≤ 0.6 ms; sampling ≤ 0.35 ms over the plain sphere-map draw. Live: the profiler's `planet_detail` row and `space` row with the toggle on vs off, Haven filling the screen.

## 9. Live calibration loop (Mark, in this worktree)

`cd .claude/worktrees/planet-surface-detail && ./build/dauntless --developer`; orbit Haven (rocky + ocean), a moon (rocky airless), a pink gas giant, an ice planet and a desert. Per type: dial strength/albedo/scale/roughness until it reads as natural from orbit; A/B with the toggle; check the level debug tint for seams. The first build ships conservative defaults; expect iterations. **"Reads as natural from orbit" is the acceptance bar.** If a type cannot get there, the fallback (as with scuffs) is a splatted authored texture behind the same field interface, not more procedural variants.

## 10. Out of scope

Terrain geometry/silhouette relief, clouds, planet spin, more than one detailed planet at a time, mod-supplied surface entries (the format allows a later merge), streaming or disk caching of the clipmap, RGBA8 atlas (only if measured adequate), gameplay use of surface type.

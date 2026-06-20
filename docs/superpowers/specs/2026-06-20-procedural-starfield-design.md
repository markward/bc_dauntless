# Procedural Starfield, Nebulae & Star Clusters — Design

**Status:** design approved, pending implementation plan
**Branch:** `feat/procedural-starfield`
**Related:** [`docs/sector-cartography.md`](../../sector-cartography.md) (findings + the PoC that
extracted the appearance metadata this feature consumes)

## 1. Summary

Replace BC's static, identical-everywhere textured starfield with a **procedural
sky** synthesized in the backdrop shader: a varied, denser point-field starfield
with real **star clusters** (Milky-Way-style bands of stars, diffuse dust glow,
and dark dust lanes) and **nebulae** rendered from their authored colour,
palette, density, direction, and span — with subtle living motion.

It is a **Modern VFX** toggle (default **on**); off is byte-identical stock BC.

## 2. Goals & non-goals

**Goals**
- Per-system variety: no two systems' skies alike (vs today's single tiled `stars.tga`).
- Star **clusters** as denser/brighter regions with Milky-Way dust structure.
- Nebulae faithful to authored intent (same colour/direction/size), rendered as
  living layered cloud instead of a flat TGA.
- Subtle **dynamism** (twinkle, gentle nebula/dust drift).
- Zero gameplay impact; faithful stock-BC fallback preserved.

**Non-goals (explicitly out of scope for this phase)**
- Gameplay, object placement, mission behaviour — untouched.
- The **MetaNebula hazard volumes** (Vesuvi/Belaruz fly-through gameplay) — separate
  system, not this pass.
- Realistic inter/intra-system scale and dynamic warping (a later phase; see
  `docs/sector-cartography.md` §7).
- Volumetric raymarched nebulae (considered, rejected as overkill/perf risk for
  non-fly-through background).

## 3. Design decisions (resolved during brainstorming)

| Fork | Decision |
|---|---|
| Data source | **Driven by recorded appearance attributes** (colour/palette/coverage/direction/span). The metadata is never discarded. |
| Nebula technique | **Procedural texture on the existing camera-anchored backdrop spheres** (reuse `backdrop_pass`; no new pass). |
| Stars & clusters | **Hash-based procedural point-field in the shader**, density boosted at star-cloud directions. |
| Dynamism | **Subtle living motion** — twinkle + slow nebula/dust drift via a time uniform. |
| Faithfulness | **Stock BC retained** as the toggle-off path (byte-identical). Procedural is a Modern VFX toggle, default on. |
| Star clusters | Three coupled layers: bright points + diffuse dust glow + dark dust lanes (Milky-Way look). |

## 4. Architecture & data flow

Mirrors today's `set_backdrops` path; swaps "sample a TGA" for "synthesize from
parameters". No NIF, no runtime image decode.

1. **Offline appearance bake** — productionize the PoC's `tga_appearance` into a
   build/tooling step that emits a committed **appearance table**
   (`backdrop_appearance.json`): `texture-basename → {meanColor, palette[5], coverage}`.
   ~25 entries, generated once from the game TGAs (needs `game/` + Pillow at bake
   time only; the runtime reads JSON).
2. **Python aggregation** — `engine/appc/backdrops.py:aggregate_for_renderer`
   (pure function) joins each SDK `BackdropSphere` (direction + span from
   `AlignToVectors`) with its appearance-table row → a **procedural descriptor**:
   - *nebula sphere*: `{kind:"nebula", direction, span, color, palette, coverage, seed}`
   - *star sphere*: `{kind:"stars", base_density, seed, clusters:[{direction, angularSize, density, dustColor}]}`
     where `clusters` come from the `galaxy*` star-cloud backdrops (direction +
     coverage + galaxy meanColor we already extract).
3. **Bindings** — `set_backdrops` (host_bindings) gains the procedural fields; a
   new `set_procedural_sky_enabled(bool)` toggle joins the Modern VFX group.
4. **C++ pass** — `backdrop_pass` keeps the existing texture path and adds a
   procedural path: bind descriptor fields as uniforms, draw the same
   camera-anchored sphere, fragment shader synthesizes the sky.

**Seed** is derived per-system (stable across visits, distinct per system).

## 5. The shaders

Vertex stage unchanged (`backdrop.vert`: translation stripped, depth at far
plane). Work is in `backdrop.frag`, plus a shared `noise.glsl` include
(hash, value/simplex noise, FBM).

**Star + cluster shader (star sphere):**
- Hash the view direction into a cell grid; a cell may hold a star with
  hash-derived brightness + slight colour temperature (cool→warm). Crisp,
  resolution-independent.
- **Cluster density:** base star probability boosted near each cluster direction
  via angular falloff (sized by `angularSize`, scaled by `density`).
- **Milky-Way dust (at cluster directions):**
  - *diffuse glow*: low-contrast FBM tinted by `dustColor` (the dim galaxy mean
    colour) — the soft luminous band.
  - *dark lanes*: higher-frequency FBM darkening term occluding both the dust glow
    and the stars behind, carving silhouetted lanes.
- **Twinkle:** per-star brightness oscillation, phase from the star hash, driven
  by the time uniform.

**Nebula shader (per backdrop sphere, within its `span` patch):**
- **FBM** over the patch, shaped by `coverage` (contrast/threshold → wispy vs dense).
- **Palette tint:** map noise value through the recorded 5-colour `palette` (cores
  brightest, edges → transparent).
- **Soft-edged** within the angular span (no hard sphere seam); alpha-blended as today.
- **Drift:** slowly advance the noise domain with the time uniform.

Bright star and nebula cores exceed the bloom threshold → glow for free via the
existing HDR pipeline.

## 6. HDR & performance

- Emits to the existing `g_hdr_target`; bloom + muted-film tone-map already handle
  bright cores (compressed, not blown out).
- One camera-anchored sphere drawn first each frame; fragment-bound but cheap
  (modest FBM octaves), **not** per-object — combat scenes unaffected.
- Renders wherever the current backdrop renders (incl. viewscreen) for parity.

## 7. Config / faithfulness

- Single toggle `set_procedural_sky_enabled`, default **on**, Modern VFX group
  (alongside `set_hdr_enabled` / `set_rim_enabled`).
- **Off** → existing texture-sampling path, byte-identical stock BC.
- No sub-toggles this phase (YAGNI); intensity knobs deferred.

## 8. Components (isolated units)

| Unit | Location | Responsibility | Depends on |
|---|---|---|---|
| Appearance bake | `tools/` | TGAs → `backdrop_appearance.json` | Pillow, `game/` (bake-time only) |
| Appearance table | committed data file | `texture → {meanColor, palette, coverage}` | — |
| Python aggregation | `engine/appc/backdrops.py` | SDK backdrop + table → procedural descriptor | appearance table |
| Bindings | `native/src/host/host_bindings.cc` | descriptor fields + `set_procedural_sky_enabled` | — |
| Procedural pass path | `native/src/renderer/backdrop_pass.{h,cc}` | bind uniforms, select path | pipeline shader |
| Shaders | `native/src/renderer/shaders/backdrop.frag` + `noise.glsl` | synthesize sky | embedded at build |

**Reminder:** shader edits require a `cmake -B build -S .` reconfigure before
`cmake --build` (embedding headers regenerate at configure time).

## 9. Data contracts

**Appearance table row:** `{ "texture": "treknebula6.tga", "meanColor":[r,g,b],
"palette":[[r,g,b]×5], "coverage": 0.50 }` (0–255 ints; coverage 0–1).

**Procedural descriptor (nebula):** `kind, direction[3], span, color[3],
palette[5][3], coverage, seed`.
**Procedural descriptor (stars):** `kind, base_density, seed, clusters: [{direction[3],
angularSize, density, dustColor[3]}]`.

## 10. Testing

- **Deterministic (unit):** appearance bake output shape; Python aggregation —
  descriptor shape, table lookup, and **fallback** (unknown texture → stock
  texture path for that backdrop).
- **Visual (FrameTest, C++):** render a known system's procedural sky offscreen;
  assert non-black and that the nebula's angular patch carries its recorded
  dominant hue; render a toggle-off frame and confirm the faithful path is
  unchanged.
- **Manual:** A/B toggle verification in the live app by the user.

## 11. Edge cases & error handling

- Backdrop texture absent from the appearance table → **graceful fallback** to the
  stock texture path for that backdrop (don't fail the frame).
- Seed must be frame-stable (no per-frame star flicker beyond intended twinkle).
- Toggle-off must be byte-identical to current behaviour (regression guard).
- Star sphere with no `galaxy*` clusters → uniform varied starfield, no dust.

## 12. Future (out of this phase)

- Intensity / per-element sub-toggles if needed.
- Rigorous nebula placement from bearing triangulation (vs current authored spans).
- The realistic-scale / dynamic-warp phase that reuses this sky (see findings doc §7).

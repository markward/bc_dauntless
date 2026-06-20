# Cubemap Sky Bake — Design

**Status:** design approved, pending implementation plan
**Branch:** continues the procedural-sky line (`feat/procedural-starfield`); a fresh
branch off it (or off main once merged) is fine — see §11.
**Related:**
- [`2026-06-20-map-driven-starsphere-design.md`](2026-06-20-map-driven-starsphere-design.md) — the projection + backdrop shader this optimizes
- [`2026-06-20-procedural-starfield-design.md`](2026-06-20-procedural-starfield-design.md) — the procedural shader being baked

## 1. Summary

The map-driven procedural sky is **static per system** — it rotates with the
view but its content is fixed until the player warps. Today the noise-heavy
backdrop shader (`fbm` + `turb` + `proc_stars` across 14 camera-anchored
spheres) is re-rendered **every frame**, recomputing an image that never
changes. This bakes that sky **once per system entry** into an offscreen
**cubemap**, then samples that cheap texture each frame.

The bake reuses the existing projection and `proc_main` shader **verbatim**, so
the result is visually identical to today's live render — only frozen (no live
twinkle/drift) and far cheaper to draw.

## 2. Goals & non-goals

**Goals**
- Replace per-frame procedural backdrop rendering with a once-per-system bake +
  cheap per-frame cubemap sample.
- Visually identical to the current live procedural sky (modulo frozen
  micro-animation).
- Preserve HDR (bright nebula cores still feed bloom).
- Stock-BC path (toggle off) and the unmapped-authored fallback stay on their
  existing per-frame textured path, byte-identical.

**Non-goals**
- Live sky animation (twinkle/drift) — intentionally frozen between bakes (the
  micro-motion is barely perceptible; the live **dust pass** keeps the scene
  feeling alive). See §3.
- Ship-position parallax / realistic scale (deferred Phase 3, unchanged).
- Changing the projection, density, or look — all the tuning from the
  map-driven phase is carried through the bake unchanged.

## 3. Design decisions (resolved during brainstorming)

| Fork | Decision |
|---|---|
| Staleness | **Static until warp.** Bake on system/vantage change or toggle flip; content frozen between bakes. Maximum perf win. |
| Capture representation | **Cubemap** (6 × RGBA16F faces). No seam, no pole distortion, uniform directional resolution, HW filtering/mips. (Equirect and dual-paraboloid rejected: both reintroduce seams/pole or nonuniform resolution.) |
| Face resolution | **1024²** RGBA16F (~50 MB + mips ≈ ~67 MB VRAM). Stars slightly softer than live render but **stable/no-shimmer** with mipmaps; nebulae unaffected. |
| Re-bake trigger | **Implicit descriptor diff** in `set_backdrops` (zero new Python plumbing). Descriptors are deterministic per vantage → identical frames don't re-bake; warp/toggle changes them → re-bake. |

## 4. Architecture & components

All additions are C++; the Python host loop is unchanged.

| Unit | Location | Responsibility | Depends on |
|---|---|---|---|
| `CubemapTarget` | `native/src/renderer/cubemap_target.{h,cc}` (new) | One 6-face RGBA16F color cubemap + shared depth renderbuffer + FBO. `allocate(face_size)`, `bind_face(i)` (attach face *i*, set viewport), `texture()`, `generate_mips()`, `face_size()`. Fixed size, window-independent. | glad |
| Sky bake | `BackdropPass::bake(backdrops, pipeline, now)` (new) | For each of 6 cube faces: set a 90°-FOV projection + that face's view rotation, `bind_face`, clear, render the backdrop spheres via the **existing** `proc_main` path; then `generate_mips()`. Camera at origin (sky is camera-anchored — only orientation varies per face). | `CubemapTarget`, backdrop shader, `sphere_mesh` |
| Skybox sample | `skybox.vert` / `skybox.frag` (new) + `BackdropPass::render_cubemap(camera, pipeline)` (new) | Draws a skybox (sphere mesh, skybox-depth `z=w` idiom) sampling `texture(u_skybox, normalize(viewDir))` into the bound HDR target. One cube fetch per fragment. | `CubemapTarget`, pipeline `skybox_shader()` |
| Dirty tracking | `native/src/host/host_bindings.cc` (`set_backdrops`) | Cache the last descriptor list; on a new list that differs, set `g_sky_dirty = true`. Also dirty when the procedural toggle state differs from the last bake. | — |
| Pipeline wiring | `native/src/renderer/pipeline.{h,cc}` + CMake | `skybox_shader()` accessor; embed `skybox.{vert,frag}` at configure time. | — |

**Reminder:** new shader files require a `cmake -B build -S .` reconfigure
before `cmake --build` (shaders embed at configure time).

## 5. Data flow

1. Python `_aggregate_backdrops(active_set)` → `r.set_backdrops(descriptors)`,
   **every frame, unchanged.**
2. C++ `set_backdrops`: if `descriptors != cached` → cache + `g_sky_dirty = true`.
3. C++ `frame()` (before any view that samples the sky, i.e. before the
   viewscreen RTT and the main view):
   - `procedural = dauntless_procedural_sky::enabled()`
   - **bakeable** = procedural sky active **and** descriptors are procedural
     (empty `texture_path` / proc-kind driven — the map-driven case).
   - If bakeable:
     - if `g_sky_dirty` || cubemap unallocated || toggle-state-changed →
       `g_backdrop_pass->bake(...)`; clear `g_sky_dirty`; record toggle state.
     - per view: `g_backdrop_pass->render_cubemap(cam, pipeline)`.
   - Else (stock BC, or procedural-on-but-unmapped authored fallback): existing
     per-frame `g_backdrop_pass->render(...)` textured path, **unchanged.**

**"Bakeable" detection.** Map-driven descriptors carry an empty `texture_path`
and a `proc_kind`; authored/stock descriptors carry a real `texture_path`. The
branch keys on "all descriptors have empty `texture_path`" (procedural) — no new
Python signal required. (If this proves fragile in implementation, fall back to
an explicit per-call flag; the implicit form is preferred.)

## 6. HDR, viewscreen, lifecycle

- **HDR:** cubemap faces are RGBA16F (linear); the skybox sample writes into the
  main HDR target so bloom lights bright nebula cores exactly as today.
- **Viewscreen RTT:** the bake runs once per frame (top of `frame()`), so both
  the main view and the viewscreen sample the same cubemap — no double bake.
- **Lifecycle:** `CubemapTarget` dtor releases GL handles; `BackdropPass` owns
  the target and is reset in `shutdown()` before the window is destroyed (same
  contract as `HdrTarget`).
- **Window resize:** cubemap is fixed-size, unaffected (only `HdrTarget`
  resizes).

## 7. Error handling & edge cases

- **Allocation failure:** if the cubemap FBO/texture fails to allocate, fall
  back to the existing per-frame procedural render so the sky never blanks
  (logged once).
- **Empty descriptor list:** skip (as today).
- **Toggle flip mid-session:** descriptors change → re-bake (procedural) or
  switch to per-frame textured (stock); the recorded toggle state forces a
  re-bake on the next bakeable frame.
- **Unmapped system (procedural on, no vantage):** `_aggregate_backdrops`
  returns authored descriptors with real `texture_path` → not bakeable → existing
  per-frame textured path.
- **First frame of a new set:** descriptors differ from cache → dirty → bake
  before the first sample.

## 8. Performance

- **Bake:** 6 faces × the backdrop-sphere render, once per system entry — a
  one-time cost folded into a load that already happens. ~6× one current
  backdrop frame, once.
- **Per frame:** one mip-filtered cube fetch per pixel instead of 14
  noise-heavy spheres with overdraw — the win.
- **Memory:** 6 × 1024² × RGBA16F ≈ 50 MB, + mips ≈ **~67 MB** VRAM.

## 9. Testing

- **C++ FrameTest:**
  - *Bake fidelity:* bake a known small model, then assert the cubemap-sampled
    framebuffer matches the live per-frame procedural render within a tolerance
    (proves the bake is faithful).
  - *Dirty logic:* `set_backdrops` with an identical list does not re-bake;
    a changed list does. (Observe a bake counter.)
  - *Toggle-off parity:* stock path remains byte-identical (regression guard).
- **Python:** existing `sky_projection` determinism tests already guarantee the
  descriptor diff is stable per vantage; no new Python tests required.
- **Manual:** confirm frame-time drop in a nebula system; confirm no visible
  difference vs the pre-bake sky (modulo frozen micro-animation); confirm the
  one-time bake hitch on warp is acceptable.

## 10. Components are isolated

- `CubemapTarget` knows only "6 RGBA16F faces + depth + FBO"; usable by anything
  needing a render-to-cubemap target.
- `bake` / `render_cubemap` are two clearly separated `BackdropPass` methods
  (produce the cubemap; consume the cubemap) that share only the owned
  `CubemapTarget`.
- The dirty flag is a single host-side boolean with one writer (`set_backdrops`
  diff + toggle-state change) and one reader/clearer (`frame()`).

## 11. Future / out of scope

- Periodic re-bake or hybrid live-stars (rejected in §3) if frozen
  micro-animation ever proves noticeable.
- Baking suns/planets into the cubemap (currently separate live passes).
- Phase 3 ship-position parallax would make the vantage continuous and require
  rethinking the static bake (out of scope here).

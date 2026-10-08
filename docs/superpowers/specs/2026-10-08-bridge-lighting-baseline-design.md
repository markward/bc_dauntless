# Bridge Lighting Baseline — Production Design

> **Status:** approved design, 2026-10-08. Branch `feat/bridge-lighting-baseline`
> (worktree `.claude/worktrees/bridge-lighting-prod`), off local `main` `6811cbf8`.
> **Source:** the spike on branch `spike/bridge-lighting`, whose living spec
> (`docs/superpowers/specs/2026-10-07-bridge-lighting-vfx-spike-design.md` on
> that branch) records every look decision, measurement and rejected
> alternative. This document is the production cut of it: read the spike spec
> for *why*, this one for *what ships*.
> **Approach:** port and harden — each task writes its tests first, watches them
> fail on main, then brings across the spike's proven code minus its spike-only
> shortcuts.

---

## 1. Goal

Replace BC's baked-lightmap bridge look with the baseline Mark accepted live on
**both stock bridges (DBridge and EBridge)** on 2026-10-08:

- smooth generated normals for set geometry authored without them;
- a dull ceiling downlight as the only base illumination (no lightmaps);
- screen-space ambient occlusion, with a player-facing quality setting;
- alert-level brightness (green brighter than yellow/red);
- lit surfaces that never bloom.

It is the foundation for the next phase (per-bridge tuning, emitters and
illuminated-surface identification), which builds on this pipeline.

**BC's lightmap look is deleted, not kept as an option** (Mark, 2026-10-08).
The new look is the only bridge look.

## 2. Scope

In: §3–§6. Out (next phase): per-bridge tuning data; emitters and
illuminated-surface identification; the red-alert strip pulse; a fade between
alert levels; the cove glow painted into DBridge `Map 3.tga`'s diffuse (a
baked-light artefact in an albedo, not a lightmap); measuring High on a gaming
GPU.

## 3. Normals at load time

**Opt-in by model kind.** `renderer.load_model(..., interior=True)` (Python) /
the native `load_model` gain an `interior` flag, passed only by the one
function that realises sets — `host_loop.py`'s set loader (bridge, comm-set
rooms) and the viewscreen model load beside it. It is folded into the asset
cache key exactly as `geosphere` is, so an interior and a non-interior load of
one NIF never share an entry. With `interior=False` — every ship, station,
rock and planet path — the loader is byte-identical to `main`.

Why sets only (Mark, 2026-10-08): of 253 stock NIFs only three lack normals,
all sets (DBridge, EBridge, DBridge viewscreen). Ship rendering stays exactly
what has been seen; extending generation to other models is a later,
separate decision.

**What runs.** For an interior model, every shape with no authored normals —
and only those — goes through, in model space, across all such shapes of the
model together:

1. **T-junction repair**: split a triangle wherever a vertex lies strictly
   inside one of its ORIGINAL edges (u ∈ (0.001, 0.999), off-line < 0.1% of
   the edge); the new vertex takes the T vertex's exact position and
   interpolates the split triangle's own attributes. Never split on a diagonal
   the repair created. Watertight: inserted vertices interpolate with the
   edge's endpoints in lexicographic order, and snap to an existing vertex of
   their own shape at the same position. Spatial-grid accelerated.
2. **Smooth normals**: weld by position (snapped to 1/1024 unit); faces join
   when chained through shared edges each folded less than the **crease angle
   (40°)**; winding is settled per edge; distinct vertices at one position with
   identical attributes (UV sets, **source float** colour) are an authored hard
   edge; contributions are **area-weighted** (the only mode); corners that
   disagree split the vertex.

Shapes with authored normals are never touched, even inside an interior model.
Each shape keeps its own vertices, frame, material and textures.

**Code.** `native/src/assets/src/normal_gen.{h,cc}` (internal to the assets
library) with the spike's unit tests. The crease angle is a named constant
beside it (the assets library cannot include renderer headers); the renderer's
tuning header (§4) points to it.

**Spike debt removed.** The spike carries vertex provenance (owner shape,
model-space position) in three spare `extra_uvs` channels and adds
`needs_normals` / `source_colors` to the public `MeshCpu`. Production uses a
dedicated build-time provenance structure, local to model building and never
stored on the `Model`.

## 4. Renderer

**One lighting path in `bridge.frag`:**

```
received = ambient × mix(down_bottom, down_top, 0.5 + 0.5·(n·up)) × ao
colour   = diffuse_ceiling(albedo × received)
```

- `ambient` is the bridge set's SDK ambient × the alert scale (§5), so
  script-driven light changes still flow through.
- `up` is bridge-local +Z, a named constant: set instances are drawn with an
  identity transform.
- Normal facing: generated normals face by winding (`gl_FrontFacing`);
  authored-normal meshes (officers) keep the eye-direction flip.
- **`diffuse_ceiling`** — *lit surfaces never bloom; only emitters do.*
  Identity below 70% of `diffuse_max`, then
  `knee + range·(1 − exp(−(b − knee)/range))` on the max channel `b`, all
  channels scaled by the same factor so hue holds. `diffuse_max = 0.88` sits
  under bloom's 0.9 threshold (`bloom_pass.h`). Why: green's brighter ambient
  pushed the up-facing floor over the threshold and the whole room bloomed.
- Unchanged and byte-identical: the viewscreen feed (unlit, full bright), the
  ViewOn/Off fade, warp flash, and officer lip-sync blend.
- Removed: the legacy lightmap branch, the spike's flat proof mode and its
  emissive-gain term (0 in the spike; emitters return as their own rule).

**Dead code deleted** (deferred-work item 32): `Material::lightmap_pass`, the
`lightmap_pass` partition in `walk_bridge_meshes`, `lightmap.{vert,frag}`,
`Pipeline::lightmap_shader()`. Lightmaps are still routed to the `Dark` stage
at load (ships share the material code); the bridge shader never samples it.

**Tuning in one place.** `renderer/bridge_lighting_tuning.h` — one documented
`constexpr` struct, each value with its provenance:

| Name | Value | Source |
|---|---|---|
| `down_top` | 1.0 | spike iteration 1 |
| `down_bottom` | 0.25 | spike iteration 1 |
| `ao_radius` | 24 (view-space units) | Mark's live pick |
| `ao_strength` | 2.0 | Mark's live pick |
| `ao_bias` | 0.5 (view-space units) | spike default |
| `diffuse_max` | 0.88 | under bloom threshold 0.9 |

A tweak is one line and a rebuild (Mark, 2026-10-08: constants, not data, for
now; per-bridge data is the next phase).

**AO as its own pass: `BridgeAoPass`** (`bridge_ao_pass.{h,cc}`), owning:

- a NORMAL + DEPTH pre-pass of the bridge from the eye, drawn with the bridge
  shaders in normal-output mode (so AO sees the same smooth normals as the
  lighting);
- the AO target at the preset's resolution scale;
- `bridge_ao.frag`: a generated golden-angle cosine-hemisphere kernel of N
  samples (the spike's fixed 16-sample table is deleted — it read blotchy),
  rotated by a 4×4 Bayer tile; distance-scaled bias; range check
  `1 − smoothstep(0.5r, 1.5r, |Δz|)`; `ao = 1 − strength·occl/N`;
- a raw (non-compare, NEAREST) sampler for depth reads.

`BridgePass` asks it for the AO and pre-pass depth textures and binds them on
explicit units 3 and 4. `bridge.frag` filters the AO 4×4, depth-aware (tap
weight `exp(−|Δz|/(0.02·|z| + 0.25))`), stepping in AO texels, and multiplies
**received light only**. AO runs for the **main bridge view only** — never the
comm-set RTT (another camera, another room); comm-set rooms get the downlight
without AO or alert scaling.

**Quality presets** — `enum class BridgeQuality { Low, Medium, High }`:

| Preset | AO samples | AO resolution | Intended for |
|---|---|---|---|
| Low | 24 | half | — |
| **Medium (default)** | 32 | half | laptops |
| High | 64 | **full** | dedicated gaming GPUs, not laptops |

Measured on an M3 Pro (spike, `GL_TIME_ELAPSED`, idle bridge, half res):
pre-pass ~0.55 ms; kernel ~0.04 ms GPU per sample → Low ~0.9 ms, Medium
~1.3 ms. High is an extrapolation (~9–10 ms on an M3 Pro) — acceptable by
design for its audience; measure it with the frame profiler's GPU column
(now `GL_TIME_ELAPSED` on main) before calling the preset done.

**Developer debug views**: off / normals / light only / AO only / triangle
id / mesh id, set by a `set_bridge_debug_view(int)` binding that is a no-op
unless `--developer`. Never set in production.

## 5. Python: alert levels and the setting

**Alert ambient** — `engine/bridge_lighting.py`, pure:
`ambient_scale_for_alert(level) -> float`: GREEN (0) ×1.5, YELLOW (1) ×1.0,
RED (2) ×1.0, anything else ×1.0. ×1.0 is the SDK-authored bridge ambient.
`host_loop` calls it per frame and pushes the result through the existing
`set_bridge_ambient_scale` binding (interior only — the comm-set feed keeps
constant brightness). Replaces `main`'s red-only ×0.5 dim. Switch is instant.
×2.0 for green was tried first and read too bright (Mark, live).

**"Bridge rendering" setting** — a new `settings_store.SETTINGS` row, modelled
on `ai_difficulty` / `aa_mode`:

- key `bridge_quality`, section `graphics`, `int`, `lo=0`, `hi=2`
  (0 Low, 1 Medium, 2 High), `reset_default=1`;
- applier → new `set_bridge_quality(int)` binding; display default reads the
  live engine value via a new `bridge_quality()` getter;
- the native side starts at Medium, so with no stored key the applier is never
  called (the absent-key rule) and boot is Medium;
- shown in the configuration panel's Graphics tab as a three-way choice
  "Bridge rendering: Low / Medium / High".

**Developer Options** entry (`--developer` only, not persisted) cycling the
debug views.

## 6. Testing

- Normal generation: the spike's `normal_gen_test.cc` cases, plus: the
  `interior` flag gates generation (a normal-less non-interior model is left
  untouched; an interior one gets generated normals); the cache key separates
  interior and non-interior loads of the same NIF; authored normals inside an
  interior model are untouched.
- Renderer (GL frame tests): AO darkens an inside corner and leaves a flat
  open floor near 1; the comm-set draw never binds AO; presets map to the
  table's sample counts and scales; the 16-sample table is gone.
- `diffuse_ceiling`: a CPU twin of the GLSL formula pins it; for any input the
  max channel stays below 0.9; identity below the knee; hue ratio preserved.
- Python: `ambient_scale_for_alert` per level incl. unknown; the settings row
  passes the existing table tests and its applier reaches the binding; the
  panel row renders and commits; the debug-view entry exists only under
  `--developer`.
- Gate: `scripts/check_tests.sh` green with no new `tests/known_failures.txt`
  entries.

## 7. Done criteria

1. The gate is green.
2. Mark confirms live, in the worktree: DBridge and EBridge at Medium match the
   spike's look; green/yellow/red alert behave as on the spike; the Bridge
   rendering setting switches live and persists across a relaunch.
3. Merge to `main` only with Mark's OK.

## 8. Task order (for the plan)

1. `interior` load flag + cache key (no behaviour change).
2. T-junction repair + normal generation for interior models + provenance
   structure.
3. Tuning header; `bridge.frag` single downlight path + `diffuse_ceiling`;
   delete the lightmap branch and dead code.
4. `BridgeAoPass` (pre-pass, generated kernel) + the depth-aware filter.
5. Quality presets + `set_bridge_quality` / `bridge_quality` bindings.
6. `engine/bridge_lighting.py` alert scaling wired in `host_loop`.
7. Settings row + configuration-panel control.
8. Developer debug views + Developer Options entry.
9. Docs: CLAUDE.md reference row; a pointer from the spike spec to this one;
   deferred-work item 32 marked done.

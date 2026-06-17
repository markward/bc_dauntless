# Hull Breach Renderer — 2a (Carve + Breach MVP) — Design

**Date:** 2026-06-17
**Status:** Design approved, ready for implementation plan
**Scope:** Spec 2a of the hull-damage renderer (spec #2 of the project's hull-damage work). Builds on the merged voxel **foundation** (`native/src/voxel/`). This is the **MVP vertical slice**: one believable breach, end-to-end. Fidelity (torn rims, modern interior, classic↔modern toggle) is **2b**; debris/embers are **2c**.

## Motivation

The foundation decodes BC's authentic per-ship voxel volume and can voxelize arbitrary hulls. This spec makes damage **visible**: on a weapon hit, carve the ship's voxel volume and render a see-through breach with the authentic chunky colored "guts" behind it — the look from the stock-game destroyed-Galaxy screenshots that started this work.

The renderer is OpenGL **4.1 core** (the macOS ceiling; raised from 3.3 by the scavenged GL bump — see "Scavenge"). 4.1 gives tessellation + geometry shaders but **no compute / no SSBOs**, so all volume work is CPU-side and rendering uses fragment clip + instanced draws.

## Approach (settled)

Three techniques were considered for showing a hole:
- **A. Fragment-clip** — sample the per-instance carve state in the hull fragment shader and `discard` carved fragments. Keeps the original hull mesh (UVs, aztec, lighting) intact; only punches holes. Cheap, no remesh.
- **B. CPU-remesh the whole carved volume** — **rejected**: BC's coarse ~15-GU voxel resolution would turn the *entire ship* lo-poly just to carve a few holes.
- **C. Hybrid** — clip (A) + CPU-remesh only the breach boundary for rims/interior geometry. The remesh half is **deferred to 2b**.

**2a uses A** (fragment-clip holes) **+ a "classic colored-voxel" interior splat** behind the hole (render the solid voxels just inside the breach as instanced colored cubes — BC's authentic guts look, which we already decoded). This delivers the nostalgic look with no remeshing and is the lowest-risk slice. The modern lit interior + torn rims + a classic↔modern toggle come in 2b.

## Scavenge (from `feat/hull-damage-hit-trigger`)

That branch (the rejected tessellation-displacement "dents" approach) is **41 commits behind main** — treat as a **donor, not a merge**. Re-apply/adapt onto current main, retargeting *crater displacement → voxel carve*:

- **Take, ~as-is:** GL 4.1 bump (`window.cc`) + `gl_caps.{h,cc}` + `gl_caps_test`.
- **Take, retargeted crater→carve:** `hit_feedback.py` emit-on-hit (gated + throttled, same block as the decal add); `deform_eligibility.py` (player + capped nearest/largest, per-tick refresh, mission-swap reset); `hull_deformation.py` damage→radius mapping; the host binding; the per-instance state pattern (`HullCraterField` → carve field); the Modern-VFX config toggle (config panel + CEF JS + `renderer.py` + host binding + tests); `Damage.tga` loading.
- **Leave behind:** the tessellation-displacement geometry (`opaque_deform.tesc/tese`, the deform draw path, vertex displacement) — the dead-end. Reuse the multi-stage shader-program loading infra in `pipeline.cc`/`shader.cc` only if a later stage needs it.

## Components

### 1. Source-volume cache (NEW)
`model_handle → VoxelVolume` (intact hull occupancy), lazily built once per model and shared across instances (immutable):
- If the ship's `*_vox.nif` exists → `from_nif_voxel_data` (exact BC volume).
- Else → `voxelize(hull_model)` (mod-ship fallback).
Lives in the voxel module or scenegraph; keyed by `ModelHandle`. Built on first damage to a model (or at spawn).

### 2. Carve field (NEW, scavenged shape)
`scenegraph/hull_carve.{h,cc}` — adapt `HullCraterField`: a fixed 24-slot, body-frame **sphere** field (`center_body`, `radius`; drop `depth`). Keep merge-within-`kMergeFactor·radius`, evict-smallest/oldest, never-serialized. Stored per-instance on `Instance` (alongside `decals`). The retargeted `hull_craters_test` covers add/merge/evict.

### 3. Carve trigger (scavenged, retargeted)
In `hit_feedback.py` `dispatch()`, in the same gated block that adds a scorch decal: when `absorbed_hull > 0`, the ship is damage-eligible (`deform_eligibility`), and the Hull-breaches toggle is on, call:
`host.hull_carve_add(instance_id, world_point, world_normal, radius, time)`
- `radius` from the damage→carve-radius mapping (retargeted `hull_deformation.py`).
- Throttled per (ship, …) like decals to avoid beam saturation.
- The host binding transforms world→body (model units), like `damage_decal_add`, and calls `instance.carve.add(center_body, radius)`.

### 4. Hole clip (NEW, in the hull shader)
`opaque.frag` (and `skinned.frag`) gain a carve-sphere uniform array (`center_body.xyz`, `radius`) + count, gated by a `u_hull_damage` uniform. Loop (≤24, mirroring the decal loop) over the fragment's existing `p_body` varying; if `p_body` is inside any active sphere, `discard`. Toggle off / count 0 ⇒ zero behavioral change (stock path byte-identical).

### 5. Breach pass (NEW)
`renderer/breach_pass.{h,cc}` + shaders, invoked in `frame()` after the opaque pass (hologram-pass pattern: look up instance → model → source volume). For each instance with an active carve field, for each carve sphere, instance-draw the source volume's **solid voxels within that sphere** as small cubes centered at `origin + (i+0.5)·cell` (body frame), scaled to `cell`, transformed by `instance.world`. Depth-tested (so they render *behind* the surrounding hull and are visible only through the hole). Color = the BC multicolor speckle: a per-voxel-index hash → color (or sampled `Damage.tga`). MVP draws all solid voxels inside each (small) sphere; deep-interior culling is a 2b perf concern.

### 6. Scorch ring (REUSE)
No new system — the same hit already emits a damage decal via the existing path. Carve-causing hits pass a slightly larger decal radius so soot frames the breach. Near-zero new code.

### 7. Config toggle (scavenged)
Modern-VFX **"Hull breaches"** toggle, full stack (`configuration_panel.py` + `configuration_panel.js` + `renderer.py` `set_hull_damage_enabled` + `host_bindings.cc` + `dauntless_hull_damage::g_enabled` in `frame.cc`). Default on. **Off ⇒ no emission, no clip, no breach pass — stock path byte-identical.**

## Data flow

```
combat hit → hit_feedback.dispatch()
   └─ if eligible && absorbed_hull>0 && toggle on:
        host.hull_carve_add(iid, world_pt, world_normal, radius, time)
           → instance.carve.add(center_body, radius)          [+ existing scorch decal]

frame():
   opaque pass  → hull shader discards fragments inside carve spheres   (see-through holes)
   breach pass  → splat source-volume solid voxels inside carve spheres (classic guts)

spawn / mission load → ensure source volume cached (decode _vox.nif, else voxelize)
mission swap          → reset per-instance carve fields (scavenged)
```

## Frame alignment

The decoded volume's coordinates already match the hull NIF vertex frame (the foundation's `voxel_inspect` confirmed vox-AABB ≈ hull-AABB directly, same units). So the **source volume, hull mesh, carve spheres, and the shader's `p_body` all live in one body-frame model-unit space**; the carve binding does world→body exactly like the decal binding (dividing out instance scale). The test plan includes an explicit alignment check: carve a known body-frame point and confirm the hole + guts land there.

## Testing

- **C++ (gtest):** carve-field add/merge/evict (retargeted `hull_craters_test`); source-volume cache (decode-path vs voxelize fallback, on a stock ship and a synthetic no-`_vox` model); breach-pass instance build (GL-skip pattern, like other renderer tests); `gl_caps` (scavenged).
- **Python:** carve emission gating/throttle/eligibility (retargeted scavenged tests); toggle-off ⇒ no `hull_carve_add`.
- **Manual (in-game):** carve a Galaxy, confirm a see-through hole with chunky colored guts at the impact point; toggle off ⇒ no holes.

## Risks

- **Source-volume association at spawn** — locating each ship's `*_vox.nif` (or triggering the voxelize fallback) and wiring it to the rendered instance is the main new integration seam.
- **Interior-splat cost** under many breaches — mitigated by splatting only voxels inside active carve spheres; full perf tuning is 2b.
- **Donor drift** — the scavenged plumbing predates 41 commits of main; integration pieces (`hit_feedback`, `host_bindings`, `instance`, config panel) need adaptation, not clean cherry-picks.

## Non-goals (2a)

- Torn-rim geometry / CPU remesh (2b).
- Modern lit interior + classic↔modern toggle (2b).
- Debris ejection, cooling embers (2c).
- Save/serialize of carve state (runtime VFX only, never serialized — same as decals/craters).
- Any change to the stock render path when the toggle is off.

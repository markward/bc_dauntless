# Hull Breach Renderer 2a — Manual Verification

**Branch:** `feat/hull-breach-renderer-2a`
**Date:** 2026-06-17

## Automated status (all green)

- **Native:** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build` → **377/377 passed** (2 pre-existing skip/disabled, unrelated). Includes the GL-context tests for the carve clip (`HullClipTest`) and the breach pass (`BreachPassGLTest`) which do real offscreen render + pixel readback.
- **Python:** `bash scripts/run_tests.sh` → **3223 passed, 3 skipped**, peak RSS 435 MB.
- GL context is **4.1** (`GlCaps.ReportsTessellationUnderTestContext` passes live).

## What 2a delivers

On a weapon hit heavy enough to carve (`absorbed_hull ≥ MIN_CARVE_HULL`, eligible ship, throttled, "Hull breaches" toggle on): a see-through hole appears in the hull at the impact point, with the authentic BC chunky multicolored voxel "guts" visible behind it, framed by the existing scorch decal. Off-toggle ⇒ stock render path, byte-identical.

## Manual in-game check (Mark drives — no synthetic input / capture)

Run `./build/dauntless`, load a combat mission, and damage a ship (the Galaxy is the best subject — it has a real `Galaxy_vox.nif`). Confirm:

1. **See-through hole:** a heavy hit (torpedo / sustained fire) opens a hole in the hull at the impact location — the silhouette is genuinely breached, not just darkened.
2. **Classic guts:** chunky multicolored voxel cubes are visible *through* the hole (BC's authentic interior splat), occluded correctly by the surrounding intact hull (you only see them through the breach, not in front of the hull).
3. **Scorch framing:** the existing soot decal frames the breach.
4. **Accumulation:** repeated hits to the same area grow the breach; hits elsewhere open new ones; breaches cap at 24 per ship (no runaway).
5. **Alignment:** the hole + guts appear *at the impact point*, not offset/mirrored (this is the frame-alignment check — the carve sphere, the source volume, and the hull all share the NIF body frame, so they should coincide).
6. **Toggle:** open the config panel → Modern VFX → toggle **"Hull breaches"** off ⇒ holes and guts disappear (ship renders stock); back on ⇒ they return on subsequent hits.
7. **Mod ship (optional):** a ship without a `*_vox.nif` should still carve (voxelizer fallback), at a coarser default grid.

## Known 2a limitations (deferred — not bugs)

- **No torn-rim geometry** and **no modern lit interior** — the breach edge is the raw clipped fragment boundary, and the interior is the flat classic-voxel splat. Both are **2b**.
- **Interior is classic-only** — the classic↔modern toggle is **2b**.
- **No debris ejection / cooling embers** — **2c**.
- **Voxelizer fallback grid is a default resolution** (mod ships); BC-matched per-ship resolution tuning is a later refinement.
- Breach guts cube **size/density** is scaled exactly to the voxel `cell`; if it reads too blocky or too sparse in practice, that's a feel-tuning knob, not a correctness issue.

## Observations (2026-06-17, in-game on a Galaxy)

**Correctness: PASS.** Heavy hits open a real see-through breach — the hole cuts
clean through the hull to the starfield behind, with the classic colored-voxel
guts recessed *inside* the cavity at the impact point. Fragment clip + breach
pass + depth ordering all confirmed working live; guts are occluded by intact
hull and visible only through the hole. No misalignment, no floating-in-front.

**Tuning items for 2b (feel, not bugs):**
1. **Effect is too strong** — breaches read as too large / too readily formed.
   Tone down for a more restrained look. Knobs: `hull_carve.CARVE_RADIUS_SCALE`
   (1.5) and `MIN_CARVE_RADIUS_GU` (0.25) → smaller holes; `MIN_CARVE_HULL`
   (40.0) → carve less readily; `HullCarveField` merge/accumulation cadence.
2. **Interior colors are candy-rainbow** — the placeholder seed→color hash in
   `breach.frag` is far more saturated than BC's muted speckle. Retune toward
   the authentic darker/muted palette (or drive from `Damage.tga`).
3. (Already-known 2b scope: torn-rim geometry, modern lit interior,
   classic↔modern toggle.)

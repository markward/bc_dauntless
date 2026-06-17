# Hull Breach Renderer 2b (Dual-Contouring Interior) — Manual Verification

**Branch:** `feat/hull-breach-2b`
**Date:** 2026-06-17

## Automated status (all green)
- **Native:** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build` → **388/388 passed** (skipped/disabled: `OfficerClipLoad`, `SkinnedBridgeTest.DumpPosedOfficerPNG`, and `PlaneIndex.GalaxyAnchors` — the latter is the *deferred* bytes2 head-tree gate, see below).
- **Python:** `bash scripts/run_tests.sh` → **3225 passed, 3 skipped**, peak RSS 435 MB.
- The DC extractor reproduces the Galaxy hull as sharp flat panels (dihedral median 6.8°, 45% of edges <5°; verified `/tmp/galaxy_dc.obj`).

## What 2b delivers
Breaches now reveal a **real dual-contouring interior surface** carved from BC's own voxel data — sharp flat-panel hull cross-sections (not see-through to stars, not a flat candy-cube splat), textured with triplanar `Damage.tga`, muted, rendered double-sided through the 2a clip holes. Carve size/threshold toned down per 2a feedback. Built via **Path B** (our own DC from the decoded fill + plane palette); the `bytes2` head-tree descent was found unnecessary and deferred.

## Manual in-game check (Mark drives — no synthetic input / capture)
Run `./build/dauntless`, combat mission, damage a **Galaxy** (has a real `_vox.nif` → full plane palette). Confirm:
1. **Solid interior, no see-through.** A breach reveals a solid hull cross-section, NOT stars through the far side.
2. **Sharp facets.** The interior reads as flat panels with crisp edges (the dual-contouring + palette result), not a rounded blob and not flat colored cubes.
3. **Texture.** The interior is `Damage.tga`-toned, muted (not candy-rainbow).
4. **Toned down.** Breaches are smaller / form less readily than 2a (radius scale 1.5→1.0, threshold 40→60).
5. **Through-and-through.** A heavy enough hit that carves both walls should still show through (that's correct — a real breach all the way through).
6. **Toggle.** Config → Modern VFX → "Hull breaches" off ⇒ stock; on ⇒ breaches return.
7. **Perf.** No stutter during sustained fire — the DC mesh re-extracts only when the carve changes, not per frame.

## Known follow-ups (deferred — non-blocking)
From the Task 6 review (all bounded, none affect correctness/in-frame perf):
1. **`SourceVolumeCache` loads the `_vox.nif` twice** (`get_for_hull` + `planes_for_hull` each parse it). One-time per-hull startup cost; refactor to decode `SurfaceData` once and populate both caches.
2. **`breach.frag` recomputes `inverse(u_view)` per-fragment** for the camera position — pass it as a `uniform vec3` instead (gratuitous per-pixel cost; negligible at DC mesh poly counts).
3. **`glActiveTexture(GL_TEXTURE0)` not restored** in the breach pass teardown (low risk — GL_TEXTURE0 is default and other passes bind explicitly).
4. **Stale shutdown comment** in `host_bindings.cc` ("releases cube VAO/VBO" — the cube splat is gone).
5. **Breach-mesh cache keyed by instance address** with no eviction — bounded harmless leak; a one-frame wrong-mesh is possible only in a near-impossible slot-recycle + seq-collision sequence (analyzed acceptable). Switch to an `InstanceId` key if `for_each_visible_in_pass` ever exposes it.

## Deferred feature (not a bug)
- **`bytes2` head-tree descent** (exact byte-faithful cell→plane reads of the 84 originals) + the **`_vox` writer** (regenerating volumes for mod ships) — both deferred. 2b uses Path B (own extraction), which serves stock ships fully and degrades gracefully for mod ships (empty palette → smoother gradient surface, still solid). WIP for the head-tree is committed with its anchor test DISABLED; notes in `bytes2-tree-descent-notes.md`.

## Observations
_(Record the in-game result here — screenshots, sharpness vs the stock BC reference, any artifacts at the neck junction (10 non-manifold edges noted in extraction), and final feel of the toned-down size.)_

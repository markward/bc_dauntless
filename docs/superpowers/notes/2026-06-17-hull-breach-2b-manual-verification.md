# Hull Breach Renderer 2b (Dual-Contouring Interior) — Manual Verification

**Branch:** `feat/hull-breach-2b`
**Date:** 2026-06-17

## Automated status (all green)
- **Native:** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build` → **388/388 passed** (skipped/disabled: `OfficerClipLoad`, `SkinnedBridgeTest.DumpPosedOfficerPNG`, and `PlaneIndex.GalaxyAnchors` — the latter is the *deferred* bytes2 head-tree gate, see below).
- **Python:** `bash scripts/run_tests.sh` → **3225 passed, 3 skipped**, peak RSS 435 MB.
- The DC extractor reproduces the Galaxy hull as sharp flat panels (dihedral median 6.8°, 45% of edges <5°; verified `/tmp/galaxy_dc.obj`).

## What 2b delivers (Path C — final, replaces the dual-contouring approach)
**Reframed mid-implementation after in-game verification.** Dual-contouring the carved volume's OUTER surface (Path B) could never align with the hull — the coarse 15-GU voxelization is fatter than the hull mesh, so the cavity poked out and clipping the hull by the fill eroded thin features. BC instead cut a hole and rendered the **inside of the volume exposed within the damage radius**. The shipped model (Path C):
- **Hull hole** = pure damage-sphere fragment clip in `opaque.frag` (discard hull fragments inside any active carve sphere). No fill sampling on the hull.
- **Interior scoop** = `breach_pass` renders a unit sphere per active carve, **front-face-culled** (recessed inner wall, can't poke out), masked by the ship's **static original voxel fill** (GL_R8 3D texture from `CarveFieldCache`): `discard` where `fill < iso` → genuine see-through where there's no ship material. Triplanar `Damage.tga` (`kTexScale = 1/40`, texture-dominant blend) reads as scorched structural guts.
- Hole and scoop are the SAME sphere in the SAME `inst.world` frame → aligned by construction. The fill is a material mask, not a surface.
- The `voxel::dual_contour` library stays (tested) but is unused by the render path.

## Manual in-game check (Mark drives — no synthetic input / capture) — ✅ CONFIRMED
Run `./build/dauntless`, combat mission, damage a **Galaxy**. All confirmed in-game:
1. **Aligned hole + interior.** The scoop sits in the hole (same sphere); no "see straight through the ship near the damage" gap. ✅
2. **No erosion / no frosting.** Only the impact region is cut; thin features (struts, saucer rim) intact. ✅
3. **No poke-out.** Recessed inner wall (front-face cull) stays inside the hull. ✅
4. **Through-and-through.** A deep enough hit shows stars through (fill mask discards where no material) — correct breach. ✅
5. **Texture reads.** Triplanar `Damage.tga` reads as scorched structural guts after the `kTexScale` 1/4→1/40 + blend fix (1/4 tiled ~12-50× across a breach → minified to flat mush). ✅
6. **Toned down.** Breaches smaller / form less readily than 2a (radius scale 1.0, threshold 60). ✅
7. **Toggle.** Config → Modern VFX → "Hull breaches" off ⇒ stock; on ⇒ breaches. ✅
8. **Perf.** No stutter — the scoop is just spheres rebuilt from carve slots; the fill texture is static per hull (no per-frame extraction). ✅

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

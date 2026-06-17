# Hull Breach Renderer 2c (Debris + Venting + Cooling Rim) — Manual Verification

**Branch:** `feat/hull-breach-2c`
**Date:** 2026-06-17
**Spec:** `docs/superpowers/specs/2026-06-17-hull-breach-2c-debris-venting-design.md`
**Plan:** `docs/superpowers/plans/2026-06-17-hull-breach-2c-debris-venting.md`

## Automated status
- **Native:** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build` → **411/411 passed** (2 disabled + 1 skipped, same as the pre-2c baseline). `build/dauntless` links.
- New tests: `BreachEventRing` (push/overwrite/expiry), `DebrisChunk` (sampling determinism + cap, transform motion + fade), `DebrisPass` GL (draws for a fresh event, nothing expired/toggle-off), `breach_venting` (attached instance_id, body-frame emit along breach normal, effect_age, stop_age=kVentLife, alpha taper, expiry), breach rim (hot breach brighter than cold).

## What 2c delivers (Approach A — analytic, event-driven)
A per-instance `BreachEventRing` is stamped in `hull_carve_add` (`{center_body, radius, birth_time=game_clock, seed}`), ticked each frame, expiring after `kEventLife` (3 s). Three transient, deterministic consumers read active events — all pure functions of `(birth_time, seed, age)`, no per-frame state, gated by the existing "Hull breaches" Modern VFX toggle:
1. **Debris** — `DebrisPass` draws up to `kChunkCount` (16) colored voxel-chunk cubes per event, sampled from the solid voxels the carve blew out, spraying outward + tumbling + fading over `kDebrisLife` (2.5 s).
2. **Venting** — `breach_venting` builds attached `ParticleEmitterDescriptor`s (radial-outward plasma jet from the breach, additive, tapering to 0 over `kVentLife` (2 s)), rendered by the existing `ParticlePass`.
3. **Molten rim** — a blackbody emissive on the breach scoop (`breach.frag`), hottest at breach, cooling white→orange→red→dark over `kRimLife` (3 s), concentrated near the rim (fill-iso proximity). Cooled/expired breach is byte-identical to the 2b scoop.

## Manual in-game check (Mark drives — no synthetic input / capture)
Run `./build/dauntless`, combat mission, damage a **Galaxy**. Confirm:
1. **Debris.** A breach throws off chunky colored hull fragments that spray outward, tumble, and fade out (~2.5 s). They read as this ship's material, not generic sprites.
2. **Venting.** A plasma/atmosphere jet vents outward from the fresh breach and tapers off (~2 s), then stops.
3. **Molten rim.** The freshly-cut interior glows hot at the rim and cools to dark over ~3 s, leaving the quiet 2b scoop.
4. **Settles.** After a few seconds a breach is a calm recessed scoop (2b) with no lingering debris/jet/glow.
5. **Progressive.** Re-hitting the same spot re-bursts (fresh debris + vent + glow) and deepens.
6. **Toggle.** Config → Modern VFX → "Hull breaches" off ⇒ no debris/vent/rim (and no breach at all); on ⇒ all return.
7. **Perf.** Sustained fire across many breaches shows no stutter or accumulation (events expire; debris capped per event).

## Known tuning knobs (eyeball, like the 2b texture scale)
- Lifetimes `kDebrisLife`/`kVentLife`/`kRimLife` in `scenegraph/breach_events.h`.
- `kChunkCount` (debris density) in `renderer/debris_chunks.h`; chunk speed/spin/fade in `debris_chunks.cc`.
- Rim band/gain in `breach.frag` (`kRimBand`, the `* 1.5` emissive gain).
- Venting jet direction is `normalize(center_body)` — a radial approximation of the breach surface normal (the body has no per-breach stored normal); revisit if a jet ever points visibly wrong.

## Final shipped state (after in-game tuning — supersedes the plan where they differ)
Confirmed in-game ("really close to the original"). The feature evolved during tuning:
- **Debris is billboard sprites, not 3D cubes.** The cube `DebrisPass`/`cube_mesh`/`debris_chunks`/`debris.vert,frag` were removed; debris is now a `ParticlePass` emitter (`renderer/breach_debris.cc`) — per breach: ~4 grey `square.tga` hull chunks (alpha) + ~15 bright **orange additive** `spark.tga` sparks. (Fixed a `ParticlePass` additive bug: BC effect textures are flat-white RGB + shape-in-ALPHA, so additive must be `GL_SRC_ALPHA,GL_ONE` (classic), not premultiplied-over — else sprites render as squares.)
- **Venting** is a short, fast gas-release burst (`kVentLife=0.5s`), jet along the real body-frame surface normal (now stored on `BreachEvent`/`HullCarve`), gated by the hull-damage toggle.
- **Interior** uses BC's 4-frame animated `data/Damage1..4.tga` (cycled ~8fps), not the static `Textures/Effects/Damage.tga`.
- **Breach shape**: an **oblate** cavity — full original hole width, shallow depth (`kDepthFactor=0.45`), jagged rim via azimuthal noise; hull-clip (`opaque.frag`) and scoop (`breach.vert`) share the math so they align. The scoop is **clamped to the hull surface** (vertex projection) so the fat-vox fill never pokes above the hull line.
- **Skeletal framework**: `Damage.tga`'s **alpha lattice** applied INSIDE the breach in `opaque.frag` — hull struts remain where the stencil is opaque (clustered toward the rim, open core), gaps reveal the interior. Surrounding hull untouched. Knobs: `kStrutAlpha`, `kOpenCore`, `kFrameUvScale`.
- Molten rim keyed on `u_breach_age`/`u_rim_life`, fill-iso-proximity rim weight.

Key tuning constants live in `breach.vert`/`opaque.frag` (KEEP IN SYNC: `kDepthFactor`, `kShapeAmp/Freq`, `kPhase`), `breach_events.h` (lifetimes), `breach_debris.cc` (counts/speeds/colours), `breach_pass.cc` (`kDamageAnimFps`, `kTexScale`).

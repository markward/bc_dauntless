# Rock fields — design (modern asteroids, rethink of sub-project 3b)

**Date:** 2026-10-02
**Status:** design approved in conversation (sections 1–4); awaiting written-spec review
**Branch:** `feat/rock-fields` (worktree `.claude/worktrees/rock-fields`), forked from
`feat/far-tier` at `cfae60c9`. far-tier is NOT merged; both land together once rock
fields are live-verified.
**Supersedes:** the tile-field parts of `2026-10-01-far-tier-design.md` (tile haze sphere
as the field's look, the 405-minor tile clouds, the procedural belt speck/impostor
generator, the full-resolution haze). Everything else in that spec stands.
**Roadmap:** `2026-09-30-modern-asteroids-roadmap.md` (3b, 4).

## Why a rethink

Live testing of far-tier (Mark, 2026-10-02) showed:

- The tile haze reads as "a grey ball" whatever the dials do; as you approach, it never
  becomes **discernible groups of rocks** — the haze clumps and the real rocks were two
  unrelated representations (noise vs 405 uniformly scattered small minors).
- **Performance was awful** in the Beol 4 preview. The prime suspect is the full-screen,
  full-resolution haze march (48 steps × 3-octave noise per pixel). GPU timing is dead on
  this Mac, so this is reasoned, not measured.
- The haze itself, once brightness-calibrated on the displayed value, **works from a long
  distance**.
- Eventually **very large areas** will be rock fields (the radial profile's `asteroids`
  column), so the design must stay convincing and bounded in cost at any scale.

## What BC does (evidence)

- **RE (clean-room spec `stbc_reference/spec/AsteroidField.md`, RE tier):** `AsteroidField`
  is a *procedural, tiled* object that **spawns and despawns asteroid tiles around ships
  that enter the field** (ship enter/exit handlers; a pool of asteroid objects and a pool of
  tiles). Defaults: outer radius 400, **tile size 10.0**, 3 asteroids per tile. A save
  stores parameters and tile membership, not geometry. The constructor, `Update` and the
  per-tile spawn/draw cores are unreconstructed (SEH/FPU walls).
- **TESTED-ish (BCMM footage, a tweaked STBC.exe; Mark):** inside a field there are large
  rocks around the ship; there is **next to no effort to render a field from far away**.
  Caveat: the E2M1 footage also contains E2M1's 16 mission rocks (`E2M1.py:445-485`,
  4–24 GU, within 180 GU of (564, 683, 897)); the field's own contribution was not isolated.
- **SDK fields:** Beol 4 (r 1000, 3 tiles/axis, 15/tile, size factor 7), Vesuvi 1 (r 100,
  3, 2, 10), Nepenthe 1 (r 114.29, 2, 3, 7), Multi7 ×3 (r 500, 3, 2, 10); Multi1/Multi6
  commented out.
- The **far view is therefore a deliberate Dauntless addition**, as are all densities
  below (Mark's live choices, not BC's).

## Decisions (Mark, 2026-10-02)

| # | Decision |
|---|---|
| R1 | One density field per source (profile belt disc, BC tile-field sphere, later rings) drives **every** distance, so a clump seen far away contains rocks when reached. |
| R2 | Keep the haze for long distance. Between haze and the ship: **tiles showing collections of rocks of various sizes**. |
| R3 | Near band: **small rocks** as meshes 0–20 GU, billboards 20–30 GU; **large rocks** about 1 per 20 GU (one per 20³ GU³ at full density), meshes 0–50 GU, billboards 50–60 GU. |
| R4 | Mid band: **baked "rock collection" sprites**, one per tile, not individual rocks (option A). |
| R5 | Large near rocks **collide and damage**, **collision only** (cheaper than real rock objects): not targetable, shootable or breakable. |
| R6 | New branch from far-tier; this spec written here, plan and execution in a new session. |

## Design

### 1. Structure

**Sources.** The far-tier `DiscSource` primitive stays: the profile belt (disc in the
system XY plane), BC tile fields (view-space spheres) and, later, rings. Each source
carries the clumpy noise (`noise_scale_gu`, `noise_contrast` ≤ 1, `noise_octaves`) in its
own frame, so every band samples the same `density(x) = a(x) · m(x)` (noise multiplies
rock density, not `a`, as far-tier established). Everything is generated
deterministically in **system coordinates** (the far-tier cell generator), so a place
looks the same when you return.

**Four bands**, all streamed and binned per drawn camera:

| Band | Range (dials) | Representation | Physics |
|---|---|---|---|
| Near: small rocks | meshes 0–20 GU, billboards 20–30 GU | catalogue fragment meshes, then lit impostor billboards | harmless shove (minors' response) |
| Near: large rocks | meshes 0–50 GU, billboards 50–60 GU | catalogue major meshes, then lit impostor billboards | **collide and damage** (native swept test) |
| Mid: rock collections | fade in ~80–150 GU, nested levels out to the haze hand-off | one baked collection sprite per tile | none |
| Far: haze | from the haze start distance outward | far-tier haze, **reduced resolution** | none |

One tier per rock per camera; no double drawing at any boundary (§2, §3).

**Kept from far-tier:** density sources and parser keys; the cell generator core; the
mission-rock / real-major ladder (mesh → impostor → speck); `opaque.frag` dither and
cutout; impostor pass; speck pass (for real majors); brightness-calibrated haze and its
displayed-value tests; dial UX (`dev_dial_groups` short lines, framed lists); preview
missions; halos and breakup debris minors.

**Removed:** the tile fields' 405-minor clouds (replaced by the near band); the
procedural belt speck/impostor generator (replaced by near billboards and mid tiles);
the full-resolution haze path.

### 2. Near band and collisions

**Streaming around the player ship** (collision needs the sim position). Every drawn
camera renders what is streamed; a viewscreen zoom camera far from the player sees mid
tiles and haze.

- Cells in system coordinates: **10 GU** for small rocks (BC's own default tile size),
  **20 GU** for large. A cell's contents are a pure function of (source seed, class,
  cell index), counted (Poisson) from `density(x)` and accepted per candidate against it.
- Generate on entering range, drop on leaving. Bounded: a few hundred cells.

**Populations at full density** (`a` = 1, e.g. inside a tile field; all dials):

| Class | Count | Radius | In range at full density |
|---|---|---|---|
| Small | ~8 per 10³ GU³ | 0.05–0.5 GU, power law (mostly small) | ~270 meshes + ~600 billboards |
| Large | 1 per 20³ GU³ | 1–5 GU, power law (mostly near 1) | ~65 meshes + ~50 billboards |

A belt at Vesuvi's 0.05 floor gets 5% of this.

**Rendering (reuse).** Meshes via the minors' instanced draw (`MinorPass`, catalogue
fragments for small, majors for large; lod0/lod1 by pixel size; slow cosmetic tumble).
Billboards via the far-tier impostor draw (16 baked views, lit through `opaque.frag`).
Mesh → billboard via the existing screen-door dither; the outer 30 GU / 60 GU edges
**dither in**, so rocks arrive softly.

**Collisions.** Large rocks: solid, fixed, **player only**, using the minors' exact swept
contact (ship box vs rock sphere; no tunnelling below the teleport guard). Native reports
`{point, normal, rel_speed, rock_radius}`; Python applies the existing ship-vs-static
response: shields up → bounce at the shield bubble with a shield hit and shield damage
(as rocks already do); shields down → hull hit, scuff decal, damage scaled by speed and
rock size. Small rocks: harmless shove + puff + grit + cosmetic flicker (today's minors).
While dashing or in the warp set: rocks stream, no collision responses.

**Known limitations (recorded, cheap to lift later):** NPC ships and weapons pass through
scenery rocks; AI does not avoid them; they cannot be targeted, scanned or broken.

### 3. Mid tiles and baking

**Nested tile levels** (cubes fixed in system coordinates; boundaries crossfade):

| Level | Tile | Distance | A sprite stands for |
|---|---|---|---|
| L0 | 150 GU | ~80–600 GU | a small collection |
| L1 | 600 GU | ~600–2,400 GU | a large collection |
| L2 | 2,400 GU | ~2,400 GU to the haze hand-off (default ~8,000 GU) | a cluster |

About 2,000–4,000 sprites in view whatever the source's size.

**Which tiles draw.** `density × noise` at the tile centre sets the chance the tile
shows a sprite, its variant (sparse / medium / dense) and its scale; the choice is a hash
of the tile index (no flicker). Busy regions fill with dense sprites; voids show none.

**Sprites.** The offline rock-catalogue tool gains a **collections** output: ~16
collections × 3 density variants, each a randomised 3D arrangement of 20–60 catalogue
rocks of mixed sizes, baked like today's rock impostors (albedo + normal + coverage, 16
views), committed with a drift test. Drawn through the existing impostor path with a
random fixed orientation per tile, lit by the same `opaque.frag`.

**Haze hand-off.** The haze **starts at a distance** (ramping in over the L2 fade-out
band) instead of at the camera, so near and mid own the look up close. The haze moves to
**quarter resolution with a depth-aware upsample** (the system nebula's machinery) — the
main performance fix. Its noise is the same field, so far clumps line up with mid tiles.

### 4. Dials, tests, performance

**Dials.** The "far" group becomes **"rock fields"**, look dials first: near densities,
sizes and the 20/30/50/60 ranges; mid level distances, tile fill and sprite scale; haze
gain, brightness, noise and start distance; collision response scale. Live only, not
persisted. Clamp `noise_contrast` to [0, 1] (above 1 the mean drifts — far-tier review).

**Dev missions.** Keep "Far Tier: Beol 4 field" (outside view) and "Far Tier: Vesuvi
belt"; add **"Rock Fields: inside Beol 4"** (start inside the field for near-band
density and collisions).

**Performance.** CPU via the frame profiler, new scopes `rock.near.stream`,
`rock.near.draw`, `rock.mid.draw`, `rock.haze`; benchmarks (report-only) for streaming at
100,000 GU/s and for a vast belt. GPU unmeasurable here — hence quarter-res haze and hard
instance caps in every band.

**Tests** (everything under `scripts/check_tests.sh`, exit 0):
- near cells and mid tiles deterministic; density follows `a · m`
- one tier per rock per camera, boundaries at 20/30/50/60 GU, dither fades
- collisions: swept hit at dash speed, shield bounce vs hull hit, damage scales with
  speed and size, none while dashing / in the warp set
- mid level crossfades; no double drawing at near/mid or at the haze start
- displayed-value tests through the real host: field visible from outside, rocks visible
  from inside
- collection-bake drift test

**Far-tier review follow-ups folded in:** clamp noise contrast; hash the noise seed once
per octave (32 → 15 hashes, identical values, both twins); restore the CLAUDE.md row's
pointer to sub-project 4's `explicit_regions`.

## Out of scope

- Scenery rocks that can be shot, broken, or collide with NPCs and weapons.
- Planetary rings (the primitive supports them; Tevron 2's ring in BCMM footage is BCMM
  content, not stock — stock `IcePlanet.NIF` is a single sphere mesh).
- Sub-project 4's rare real majors and `explicit_regions`.

## Risks

- **GPU cost unmeasurable** on this Mac; quarter-res haze and instance caps bound it.
- **Collection sprites are not the exact rocks** you meet up close; density continuity is
  the promise, not rock identity, at 80 GU+.
- **Collision-only rocks** can feel odd when NPCs or torpedoes pass through them.
- **Densities are taste**: expect live tuning rounds.

## Live check (Mark)

`./build/dauntless --developer` from the worktree, Developer missions:
- Beol 4 field from outside: haze far, collection tiles as you close in, large rocks then
  gravel; no pops at 150/60/30 GU.
- Inside Beol 4: density, collisions (shields up and down), dash through.
- Vesuvi belt: the same ladder at belt scale (sparse at the 0.05 floor).
- Profiler `rock.*` scopes; frame rate acceptable.

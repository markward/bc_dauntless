# Rock fields — design (modern asteroids, rethink of sub-project 3b)

**Date:** 2026-10-02
**Status:** implemented on `feat/rock-fields` (Tasks 1–14 complete, local `check_tests.sh`
green), **awaiting Mark's live check** — see "Live check" below and the "As built"
section for what changed from this design during execution.
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
Billboards via the far-tier impostor draw (64 baked views on an 8x8 octahedral grid,
blended 3 at a time so a tumble is a smooth closed loop -- rock-blend 2026-10-03; lit
through `opaque.frag`).
Mesh → billboard via the existing screen-door dither; the outer 30 GU / 60 GU edges
**fade in translucent** (alpha-blended, rock fade 2026-10-03 — originally a dither-in),
so rocks arrive softly.

**Collisions.** Large rocks: solid, fixed, **player only**, using the minors' exact swept
contact (ship box vs rock sphere; no tunnelling below the teleport guard). Native reports
`{point, normal, rel_speed, rock_radius}`; Python applies the existing ship-vs-static
response: shields up → bounce at the shield bubble with a shield hit and shield damage
(as rocks already do); shields down → hull hit, scuff decal, damage scaled by speed and
rock size. Small rocks: harmless shove + puff + grit + cosmetic flicker (today's minors).
While dashing or in the warp set: rocks stream, no collision responses.

**Known limitations (recorded, cheap to lift later):** NPC ships and weapons pass through
scenery rocks; AI does not avoid them; they cannot be targeted, scanned or broken; the
headless sim never spawns scenery rocks at all (near/mid/haze are render-only, so a
headless mission sees none of this); a contact only responds while the player's
containing set IS the viewed set (a player seen from another region's camera gets no
scenery collisions); and the "Rock Fields" dev toggle (Dev Options → Lighting, native
key `far_tier`) also disables scenery collisions, because it gates the same native
stream that both draws the near band and drains its contacts.

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

## As built

Execution (`.superpowers/sdd/2026-10-02-rock-fields/progress.md`, Tasks 1–14) made a
handful of rulings that change this design's letter without changing its intent:

- **Cluster snap (Task 14).** §3 describes a tile grid picking its own sprite at the
  tile centre. A `DiscSource`/sphere source smaller than its tile's own size (e.g. a
  small `AsteroidField`) would otherwise never register at the tile-centre sample and
  read as empty. `MidField` now **snaps**: a source with diameter < the tile size
  replaces that tile's centre-density sprite with one sitting at the source's own
  centre (jitter scaled to the source radius, not the tile) — one sprite, not two.
  Belts are unaffected (they are large relative to a tile).
- **Haze march clipping (Task 12).** The haze's ray march now early-outs when `t1 <=
  start` and clips `t0 = max(t0, start)`, so the fixed step budget lands inside the
  ramp where the haze actually exists, rather than spending steps on the dead zone
  before `haze_start_gu`. `start = 0` (no hand-off) stays bit-identical to the
  un-clipped form.
- **Displayed-metric changes (Task 14).** The spec's single "haze visible from
  outside" bar is now two assertions at two distances, because the mid band — not
  the haze — carries the 3,000–8,000 GU range: a changed-pixel-share bar at 6,000 GU
  (mid sprites) and a separate centre-mean bar at 8,000 GU (haze, unchanged
  calibration). The Beol 4 "Player Start" viewpoint (2,079 GU) is now owned by mid
  tiles, not haze.
- **2×2-pixel dither (Task 14).** `opaque.frag`'s screen-door dither moved from
  per-pixel to per **2×2 pixel group**, fixing a bug where half of a discarded quad
  could still shade up to 159/255 wrong. The visible pattern is a coarser 8 px
  screen-door than before — accepted; filed as a trade for correctness, not reverted.
- **Mid sprite count vs the spec's estimate.** §3 estimated "2,000–4,000 sprites in
  view"; at the shipped default tile sizes the real number is **~150**. The 4,000 cap
  is kept (headroom for denser dial settings) but the typical scene is far sparser
  than the design's prose suggested — tunable live via `mid_fill` / `mid_sprite_scale`
  without a rebuild.
- **Final whole-branch review fixes.** (1) The near band has its **own** contact player
  (`rockfield_set_player`, pushed every frame by `far_tier.reconcile`, None when
  scope-hidden) instead of borrowing the minors' player — disabling Minor Rocks used to
  silently stop scenery collisions and stream the band around the camera. (2) A large
  rock that still penetrates the contact box at the current pose (`pen > 0`) reports
  **every step**, cooldown or not; `collide_cooldown_s` only silences repeats once the
  ship is clear, and Python's receding gate is the debounce (as `_respond_pair`).
  (3) The mid band's near-band guard, level weight and dither use the **drawn sprite's**
  distance (after jitter), so no sprite sits nearer than `mid_in_lo_gu`; selection is
  still keyed by the tile. (4) Small-rock shoves use the bare hull box — only large
  contacts inflate to the shield bubble.
- **Rock fade: alpha instead of the screen door for distant impostors (2026-10-03).**
  Mark, live inside Beol 4: distant asteroids showed a checkerboard dot grid — in a
  dense field many impostors are always mid-fade, and the 8 px screen door reads as a
  grid over black space. Now every mid-sprite fade (L0 in, the level crossfades, L2
  out) and the near billboards' OUTER fade at `billboard_gu` draw **translucent**
  (`NearOutput::billboards_fading`, `MidOutput::sprites_fading`;
  `FarPass::render_impostors_blended`, profiler scope `rock.fade.draw`, in phase 2
  straight after `rock.haze`, into the resolved target: depth-tested, no depth writes,
  premultiplied, no MSAA — before the haze, the haze marched through the depth a
  fading rock never writes, fogged it and popped when it turned solid). Alpha is the coverage
  the item's signed dither would have kept (`far::impostor_fade_alpha`), so every
  item is byte-identical to before — only which list it is in changed. The screen
  door stays ONLY where two representations overlap and must complement: the near
  mesh ↔ billboard hand-off and the far tier's flagged-rock mesh ↔ impostor ladder.
  Order: mid fading before near fading; mid bins by fade band farthest first, then
  atlas; near bins by class (larger `billboard_gu` first), then rock; items farthest
  first. Two overlapping fading sprites of DIFFERENT bins in the SAME band can blend
  in the wrong order (both alpha < 1, similar grey: accepted). Cost: the band split
  roughly doubles mid draw calls (Beol 4 inside: 18 → 34 bins, ~4.5 µs CPU each).
  **Live check:** where an L_n sprite (alpha 1 − x) and an L_n+1 sprite (alpha x)
  overlap mid-crossfade, "over" covers 1 − x(1 − x) — a 25% coverage dip at the
  midpoint (the screen door's complementary patterns had none); watch for a darker
  ring at 450–600 / 1,800–2,400 GU.
- **Filmic CA fringing left unchanged.** `filmic.frag`'s chromatic-aberration pass
  fringes the dither pattern on near/far mesh↔impostor edges. Investigated and left
  out of scope for this plan; reported for Mark's live check, not fixed here.
- **Look retune (Mark, live 2026-10-03): fewer big asteroids, visible a bit
  further; slightly more small rocks, as billboards closer in.** Supersedes the
  20/30/50/60 GU boundaries and the mid L0 "~80–150 GU" fade-in quoted above:
  `near_small_density` 0.008 → 0.010, `near_small_mesh_gu` 20 → 15 (billboards
  start closer in); `near_large_density` 1.25e-4 → 6.25e-5, `near_large_mesh_gu`
  50 → 60, `near_large_billboard_gu` 60 → 90 (fewer, but visible further);
  `mid_in_lo_gu` 80 → 100 and `mid_in_hi_gu` 150 → 170 (keeps mid sprites outside
  the widened near large billboard range). `engine/rocks/far_dials.py` DEFAULTS
  (mirrored in `rock_near.h` / `rock_mid.h`) is the live source of truth for
  these dials, not the numbers above.
- **Every big-asteroid silhouette is a real rock (rock-real Part 1, 2026-10-03).**
  Mark, live: flying at a big-asteroid billboard, it faded out and nothing real
  stood behind it — it was a rock painted into a mid collection sprite. The large
  class now has a **far shell**: with `near_large_far_gu` > `near_large_billboard_gu`
  its SAME rocks (same generator, density, field) stream on past 90 GU as billboards
  (no fade at 90 any more) out to `near_large_far_gu`, fading out translucent over the
  last `near_large_far_fade_gu` (40); a large billboard (no mesh weight) at or below
  `near_large_min_px` (1.5) on screen draws nothing and fades in over the next 1 px
  (`near_large_weights`). Each rock is in exactly one representation per camera
  (mesh / mesh↔billboard hand-off / billboard / gone); a far billboard flown at
  becomes a near billboard then a mesh, by key. Large cells are now 50 GU
  (`near_large_cell_gu` 20 → 50, so 250 + margin stays under the 33-per-axis cap —
  this redefines which large rocks exist, still deterministic) and the large cap
  `near_large_max` 1000 → 4000. The step's large-cell loop has a cheap system-space
  AABB pre-cut, so the far shell costs contacts no per-rock work. **Default 250, not
  the 400 target:** Beol 4 inside bench (`NearBench.InsideBeol4`, Debug): stream +
  step + build 0.36 ms before → 0.73 ms at 250 (~425 far billboards per frame,
  ~5,500 large rocks streamed); 400 measured 1.92 ms, 300 1.01 ms. Mid sprites keep
  starting at `mid_in_lo_gu` and now overlap the far shell (boulders in front of
  gravel clouds; Part 2 removes the big rocks from the collections). Translucent
  ordering: the near list (far shell fading at 210–250 GU) draws after the mid list,
  so a far-shell rock fading out behind a mid sprite fading in at 100–170 GU blends
  in the wrong order where they overlap (both alpha < 1: accepted).
  **Review follow-ups (2026-10-03).** (1) *Dash:* the shell is visual only and
  flashed past at dash speed while being regenerated every frame. A `stream()`
  whose centre moved more than `near_far_shell_max_step_gu` (25 GU = 1,500 GU/s at
  60 Hz, 3.75× in-system warp's 6.7 GU/frame, still above it down to 16 fps)
  shrinks the large reach to `near_large_billboard_gu` (drawn by the old rule);
  slower streams regrow it by at most `near_far_shell_regrow_gu` (20) each, so it
  returns over ~8 frames, never in one hitch. `NearField::clear()` restarts with the
  whole shell (a source change mid-dash costs that one frame). `NearBench.
  StreamAt100kGups`, Debug, isolated runs: before stream mean 2.8–3.1 ms, worst
  3.3–4.1 ms (the reviewer's 3.36 / 30.1 ms were measured under the gate's load);
  after mean 0.86–0.93 ms, worst 2.7–3.0 ms — frame 0, the initial whole-shell
  stream; the regrow afterwards: 9 frames, mean ~0.41, worst 0.82–0.90 ms.
  Beol 4 build worst: 0.61–0.67 ms in six isolated runs; the reviewer's 5.5 ms was
  not reproduced (presumably machine load during the gate — not proven).
  (2) The drawn shell is clamped to the streamed reach (`large_far_gu` past the
  33-cells-per-axis cap fades out at the cap instead of cutting).
  (3) The pixel floor blends in over [`mesh_gu`, `mesh_gu` + `fade_gu`], so no
  rock pops where its mesh ends at any viewport size.

## Live check (Mark)

`./build/dauntless --developer` from the worktree, Developer missions:
- Beol 4 field from outside: haze far, collection tiles as you close in, large rocks then
  gravel; no pops at 150/60/30 GU.
- Approach to Beol 4 from 6,000 GU down to 600 GU: the small field is ONE cluster-snapped
  L2 sprite (~2,000 GU across, its rocks drawn 30–150 GU) until it crossfades into ~37 L1
  tiles. Check it reads as a clump of rocks, not a blob, and that the L2 → L1 hand-over
  does not pop.
- Inside Beol 4: density, collisions (shields up and down), dash through.
- Shields-down collision damage at the defaults: a Galaxy at full impulse into an
  r ≈ 1–1.5 GU rock loses ~16–24% hull. If that feels wrong, dial
  `collide_damage_scale` (rock fields group).
- Vesuvi belt: the same ladder at belt scale (sparse at the 0.05 floor).
- Profiler `rock.*` scopes; frame rate acceptable.

# Layered hull damage — production design

**Status:** **implemented** on `spike/damage-redesign` (phases 1–4, finished
2026-10-22; phase 4 is `2026-10-22-layered-damage-p4-finish-design.md`). Not
merged to main: that waits for Mark's live check and his word. The final
measurement against the §3 rule is a later task; final verdict: see
`docs/engine/perf-register.md` P-12. How it was built, where it departs from
this design and the backlog are in §10.

Design, 2026-10-21. Builds on the spike on `spike/damage-redesign`
(worktree `.claude/worktrees/damage-redesign`). The spike's review and the
first product sketch are in `2026-10-20-layered-hull-damage-productisation.md`;
this document supersedes its §3–§5 where they disagree.

## 1. Intent

The layered damage spike replaces BC-style "swiss cheese" voxel holes with
hull that takes a beating in layers:
- plating panels strip;
- the skeleton (ribs that follow the hull's detected parts) bends and snaps;
- the inner pressure hull dents, then tears;
- through a tear you look into decks and rooms.

Mark judged it in game "such an upgrade on the legacy approach". He now wants
three things:
- it made production quality;
- the old damage systems removed outright;
- it optimised as far as is sensible.

**Why:** the new look is better, and keeping two damage systems doubles the
code, the bugs and the frame cost. On Mark's main branch the old system also
misbehaves: one part's interior texture follows another part's rotation.

## 2. Goals

1. **One visible-damage system: the layered one.** There is no Classic/Layered
   setting.
2. **Every visible damage source feeds it:**
   - **Torpedoes** strip plating, then expose ribs, then tear through, as on
     the spike.
   - **Phasers** wear plating too, but much more slowly than torpedoes:
     sustained fire eventually strips panels (Mark).
   - **Big collisions** wear plating as well as leaving their scuff marks.
     Small bumps stay scuffs only (Mark).
   - **Internal blasts** (a destroyed subsystem) and the **death cascade**
     work as on the spike.
3. **Holes show the interior up close only.**
   - Within **20 GU of the camera that is drawing** (main view or Z zoom; the
     viewscreen feed only for its own target, §3), a hole shows the
     deck-and-room interior. Mark first
     said 10 GU; he chose 20 on 2026-10-21 once told that the chase camera
     sits about 14 GU behind the player, so 10 would almost never show
     rooms on an enemy.
   - Further out, the hull paints the hole as dark, burnt wreckage, with the
     odd fire or lit window. No marking or interior draw runs for that ship.
   - **Blown through** (past deck-break wear) is cut at any distance, so the
     ship shows what is behind it there, near or far. The look does not jump
     at the 20 GU switch. *(My call.)*
4. **Asteroids keep craters** "much as we had it" (Mark). They are rebuilt on
   the new system: the cut comes from the damage records, and a short march
   into the damage finds the crater wall. That wall is shaded with the rock's
   own texture, darker with depth, scorched at the rim. Rocks get no panels,
   ribs or rooms.
   - The crater march needs the fill volume, a 3D texture, so it runs in the
     interior pass (marked, like a ship's hole), never in `opaque.frag`.
   - Beyond 20 GU a crater is painted in place as darkened, scorched rock,
     with no cut. *(My call.)*
5. **Ships can still shed chunks.**
   - The debris pieces and the "systems inside a severed piece are destroyed"
     rule stay. This happens far less than with the carve (Mark expects and
     accepts that).
   - **A chunk is a whole detected structure part** *(my call)*: a nacelle,
     a pylon section, a saucer. Today a chunk is a copy of the whole model,
     clipped by the per-instance damage field that §6 removes. Instead:
     - **When a part is severed:** the CPU marks it so when wear past deck
       break cuts through everything that joins it to the main body. The
       connectivity check runs on the fill volume, labelled by part.
     - **The parent** stops drawing that part's fragments. A per-instance
       bitmask of severed parts is checked against `plating_part`, and no
       new sampler is added.
     - **The chunk** is a copy that draws only that part.
   - Articulated-node severance (`part_severance`) is unchanged.
6. **Damage never heals.**
   - Wear and holes live in a per-instance store, not the 24-slot scorch
     ring.
   - When the store is full, nearby records merge; nothing is evicted.
7. **Structure parts exist before the first hit.** They are detected at
   model load on a bounded worker, prefetched for the warp destination, and
   cached on disk.
8. **Damage moves with articulated parts** (LC Intrepid nacelles).
9. **Live dials move to Developer Options,** with one source of defaults.

## 3. Performance (Mark's rule)

**A damaged ship costs no more than double the same ship undamaged.** The
death throes are judged differently (Mark, 2026-10-21): no costlier than the
legacy carve's death. Indicative cross-build numbers put Layered's death at
roughly a quarter of Classic's GPU cost and well under its CPU cost
(SIG-090, SIG-098 vs SIG-110), and Mark accepted that without a same-build
re-run.
- The rule holds on both the GPU and the CPU.
- It holds at the default DP distance and at the close-up.
- It holds while alive and during the death.

How it is measured *(my call)*: at the PASS level.
- The cost is the sum of `space.opaque` and `space.hull_interior`, the
  scopes the damage adds to.
- In one DP run, compare the windows against the undamaged window before the
  blasts:
  - the damaged-but-alive window;
  - the dying window.

  Same build and scene; CPU from a CPU-only run.
- **The near-interior case needs a scenario where rooms draw:** the Akira
  inside 20 GU of the camera. DP's camera sits about 14 GU behind the
  player, so the 1.5 GU close-up qualifies. Confirm the camera distance from
  a screenshot.
- At pass level the spike is about 2.4x today, so optimisation is real work
  in this plan.

Measure with the DP scenario in `docs/engine/perf-register.md`:
- GPU-focus runs give attribution only.
- CPU-only runs give CPU cost.
- Record a Debug build like the existing baselines. **No Release capture**
  (Mark, 2026-10-21): Release can only be lower than Debug, so a Debug pass
  that meets the rule is enough, and a second build folder would break the
  one-build-tree rule.

Known levers, from the step-2c review (SIG-103, SIG-104):
- The marking draw runs the whole `draw_model`, an estimated 65–80% of the
  0.37–0.40 ms CPU. Give it a lean path that sets only what the plating
  discard reads.
- Cache uniform locations in `draw_model` and `draw_model_positions_only`.
- Skip the mark and the interior beyond 20 GU (goal 3).
- An eligibility cap for the near interior, as the old carve had: the player,
  the target, the nearest few.

Added with Mark on 2026-10-21:
- **Upload only the records near the drawn hull.** The store grows from 24
  to 64 records, and every near-damage pixel loops over all of them.
  - Upload per draw only the records whose reach touches the part of the
    hull being drawn.
  - Merge records more eagerly, so the shader loop stays near today's
    length.
- **A deck-break subset for the interior walk.** The walk adds up interior
  wear at every crossing (up to 24) over every record. On the CPU, pick out
  only the records that could push wear past deck break, alone or summed
  where they overlap, and give the walk that subset.
- **Build the damage list once per instance per frame,** and share it
  between the plating draw and `submit_plating_interior`. Today it is built
  twice.
- **Prefetch the fill volume.** It loads synchronously on a hull's first cut
  (`CarveFieldCache::get_for_source`). Load it at model load and for the warp
  destination, on the same bounded worker as structure parts.
- **The bridge viewscreen shows rooms for its own target only.** It renders
  the space scene a second time, small on screen.
- ~~Judge the final result in a Release build~~: dropped by Mark on
  2026-10-21 (see above).

## 4. Non-goals

- New interior content beyond the current look. Rooms, zones, contents and
  wrecked lighting stay as tuned live on 2026-10-21.
- Interior rooms on small craft at a different scale. Deck pitch stays one
  global constant.
- Persisting damage in save games. Saves do not hold carve state today
  either; do not add it.
- Gameplay changes to hull or subsystem health. This is visible damage only,
  apart from severance (goal 5), which already exists.

## 5. Anti-goals (failure even if it "works")

- **Holes that heal,** or plating that re-plates, during a fight.
- **A damaged ship that reads as a lit tower block,** or a hole showing the
  scene behind the ship where the ship is not blown through.
- **Asteroids with panels, ribs or rooms.**
- **An undamaged hull that renders differently from today's stock program.**
- **Old carve code left behind "just in case".** No dead branches, no unused
  caches, no stale CLAUDE.md rows.

## 6. What is removed

All of the following, together with their tests, dials, docs and CLAUDE.md
rows:
- **Python:** the voxel hull carve, `engine/appc/hull_carve.py` and
  `core_breach_carve.py` (the warp-core breach keeps its visual through the
  new system).
- **Carve storage:** `scenegraph` `hull_carve` and the field brush.
- **Damage volumes:** the per-instance damage field (`instance_field_cache`,
  the field atlas, the distance-field brush).
- **The old carve's draws:** the carve stencil pass, `breach_pass` and
  `breach.frag`/`breach.vert`, the Damage1-4 frame textures, and opaque.frag's
  carve clip (`hull_cut_at`, `u_carve_*`, `u_hull_field_*`).
- **Carve switches:** `DAUNTLESS_HULL_CARVING` and `host_io` carve gating.

**Kept or re-homed:**
- **The original fill volume.** The interior's "left the ship" test needs the
  hull's solid volume, which today comes through `CarveFieldCache`. Keep the
  fill under a name that says what it is.
- **Breach venting and debris.** Today they are driven by carve and breach
  events. Re-drive them from the new system's tear events: a record whose
  wear first crosses breach.
- **`hull_breakup`, `debris_chunk` and `part_severance`.** Keep them, with
  the connectivity input changed (goal 5).
- **`breach.vert`.** If the interior pass still uses it, move it under a name
  that belongs to the interior.

Before deleting, list every caller of each removed piece, and say in the plan
where each goes.

## 7. Decided how

- The hull damage store, the merge rule, its size (64 to start) and upload as
  a uniform block are as spike spec §3.1.
  - Check that a sampled store would not trip the `opaque.frag` sampler
    miscompile.
- **Wear counts damage dealt, not emit counts** *(my call on the
  conversion)*:
  - One stock photon's hull damage (500) is 1 wear, so the live-tuned look
    holds for photons.
  - Every projectile, disruptors and pulse cannons included, wears by its
    hull damage, as `clamp(damage / 500, 0.25, 1.5)` per hit (both bounds are
    dials).
  - A Klingon torpedo (1400) therefore counts as 1.5, not 2.8. Hulls still
    take several big hits before breaching, as Mark asked on 2026-10-20.
  - The per-ship emit throttle no longer drops wear. Wear is accumulated per
    hit even when the scorch emit is throttled.
- Torpedo wear stays as live-tuned (strip 0.5, rib break 2.5, breach 4.5,
  deck break 6.0, toughness spread 0.6, lumps 1.0, member survive 4.0).
- Phaser wear rate is set so a sustained beam strips a panel noticeably
  slower than a torpedo volley. The exact rate is a dial, tuned live with
  Mark.
- The collision threshold for "big": collisions that already do hull damage
  above a dial threshold also add wear; below it, scuffs only. Tuned live.
- The rock crater march is an analytic walk of the damage field from the cut
  point (no voxel field). It falls back to the fill volume to stop at the
  rock's far side.
- Interior rendering keeps the spike's architecture:
  - front-faces-only plating draw;
  - a per-hull stencil mark (values 2+k);
  - an interior draw with `GL_LESS` and polygon offset.
- Driver rules:
  - Never add a sampler to `opaque.frag`.
  - Never `return` early from its PLATING main; a single discard works.
  - Run `OpaqueDegenerateNormalTest` and `ScuffTest` after any `opaque.frag`
    edit (`HullClipTest` went with the carve; see §10).
- The work happens in this worktree's branch. Merge to main only when Mark
  says so; the gate runs then and only then.

## 8. Left to the builder

- **The 20 GU switch.** Whether it is a hard switch or a short cross-fade,
  and whether it runs per ship or per pixel.
- **The eligibility cap's size,** if one is still needed after the 20 GU cut.
- **The articulation approach.** Spike spec §3.3: parts per articulated node,
  and records in the rest frame via `u_node_rest_fix`. First reproduce Mark's
  main-branch interior-rotation report and design around its real cause.
- **Disk cache format and location** for parts (per-user data dirs,
  `report_write_failure`), keyed by content hash plus detection version.
- **Task order and split.** Removal should land after the replacement for
  each removed capability exists (rocks, venting, chunks), so the game never
  loses a feature mid-branch.

## 9. Proof

- **Render tests:**
  - undamaged hull unchanged;
  - phaser wear strips more slowly than torpedo wear;
  - a big collision wears and a small one does not;
  - a rock crater shows rock, not rooms and not space;
  - beyond 20 GU a hole paints as wreckage, with no mark or interior draw;
  - blown through, the hole is cut at any distance.
- **Store tests:**
  - merge-not-evict;
  - wear from damage dealt;
  - holes survive 200 later hits.
- **Severance test:** a pylon blown through past deck break severs its
  nacelle part. The parent stops drawing that part, the chunk draws only it,
  and the subsystems inside it are destroyed.
- **Perf:** the §3 rule, recorded in `perf-register.md`, with a P-12 verdict.
- **Docs:**
  - a CLAUDE.md row for the layered system;
  - the DamageTool, Rock class and Damage Preview rows corrected;
  - `damagetool-and-hull-damage-gaps.md` updated or retired.
- **Mark's live check** of rocks, phasers, collisions and severance.

## 10. As built, and backlog

Written 2026-10-22, after phase 4. The sections above are the design and are
left as written; where the build differs, this section wins.

**As built** (detail in the phase-4 spec and the code named):
- **Store.** `scenegraph::HullDamageStore` (`hull_damage.h`), `kCapacity` 64,
  merge never evict. Wear from damage dealt: `hull_wear.wear_for_hit` (phaser
  ticks × `PHASER_RATE`; a collision wears only when it crumples and deals at
  least `COLLISION_MIN_HULL_DAMAGE` hull). One predicate,
  `hit_feedback._structural_hit`, gates both the wear and the part-severance
  share, so light (PP_LOW) phaser fire records neither.
- **Articulated parts.** Records live in each part's REST frame with their
  node (−1 = the body); the wear bindings attribute a hit geometrically, and
  per-mesh uploads (records and rims) are filtered by the mesh's POSED OWNER.
  Rigged instances are flagged at realize (`set_instance_rigged`, via
  `host_loop._mark_rigged`).
- **Structure parts.** Detected when a model is realised or warp-preloaded
  (`prefetch_structure_parts`), cached at `<cache_dir>/structure_parts/
  <fnv1a64 of the NIF bytes>-v<kStructurePartsVersion>.sps`. Bump
  `kStructurePartsVersion` whenever detection changes. Scaled (`#s=`) NIF
  loads are prefetched eagerly like any NIF but never disk-cached; only glTF
  (catalogue rocks, which never sever) is skipped by the prefetch and
  detected lazily, also never cached.
- **Severance.** Unrigged hulls only (`hull_breakup.after_wear`'s rig gate and
  the native `can_structure_sever`). The parent hides the lost part by its
  `plating_part` label, in the plating draw and in the part-mask shadow
  program (`shadow_parts.frag`); the chunk draws only that part, dark
  (emissive 0). Lights and emitters on the lost part go out; each light's
  part label is cached per (instance, severed mask). The check
  (`find_severed_parts`) runs on a worker (`part_severance_jobs.h`, final
  review Ruling 10): `hull_split_parts` answers None while it runs, and a
  result whose damage or severed mask moved meanwhile is dropped and
  re-queued.
- **Molten rims.** The four freshest breach events younger than `kRimLife`.
- **Warp-core breach.** Three Internal records growing at the core over
  1.0 s.
- **Dials.** One source of defaults, C++ `g_params`, read through
  `plating_param_defaults()` (Python `plating_dials.DEFAULTS` is the headless
  fallback, drift-tested). Developer Options → "Hull damage" tab, and the
  `/ L O` "plating" dial group.
- **GLSL twins.** `shadow_parts.frag`'s `plating_part` and hide rule copy
  `opaque.frag`'s (drift test `ShadowPartsShader.PlatingPartIsTheTwinOfOpaque`);
  `opaque.frag`'s `plating_rim_heat` and `hull_interior.frag`'s `rim_heat`
  are the same body with no drift test: change both.
- **§7's driver-rule tests.** `HullClipTest` is now
  `OpaqueDegenerateNormalTest` (the clip went with the carve). The
  undamaged hull is pinned by `PlatingRenderTest.UndamagedHullUnchangedByCarveRemoval`,
  a 64-bit hash of the read-back pixels.

**Backlog** (none blocks the merge):
- The `CellBox` / `DistanceField` lattice has no production consumer left.
- Duplication: the write-to-tmp-then-rename helper exists in both `dvox.cc`
  and `structure_parts_io.cc`, and `structure_parts_io.cc` spells the raw
  FNV-1a constants again, as several other `.cc` files already do, instead of
  sharing one hash helper.
- `_mark_rigged` reads the rig once, at realize: a rig authored fresh in the
  Ship Property Viewer leaves the instance unflagged (dev-only).
- The interior's posed-path rim upload has no pixel test.
- The shadow program's rest-frame fix is untested. Unreachable today
  (rigged hulls never structure-sever); it becomes Important if structure
  severance is ever allowed on rigged hulls.
- A crash between a cache write and its rename leaves a uniquely named
  `*.tmp` in the structure-parts cache root, and they accumulate. Sweep stale
  `.tmp` files when the root is set.
- Renaming over a cache file that another process has open is untested on
  Windows.
- The undamaged-hull hash is tied to this machine's GL driver; another
  driver needs a new hash (the test says how to take one).
- The undamaged reference `.bin` was deleted, but it remains in branch
  history at `d21f0188a`: a squash decision for Mark at merge.

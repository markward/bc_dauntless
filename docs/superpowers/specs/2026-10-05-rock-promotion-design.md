# Rock promotion — design (modern asteroids, sub-project 4)

**Date:** 2026-10-05
**Status:** approved in brainstorming (Mark, 2026-10-05); spec awaiting review.
**Programme:** `2026-09-30-modern-asteroids-roadmap.md`. This replaces the roadmap's
"Sub-project 4: profile seeding", whose seeding half was delivered by 3b and rock
fields (`2026-10-01-far-tier-design.md`, `2026-10-02-rock-fields-design.md`).

## Intent

Rock fields (merged 9ec834d4) already fill belts and BC tile fields with
deterministic scenery rocks that collide with and damage the player. Two things are
missing, and one thing is wrong:

- **Large rocks cannot be targeted.** A big rock is scenery only. It cannot be
  targeted, scanned or broken, and torpedoes pass through it.
- **NPCs ignore large rocks.** They fly straight through them.
- **Vesuvi's story scenes contain large rocks.** Large near-band rocks scale linearly
  with `asteroids`, with no threshold. At Vesuvi's 0.5 band (Haven: E1M1, E1M2,
  E2M0, E2M1, E2M2, E3M2; Geki: E2M1) that is about one large rock every 32 GU, and
  one every ~68 GU at the 0.05 floor across the system. Mark: large rocks contradict
  the story — "you're clearing 12 or so large rocks in an area filled with large
  rocks".

## Decisions (Mark, 2026-10-05)

| # | Decision |
|---|---|
| P1 | **Story scenes: many small rocks, no large ones.** Small rocks keep exactly today's contact (shove, puff, grit, cosmetic shield flicker; no damage). |
| P2 | **Large rocks follow the majors threshold** from the roadmap: none at `a ≤ 0.5`, full at `a = 1.0`. Vesuvi's band (exactly 0.5) then has no large rocks with no edit to Vesuvi's map. The planned 0.5 → 0.4 band edit is **dropped**. |
| P3 | **No new belts in this sub-project.** Belt authoring (an asteroids-only override, and which systems get belts) is deferred. |
| P4 | **Big rocks are targetable** above a size threshold, by **promoting** generator rocks near the player into real `RockClass` objects (approach 1). This matches how the rocks are drawn: a distance ladder around the camera. |
| P5 | **Count control: nearest N** (default 8) qualifying rocks within range. |
| P6 | **NPCs avoid large rocks, but do not collide with scenery.** Avoidance asks the native field directly, so it covers every large rock, promoted or not. Promoted rocks are real objects, so NPCs near the player collide with them through the existing collision code; no special case. |
| — | Design sections 1–3 approved as presented. |

## Facts this design rests on (checked 2026-10-05)

- **Rock identity** (`native/src/renderer/rock_near.cc:58-64`): a near rock's key is
  `mix(cell_key, index + 1)`, with `cell_key = mix(source.id, class, i, j, k)`. A cell's
  contents are a pure function of `(source seed, class, ijk)` (`:253`).
- **Per-rock data** (`rock_near.h:73-79`, `NearRock`): `pos_sys` (system coordinates),
  `radius`, `rock` (catalogue index: a major for the Large class), `tumble_axis`,
  `tumble_rate`, `phase`. Render scale is `radius / bound_mu[slot]` (`rock_near.cc:846`).
- **The one per-rock exclusion** today is `in_explicit` (`rock_near.cc:40-44`, used at
  `:267`). There is no per-key exclusion and no point query; `NearField::for_each`
  (`rock_near.h:189`) is C++-only.
- **Density is applied per class** in `generate_near_cell` (`rock_near.cc:240-272`):
  `n_bound = c.density · a_bound · noise_m_bound` and the acceptance test
  `accept ≥ c.density · field_density(s, p) / n_bound`. `c = class_dials(d, cls)`, so a
  Large-only factor belongs here.
- **The speck band is the same rocks:** `rock_speck.cc:289` calls
  `generate_near_cell(s, NearClass::Large, …)`. Anything that changes which large rocks
  exist changes the specks identically.
- **Large-rock density** is `near_large_density` 6.25 × 10⁻⁵ rocks/GU³ at field density
  1 (`engine/rocks/far_dials.py:62`), radii 1–5 GU, power law exponent 2.5. About 4%
  of large rocks are ≥ 4 GU, so a full-density field holds ~275 of them within 300 GU.
- **`RockClass_Create(radius_gu, *, family, seed, name, kind, hull, mass)`**
  (`engine/rocks/rock.py:136-160`) quantises the radius to 2 significant figures
  (`stats.quantise_radius`) and picks the model by `catalogue.pick(seed, …)`. It
  cannot force a specific catalogue rock. `effective_radius` = base × `GetScale()`
  (`rock.py:59-69`).
- **`far_tier.reconcile`** runs every frame (`host_loop.py:6702`) and pushes sources,
  dials, frame and the contact player. `far_tier.reset` runs on mission swap
  (`host_loop.py:6887`).
- **Rock death:** `rocks.death.begin` posts `ET_OBJECT_EXPLODING`; `advance` retires
  through `ship_death.retire`, which posts `ET_OBJECT_DESTROYED`. There is no
  rock-died callback.
- **Collision avoidance** (`engine/appc/collision_avoidance.py`) gathers obstacles
  from the set's objects (`_build_obstacle_snapshot`, `:808-845`) and reads unscaled
  `GetRadius()` at `:387`, `:485` and `:827`. It re-decides at 4 Hz per evading ship
  (`docs/engine/perf-cadences-and-latency.md` §3).
- **SDK names in Beol 4:** E2M1 creates `"Asteroid 0"`…`"Asteroid 15"` and its
  collision handler matches `sName[:8] == "Asteroid"` (`E2M1.py:655`). No SDK code
  selects objects by asteroid genus.
- **Sensor model** (`2026-10-03-sensor-model-roadmap.md`, decision 7 and its
  sub-project 2 notes): occluders are `RockClass` majors above a dial radius; near-band
  rocks never occlude. Promoted rocks are `RockClass`, so they become eligible
  occluders once that sub-project lands.

## Design

### 1. Large-rock threshold

- The Large class's acceptance density gains a factor `ramp(a; large_ramp_lo,
  large_ramp_hi)`: 0 at or below `lo` (0.5), 1 at or above `hi` (1.0), linear between.
  `a` is the source's `a(x)` (`far::density_a`), **not** the noise-multiplied field
  density: a clump never lifts a 0.5 band over the threshold.
- `n_bound` uses the ramp of `a_bound`, so the rejection sampling stays exact.
- Small rocks and puffs are unchanged. The speck band follows automatically (same
  generator).
- BC tile fields have `a = 1` inside and a linear edge ramp over the outer 20% of the
  radius, so their interiors are unchanged; large rocks thin slightly earlier in the
  edge zone.
- The Python twin (`engine/rocks/density.py`) gains the same ramp, pinned against the
  native value as `table_a` already is.

### 2. Promotion

New `engine/rocks/promotion.py`, driven from `far_tier.reconcile` at `promote_hz`
(4 Hz), never every frame.

**Query.** A new binding `rockfield_query_large(centre_sys, radius_gu, min_radius_gu)`
returns the Large-class rocks with radius ≥ `min_radius_gu` whose centres lie within
`radius_gu` of `centre_sys`, as `(key, pos_sys, radius, rock, tumble_axis,
tumble_rate, phase)`. It generates the cells it needs through `generate_near_cell`
(the same function, so results are identical to what is drawn), with its own small
LRU. It does not depend on what the camera has streamed, so it works for NPCs far from
the player too (§4).

**Selection.** Each promotion tick, for the player in the viewed set:
- query `promote_range_gu` (300) at `promote_min_radius_gu` (4.0);
- keep the `promote_max` (8) nearest, by centre distance;
- skip keys destroyed this session (§3);
- nothing is promoted while dashing (`dash.is_dashing`) or while the player is in the
  `"warp"` set, and nothing when the field master toggle is off.

**Promote.** For each newly selected key:
- `RockClass_Create` builds the rock with two new keyword options: `catalogue_index`
  (force the generator's catalogue major, bypassing `catalogue.pick`) and an exact
  radius. The model still loads at the 2-significant-figure radius so models are
  shared, and `SetScale(r / r_q)` supplies the remainder, so `effective_radius`
  equals the generator radius.
- Pose: the generator position converted from system coordinates to the viewed set's
  coordinates (the frame `far_set_frame` already uses); orientation from the tumble
  axis and phase at the current time; `SetAngularVelocity` from the tumble axis and
  rate in world space, so its spin continues as the near band drew it.
- Name: `"Field Rock %04X"` from the low bits of the key, never `"Asteroid …"`, so no
  SDK name check matches it (E2M1 matches the `"Asteroid"` prefix). Display name the
  same.
- Flags: targetable and scannable, not hailable. In no mission group, so it reads as a
  neutral contact.
- Hull: `stats.size_hull(r)`, times the stored hull fraction if the key was damaged
  earlier this session.
- The native band is told to skip that key through a new binding
  `rockfield_set_promoted(keys)`, a per-key exclusion beside `in_explicit`. It applies
  to the near band and the speck band.

**Demote.** A promoted rock returns to scenery when all of these hold: it is farther
than `promote_range_gu × demote_range_mult` (1.5) from the player, it is not the
player's target, and it is not dying. Its hull fraction is recorded if below 1, the
object is removed from its set without a death sequence, and its key leaves the
exclusion list.

**Why not `explicit_regions`.** A region is a sphere and hides every rock inside it,
including neighbours. The promotion contract needs exactly one rock to swap. The
regions stay unused, for later.

### 3. Session record and lifecycle

- **Destroyed keys.** Promotion keeps a key → object map; when a promoted rock's
  `ET_OBJECT_EXPLODING` arrives (or `rocks.death.is_dying_rock` turns true at the next
  tick), its key joins the destroyed set and stays excluded from the native band, so
  the field never regrows it. Its breakup runs through `rocks.death` as for any rock,
  including the remnant rule ("<name> - Remnant", targetable only if ≥ 2.0 GU).
- **Damaged keys.** The hull fraction recorded at demotion is applied at the next
  promotion.
- **View-set change, warp or region hand-off:** every promoted rock is removed from its
  set (no death sequence) and the exclusion list is cleared; the record survives.
- **Mission swap:** `far_tier.reset` also clears promotion and its record, so a
  restarted mission gets a fresh field.
- **No contact-time swap.** Promotion and demotion happen hundreds of GU away, and
  never while dashing, so a rock never changes owner mid-collision. The native player
  contact stays the authority for unpromoted rocks; promoted rocks collide through
  `collisions.py` like any rock.

### 4. NPC avoidance

- `collision_avoidance` gains field obstacles: for an evading ship, a call to
  `rockfield_query_large(ship_pos_sys, avoid_query_radius_gu, large_r_min)` (150 GU,
  every large rock), merged into its obstacle snapshot as spheres. Promoted rocks are
  already set objects, so their keys are excluded from the query results to avoid
  double-counting.
- The query runs at the avoidance cadence (4 Hz per evading ship), only for ships in
  the viewed set's system with a field source in reach.
- **Radius fix (folded in):** the three unscaled `GetRadius()` sites (`:387`, `:485`,
  `:827`) use `collisions.world_radius`, so scaled objects (E1M2's rocks at scale
  3–8.5) are avoided at their real size. The `hull_bounds.bound_radius` widening stays.
- NPCs do not collide with unpromoted scenery rocks (P6).

### 5. Dials, testing, performance

**Dials** ("rock fields" group on `/ L O`, read at use): `promote_min_radius_gu` 4.0,
`promote_range_gu` 300, `promote_max` 8, `demote_range_mult` 1.5, `promote_hz` 4,
`large_ramp_lo` 0.5, `large_ramp_hi` 1.0, `avoid_query_radius_gu` 150. The ramp dials
are pushed to native with the other near-band dials and regenerate the large rocks
and specks (they change which rocks exist).

**Tests (test-first):**
- Threshold: zero large rocks at `a ≤ 0.5`; full density at 1.0; small rocks and puffs
  unchanged; Python and native twins agree; Vesuvi's band generates no large rocks;
  Beol 4's interior large-rock count is unchanged.
- Query: returns exactly the rocks `generate_near_cell` produces in range (same keys,
  positions, radii, catalogue indices), independent of the camera.
- Promotion identity: a promoted rock's position, effective radius, catalogue model and
  spin match its generator rock; the native band skips exactly that key and keeps its
  neighbours.
- Count and hysteresis: never more than `promote_max`; the nearest win; a rock sitting
  at the range edge does not flicker.
- Session record: damaged re-promotes damaged; destroyed never regrows; record cleared
  on mission swap, kept across a set change.
- Breakup: a destroyed promoted rock follows `rocks.death`; its key stays excluded; the
  hit-effect probe shows no grind spam.
- SDK safety: promoted names never match the `"Asteroid"` prefix; E1M2, E2M1 and E3M2
  integration tests stay green.
- Avoidance: field spheres reach the obstacle snapshot; an NPC on a collision course
  steers round an unpromoted large rock; promoted rocks are not double-counted; the
  scaled-radius fix is pinned.
- Headless end to end: flying through Beol 4, rocks promote, can be targeted, destroyed
  and demoted.

**Performance:** profiler scopes `rocks.promotion` and `avoid.field_query`. Measure CPU
with the frame profiler (Developer Options → Diagnostics → Frame Profiler) in Beol 4
and with combat_stress. GPU timing is dead on this Mac.

## Live check (Mark)

`./build/dauntless --developer` from the worktree, then:

- **Vesuvi:** E1M1 and E1M2 at Haven show many small rocks, no large ones, and an
  occasional graze.
- **Beol 4:** nearby big rocks appear in the target list, at most 8; one can be scanned
  and shot down to a remnant; fly away and back and it stays gone.
- **NPCs** in Beol 4 steer round big rocks.
- **No visible change** at the moment a rock is promoted or handed back.

## Out of scope

- New belts and the asteroids-only profile override (P3).
- NPC collision with unpromoted scenery rocks (P6).
- Persisting destroyed or damaged rocks across save/load (session only).
- Sensor occlusion (the sensor-model project; promoted rocks fit its occluder rule).
- Weapons hitting unpromoted scenery rocks.

## Risks

- **Target list noise.** Up to 8 neutral rocks join the list in a dense field. The cap
  is a dial; the remnant experience says keep it low.
- **Promotion seam.** Any mismatch in mesh, scale, lighting or spin shows as a pop at
  300 GU. The identity test pins the numbers; the look needs the live check.
- **NPC passes.** An NPC that misses its avoidance passes through scenery, as torpedoes
  do today.
- **Sensor interaction.** Once sensor occlusion lands, the nearest promoted rocks can
  hide ships while farther large rocks cannot. That asymmetry belongs to the
  sensor-model design.
- **Tuning.** Every number here is a starting value for live tuning.

## Amended during planning (2026-10-05)

- **R1 — demote cap (speck-band exclusion superseded, final review M1).** Demotion is
  capped below the speck band's start (`near_large_billboard_gu - near_fade_gu - 1`,
  400 GU by default) and a dash start demotes every promoted rock. The original ruling
  ("no speck-band exclusion") left destroyed rocks reappearing as specks past ~405 GU,
  so the speck band now excludes every key `rockfield_set_promoted` pushes — promoted
  AND destroyed — keyed exactly as the near band (`near_rock_key`), with the set copied
  into each worker rebuild. The demote cap stays as a useful bound.
- **R2 — promoted rocks have no halo** (scenery large rocks have none).
- **R3 — death is detected by polling** (`rocks.death.is_dying_rock`, set membership)
  each promotion tick; there is no rock-died callback.

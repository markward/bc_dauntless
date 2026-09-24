# One solar system per star — system frames (design)

**Date:** 2026-09-24
**Status:** design approved in brainstorming; spec awaiting review. Not implemented.
**Branch:** `feat/system-frames`, cut from `main` at `36f6f9e5`.
**Supersedes** (all on the unmerged reference branch `worktree-system-navigation`,
tip `9efad5fb`):

- `docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`
- `docs/superpowers/specs/2026-09-23-celestial-layer-design.md`
- `docs/superpowers/specs/2026-09-24-region-scoping-design.md`
- `docs/superpowers/specs/2026-09-24-set-lifetime-correction-design.md`

Those documents, and the 19 rulings in that branch's
`.superpowers/sdd/2026-09-25-set-lifetime/progress.md`, are the record of how we
got here. They are not the target. Where this spec and they disagree, this spec
wins; the reversals are listed explicitly in "Decisions this reverses".

## Goal

BC's places are separate, unrelated maps ("sets"), each with its own sun. We are
building **one solar system per star**: a system is ONE coordinate space, and
BC's sets are placed in it as **regions**, each at an **anchor**. Standing
anywhere in a system you see that system — its star in a consistent direction,
its other worlds at their true bearings, distances and sizes — and what can hit
you, hear you or see you is decided by where things actually are, not by which
set they belong to.

## The mindset shift

**A set stops being a spatial concept.** It keeps three jobs:

1. a **loading unit** — the thing a region module's `Initialize()` creates;
2. an **ownership / lifetime unit** — its creator owns it; nothing unloads until
   the mission changes;
3. **BC's coordinate origin** — the frame its scripts are authored in, which must
   never break.

It loses one: **spatial scope.** "Which set am I in" is no longer the answer to
"what can hit me, hear me, or see me." Everything spatial keys off **system
position** and distance.

## What the reference branch taught (measured, not recalled)

**What it got right, and is kept.** The 32 system maps and their generator
(`tools/systems/{layout,survey}.py`, `tools/gen_system_maps.py`); the 747-line
map validator (`engine/systems/validate.py`); set name → system/region/anchor
resolution (`engine/systems/resolve.py`); `engine/systems/apply_map.py` (a
region's bodies take the map's radius and system-relative position); the far
plane raised with virtual distance only beyond it; and the set-lifetime
correction — departure does not destroy the set you left (that was OUR
behaviour, never BC's: all 102 BC region modules put `DeleteSet` only inside
`Terminate()`, and nothing calls `Terminate()`), and arrival adopts an existing
set rather than re-`Initialize()`ing it.

**What it got wrong, and is the reason for starting again.** It drew a body
from its set when the region was loaded and from the map when it was not — two
sources for identical data (`apply_to_set` is what wrote the set *from* the
map), arbitrated every frame. That produced a proxy cache, a supersession queue,
an eviction pass, a destruction pass, a ghost sweep, and finally a live bug:
warping parks the player in a transit set belonging to no system, and every
planet instance is destroyed. Live, confirmed both directions: fly Ona 1 → Ona 2
and Ona 1 is gone from the sky; come back and Ona 2 is gone.

The justification for two sources ("a mission may have moved a body") describes
a case that does not exist: across the 1,228-file SDK, `Planet_Create` and
`PlanetClass` appear only in `Systems/*/<Region>_S.py` (plus `App.py`, the
interface definition) — re-verified for this spec. No mission creates, moves
or references a planet. (The handover's "`SetTranslateXYZ` appears zero times
in any mission file" is wrong as worded: 110 files under `Maelstrom/` call it,
but 105 are `*_P.py` / `*_Placements.py` waypoint files, and the remaining
three mission scripts — E6M3, E6M5, E8M2 — move a bridge camera or a bridge
character. The conclusion stands; the citation did not.)

**It also relied on a rule that could not survive the goal.** "You interact only
with your own region" (the region-scoping spec) made several resident sets safe
by filtering. It cannot survive flying between regions, and it treats as special
what is BC's normal case — 16 shipped missions `Initialize()` two or more regions
of one system at once.

## Measurements this design rests on

Taken 2026-09-24 against `main` and the reference branch's maps.

**Physics precision — the simulation is double throughout.** `TGPoint3` holds
Python floats (`engine/appc/math.py:15-23`); the native transform store is
`double pos[3]; double rot[9]` (`native/src/transforms/include/dauntless/transform_store.h`);
motion integrates in Python (`engine/appc/ship_motion.py`); collision is Python
(`engine/appc/collisions.py`). **PyBullet is not used at all** (`pyproject.toml`).
Precision is lost only where positions cross into the renderer:

- `compose_world_matrix` (`native/src/transforms/src/transform_store.cc:106-121`)
  narrows the **absolute** position to float; `_world_matrix_from`
  (`engine/host_loop.py`) and `set_world_transform` do the same; `set_camera`
  takes a float eye. There is no camera-relative rendering anywhere.
- Five mesh-query bindings take world-space float points and invert a float
  world matrix: `ray_trace_mesh`, `shield_hit`, `hull_carve_add`,
  `hull_carve_capsule`, `world_to_body` (`native/src/host/host_bindings.cc`).

At 1,000,000 GU a float32 ulp is 0.0625 GU. Player-centring is therefore **not**
a physics requirement; it **is** a rendering and mesh-query requirement.

**Sensor range separates regions — at the doubled scale.** Authored
`SetBaseSensorRange` spans 800–12,000 GU (12,000 is `fedstarbase`; ships top out
lower). Measuring the gap between region spheres (anchor distance minus both
radii) across all 150 same-system region pairs:

| | gap < 12,000 GU | gap < 30,000 GU |
|---|---|---|
| maps as generated today | 21 pairs | 26 pairs |
| orbits doubled | **0 pairs** | **2 pairs** (Artrus 1↔2 24,039; Albirea 2↔3 28,363) |

The 30,000 column matters because 18 of 52 hardpoint files author no sensor
range and fall back to `sensor_detection.FALLBACK_RANGE_GU = 30000`. So at the
new scale, distance-scoped sensing changes nothing between regions for any
authored range; only the fallback reaches two pairs, and only edge to edge. That
is a tuning note, not a design problem.

**The system reads too small because of spacing.** Confirmed with Mark
2026-09-24: the problem was crowding, not flatness. For the record, the maps
**are** flat — 91 of 118 bodies sit exactly on the ecliptic, the median region
anchor is 0.35° off it, and `layout.py` has no inclination concept — and that is
accepted, not a defect.

**Main already has the cross-set bug, without any of this work.** On `main`,
`resolve_collisions`, `splash_damage.apply`, `projectiles.update_all` /
`incoming_ids`, `damage_eligibility`, dust density and lens-flare aggregation
compare positions across **every** loaded set with no scope. E7M3 loads eight
sets at mission start. Converting these consumers fixes a live defect, not only
a future one.

## Scale

**Orbits double.** Current system coordinates run to ~450,000 GU (Itari's widest
sightline is 452,715 GU); the target is ~1,000,000. The maps are **regenerated**
at the new scale by the generator, not ported and then edited.

- Orbit distance and body radius are separate knobs; **only distance changes.**
  The ×20 body radius stays (every one of the 118 mapped bodies is exactly
  20.000 × its BC radius today). Apparent sizes therefore halve; the live pass
  judges whether that undoes what ×20 bought.
- Region radii are measured from BC content and do not scale.
- Travel time doubles. Ona 1 → Ona 3 is ~266,000 GU at doubled scale: ~11.7 hours
  at a Galaxy's 6.3 GU/s full impulse. **In-system warp is load-bearing.**

## Design

### 1. Frames and the accessor

**A frame is one coordinate space.** Every set belongs to exactly one:

| Set | Frame | Anchor |
|---|---|---|
| A mapped region (`Ona1`) | its system (`Ona`) | the region's `anchor_gu` |
| Any unmapped set — Starbase 12, DeepSpace, a mission's own set, the warp transit set (`warp._WARP_TRANSIT_SET_NAME`, `"_WarpTransit"`), the bridge, QuickBattle arenas, comm-viewscreen sets | its **own** frame, named for the set | `(0, 0, 0)` |

An unmapped set is a one-set world: its system position equals its set-local
position, exactly as today.

**An object's frame is its containing set's.** An object in no set has no frame
and is comparable to nothing.

**The accessor** — `engine/systems/frames.py` (as built in Plan 2):

- `frame_of(pSet) -> Frame | None` — `Frame(key, anchor_gu)`. A mapped region
  (marked by the region hook) is `("system", <system>)` at the region's
  `resolve.anchor_of` anchor; every other `SetClass` is `("set", pSet)` at
  `(0, 0, 0)`; anything that is not a set is `None`. **No cache.**
  `anchor_of()` is a dict lookup returning an immutable tuple, and a set's
  frame changes exactly once — when the region hook marks it mapped after
  BC's `Initialize()`. A cache would have to know about that transition (and
  about `DeleteSet` and mission swap); a lookup does not. Nothing goes near
  `resolve.for_set`'s deep copy.
- `containing_set(obj)` — the object's set, or `None` (no set, or no
  `GetContainingSet`). `frame_of_object(obj)` composes the two.
- `offset_between(set_a, set_b) -> (dx, dy, dz) | None` — **the primitive.**
  Add it to a point in b's set-local coordinates to express it in a's. Same
  set → exactly `(0, 0, 0)`, so same-set results are byte-identical to
  comparing raw numbers; different frames, or either side setless → `None`,
  so a consumer cannot forget the frame check.
- `local_in(set_a, obj)` — `obj`'s position in `set_a`'s coordinates, or `None`.
- `in_view(view, pSet, x, y, z)` — a pSet-local point in the viewed set's
  coordinates, or `None` when pSet is outside the viewed frame (the render
  feeds' one filter). Same set returns the point untouched.
- `shifted(p, off, sign=1.0)` — a `TGPoint3` moved by `±off`, or `p` itself
  when `off` is zero/`None`, so a same-set comparison runs the old arithmetic
  on the same objects.
- `system_position(obj) -> (frame_key, x, y, z) | None` — set-local position
  plus anchor. `same_frame(a, b)`.
- `system_distance(a, b) -> float` — `math.inf` across frames.
- `viewing_set()` / `is_space_scene(pSet)` — the viewed set (below).
- `UNSCOPED` — sentinel for "no view given" in the aggregators that take an
  optional view, so `view=None` can mean "nothing is viewed".

A **bulk** form (one anchor added to a whole transform-store bucket, for
`contact_index` and perception's `_get_xyz`, which read the store directly) is
**deferred to the widening plan** — those consumers are still set-scoped. The
two hot pair loops that did need it memoize `offset_between` per distinct
`(set_a, set_b)` per call instead (`projectiles.update_all`,
`collisions.resolve_collisions`).

**Cross-frame comparisons are undefined, not zero.** Objects in different frames
cannot collide, sense, target or hear each other. E7M3's eight sets across six
systems are six frames; E5M4's eight Alioth sets are one.

**BC's surface is untouched.** `GetWorldLocation`, `SetTranslate*`,
`PlaceObjectByName`, `GetNearObjects`, `LineCollides`,
`GetRelativePositionInfo` — anything the SDK hands a point to or reads one from —
stay set-local. That is BC's contract with its 1,228 scripts.

**The invariant every conversion is tested against:** for two objects in the same
set, a converted consumer produces exactly today's result. Behaviour changes only
for pairs in different sets of one system — from wrong to right. This is what
makes the migration additive, one consumer at a time, with no flag day.

**The viewing frame** is the frame of `frames.viewing_set()`: the explicit
rendered set (`get_explicit_rendered_set()`, `MakeRenderedSet`) **only when it is
a space scene**, else the player's own containing set (`ship_iter.active_set()`).
`is_space_scene` is False for the bridge (a `BridgeSet`, or whatever is
registered as `"bridge"`) and for interior/comm rooms (`MissionLib.SetupBridgeSet`
sets, recognised by their background model). The rule exists because cutscenes
end with `ChangeRenderedSet("bridge")` (E6M1, E6M2, E7M1, E8M1, …) and only a
warp arrival resets it, so the explicit rendered set is routinely the bridge
while the player flies in tactical view; taking it literally would blank the
world scene. Consequences: an in-space cutscene rendering another set draws that
set's frame; a bridge<->space camera toggle does not change the viewed frame
(audio's `scene_scope` included); the warp tunnel is its own unmapped frame, so
the sky is empty in transit (BC's tunnel shows its own backdrop).

### 2. Map application — one interception point

Four paths create a region set: warp arrival (`warp.py`
`ChangeRenderedSetAction`), `MissionLib.SetupSpaceSet`, a mission calling
`Systems.X.Y.Initialize()` directly (E7M3), and system loading (§3). All four end
in the region module's `Initialize()`.

`apply_to_set` cannot run at `AddObjectToSet`: BC's `<Region>_S.py` adds a body
**then** calls `PlaceObjectByName`, which would overwrite it. It must run after
`Initialize()` returns.

So: when a module `Systems.<Sys>.<Region>` whose region is mapped is imported,
its `Initialize` is wrapped — BC's body runs unchanged, then `apply_to_set` on
the set it created. Same pattern as the QuickBattle `RecreatePlayer` wrap
(`engine/bridge_selection.install_quickbattle_hook`). This closes the
`SetupSpaceSet` gap the branch recorded as a follow-up, and guarantees the map is
applied **before** anything realizes the set — the ordering the branch proved
load-bearing (applied after realization, `_RenderState.planet_natural_scale`'s
one-shot cache leaves a body DRAWN at 90 GU and TARGETED at 1,800).

`apply_to_set` sets a **mapped flag** on the set. Realizing a set whose frame is a
system but whose flag is unset raises a loud alarm. This replaces the branch's
radius- and star-position heuristics with a fact.

A region's own bodies remain real objects in its set — Orbit
(`AI/Player/OrbitPlanet.py`), targeting, collision and hailing work through them —
at the position and radius the map gives. The star is handled as the branch did:
a set with a Sun keeps it, moved to `-anchor` with the map's radius; Belaruz and
Vesuvi, which author none, get one created from the map (`676cf193`,
`07c396b5` carry the five-argument `Sun_Create` and the proportional atmosphere).

### 3. Loading a system

**Entry** is level-triggered: each tick, the player's frame is compared with the
last loaded one. When it becomes a system whose regions are not all present, the
missing ones are created **through their own modules** (so §2's wrap maps them);
sets that already exist are adopted, never re-created. Being level-triggered, it
covers every arrival — Set Course, mission start, dev swap — which is the
single-caller mistake the branch made (`residency.enter()` had one caller, a dev
mission).

**Nothing unloads until the mission changes.** Leaving a system does not delete
it. That is BC's own bound: the mission-swap `_sets.clear()` in `host_loop.py`.

**Departure never deletes a set; arrival adopts an existing one.** Re-implemented
test-first against this design rather than cherry-picked — the branch's commits
for it (`34a1e89d`, `dcdc1533`, `fbb44458`) are built on the residency and proxy
code this design does not have.

**Only the lifetime call goes; the render teardown stays until §4 replaces it.**
`warp.py` makes two separate calls at departure: `_teardown_hook(src)`
(`host_loop.teardown_set_objects` — destroys render instances only, never
objects) and `DeleteSet`. The branch removed both, and losing the first is what
produced its ghost planet (Ruling 18): a left set's Planet instance survived,
drawn unshifted in the next system's sky. Plan 1 removes `DeleteSet` only.
Returning re-realizes the set through `_realize_hook` (`realize_set_objects` is
idempotent), recomputing `planet_natural_scale` from the map radius. §4's
diff-driven drawing retires the teardown hook in Plan 3.

### 4. Drawing

**In a mapped frame, the system map is the only source for celestial bodies.**

- Map bodies — star, planets, moons — are drawn, keyed by `(system, body)`. The
  draw list is a **pure function of the viewing frame.** When the viewing frame
  changes, instances are diffed against the new list. No proxy cache, no
  supersession, no sweep.
- A mapped set's Planet and Sun objects are **never realized as render
  instances.** They exist for interaction. `apply_map` placed them exactly where
  the map body is drawn, so the picture and the object coincide by construction.
- A script that moves or resizes a mapped body is **logged loudly, not
  arbitrated.** The SDK says it never happens; if it does, we want to know.
- Lens flares: one, from the map star, using the rendered set's authored flare
  style (`Tactical.LensFlares.*` attaches one to each region's Sun).
- **Unmapped frames draw exactly as today**, from set objects.

**Ships** are realized from every set in the viewing frame, not just the active
set, culled by distance from the render origin — so a ship in a sibling region
appears as you approach it.

**Proximity tiers.** True-position mesh inside the far plane; the existing
conditional virtual-distance treatment beyond it; a draw-distance cull for ships.
No impostors or body LOD — ~15 bodies per system does not need them.

**Far plane ≈ 1,000,000 GU** for the exterior scene and bridge viewscreen only
(the interior, SPV and comm cameras keep theirs). The exact figure is derived from
the regenerated maps' widest sightline, with margin, and pinned by a test that
derives rather than restates it — a far plane that stops covering the widest
sightline fails silently by clipping one world in one system. Depth cost is
negligible: forward-Z precision is `Δz ≈ z²/(2²⁴·n)` once `f ≫ n`, governed by
`near`, which stays at 1.0.

**Lighting and backdrops are unchanged.** Backdrops stay per-set (BC authored
them that way); lighting resolves via the rendered set, as today.

### 5. Precision — the render origin

The render origin is the camera eye's system position in the viewing frame, held
in **double**.

- `compose_world_matrix`, `_world_matrix_from` and the shadow/light matrix
  builders subtract it in double **before** narrowing to float.
- `set_camera` receives the eye relative to it — always ≈ `(0, 0, 0)`.
- This replaces the branch's per-body anchor-difference offset in the draw data:
  one frame, one subtraction, one place.
- The five mesh-query bindings receive points made relative to the queried
  instance's position, in double, in Python; C++ inverts rotation and scale only,
  never a large translation. Hit points, scuffs, shield splashes and carves then
  land identically at the origin and at 1,000,000 GU.

A body 400,000 GU away loses ~0.03 GU to float — invisible at that range.
Near-camera geometry keeps full precision anywhere in the system.

### 6. Converting consumers — order is a safety property

**§3 (loading a whole system) is exactly what killed the player on the branch.**
So every consumer that compares positions **with no set scope** must be converted
**before** a second set of one system can exist:

| Consumer | Where (main) |
|---|---|
| Collision pairing | `collisions.py` `iter_collidables`, `resolve_collisions`, `_deepest_piece_overlap` |
| Splash damage | `splash_damage.apply` |
| Torpedoes | `projectiles.update_all`, `is_incoming`, `incoming_ids` |
| Damage eligibility | `damage_eligibility.select_eligible` |
| Dust density | `host_loop._aggregate_planets` (called with all `_sets`) |
| Lens flares | `host_loop._aggregate_lens_flares` (all `_sets`) |
| Torpedo / explosion / hit-VFX lights and render data | `host_loop` `_build_dynamic_light_render_data` et al. |

A **tripwire test** enforces the order: with three Ona regions loaded, none of
these pairs objects across regions by raw position.

**Audio converts early too** — it is wrong today, not merely under-reaching:
`engine/audio/tg_sound.py` tags a positional sound with the player's
(`scene_scope.rendered_set()`) set rather than the emitter's. It moves to the
emitter's frame, with distance from the listener in system coordinates.

**Status (Plan 2).** All of the above are converted: collision pairing,
splash damage, torpedoes (hit/home/incoming), and damage eligibility compare
through `engine/systems/frames.py`, not raw set-local numbers; dust density,
lens flares, torpedo/explosion-light render data, and the rest of the render
feeds carry only the viewed frame; and audio keys `scene_scope` by frame and
refuses a cross-frame `Play()`. The Plan-1 `same_set`
(`ship_iter`'s containing-set-equality) stopgap is retired —
`tests/integration/test_frame_tripwire.py` is the tripwire named above, and it
guards every one of these consumers together in one scenario (three Ona
regions plus an unrelated XiEntrades4 region and an unmapped Starbase12, with
identical local numbers placed in every set on purpose). The set-scoped
widening list below remains open — perception, avoidance, AI conditions,
weapon range gates, the target list, and camera modes are unaffected by this
plan.

**Set-scoped consumers widen afterwards, one at a time.** Perception and contacts
(`perception.perceived_by`, `contact_index`), collision avoidance, AI conditions
and `ProximityCheck`, weapon range gates, the target list and range readouts,
camera modes. Most are safe today — they only under-reach, never seeing a sibling
region's ship — and per the sensor measurement, widening them changes nothing
until the player can be physically near another region, which the hand-off (§7)
enables. Each lands with the same-set-pair invariant test.

**Weapons did NOT only under-reach.** The phaser damage tick
(`host_loop._advance_combat`) and `weapon_subsystems._target_within_range_gu`
(phaser `_target_in_system_range`, tractor `_can_engage`) compared raw set-local
numbers with no set gate at all, over every set's ships: a bank left firing could
damage a ship in another set wherever raw numbers coincided — invisibly, once
cross-frame beams stopped being drawn. Plan 2 closes that with an **interim
guard** (controller Ruling 5): a target not in the *same set* as the firing ship
(setless either side included) is out of range, and the damage tick stops such a
bank without damage. Cost until frame-aware engagement lands here: a ship cannot
phaser or tractor a target in a sibling region even when physically close.
`ProximityCheck` likewise rejects a pair when either side is setless (Ruling 6),
so a dead anchor cannot keep firing on ships in other sets.

### 7. Moving through a system — rules only

The hand-off and the dash are designed in detail after §1–§6 survive a live
pass, because what that pass shows will shape them. These rules bind that design;
each gets a guard test.

**There is no "space set."** A set is not spatial, so a player who leaves Ona 1's
sphere simply stays in the Ona 1 set until entering another region's sphere.

| # | Rule |
|---|---|
| **A** | Entering another region's sphere hands the player off: moved into that set, pose and velocity kept, set-local position rebased by the anchor difference, so **`system_position` is identical before and after** — the test asserts exactly that. |
| **A′** | The hand-off emits `ET_EXITED_SET` / `ET_ENTERED_SET`, and `ET_EXITED_WARP` for the player, so the 33 mission arrival hooks (9 `ET_EXITED_WARP`, 24 `ET_ENTERED_SET`) fire unchanged. |
| **H** | Hysteresis: enter at the region radius, leave at radius + margin. |
| **C** | System-to-system Set Course keeps BC's tunnel. E6M1–E6M5 create ships during it; E6M1 dereferences them on arrival with no None check. |
| **D** | Dash engage and region exit both run BC's warp gate (`Bridge/HelmMenuHandlers.py` checks plus the mission `ET_WARP_BUTTON_PRESSED` chain), so mission refusals hold. |
| **N** | NPCs are **not** handed off. A set is an NPC's owner and loading unit; the accessor makes its physical whereabouts correct without it. |

The reference spec's dash design (speed from distance, slow final approach,
steering locked, `WarpFlash`) is the starting point for that pass. Known blocker,
recorded: `AI/PlainAI/FollowThroughWarp.py` cannot run in this engine (Python 1.5
string exceptions; see `docs/engine/cross-region-ship-handoff.md` on the
reference branch).

## The ten categories, mapped

| # | Category | Where it lands |
|---|---|---|
| 1 | Rendering | §4 — map only; own region's bodies also real set objects |
| 2 | Lighting and backdrops | §4 — unchanged, per rendered set |
| 3 | Navigation options | galaxy map + system map; §7 |
| 4 | Physics | §1 accessor, §5 render origin, §6 collision first |
| 5 | AI | already global (`iter_ships`); §3 loads the whole system |
| 6 | Sensors | §6 widening; measured free at the new scale |
| 7 | Mission scripting and triggers | active in every loaded set; §2 maps sets missions create outside the player's system too |
| 8 | Audio | §6, early — emitter's frame |
| 9 | Persistence | out of scope |
| 10 | Nebulae and anomalies | part of the system map (`clouds`), under §4 when drawn |

## Decisions this reverses

| Reference-branch decision | Now |
|---|---|
| Draw a body from its set when loaded, from the map otherwise | Map is the **only** draw source in a mapped frame |
| Per-body anchor-difference offset added to draw data | One render origin, subtracted once, in double |
| "Interact only with your own region; see across regions" | Compare by system position; cross-**frame** is undefined, cross-region within a frame is ordinary |
| A "space set" per system for the space between regions | None — the player stays in their last region's set |
| Residency: only a system's regions are loaded, torn down on leaving | Whole system loaded on entry; nothing unloads until the mission changes |
| Far plane 500,000 GU | ~1,000,000 GU, derived from regenerated maps |
| Radius / star-position alarm for an unmapped set | A mapped flag set by `apply_to_set` |
| Map applied by per-call-site `create_region_set` | One wrap on the region module's `Initialize` |

## Plans, in order

1. **Foundation.** Merge `67091184` into this branch (verified conflict-free
   against `main` with `git merge-tree`); cherry-pick `3b55ab30`, `676cf193`,
   `07c396b5` (apply_map only), `c2f9d0c2` (far-plane bound derived from the
   maps), `fab31c8a` (arrival-adopts tests) and `c31a5a0d` (dry-run 2026-09-24:
   all apply cleanly except `c31a5a0d`, whose `conftest.py` hunk conflicts with
   residency-era context and is resolved by hand); regenerate the 32 maps at doubled
   orbits; enforce the 20× radius ratio in `validate.py`; far plane to the derived
   figure; departure-keeps / arrival-adopts re-implemented test-first; the §2 wrap
   and mapped flag.
2. **Accessor and the unscoped consumers.** `engine/systems/frames.py`; every
   §6 table row; audio; the tripwire.
3. **Seeing the system.** Render origin (native + Python) and mesh-query
   relativisation; map-drawn bodies; whole-system loading; ships across the
   viewing frame. **Mark flies after this plan.**
4. **Widening.** The set-scoped consumer list, one per task.
5. **Moving through it.** Hand-off and dash — detailed design first.

## Testing

**In the gate (`scripts/check_tests.sh`):**

- Map validity: `validate.py` over all maps, plus the 20× radius-ratio rule.
- Far plane derived from the maps' widest sightline, never restated.
- Accessor: same-set pair identical to raw positions; cross-frame `None` / `inf`;
  unmapped set has zero anchor.
- Tripwire: three Ona regions loaded; no §6 unscoped consumer pairs across
  regions by raw position.
- Map application: each of the four creation paths yields a mapped set, tested
  separately; the alarm fires for a mapped-frame set realized unmapped.
- **Sky round trip — the live bug as a test:** Ona 1 → tunnel → Ona 2 → tunnel →
  Ona 1; at each station the draw list is exactly that frame's map bodies, and in
  the tunnel it is empty.
- Precision (ctest): an object at 1,000,000 GU with the camera 50 GU away composes
  to the same view-space matrix, within float tolerance, as the same scene at the
  origin; mesh queries return the same body-space hit at both.

**Live yardstick,** handed to Mark before he flies (`--developer` → Load Mission →
Developer → System Preview). Derived by running the dev mission **headlessly**
against the regenerated maps, not by hand: bearing, apparent size
(`2·atan(r/d)`) and range of every body from Ona 1's Player Start, and again on
arrival at Ona 2. What must visibly hold: the star is smaller from the far region;
no body changes size or jumps when its set loads; **Ona 1 is still in the sky
after Ona 1 → Ona 2, and Ona 2 after coming back.**

## Deliberately out of scope

- Persistence of in-system position (save/load does not exist yet).
- Orbital inclination — the maps are flat and that is accepted.
- Body impostors / LOD.
- Procedural planet appearance (the map's identity/appearance split already
  allows it later).
- Sleeping or unloading distant regions' simulation — needs a measurement first.
- Rewriting any campaign mission.

## Open, to settle in the plans

- **The 30,000 GU sensor fallback** reaches two region pairs edge to edge at the
  new scale. Leave, or lower — a tuning call for Mark once widening lands.
- **Apparent-size loss.** Halved by doubling distance with radius fixed. Judged in
  the live pass, not pre-empted.
- **Ship draw-distance cull** figure — chosen in Plan 3 from what a ship's
  apparent size is at range, stated with its derivation.

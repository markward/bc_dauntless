# Collision avoidance runs twice

## The finding

Two independent avoidance controllers steer the same ship in a real SDK mission:

| | where | when |
|---|---|---|
| A | `AvoidObstacles`, an SDK **preprocessor** in the AI tree (`AI/Preprocessors.py:1621`) | inside `tick_all_ai` |
| B | `collision_avoidance.tick_collision_avoidance` | later in the same `GameLoop.tick` |

`tick_all_ai` runs first, so A does a full obstacle scan and calls
`TurnTowardDirection` / `SetImpulse`. Then B runs and overwrites the result.
**A is computed at full price and thrown away**, and where the two disagree, the
SDK's decision is discarded silently.

Measured (`scratchpad/dualavoid.py` pattern, E3M1): 1 ship with an AI, its tree
contains `AvoidObstacles_NonLethal`, and B steers it — B steers *every* ship
with an AI, unconditionally.

⚠️ `combat_stress` attaches `BasicAttack`, which installs **no**
`AvoidObstacles`. Every avoidance measurement taken against that mission before
2026-08-28 is therefore of path B alone, and understates real-mission cost.

✅ **Fixed.** `combat_stress.avoidance_enabled()` now defaults **ON**, wrapping
each ship's tree the way `QuickBattle/QuickBattleAI.py:83-92` wraps its own
(BasicAttack inside a PriorityList inside an `AvoidObstacles` PreprocessingAI).
The mission is a QuickBattle stand-in, so QuickBattleAI — not BasicAttack — is
the right reference for what "faithful" means here. `DAUNTLESS_COMBAT_AVOID=0`
turns it off to isolate non-avoidance cost, and the mission's scene line names
the setting either way, so a capture always announces its configuration.
⚠️ `docs/engine/frame-profiler.md`'s example command predates this flip; its
numbers were taken with avoidance off.

## Why B exists, and why the reason is wrong

`tick_collision_avoidance`'s docstring says it "restores the original Appc
autopilot's obstacle avoidance (the SDK movement scripts only command a heading;
the C++ autopilot steered around obstacles)".

BC had no such autopilot layer. `PreprocessingAI::SetContainedAI` (`0x0048E570`)
does not store the AI it is handed — it calls `newAI->GetOptimizedVersion()`
(vtable `+0x34`) and stores the **returned** object. `PreprocessingAI` overrides
that slot (`0x0048EB20`): it reads the bound Python preprocessor's class name,
looks it up in a native registry, allocates a native node, steals the contained
subtree, and deletes the Python-backed node. Four classes are registered in the
binary — `AvoidObstacles`, `FireScript`, `ManagePower`, `SelectTarget` — and in
the shipped game all four Python `Update` bodies are dead code.

So avoidance was always a node in the AI tree. It was native, not Python, but it
sat exactly where the SDK puts it.

## The resolution — IMPLEMENTED (the faithful model)

Replace `ai_optimized.py`'s `"AvoidObstacles": _wrap_non_lethal` with a real
engine-side node, and **delete `tick_collision_avoidance` as a GameLoop phase**.
This uses BC's own substitution point rather than working around it.

Consequence, accepted deliberately: **only ships whose doctrine installs
`AvoidObstacles` get avoidance.** Ships under doctrines that do not install it
(`BasicAttack` among them) will not dodge. That matches BC and is the desired
behaviour going forward.

## Why this is also the performance fix

The SDK node is structurally **per-observer** — each instance is bound to one
ship and can only ask "what is near me", which is why it scans the world. An
engine-side node has no such constraint: it can consult a threat index built
once per tick for the whole world.

That matters because the current query is poorly posed for a battle. Measured
over 40,320 pair-samples at 64 ships:

```
  within the 225 GU proximity query :  47.7%
  actually converging (swept test)  :   1.48%
```

**Convergence is a ~32x tighter filter than proximity**, so it is the predicate
worth spending on. `AVOID_MINIMUM_RADIUS_GU` is 225 GU (~40 km, the SDK's
`fMinimumRadius`), which is coarse relative to the distances that matter.

⚠️ **CORRECTED.** This section first reported 100.00% / 0.00%, measured on a
scene where every ship had `GetRadius() == 0`: the headless harness has no
realize step, so `SetRadius` never ran. A zero radius makes `personal_space`
zero and trips `_test_course_override`'s `if ob_r <= 0.0: continue`, so headless
avoidance processed NOTHING while appearing to run, and the swept test was being
asked whether dimensionless points would collide. The positive controls passed
because they fed hardcoded non-zero radii and so never touched the scene's real
values — a control aimed at the wrong thing. `combat_stress` now seeds a
nominal hull radius, and sizes its ring so hulls do not interpenetrate.

The design: one shared broadphase per tick over ship bounding spheres running
the swept relative-velocity test; only converging pairs reach narrowphase, and
narrowphase uses a **coarse** hull (8–16 spheres), not the 128-leaf collision
decomposition, which exists for hit detection.

⚠️ A spatial index over the *proximity* query was tried and measured worthless
(1.5% of pairs skipped) — see the note in `collision_avoidance.py`. Convergence
is a different predicate; that is the whole distinction.

## Open questions before building

* **What does the native node return with no ship?** `ai_optimized.py` flags
  this as a KNOWN DIVERGENCE. The current wrapper translates `PS_DONE` to
  `PS_NORMAL` with documented reasoning that must be preserved.
* **Is the ship bounding sphere guaranteed to enclose all hull pieces?**
  Broadphase-then-refine is only conservative if it is.
* **Static obstacles** (stations, asteroids, planets) never steer but must
  remain *in* the broadphase; the swept test handles zero velocity naturally.
* **The already-overlapping clause** — `_need_to_avoid` returns True on
  `dist < personal_space + rb` regardless of velocity — must survive.

## Status

**Implemented.** `ai_optimized.OPTIMIZED_PREPROCESSORS["AvoidObstacles"]` is now
`_replace_avoid_obstacles`, and `GameLoop.tick` no longer calls
`tick_collision_avoidance`.

The replacement subclasses the **non-lethal** wrapper (so the `PS_DONE`-with-no-ship
edge stays de-fanged) and overrides **`TestCourseOverride`** plus a one-off phase
offset in `GetNextUpdateTime` (see *Thundering herd* below). Everything else is
still SDK code running on SDK state: the `PS_SKIP_ACTIVE` return, the
`TurnTowardDirection` / `SetImpulse` calls, the `fUpdateDelay` the SDK `Update`
writes, and the pickle hooks. The alias shares the original's `__dict__`, so
every parameter the SDK constructor set stays live.

### What the engine scan does NOT read off the node

`course_override_for` is handed only the node — for its ship and its
`vOverrideDirection`. Everything else comes from `collision_avoidance` module
constants:

| SDK node field | what the engine scan actually uses |
|---|---|
| `fPredictionTime` | `AVOID_PREDICTION_TIME_S` |
| `fMinimumRadius` | `AVOID_MINIMUM_RADIUS_GU` |
| `fPersonalSpace` | `AVOID_PERSONAL_SPACE_MULT` |
| `lDontAvoidTypes` | module-level `_dont_avoid_types()` |

All four are still present on the instance and still read by the SDK `Update`;
they simply no longer steer the scan. **`lDontAvoidTypes` belongs in this table,
not in the "preserved" list above** — it was listed as preserved, and it is not.

This is inert for shipped content: no stock SDK script customises any of the
four, and `test_our_constants_match_the_sdk_defaults` /
`test_our_dont_avoid_types_match_the_sdk_list` pin each against the real
`AI.Preprocessors.AvoidObstacles` defaults (against the SDK class itself, not a
hand-written double carrying the same literals — the earlier version of that
test compared a copy to itself and could not fail). A mod that varied any of the
four per-doctrine would be silently ignored; closing that means threading them
off the node in `course_override_for`.

### Thundering herd

`AVOID_EVADING_UPDATE_DELAY_S` sets `fMinimumUpdateDelay` to
`fMaximumUpdateDelay` (0.25 s), and `ai_driver._tick_preprocessing` reschedules
as `game_time + interval`. That is a pure **period with no phase**: nodes that
are ever due on the same tick stay due on the same tick forever, and ships
spawned in the same frame start that way. Measured at 8 ships, scans per tick
was `[8,0,0,…,0,8,0,…]` — the mean dropped 15x but the **per-tick peak did not
move**, so the frame spike the cadence exists to flatten survived.

Fixed by a one-off offset on the node's **first** reschedule
(`ai_optimized._phase_factor`): deterministic (derived from the ship's object id
— no `random` in sim code), and always a *fraction* of the interval, so it can
only bring a re-scan forward, never past BC's own `fMaximumUpdateDelay`. Same
scene after: **peak 8 → 2**, mean unchanged.

The id is put through a full avalanche (multiply / xor-shift / multiply /
xor-shift) before the modulo. Two weaker versions were tried and are recorded
because both look reasonable:

* plain `obj_id % buckets` — object ids come off one global counter shared with
  every subsystem a ship allocates, so consecutive *ships* are strided, and any
  stride that is a multiple of the bucket count puts every ship back in one
  bucket;
* one Knuth multiply, then a hand-picked bit window (`>> 20`) — bits 20-23 of
  `id * 2654435761` barely move across small strided ids, which collapsed an
  8-ship crowd onto 3 tick phases and pushed the measured peak **up** to 7.

### ⚠️ Nothing invalidates a held decision

To a **new** threat, reaction latency is 0.25 s both before and after this
branch. What the cadence changed is re-decision **while already evading**:
16.7 ms → 250 ms.

There is **no `ForceUpdate()` caller for avoidance anywhere**. So for up to
250 ms after an override is issued, the ship flies the committed heading
through: an obstacle appearing *in* the escape path; the avoided obstacle dying
or warping out; a collision impulse or tractor knocking it off the commanded
heading. None of those produce an early re-scan. Against the 15 s
`fPredictionTime` horizon a 250 ms stale decision is 1.7% of the lookahead,
which is why this is tolerable rather than urgent — but the fix is an
event-driven `ForceUpdate` on those edges, not a smaller cadence.

`tick_collision_avoidance` still exists but is **no longer called by the engine**.
It is retained as the driver for `tests/integration/test_collision_avoidance.py`,
which exercises the same `_test_course_override` the preprocessor path uses.

---

# The shape-aware hull feature is INERT in the live game

Found while trying to measure the convergence gate. Recorded here because it
invalidates two commits' claims and because the obvious fix is a performance
trap.

## The bug

`cache_hull_bound_spheres` is called from **one** place — `host_loop.py:4443`,
inside `realize_set_objects`. The *other* realize path, the mission-loader one
that actually runs at load, loads the model, seeds `GetRadius()`, creates the
instance, and never caches hull bounds.

So mission-loaded ships have no pieces, `has_hull_bounds` is False for every
one of them, and both consumers silently take their whole-model-sphere
fallback. Measured live at 100 ships with avoidance on: **13,000,000 avoidance
pair-tests, `with_pieces=0`.**

That makes these inert for real ships:

* `4bf8d748` — "obstacles are their hull PIECES, not one model-wide sphere"
* `57e7686a` — "narrow-phase against hull pieces, not the model-wide sphere"

The integration tests pass because their fixtures cache bounds explicitly. The
live game never does. This is the same failure mode the comment at the working
call site already warns about ("the guard skipped every ship and the whole
feature shipped inert"), reached by a different route: the call was added to one
realize path and not the other.

The machinery itself is fine — `model_bounds` returns 128 entries for a Galaxy
and `cache_hull_bound_spheres` succeeds when called.

## Why the one-line fix was reverted

Adding the call to the loader path works, and it is unaffordable:

| | gl.ai |
|---|---|
| 33 ships, no pieces | 34 ms |
| **9 ships, pieces** | **94.5 ms** |

Avoidance runs per (ship × obstacle) — O(N²) — and a hull is up to 128 leaves.
`collisions.py` uses the same pieces and does **not** have this problem, because
its narrow phase runs only between two objects already in contact.

Moving avoidance to the whole-model sphere to dodge the cost is also not
available: it fails `test_ship_in_a_docking_bay_is_not_avoided` and
`test_an_obstacle_whose_pieces_are_all_out_of_range_is_not_avoided`. Concavity
is the entire reason the pieces exist — a ship leaving a starbase's docking bay
reads as *inside* the station under one sphere, and the already-inside-personal-
space clause then fires every tick (E6M2's fly-in).

## What actually fixes it

A **coarse hull for avoidance** — 8–16 spheres, enough to express the void in a
docking bay, instead of the 128-leaf collision decomposition. Then:

1. cache the pieces on the loader path (the one-line fix), so collisions work;
2. avoidance consumes the coarse hull, so it stays affordable;
3. the convergence gate finally has something to protect — measured live it
   rejects **91.3%** of pairs (13.0 M tested, 11.9 M rejected), which today
   protects only a single cheap sphere test. (That live figure was taken on the
   old 20 GU ring but with real radii, since the live path does realize; it is
   a different scene from the 47.7% / 1.48% above, and both support the gate.)

The coarse hull must ENCLOSE the fine one, or avoidance starts missing
obstacles — a conservative clustering, not a sample.

## Current state

Both changes reverted. Live behaviour is exactly as it was: no pieces for
mission-loaded ships, avoidance on the whole-model sphere, collisions likewise.
Nothing regressed; the feature is simply not yet doing what its commits say.


---

# The test scene was not physical (corrected)

`combat_stress` placed ships on a fixed 20 GU ring. That circumference is 126 GU
and a hull is ~8 GU across, so it holds about 15 ships without overlap — and it
was being asked to hold 100, at **1.26 GU spacing**. Every high-count
measurement was of a pile-up resolving itself, not a battle.

Worse, headless ships had **`GetRadius() == 0`** (no realize step without a
renderer), which silently disabled avoidance entirely: `_test_course_override`
skips any obstacle with `ob_r <= 0.0`, and `personal_space` is
`radius * AVOID_PERSONAL_SPACE_MULT`.

Both fixed. The ring is now sized from the ship count
(`radius = N * hull_diameter * SPACING / 2*pi`, floored at 20 GU) and a nominal
4 GU hull radius is seeded when a ship has none. At 100 ships that gives a 255 GU
ring with 16 GU spacing (~2 hull diameters), median pair separation 360 GU.

**Every measurement taken against this mission before this fix should be treated
as suspect**, including the scaling curve to 100 ships and the avoidance
figures. Live captures through `dauntless.exe` had real radii but still used the
over-dense ring.

100 ships on the corrected scene, avoidance ON: frame ~646 ms, `sim` 515 ms,
`gl.ai` 209 ms (avoidance included), `gl.motion` 73 ms, `sim.combat` 136 ms.

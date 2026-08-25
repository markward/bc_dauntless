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

⚠️ `combat_stress` uses `BasicAttack`, which installs **no** `AvoidObstacles`.
Every avoidance measurement taken against that mission is therefore of path B
alone, and understates real-mission cost.

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

That matters because the current query is badly posed for a battle. Measured
over 40,320 pair-samples at 64 ships:

```
  within the 225 GU proximity query :  100.00%
  actually converging (swept test)  :    0.00%
```

(Positive controls: a head-on pair returns True, a distant parallel pair
returns False, ship speeds mean 2.20 / max 4.42 GU/s — so the 0% is real, not a
vacuous test.)

**Proximity does not discriminate; convergence does.** `AVOID_MINIMUM_RADIUS_GU`
is 225 GU (~40 km, the SDK's `fMinimumRadius`) while combat happens within a few
GU, so the filter that costs 216 ms at 100 ships rejects nothing, and the filter
that costs ~20 float ops rejects everything.

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
edge stays de-fanged) and overrides **only `TestCourseOverride`**. Everything else
is still SDK code running on SDK state: the `PS_SKIP_ACTIVE` return, the
`TurnTowardDirection` / `SetImpulse` calls, the `fUpdateDelay` cadence and
`GetNextUpdateTime` — which the driver already honours, so BC's 0.25 s idle /
every-tick-while-evading cadence is preserved without reimplementing it — the
`lDontAvoidTypes` list, and the pickle hooks. The alias shares the original's
`__dict__`, so every parameter the SDK constructor set stays live.

No shipped SDK script customises `fPredictionTime`, `fMinimumRadius` or
`fPersonalSpace`, so the engine scan reads module constants;
`test_our_constants_match_the_sdk_defaults` guards that equivalence.

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
   protects only a single cheap sphere test.

The coarse hull must ENCLOSE the fine one, or avoidance starts missing
obstacles — a conservative clustering, not a sample.

## Current state

Both changes reverted. Live behaviour is exactly as it was: no pieces for
mission-loaded ships, avoidance on the whole-model sphere, collisions likewise.
Nothing regressed; the feature is simply not yet doing what its commits say.

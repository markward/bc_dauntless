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

## The resolution (decided: the faithful model)

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

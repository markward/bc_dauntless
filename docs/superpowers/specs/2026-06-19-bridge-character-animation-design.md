# Bridge Character Animation System — Design

**Date:** 2026-06-19
**Status:** Approved design, pending implementation plan
**Scope:** Load-time placement (bug fix) + idle ambient gestures + hit reactions, unified
under one per-character animation runner. Lipsync/phoneme and guest-chair animations are
explicitly deferred.

## Problem

When a bridge loads, officers visibly play a "stand up" motion instead of simply
appearing standing at their stations. Investigation traced this to a single last-mile
divergence: the SDK places officers with a **`TGAnimPosition`** (a *static* pose snapped
from a clip's keyframes), but our renderer plays that clip **through its full duration**
before settling on the last frame. The motion the player sees is the placement clip
(`db_stand_h_m`, etc.) animating from its first frame into the standing pose.

A full audit of the bridge-character animation lifecycle established the broader picture:

| Category | SDK / original-engine behavior | Our engine (before this work) | Status |
|---|---|---|---|
| Load-time placement | `TGAnimPosition` → snap to static rest pose | plays the clip through | **active bug** |
| Idle/ambient gestures | `AddRandomAnimation` → C++ schedules random gestures | stored in `_random_animations`, never played | missing |
| Hit reactions | `AddAnimation("…HitStanding")` → C++ plays on damage | `PlayAnimation` is a no-op | missing |
| Speech lipsync | phoneme/mouth anim during `SpeakLine` | `AddPhoneme` no-op; audio+subtitle only | missing (deferred) |
| Camera walk-on / doors | `TGAnimAction` on camera/object nodes | cutscene controller plays them | implemented |
| Guest chair in/out | `PutGuestChairOut/In` | not triggered | missing (deferred) |

**Key fidelity finding:** we do **not** trigger anything beyond the SDK. If anything we
*under*-animate — three systems the original engine drove are no-ops. The single exception
is the placement play-through, which is "playing an SDK *static-pose* request as motion."

## Faithfulness boundary

The clip choices and their authored transitions come entirely from the SDK's
`Bridge/Characters/CommonAnimations.py` functions — **we never invent motion**. We own only
the **scheduling policy** (idle timers, hit→direction mapping), which was always closed C++
and never lived in SDK Python. This is the project's organizing principle: add exactly the
engine behaviors the original had, sanctioned by the SDK's own animation builders.

## Core model

Every visible officer has a **static rest pose** (its placement) plus an optional
**transient action** (a gesture or reaction) playing over it. All three behaviors collapse
to one path:

```
rest pose ──(idle timer fires / ship takes a hit)──▶ play SDK TGSequence's clips in order ──(AT_DEFAULT)──▶ rest pose
```

This is faithful because the SDK's `CommonAnimations` functions return `TGSequence`s that
already chain the authored transition clips and terminate in
`CharacterAction_Create(pCharacter, AT_DEFAULT)` — and `AT_DEFAULT` is exactly "snap to the
static rest pose." We chose **authored-transitions-only**: no engine-side blending; the
renderer plays clips and treats `AT_DEFAULT` as "restore the rest-pose palette."

## Architecture and division of labor

Follows the existing split (game logic in Python, palette math in native) and mirrors how
`engine/bridge_cutscene.py::BridgeCutsceneController` already drives camera/door anim nodes.

### Python (`engine/`)

- **`BridgeCharacterAnimController` (new).** Owns, per character: the rest-pose handle, an
  idle timer, and a small action queue. Advances through a `TGSequence`'s clips (it knows
  each clip's duration from clip metadata), and on `AT_DEFAULT` tells the renderer to
  restore the rest pose. The character-targeted `TGAnimAction` branch currently
  instant-completing in `engine/appc/actions.py:493-496` is routed here, exactly like the
  camera/object branches already are.
- **Idle scheduler.** Per-character random timer (next gesture in a randomized window,
  seeded RNG). On fire: pick one of that character's stored `_random_animations` entries
  respecting its `SITTING_ONLY`/`STANDING` mode, **call the real SDK builder**
  (`CommonAnimations.LookAroundConsole(char)`, etc.) to get a `TGSequence`, enqueue it.
  A character already mid-action skips its tick (no overlap on one officer; officers are
  independent so the bridge stays organically alive). Timer reschedules after completion.
- **Hit handler.** Subscribes to the existing `WeaponHitEvent` in `engine/appc/combat.py`.
  On a player-ship hit: compute the impact bearing relative to the ship's frame → left/right;
  map damage magnitude → `HitStanding` (light) / `HitHardStanding` (hard) / `Blast` (severe).
  For each visible officer, resolve its registered reaction key, build the `TGSequence`,
  enqueue.

### Native (`native/src/`)

Rebuild `dauntless` after any `host_bindings.cc` change (it compiles into both the binary
and the `_dauntless_host` module).

- **Rest-pose storage/restore.** Extend `scenegraph::Instance::AnimationState` with a stored
  rest palette (or rest clip+frame). New bindings:
  - `set_instance_rest_pose(iid, clip_index, at_start)` — compute and freeze the static
    placement palette; also set it as the current palette.
  - `restore_rest_pose(iid)` — snap the palette back to the stored rest pose (this is
    `AT_DEFAULT`).
- **Transient clip playback.** Reuse the existing play-once-hold-last-frame path in
  `native/src/renderer/animation_update.cc`, but a completed transient reverts to the rest
  palette rather than freezing on its own last frame — the Python controller issues
  `restore_rest_pose` on `AT_DEFAULT`.
- **Runtime clip loading.** `assemble_officer` today bakes in one placement clip. Add
  `load_instance_clip(iid, nif_path) -> clip_index` so gesture/reaction NIFs can be attached
  to an officer model on demand (lazy, cached per clip).

## Behavior detail

### (a) Placement rest pose — the bug fix

`engine/appc/bridge_placement.py::capture_placement` already returns the right clip + frame
intent. The fix is purely in rendering: instead of playing the clip over its duration,
sample it **once at the rest frame** and hold that palette as the instance's stored rest
pose.

- The rest frame is the existing first-vs-last decision: **frame 0** for `sample_at_start`
  clips (Science/Engineer move-from-station), **last frame** for "stand"/"seated" clips.
  We generalize the native `sample_at_start` settle-immediately logic so the `False` case
  *also* settles immediately — at `t=dur` instead of `t=0`. No play-through either way.
- The `sample_at_start` heuristic (`_FRAME0_FRAGMENTS` in `bridge_placement.py:40`) stays
  as-is. It is adjacent to the bug, not the bug. If the GUI shows a wrong-end officer we
  reclassify that clip, but that is not blocking and not in scope to rework now.
- The placement call at `engine/host_loop.py:2521` switches from the play-through
  `set_instance_animation` to `set_instance_rest_pose`.

### (b) Idle ambient gestures

Per-character independent timer; seeded RNG for testability. On fire: pick a registered
entry respecting standing/sitting mode, call the SDK builder for a `TGSequence`, enqueue.
The controller plays each clip to its authored end, then `AT_DEFAULT` restores the rest
pose. Timer reschedules. Officers are scheduled independently (faithful to the original
per-`CharacterClass` C++ scheduling); the bridge feels continuously alive.

### (c) Hit reactions

On a player-ship `WeaponHitEvent`: compute impact bearing → `ReactLeft`/`ReactRight`; map
damage magnitude → `HitStanding`/`HitHardStanding`/`Blast`. Resolve each visible officer's
registered key for that reaction, build the `TGSequence`, enqueue.

### Priority and preemption

Reactions > idle. Only one transient action per character at a time. A higher-priority
action **cancels** the current one and jumps straight into the reaction's first authored
clip — consistent with authored-transitions-only, since reaction clips are authored to
start from the rest/standing pose. All SDK sequences terminate in `AT_DEFAULT`, so any
action (completed or preempted-then-finished) returns the officer to rest.

## Primary risk — gesture-clip retargeting (Phase 0 spike, gates idle + hit)

The gesture/reaction NIFs (`Yawn_M.NIF`, `react_console_left.NIF`, …) are separate keyframe
files that must **retarget onto our skinned officer skeleton** — their track node names must
match the officer body NIF's bone nodes. Placement clips already work this way, so it is
plausible, but gesture clips may target a different/larger bone set.

**The first task in the implementation plan is a spike:** load one gesture clip onto a posed
officer and confirm it animates correctly on the rig. If retargeting fails or needs real
work, we **fall back to placement-fix-only** and split idle + hit into a follow-up project.
The placement bug fix does not depend on runtime gesture loading and stays unblocked
regardless of the spike outcome.

## Testing

- **Placement fix** — unit test (FakeRenderer): a "stand" placement settles at its rest
  frame immediately, `settled == True` on the load frame, zero play-through. Regression
  guard against the stand-up.
- **Controller** — deterministic queue test: clips advance in order by duration,
  `AT_DEFAULT` restores rest, preempt cancels cleanly. Seeded clock, no GUI.
- **Idle scheduler** — seeded RNG: fires on schedule, only picks valid registered entries,
  respects sitting/standing mode, skips busy characters.
- **Hit mapping** — table test: (bearing, severity) → expected reaction key; left/right and
  light/hard/blast boundaries.
- **GUI verification (Mark)** — the real acceptance gate: officers stand still at load,
  gesture ambiently, flinch on hits with direction/severity correlation. Unit tests guard
  the logic; the GUI confirms the visual.

## Out of scope (deferred to follow-up projects)

- Lipsync / phoneme mouth animation during `SpeakLine` (`AddPhoneme`).
- Guest-chair in/out animations (`PutGuestChairOut`/`PutGuestChairIn`).

## Affected files (anticipated)

- `native/src/scenegraph/include/scenegraph/instance.h` — rest-pose state.
- `native/src/scenegraph/src/world.cc` — rest-pose set/restore.
- `native/src/renderer/animation_update.cc` — transient-completes-to-rest behavior.
- `native/src/host/host_bindings.cc` — `set_instance_rest_pose`, `restore_rest_pose`,
  `load_instance_clip` bindings (triggers `dauntless` rebuild).
- `engine/renderer.py` — Python wrappers for the new bindings.
- `engine/appc/actions.py` — route character-targeted `TGAnimAction` to the new controller.
- `engine/bridge_character_anim.py` (new) — `BridgeCharacterAnimController`, idle scheduler,
  hit handler.
- `engine/host_loop.py` — placement uses `set_instance_rest_pose`; pump the character anim
  controller each tick; wire idle/hit.
- `engine/appc/combat.py` — confirm `WeaponHitEvent` carries hit position; subscribe path.
- `tests/` — placement regression, controller queue, idle scheduler, hit mapping.

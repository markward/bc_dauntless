# Bridge Breathing Idle — Design

**Date:** 2026-06-19
**Status:** Approved design, pending implementation plan
**Scope:** Make bridge officers continuously play their authentic per-station breathing idle
(looping, layered over the placement pose) as their default state, instead of freezing on a
static placement frame. Builds directly on the merged bridge-character-animation system.

## Problem

Bridge officers currently hold a **static** placement frame between gestures — frozen, not
breathing. In the original game every officer continuously plays a subtle looping breathe idle
(the `AddRandomAnimation` gestures play *over* it); without it the bridge feels lifeless between
gestures.

## Principle

SDK-driven and authentic. The officer's idle **posture and motion come entirely from its
registered breathe clip** — we never choose or invent a pose. Engine owns only the policy that
the breathe loops continuously as the default state.

## SDK facts (verified 2026-06-19)

- Every station registers a breathe animation keyed `"<location>Breathe"`, e.g.:
  - `DBHelmBreathe → SeatedM`, `DBTacticalBreathe → SeatedL`, `DBCommanderBreathe → SeatedM`,
    `DBGuestBreathe → SeatedM` (these stations **sit**).
  - `DBScienceBreathe → StandingConsole`, `DBEngineerBreathe → StandingConsole` (these **stand**).
  - E-bridge equivalents (`EBHelmBreathe → SeatedM`, `EBScienceBreathe → SeatedS`, …) and guest
    variants (`X/X1Breathe`).
- The breathe clips (`standing_console.nif` 2.5s, `breathing.nif` 12.1s, `seated_*.nif`, …) are
  **root-less** (no Bip01 translation) full-body idle poses — i.e. they layer over the placement
  exactly like gestures/reactions.
- There is also a `"<location>BreatheTurned"` variant (used when the officer is turned toward
  someone) — **out of scope here**, it belongs with the turn-to-captain follow-up.

## Architecture

### 1. Breathe-clip capture (Python)

`engine/appc/bridge_placement.py` (or a sibling) gains `capture_breathing(character)`, mirroring
`capture_placement`:
- Read `character.GetLocation()`.
- Find the character's `_animations` entry whose key equals `<location>Breathe`.
- Resolve the registered module path → call the SDK builder (e.g.
  `CommonAnimations.StandingConsole(char)`) → extract the clip name → resolve the NIF via
  `g_kAnimationManager.path_for`.
- Return `{"clip_nif": <path>}` or `None` when the officer has no breathe registration.

The breathe clip is the **authoritative idle body pose**; the placement supplies only the root
(position). Layering composes them via the existing `sample_pose_over_base`.

### 2. Native: a looping-layered idle play path

The renderer already supports `loop=true` + `layer_over_rest=true` together (`animation_update.cc`
computes the looped `t` via `fmod`, then samples over the rest pose). Add ONE binding + wrapper:

- `play_instance_idle(iid, clip_index)` — sets the instance's `AnimationState` to
  `{clip_index, loop=true, layer_over_rest=true, start_wall_time=now}`. The breathe loops,
  layered over `inst.rest_pose` (the placement), so the root stays at the station and the body
  takes the breathe pose, cycling forever.
- `engine/renderer.py::play_instance_idle(iid, clip_index)` wrapper (direct `_h` call, existing
  style).

No new sampler, no new `Instance` field, no change to the non-idle paths.

### 3. Breathing becomes the default state

- **At placement** (`engine/host_loop.py::_place_one_character`): after `set_instance_rest_pose`
  (which still sets `rest_pose` = the placement frame 0, the layering anchor), `capture_breathing`,
  `load_instance_clip(breathe_nif)`, and `play_instance_idle(iid, breathe_idx)`. Officers breathe
  from the moment they appear. Register the breathe clip index with the controller so it knows the
  officer's default idle (`controller.set_idle(iid, breathe_idx)`).
- **After a gesture/reaction** (`engine/bridge_character_anim.py`): the controller's completion
  path currently calls `restore_rest_pose(iid)`. It instead **resumes the breathe loop** via
  `play_instance_idle(iid, idle_idx)` when an idle clip is registered for that iid; otherwise it
  falls back to `restore_rest_pose` (static placement) so an officer with no breathe registration
  still behaves correctly.
- **Priority/queue unchanged:** breathing is the *default* (not a queued `_active` action). Idle
  gestures (priority 0) and hit reactions (priority 1) still preempt and queue as before; when an
  officer's transient queue empties, the controller returns to breathing instead of the static
  frame.
- **Mission swap:** the controller's `reset()` clears the per-iid idle registry alongside
  `_active` (officers are re-realised fresh; a stale idle iid must not leak).

## Components & boundaries

- `capture_breathing(character) -> {"clip_nif": str} | None` — pure SDK lookup, headless-safe
  (mirrors `capture_placement`; no renderer dependency).
- `play_instance_idle` binding + wrapper — the only native addition (loop+layer idle).
- `BridgeCharacterAnimController.set_idle(iid, clip_index)` + completion change — the controller
  owns the "default state is the breathe loop" policy and the per-iid idle registry.
- `_place_one_character` wiring — establishes breathing at load.

## Error handling / edge cases

- Officer with no `<location>Breathe` registration → `capture_breathing` returns `None`; no idle
  registered; the officer keeps the existing static-rest behavior (controller falls back to
  `restore_rest_pose`). No crash, no T-pose.
- Hidden / unrealised officers are skipped (same guards as placement/gestures).
- The breathe NIF retargets onto the officer rig the same way gestures do (root-less, Bip01
  family) — already proven by the gesture spike; no new retarget risk.

## Testing

- **`capture_breathing`** — unit test: resolves `<location>Breathe` → the right clip per station
  (helm→SeatedM, engineer→StandingConsole, …); returns `None` when unregistered. Mirrors
  `test_bridge_placement_capture`.
- **Native loop+layer** — C++ test: an instance with `loop=true, layer_over_rest=true` keeps the
  root at the rest-pose station translation across cycling `t` values (root anchored while the
  body animates), and the palette rebuilds each frame (never settles, because looping).
- **Controller** — unit test: after a gesture completes, the controller calls
  `play_instance_idle(iid, idle_idx)` (NOT `restore_rest_pose`) when an idle clip is registered;
  falls back to `restore_rest_pose` when none; `reset()` clears the idle registry.
- **GUI gate (Mark):** each station breathes continuously in its authentic posture (seated
  stations seated, standing standing), positioned correctly at the console; gestures play over
  breathing and return to breathing (no freeze).

## Out of scope (deferred)

- `BreatheTurned` posture selection (belongs with the turn-to-captain follow-up).
- Turn-to-captain on station select (separate queued follow-up).

## Affected files (anticipated)

- `engine/appc/bridge_placement.py` — add `capture_breathing` (or a new `bridge_breathing.py`).
- `native/src/host/host_bindings.cc` — `play_instance_idle` binding (triggers `dauntless` rebuild).
- `engine/renderer.py` — `play_instance_idle` wrapper.
- `engine/bridge_character_anim.py` — `set_idle`, idle registry, completion resumes breathing,
  `reset()` clears the registry.
- `engine/host_loop.py` — `_place_one_character` establishes breathing at placement.
- `tests/` — `capture_breathing` resolution, native loop+layer anchor, controller resume-breathing.

# In-scene orientation family — `AT_TURN` / `AT_GLANCE` + `AT_WATCH_ME` camera framing

**Date:** 2026-07-08
**Status:** Design — approved, pending spec review
**Branch:** `feat/orientation-family` (to be created)
**Follows:** `docs/superpowers/specs/2026-07-07-e1m1-character-walk-on-design.md`
(the `AT_MOVE` movement primitive, merged to main 2026-07-08). This is deferred
follow-up **SP-C** from that work's follow-up list.

## Problem

The `AT_MOVE` walk-on primitive shipped, but the *in-scene orientation* actions
that mission `TGSequence`s use alongside it are still stubs:

- `AT_TURN` / `AT_TURN_BACK` (and the `_NOW` variants) — turn a bridge
  character's body to face a named target ("Captain", "C1", "E", …). Used in
  **10-11 mission files** across the campaign; the dominant in-scene
  choreography verb.
- `AT_GLANCE_AT` / `AT_GLANCE_AWAY` — a quick head/upper-body glance. Used in
  **1 mission** (niche).
- `AT_WATCH_ME` / `AT_STOP_WATCHING_ME` / `AT_LOOK_AT_ME` / `AT_LOOK_AT_ME_NOW`
  — aim the first-person captain's-eye bridge **camera** at the named character.
  Used across **8 mission files**; E1M1's opening leans on them heavily
  (`E1M1.py:1909, 2028-2356`).

Today (`engine/appc/ai.py`, `CharacterAction.Play`): `AT_TURN`/`AT_TURN_BACK`/
`AT_GLANCE_*` fall through to the inline no-op path (they complete but nothing
moves); `AT_WATCH_ME`/`AT_STOP_WATCHING_ME` set/clear `CS_TURNED` and complete.
The other two (`AT_LOOK_AT_ME`/`_NOW`) are untouched no-ops.

### Root-cause reframing — "watch me" is a CAMERA directive

The `AT_MOVE` follow-up list described `AT_WATCH_ME` as "the visual body-yaw
head-track — the character orienting toward the captain," and the shipped code
mapped it to `CS_TURNED` (a character-turn status flag). **That reading is
wrong.** The SDK is decisive:

- In E1M1, `AT_WATCH_ME` actions are named `pWatchPicard`/`pWatchSaffi` and
  bracket the beat where that character is the subject
  (`AddAction(pWatchPicard, pCaptainStand, 0.5)`, `E1M1.py:1923`).
- The same slots are filled interchangeably with **`AT_LOOK_AT_ME`**
  (`E1M1.py:2028-2041`), which unambiguously means *"the camera looks at ME
  (this character)."* `AT_WATCH_ME` is simply the **persistent** form
  ("keep watching me until `AT_STOP_WATCHING_ME`"); `AT_LOOK_AT_ME_NOW` is the
  snap form.
- BC's own camera scripting uses the verb `PlacementWatch` (`E1M1.py:2527`) —
  "watch" is **camera** terminology in BC.

So the "-ME" suffix names the character being framed, and the *camera* does the
watching. There is **no procedural bone-track**. The character-side orientation
is the separate `AT_TURN` family. This is a strict simplification of the
originally-imagined design: no new renderer capability is required.

## The mechanism we are reproducing (SDK ground truth)

### Turns and glances are registered clips (same shape as `AT_MOVE`)

`AT_TURN "Captain"` from location `"DBGuest"` composes the animation key
`"DBGuest" + "Turn" + "Captain"` = `"DBGuestTurnCaptain"`, looks it up in the
character's `AddAnimation` registry, and runs the registered builder:

- `Picard.py:137`: `AddAnimation("DBGuestTurnCaptain",
  "…MediumAnimations.TurnAtXTowardsCaptain")`
- `Picard.py:138`: `AddAnimation("DBGuestBackCaptain",
  "…CommonAnimations.SeatedM")` (the return).

The builder returns a `TGSequence` carrying the officer's **body-turn clip**
(a `TGAnimAction` on the character anim node, e.g. `db_face_capt_h`) and, for
seated officers, a **chair clip** on the bridge-set node. `AT_TURN_BACK`
composes `"…Back" + detail` and plays the reverse. This is the **identical**
composition rule (`key = location + suffix`,
`bridge_placement.py:_resolve_builder_sequence`) that `AT_MOVE` uses, and it is
exactly what our existing crew-menu turn-to-captain already resolves via
`capture_registered_clip(character, "TurnCaptain")`.

Confirmed argument shapes across the campaign:

- `AT_TURN` **always carries a target detail**: `"Captain"` (dominant), plus
  `"C1"`, `"E"`, `"T"`, `"Science"`, `"C"`, `"H"`.
- `AT_TURN_BACK` is **always bare** (no detail) — it reverses whatever the
  character last turned toward, so the reverse key is
  `location + "Back" + <last-turn-detail>`.
- `AT_GLANCE_AT "Left"` → `GlanceLeft` (`CommonAnimations.py:1054`);
  `AT_GLANCE_AWAY` bare → the reverse. Location-independent short clips.

### Camera framing is a look-at spring we already have

`_BridgeCamera.set_zoom_target(world_xyz, dt)` (`host_loop.py:2173`) eases the
captain's-eye camera to frame a world point and suspends free-look while active;
`compute_camera()` blends that look-at with the free-look base pose. This is
what zoom-to-officer uses (`_active_zoom_officer_world`, `host_loop.py:2291`,
resolving the officer's `get_instance_head_center(iid)`). Camera-framing actions
reuse this directly: the aim point is the watched character's head centre.

## Goals / scope

### In scope

**Family A — character-body turn (bones).** `AT_TURN`, `AT_TURN_NOW`,
`AT_TURN_BACK`, `AT_TURN_BACK_NOW`, `AT_GLANCE_AT`, `AT_GLANCE_AWAY`: resolve the
registered turn/glance clip and play it through the **existing**
`bridge_character_anim` controller (body-turn clip + chair coupling + hold/return
already solved), with a new **deferred-completion** hook so a turn inside a
mission `TGSequence` advances when its clip settles.

**Family B — camera framing.** `AT_WATCH_ME`, `AT_STOP_WATCHING_ME`,
`AT_LOOK_AT_ME`, `AT_LOOK_AT_ME_NOW`: aim the captain's-eye camera at the named
character via a new small controller feeding `_BridgeCamera.set_zoom_target`.
Replaces the incorrect `AT_WATCH_ME → CS_TURNED` mapping.

### Out of scope (explicit follow-up tracking — see below)

- The other SP-A/B/D/E follow-ups (primitive-robustness bugs, other-mission
  sweep, lift-door ownership, crew-intro `AT_MENU_UP`/`DOWN`). Family A's turn
  path and the crew-menu turn path share the `bridge_character_anim` controller;
  this spec does **not** re-wire the menu path onto `AT_MENU_UP`/`DOWN`.
- Any baked cutscene camera **path** work (`bridge_cutscene`) — camera framing
  here is a look-at spring, not a keyframed dolly; the baked path retains top
  camera priority.
- Non-bridge (comm-set) orientation.

## Architecture

Two independent mechanisms. Each reuses a proven controller; one tiny new
controller is added for camera framing. **No native/renderer change → no
`dauntless` rebuild.**

### Camera priority (host, per bridge frame)

Single precedence resolver, highest wins:

1. **Baked cutscene camera path** — if `bridge_cutscene` has an active path it
   already drives `set_anim_pose` (unchanged; top priority).
2. **`AT_WATCH_ME` / `AT_LOOK_AT_ME` target** — the watch controller's resolved
   head-centre feeds `set_zoom_target`.
3. **Crew-menu zoom** — the existing `_active_zoom_officer_world`.
4. **Free-look** — default (no target).

Implementation: the current unconditional
`bridge_camera.set_zoom_target(_active_zoom_officer_world(...), dt)` call becomes
`set_zoom_target(_resolve_bridge_focus_world(...), dt)`, where the resolver
returns the watch target if one is set, else the menu-zoom target, else `None`.
The baked-path case is unaffected (it uses `set_anim_pose`, a separate channel
that `compute_camera` already prefers).

### Family A components

**A1. Dispatch — `engine/appc/ai.py` `CharacterAction`.** New branches in
`Play()`:

- `AT_TURN` / `AT_TURN_NOW`: compose suffix `"Turn" + detail`; record
  `self._character._last_turn_detail = detail`; resolve body clip via
  `capture_registered_clip(cc, "Turn" + detail)` and chair via
  `capture_chair_clip(cc, "Turn" + detail)`; `submit()` to the walk/anim
  controller. Non-`NOW` defers completion (fires on settle); `NOW` plays and
  `Completed()` inline.
- `AT_TURN_BACK` / `AT_TURN_BACK_NOW`: read
  `getattr(cc, "_last_turn_detail", "Captain")`; compose `"Back" + detail`;
  resolve + submit the reverse; same deferred/inline rule; clear
  `_last_turn_detail`.
- `AT_GLANCE_AT` / `AT_GLANCE_AWAY`: resolve a glance clip
  (`capture_registered_clip(cc, "Glance" + detail)`, falling back to a direct
  `GlanceLeft`/`GlanceRight` builder resolution if unregistered); submit as a
  React-band transient that returns to the prior pose. Defers completion on
  settle.

All best-effort: no controller, no `CharacterClass` cast, or unresolved clip →
`Completed()` inline so the sequence never stalls. `_do_play` is unchanged
(still handles speak types); these branches intercept before it.

**A2. Deferred completion on `engine/bridge_character_anim.py`.** `submit()`
gains an optional `on_complete` callback stored on `_Action`. `update()` fires
it exactly once when the action finishes:

- non-`hold`: at the moment `_return_to_default` runs (clip settled → idle);
- `hold=True`: when the last clip reaches its end (the hold point), so the
  sequence advances while the turned pose is held.

The crew-menu turn path passes no `on_complete` (unchanged behaviour). This is
the only change to the existing controller; chair coupling, priorities, and
hold/return are untouched.

### Family B components

**B1. Watch controller — `engine/bridge_camera_watch.py` (new).** A minimal
singleton mirroring the other bridge controllers:

- `watch(character, snap=False)` — set `_watched_character` (+ `snap`). Called by
  `AT_WATCH_ME` (persistent), `AT_LOOK_AT_ME` (ease), `AT_LOOK_AT_ME_NOW`
  (`snap=True`). Each call supersedes the prior target (the intro re-points per
  speaker).
- `clear()` — drop the target (`AT_STOP_WATCHING_ME`).
- `resolve_target_world(renderer)` → the watched character's
  `get_instance_head_center(iid)`, or `None` (hidden/unrealized/no renderer).
- `consume_snap()` → `True` once if the last set was a snap (host uses it to jump
  `_zoom_t` to 1 for `_NOW`).
- `reset()` on mission swap; module `get_controller`/`set_controller`/
  `clear_controller` singletons.

**B2. Dispatch — `engine/appc/ai.py`.** `AT_WATCH_ME`/`AT_LOOK_AT_ME`/
`AT_LOOK_AT_ME_NOW` call `watch(cc, snap=…)`; `AT_STOP_WATCHING_ME` calls
`clear()`; all `Completed()` **inline** (camera eases underneath — approved).
Removes the `CS_TURNED` mapping.

**B3. Host wiring — `engine/host_loop.py`.** Construct + reset the watch
controller alongside the walk controller; the `_resolve_bridge_focus_world`
precedence resolver; snap handling on `_NOW`.

## Data flow

```
Mission TGSequence
  AT_TURN "Captain"                         AT_WATCH_ME / AT_LOOK_AT_ME(_NOW)
        │                                          │
        ▼                                          ▼
CharacterAction.Play                        CharacterAction.Play
  suffix "TurnCaptain"                        watch_ctrl.watch(cc, snap)
  capture_registered_clip + chair             Completed() inline
  anim_ctrl.submit(on_complete=Completed)          │
        │  (clip settles)                          ▼ (each bridge frame)
        ▼                                     _resolve_bridge_focus_world:
  on_complete → Completed()                     baked? → set_anim_pose
  → TGSequence advances                         else watch target →
                                                  get_instance_head_center →
                                                  set_zoom_target(head, dt)
                                                else menu-zoom else None
```

## Error handling

Every resolution step is best-effort and collapses to a no-op, consistent with
the `capture_*` helpers and the walk controller: a bad builder import, missing
clip, unrealized/hidden character, or headless renderer makes the turn silently
not play / the camera not move, rather than crashing the mission. Turn/glance
actions always `Completed()` (inline on any failure) so a `TGSequence` can never
stall. Camera-framing actions always `Completed()` inline by design. The
dialogue/speak path is untouched.

## Testing

- **Family A dispatch** (`tests/unit/test_character_action_turn.py`): key
  composition (`DBGuestTurnCaptain`, `Back<lastDetail>` for bare
  `AT_TURN_BACK`), `_last_turn_detail` round-trip, submit to a recording
  controller with `on_complete`, deferred completion (not done until controller
  signals) vs `_NOW` inline, glance best-effort resolution + fallback, and the
  unresolved → inline-completion path.
- **Deferred completion** (`tests/unit/test_bridge_character_anim_complete.py`):
  `submit(on_complete=…)` fires once on settle for non-hold, once at hold-point
  for `hold=True`, and never for a no-`on_complete` submit (menu path
  unchanged).
- **Family B controller** (`tests/unit/test_bridge_camera_watch.py`): `watch` /
  `clear` / `resolve_target_world` (fake renderer head-centre), snap consume,
  target supersession, reset.
- **Focus precedence** (`tests/unit/test_bridge_focus_resolver.py`):
  `_resolve_bridge_focus_world` returns watch target over menu-zoom, menu-zoom
  when no watch, `None` when neither (free-look).
- **Regression**: speak-line completion timing and the existing crew-menu
  turn-to-captain (`bridge_character_anim`) behaviour are unchanged.
- **Gate**: `scripts/check_tests.sh` (pytest + ctest) green; no new
  `tests/known_failures.txt` entries. (No native change, but the gate still runs
  ctest.)
- **GUI verify (final sign-off)** — E1M1 opening + intro: characters turn to
  face the captain on `AT_TURN "Captain"` and return on `AT_TURN_BACK`; the
  camera holds on each character as they're introduced (`AT_WATCH_ME` /
  `AT_LOOK_AT_ME`), snapping on `_NOW`; a baked dolly (walk-on cutscene) still
  overrides the watch framing; crew-menu zoom still works post-mission. The
  render/camera path cannot be asserted headlessly — consistent with prior
  bridge-character sign-offs.

## Follow-ups to pick up after this plan (do not lose)

These remain from the `AT_MOVE` follow-up list and are **not** in this spec:

1. **SP-A primitive-robustness bugs** — walk pump gated on `is_bridge`
   (completion stalls on tactical-view switch / pause mid-walk) and two
   concurrent `AT_MOVE`s on one character overwriting `_active[iid]`. Both
   confirmed on HEAD; small, general-purpose, headlessly testable.
2. **SP-B other-mission `AT_MOVE` sweep** — the 14 non-E1M1 missions using
   `AT_MOVE`; best after SP-A lands.
3. **SP-D lift-door ownership** — camera-path vs `AT_MOVE`-builder door owner;
   verify timing across callers.
4. **SP-E crew-intro completeness** — `AT_MENU_UP`/`AT_MENU_DOWN` (still no-ops),
   which drive the seated-officer turn-to-captain via the same
   `bridge_character_anim` controller this spec extends. Wiring the SDK
   `AT_MENU_*` actions onto that controller's `request_turn`/`request_turn_back`
   (currently driven only by our crew-menu UI) is the natural next step and
   composes cleanly with Family A here.

## Related memories

`project_e1m1_character_walkon`, `project_bridge_character_animation_shipped`,
`project_bridge_camera_walkon`, `project_bridge_character_placement`,
`project_cutscene_camera`, `project_bc_target_camera_auto_engage`,
`feedback_sdk_drives_everything`.

# Real-Duration Completion Gating for Timed Action Sequences — Design

**Date:** 2026-06-18
**Status:** Approved (pending implementation plan)
**Scope:** `engine/appc/actions.py`, `engine/appc/ai.py` (`CharacterAction`),
`engine/appc/crew_speech.py`, `engine/audio/tg_sound.py`, the native audio
subsystem (`native/src/audio/`), and `engine/appc/bridge_set.py` (remove the
interim hold hack). Builds directly on the shipped action-sequence timing system
(`docs/superpowers/specs/2026-06-11-action-sequence-timing-design.md`), which
this design extends — it closes that spec's explicitly-deferred §6.

## Problem

SDK-defined timed cutscene sequences (comm hails, the bridge walk-on, mission
beats) collapse: every step fires in one frame instead of pacing over the real
duration of its dialogue/sound.

**Live evidence — E1M1 Starbase 12 hail.** The briefing sequence
(`E1M1.py:1859-1873`) chains via `AppendAction`:

```
ViewscreenOn → LiuBriefing1 → 2 → 6 → 4 → 5 → 8 → ViewscreenOff
```

Each step gates on the **previous action's `Completed()`**. The dialogue steps
are `CharacterAction(AT_SAY_LINE)`. In `engine/appc/ai.py`,
`CharacterAction._do_play()` calls `crew_speech.emit()` (fire-and-forget) and
the base `TGAction.Play()` immediately calls `self.Completed()`. So every
dialogue step completes the same frame it starts, collapsing the whole chain —
`MissionLib.ViewscreenOn` (MissionLib.py:1271) and `ViewscreenOff`
(MissionLib.py:1340) fire back-to-back. Result: comm dialogue doesn't pace, and
the comm view would revert instantly (currently masked by an interim hold hack
in `bridge_set.py:SetRemoteCam`, added in commit 60419a31).

The `TGSequence` machinery itself is correct (it honors delays + completion
chaining). The defect is that **leaf audio actions report completion instantly
instead of after their audio's real wall-clock duration.**

## Root cause — the three gaps

The prior timing spec's §6 deliberately left these as no-ops:

1. **`CharacterAction` speak-types don't gate on voice duration.** They emit and
   complete inline. *(This is the load-bearing gap for the comm hail.)*
2. **`TGSoundAction` completes instantly** (no real-duration gating), so the
   SDK's "ViewOn whoosh gates ViewscreenOn" pattern is inert.
3. **`g_kTGActionManager` has no `ET_ACTION_COMPLETED` handler**, so the SDK's
   manager-ObjPtr deferred-completion pattern (`ViewscreenOn`/`ViewscreenOff`/
   `PlayDialog`) never fires.

## The SDK completion conventions this design honors

Two distinct mechanisms, both in the SDK ground truth:

- **TGSequence-internal chaining** (our existing mechanism): the sequence
  subscribes to each member's `Completed()` via a private
  `_ET_SEQ_STEP_COMPLETED` event. Works today. The dialogue chain uses this —
  each `CharacterAction` is a sequence member.
- **Manager-ObjPtr deferral** (SDK-literal): a leaf action gets
  `AddCompletedEvent(ET_ACTION_COMPLETED, dest=g_kTGActionManager,
  objptr=pOwnerAction)`. When the leaf finishes, the manager calls
  `pOwnerAction.Completed()`. Used by `ViewscreenOn`/`PlayDialog`
  (MissionLib.py:1290-1301, 688-704).

**Script-action completion convention — the return value.** A `TGScriptAction`'s
target function signals completion through its return value:

- **falsy (`0`/`None`) ⇒ auto-complete.** Instant functions —
  `RemoveControl`, `StartCutscene`, `EndCutscene`, `PreloadSequenceLines` —
  `return 0` ("Return: 0 - Action completed").
- **truthy (`1`) ⇒ deferred; do NOT auto-complete.** `ViewscreenOn` (success
  path) and `PlayDialog` `return 1` and wire a manager-ObjPtr deferred
  completion that fires later.

Our `TGScriptAction._do_play` currently **discards** the return value, so
everything auto-completes — masking the deferred path. Honoring the return value
is the faithful fix.

## Decisions

- **Real audio duration is the source of truth** for how long a speak/sound
  action gates, with a word-estimate fallback for text-only/unloaded/no-backend
  lines. (Chosen over estimate-only and estimate-primary.)
- **Full SDK-literal scope.** Implement all three leaf fixes *and* activate the
  manager-ObjPtr path, so `ViewscreenOn` gates on the ViewOn whoosh and
  `PlayDialog` gates on its sound — not just the minimal CharacterAction fix.
- **Realtime stream for audio completion.** Voice/sound duration is wall-clock;
  schedule completion on `g_kRealtimeTimerManager` (the unscaled stream), so VO
  pacing is independent of game time-scale. Matches CLAUDE.md's two-stream model
  and reuses `TGSequence._schedule_timer`'s proven realtime path.
- **Zero duration ⇒ inline completion.** Preserves the synchronous guarantee:
  the headless/null audio backend reports 0 duration, so existing zero-delay
  sequence tests stay byte-for-byte synchronous. Deferral only activates when
  there is real audio to wait on.

## §1 — Shared primitive: `_complete_after` (base `TGAction`)

Add to `engine/appc/actions.py`:

```
class TGAction:
    _ET_ACTION_DEFERRED_COMPLETE = 0x5E03   # private; routed to self.ProcessEvent

    def _complete_after(self, duration_real_s: float) -> None:
        """Post Completed() after duration_real_s wall-clock seconds via
        g_kRealtimeTimerManager. duration <= 0 completes inline (synchronous)."""
```

- `duration <= 0` → `self.Completed()` inline.
- `duration > 0` → create a one-shot `App.TGTimer_Create()` on
  `App.g_kRealtimeTimerManager` (`SetTimerStart(now+dur)`, `SetDelay(-1.0)`);
  its event has `SetDestination(self)`, type `_ET_ACTION_DEFERRED_COMPLETE`.
  `TGAction.ProcessEvent` handles that type by calling `self.Completed()`.
- Track the pending timer on the instance; `Abort()`/`Stop()` remove it from the
  manager. The fire path and `Completed()` must be defensive (a death-explosion
  sound may outlive its set) — already true of `Completed()`; wrap the timer
  callback so a torn-down world cannot raise.

This is the same timer→event→`ProcessEvent` shape `TGSequence._schedule_timer`
already uses; no new manager or host-loop wiring.

## §2 — Real audio duration (native)

The decoded PCM length and format are known at load but currently discarded.

- **`native/src/audio/src/audio_system.cc`** — at `load_sound`, compute
  `duration_sec = pcm_bytes / (sample_rate · channels · bytes_per_sample)` and
  store it in the per-sound record. Add
  `double AudioSystem::get_duration(const std::string& name) const` (0.0 if
  unknown). Header updated in `native/src/audio/include/...`.
- **`native/src/audio/src/python_binding.cc`** —
  `m.def("get_duration", &get_duration_impl)` (by name, returns float seconds).
- **`engine/audio/tg_sound.py`** — `TGSound.GetDuration() -> float` and/or
  `TGSoundManager.duration_for(name) -> float` delegating to
  `_audio.get_duration(name)`; returns `0.0` when `_audio` is absent (tests) or
  the sound is unloaded.

Rebuild required: `cmake -B build -S . && cmake --build build -j`. Per the build
rules, rebuild from `build/` (the audio module is compiled into the tree); a
stale binary would expose WAV-only / no `get_duration`.

## §3 — Wire the four touch-points

**`CharacterAction` speak-types** (`engine/appc/ai.py`). The bus computes **one**
duration and returns it; the action defers on it:

- `engine/appc/crew_speech.py`: `bus.speak(...)` resolves
  `duration = real-audio-duration if wav loaded else _estimate_duration(text,
  wav)` and uses that single value for subtitle dwell, bus expiry, **and**
  returns it. `emit(...)` returns the duration (0.0 if the line was dropped /
  nothing to say).
- `CharacterAction`: for `AT_SPEAK_LINE`/`AT_SPEAK_LINE_NO_FLAP_LIPS`/
  `AT_SAY_LINE`/`AT_SAY_LINE_AFTER_TURN`, after `emit` returns `dur`, call
  `self._complete_after(dur)` instead of completing inline. All other action
  types complete inline (unchanged). Implemented via a `Play()` override (or an
  internal `_deferred` flag), mirroring the existing `TGAnimAction` pattern.

**`TGSoundAction`** (`engine/appc/actions.py`). `Play()` runs `_do_play()` (plays
the sound), captures the real duration
(`TGSoundManager.duration_for(self._sound_name)`), and calls
`self._complete_after(dur)`. Zero duration → inline. Effects-explosion and
RedAlert sounds are root/last sequence steps (verified: `Effects.py:579`
`AddAction` parallel; `MissionLib.py:2846` last `AppendAction`), so their
deferral only delays harmless sequence self-completion, never a visible step.

**`TGScriptAction`** (`engine/appc/actions.py`). Honor the return value: capture
`ret = fn(self, *args)`; if `ret` is truthy, mark deferred and do **not**
auto-complete; if falsy/`None`, auto-complete inline (today's behavior). The
recursion-guard / missing-module / missing-fn early returns yield `None` →
auto-complete, unchanged.

**`g_kTGActionManager`** (`TGActionManager.ProcessEvent`,
`engine/appc/actions.py`). On `App.ET_ACTION_COMPLETED`, read the event's
`GetObjPtr()` and call `objptr.Completed()` (guarded). This fires the deferred
`TGScriptAction` (e.g. `ViewscreenOn`) when its ViewOn `TGSoundAction` completes
after the whoosh's real duration.

**End-to-end trace (E1M1 hail), all changes applied:**

1. Sequence fires `pStarbaseViewOn` (`TGScriptAction`). `_do_play` calls
   `MissionLib.ViewscreenOn(...)`, which plays the `ViewOn` `TGSoundAction`
   (wired `ET_ACTION_COMPLETED → g_kTGActionManager, objptr=pStarbaseViewOn`)
   and returns `1`.
2. Return is truthy → `pStarbaseViewOn` deferred; sequence waits. View is ON.
3. ~0.5 s (realtime) later the `ViewOn` sound's deferred timer fires →
   `sound.Completed()` → `ET_ACTION_COMPLETED` to `g_kTGActionManager` →
   `pStarbaseViewOn.Completed()` → `_ET_SEQ_STEP_COMPLETED` → sequence advances.
4. `pLiuBriefing1..8` (`CharacterAction`) each fire, emit Liu's line, and defer
   completion by the line's real audio duration. View stays on throughout.
5. After `pLiuBriefing8` completes, `pViewOff` fires →
   `MissionLib.ViewscreenOff` reverts the remote cam to the player camera,
   returns `0` → auto-completes → `pPicardWalkOn` fires.

Comm dialogue plays in sync; the view holds for the dialogue then reverts
naturally to the forward view.

## §4 — Remove the interim hold hack

With timing correct, `ViewscreenOff` fires only *after* the dialogue. It sets the
viewscreen remote cam to `Game.GetPlayerCamera()` — a truthy stub here, not a
real `CameraObjectClass`. `host_loop._active_comm_feed` returns `None` for any
remote cam that is not a comm-set `maincamera`, so the host falls back to the
forward view. That is the natural, correct revert.

- `engine/appc/bridge_set.py:ViewScreenObject.SetRemoteCam` → delete the hold;
  restore `self._remote_cam = cam`.
- Delete `tests/unit/test_viewscreen_remote_cam_latch.py`.
- Confirm (live + integration) the comm scene still persists for the dialogue
  and then reverts to the forward view.

## §5 — Units, boundaries, dependencies

- **`_complete_after`** (base `TGAction`): one purpose — "complete me after N
  realtime seconds." Depends only on `App.g_kRealtimeTimerManager` +
  `App.TGTimer_Create`. Independently unit-testable by ticking the realtime
  manager.
- **`audio.get_duration` / `TGSound.GetDuration`**: one purpose — report a loaded
  sound's length. Depends on the audio backend; returns 0 without it.
- **`crew_speech` duration**: single source feeding subtitle + bus + action, so
  they cannot disagree.
- **`TGActionManager` ET_ACTION_COMPLETED**: one purpose — route a leaf's
  completion to its declared owner action.

Each touch-point is small and observable from outside without reading internals.

## §6 — Risks and mitigations

- **Honoring `TGScriptAction` return value could hang a sequence** if some
  target function returns truthy without wiring a deferred completion.
  Mitigation: audit the finite set of functions used as `TGScriptAction_Create`
  targets (grep the SDK) for return-truthy-without-deferral; this matches SDK
  semantics (such a function would hang in BC too). Mission integration tests
  (`tests/integration/tutorial/test_m3gameflow.py`, tutorial flow) and the live
  E1M1 run catch any hang.
- **Manager activation shifts `PlayDialog` pacing** — a change the prior spec's
  §6 deliberately avoided. It is more faithful (the next step now waits for the
  VO). `PlayDialog` is not used in the E1M1 briefing, so the comm hail is
  unaffected; verify no regression via integration tests and normal-play crew
  speech.
- **Deferred completion outliving a torn-down world** (death-explosion sound on
  a destroyed ship). Mitigation: the timer-fire path and `Completed()` are
  guarded so a missing set/object cannot raise; `Abort()`/`Stop()` cancel
  pending timers.
- **Bridge walk-on cutscene** (`project_bridge_camera_walkon`) shares this very
  E1M1 sequence (`pWalkSequence`, `pPicardWalkOn`, `pCrewIntros`). Correct
  timing should help it; verify it still plays (camera path + crew intros) and
  has not regressed.

## §7 — Testing (TDD)

New/updated unit tests (`tests/unit/test_actions.py` or a focused sibling):

- `_complete_after(0)` completes inline; `_complete_after(d>0)` does not complete
  until the realtime manager advances past `d`, then completes exactly once.
- `CharacterAction` speak-type gates a sequence step by its real (mocked)
  duration: next step does not fire at `d-ε`, fires at `d+ε`.
- `CharacterAction` non-speak types still complete inline.
- `TGSoundAction` gates by its (mocked) duration; zero duration ⇒ inline.
- `TGScriptAction` defers when its target returns truthy, auto-completes when it
  returns falsy/`None`.
- `g_kTGActionManager` calls `objptr.Completed()` on `ET_ACTION_COMPLETED`.
- Zero-duration synchronous preservation: a sequence of zero-duration audio
  actions fully resolves within the launching `Play()` call.
- `crew_speech` returns one duration that equals subtitle dwell and bus expiry.

Regression gate (must stay green): existing `tests/unit/test_actions.py`,
`tests/unit/test_particles_sequence.py`,
`tests/integration/tutorial/test_m3gameflow.py`. Delete
`tests/unit/test_viewscreen_remote_cam_latch.py` (its behavior is removed).
Run focused subsets; full `uv run pytest` via `scripts/run_tests.sh`.

Live verification (Mark drives the GUI): `./build/dauntless --developer` → load
E1M1 → trigger the Starbase 12 hail. Target: Liu speaks, the view holds for the
line(s), then returns to the forward view. Plus: bridge walk-on cutscene and
normal-play crew speech unchanged.

## §8 — Out of scope

- Lip-sync / phoneme-driven mouth animation (duration only, not visemes).
- Skippable-action / cutscene-skip fast-forward semantics
  (`SetSkippable`/`Skip`) beyond what already exists.
- Save/load of a mid-flight sequence (pending deferred-completion timers).
  Sequences remain transient and are not pickled.
- Any host-loop or renderer change beyond removing the comm-feed hold hack.

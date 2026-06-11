# Timed / Dependency-Aware Action Sequences — Design

**Date:** 2026-06-11
**Status:** Approved (pending implementation plan)
**Scope:** `engine/appc/actions.py` and its wiring into the existing timer
(`engine/appc/timers.py`) and event (`engine/appc/events.py`) managers. No
host-loop change. No changes to `Effects.py`, the particle backend, or any
mission script.

## Problem

Phase 1's action system executes synchronously. `TGSequence.AddAction(action,
dependency, delay)` captures the dependency/delay args in `*extra` and discards
them; `Play()`/`Start()`/`_do_play()` fire every child immediately in insertion
order. Any SDK sequence built with timed or dependency-chained steps collapses
to one simultaneous burst. The most visible symptom is ship-death explosion
cascades (`Effects.ObjectExploding`) that should play over 5–15 s firing all at
once.

The goal: make sequences honor real game-time delays and completion
dependencies, building on the existing game-time `TGTimerManager`
(`AddTimer()`/`tick()`, already advanced every frame by
`engine/core/loop.py:24`) and the existing completion-event plumbing
(`TGAction.Completed()` already posts events to `g_kEventManager`).

## Key architectural facts this design relies on

1. **`TGEventManager.AddEvent` dispatches inline / synchronously**
   (`engine/appc/events.py:264`). It is not a queue. A completion event posted
   during `Play()` is processed within the same call stack.
2. **`g_kTimerManager` is ticked every frame** by `GameLoop.tick`
   (`engine/core/loop.py:24`). The integration point for game-time delays
   already exists; no host-loop change is needed.
3. **`TGAction.Completed()` already posts completion events.** Deferred
   completion (a condition flipping on a future frame) is therefore already
   expressible through the existing event bus.

Consequence: a zero-delay dependency chain **already resolves fully
synchronously** through inline event dispatch. Frames are only ever spanned
when a real `delay > 0` or a genuinely-deferred completion exists. This is what
makes the synchronous-caller compatibility guarantee fall out for free rather
than requiring an opt-in flag.

## Decisions

- **Unified event-driven model** (not opt-in async, not global async). One
  execution path for all sequences. Zero-delay sequences stay byte-for-byte
  synchronous automatically.
- **Inter-step delay only.** An action completes the instant its `Play()`
  returns (today's behavior), except for genuinely-deferred actions (§4). The
  thing that spans frames is the explicit `delay` arg on
  `AddAction`/`AppendAction`. An action's own duration (sound length, subtitle
  dwell) does **not** gate the next step.
- **Honor deferred completion.** A dependent step waits across however many
  frames it takes for its dependency to actually complete — including
  `TGConditionAction` gates and externally-posted completed-events.

## §1 — API semantics (the contract)

`AddAction` / `AppendAction` parse `*extra` **by type**: a `TGAction` arg is a
dependency; a number is a delay (seconds).

| Call | Dependency | Delay | Starts at |
|---|---|---|---|
| `AddAction(a)` | None | 0 | sequence start (parallel) |
| `AddAction(a, dep)` | `dep` | 0 | when `dep` completes |
| `AddAction(a, dep, d)` | `dep` | `d` | `d` s after `dep` completes |
| `AppendAction(a)` | previous action | 0 | when previous action completes |
| `AppendAction(a, d)` | previous action | `d` | `d` s after previous completes |

Rules:

- **`AddAction` = parallel / explicit dependency.** With no extra args the
  action is a *root* step (dependency `None`) and fires at sequence start.
- **`AppendAction` = sequential chain.** Its implicit dependency is the
  *previous* action added to the sequence by either method, in insertion order.
  If it is the first action, its dependency is `None` (fires at sequence start).
- **Throwaway-null dependency idiom.** The SDK passes a fresh
  `App.TGAction_CreateNull()` as the dependency to anchor a pure time delay to
  sequence start, e.g.
  `AddAction(pExplosion, App.TGAction_CreateNull(), 0.15)` = "fire 0.15 s after
  sequence start." Such a dependency is not a sequence member; the sequence
  plays it at start so it completes immediately, anchoring the delay at t=0.
- **Delay is always measured from the dependency's completion time**, never
  from sequence start directly (sequence start is just the completion time of a
  `None`/throwaway dependency).

This section encodes inferred BC semantics derived from SDK usage
(`Effects.ObjectExploding` cascade, `MissionLib` dialog/game-over sequences),
not from a documented Appc spec.

## §2 — Internal representation

`TGSequence` stops storing bare actions. It stores ordered `_Step` records:

```
_Step:
    action      : TGAction
    dependency  : TGAction | None   # None => root (fires at sequence start)
    delay       : float             # seconds; 0 => fire on dependency completion
```

`GetNumActions()` / `GetAction(index)` continue to index the member-action list
(so existing tests that count actions keep passing). `AddAction`/`AppendAction`
append a `_Step`; `AppendAction` resolves its implicit dependency to the
member action of the previously appended step (or `None` if first).

## §3 — Execution engine (sequence-owned)

State and scheduling live on the `TGSequence` instance (self-contained and unit
testable). The same engine backs both `Play()` (fires children with `.Play()`)
and `Start()` (the particle entry point — fires children with `.Start()` where
available, else `.Play()`); the only difference is the verb used to launch a
child.

On launch:

1. Record `start_time = App.g_kTimerManager.get_time()`.
2. **Subscribe to every member action's completion.** For each member action,
   append an internal completion event to it via `AddCompletedEvent`: a
   `TGObjPtrEvent` with destination = this sequence, `ObjPtr` = the action, and
   a private event type (distinct from the SDK's `ET_ACTION_COMPLETED` so we
   never collide with mission handlers). When the action calls `Completed()`,
   this event is posted and routed back to the sequence's `ProcessEvent`.
3. **Play any non-member dependency** (the throwaway-null idiom) once at start
   so it completes immediately and anchors its dependents at t=0. Subscribe to
   it the same way.
4. **Fire all root steps** (dependency `None`) immediately, using the launch
   verb.

When `ProcessEvent` receives a member/dependency completion event, the sequence
marks that action complete and **schedules every step that depends on it**:

- `delay <= 0` → launch the step's action **inline** (same call stack —
  synchronous).
- `delay > 0` → create a one-shot `TGTimer` (start = current manager time +
  delay, delay/period = -1 so it fires once then marks itself done) added to
  the appropriate manager. The timer's event, when it fires on a future
  frame's `tick`, is routed to the sequence's `ProcessEvent`, which launches
  the step's action. Timers default to game-time (`g_kTimerManager`); an action
  whose `IsUseRealTime()` is true routes through `g_kRealtimeTimerManager`.

Routing both completion events and timer events to the same `ProcessEvent`
handler keeps all sequence advancement in one place. The handler distinguishes
"a dependency completed" from "a delay timer fired" by event type.

**Synchronous preservation:** because `AddEvent` dispatches inline, a sequence
whose steps are all zero-delay and instantaneous resolves entirely within the
launching `Play()` call — identical to today's behavior.

## §4 — Deferred completion and the condition-action fix

Today `TGAction.Play()` unconditionally calls `Completed()` at the end. This is
correct for instantaneous actions but wrong for `TGConditionAction`, which
currently "completes" on `Play()` even when its condition has not fired —
masking the dependency that SDK sequence gates rely on.

Fix: `TGConditionAction.Play()` runs `_do_play()` (which may detect an
already-satisfied condition) and calls `Completed()` **only if** a condition is
already satisfied. Otherwise it stays in `TGCA_WAIT` and calls `Completed()`
later from `ConditionChanged()` when a condition actually flips. A sequence step
gated on a condition action therefore waits across frames until the condition
fires.

No other action type changes. `TGScriptAction`, `TGNullAction`, `TGSoundAction`,
`TGCreditAction`, and `SubtitleAction` keep completing inline on `Play()`.
Externally-deferred completion (a mission posting `Completed()` from its own
event handler on a later frame) is already handled by the inline event bus and
needs no special case.

## §5 — Sequence self-completion

A `TGSequence` fires its **own** `AddCompletedEvent` list (e.g. `PlayDialog`'s
"end of dialog" hook) only when **all member steps have completed and no
delay timers remain outstanding** — not unconditionally at the end of `Play()`.

A sequence whose steps are all instantaneous and zero-delay still completes
inline within the launching call (the last completion event resolves the final
step synchronously), so `test_sequence_play_completes_self` and equivalent
synchronous expectations remain green.

## §6 — Out of scope (explicit)

- **The `PlayDialog` manager-ObjPtr pattern stays a no-op, as today.**
  `MissionLib.PlayDialog` wires `pSound.AddCompletedEvent(event(dest=
  g_kTGActionManager, ObjPtr=pSubtitle))`. Today `g_kTGActionManager` has no
  `ET_ACTION_COMPLETED` handler, so this is inert and sound+subtitle both fire
  at sequence start. This design does **not** change that: dialog sound and
  subtitle continue to fire together. Dialog pacing is not the target, and
  activating the manager-ObjPtr path risks dialog regressions.
- **Save/load of a mid-flight sequence** (pending timers, partially-completed
  steps). Sequences are transient (death effects, dialogs) and are not pickled
  today.
- **No changes** to `Effects.py`, the particle backend, the host loop, or any
  mission script. This is purely the general action model.

## §7 — Testing

New unit tests in `tests/unit/test_actions.py` (or a focused sibling):

- `AddAction` with no args fires all roots at sequence start (parallel).
- `AppendAction` chains each action to the completion of the previous one.
- `AddAction(a, dep)` gates `a` on `dep`'s completion.
- Delay timing: `AddAction(a, null, d)` fires `a` after `d` game-seconds —
  advance the clock via `loop.tick()` / `g_kTimerManager.tick(delta)` and assert
  the firing frame (e.g. nothing at `d - ε`, fired at `d + ε`).
- Condition-gate deferral: a step gated on a `TGConditionAction` does not fire
  until the condition flips on a later frame.
- Zero-delay synchronous preservation: a sequence of zero-delay instantaneous
  actions fully resolves within the `Play()` call.
- Sequence self-completion fires after the last outstanding step/timer.

Regression gate (must stay green): existing `tests/unit/test_actions.py`,
`tests/unit/test_particles_sequence.py`,
`tests/integration/tutorial/test_m3gameflow.py`. Run focused subsets only —
full `uv run pytest` against the whole suite OOMs the host.

## Risks and mitigations

- **Subtle change to `TGSequence.Play()` completion timing** could break a
  caller that reads sequence state right after `Play()`. Mitigation: the
  regression survey found no mission caller that reads sequence state
  post-`Play()`; all are fire-and-forget. The zero-delay synchronous path is
  preserved by inline event dispatch.
- **Type-based arg parsing** (`TGAction` ⇒ dependency, number ⇒ delay) must
  handle `None` dependencies and numeric delays robustly. Covered by unit tests
  for each signature form in §1.
- **Timer leakage** if a sequence is abandoned mid-flight. `Stop()`/`Abort()`
  must remove any outstanding timers it created from the manager.

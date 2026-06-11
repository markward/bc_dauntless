# Timed / Dependency-Aware Action Sequences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `TGSequence` honor real game-time delays and completion dependencies so timed/dependency-chained SDK sequences (e.g. ship-death explosion cascades) play out over time instead of as one simultaneous burst.

**Architecture:** A single event-driven model. Each sequence stores ordered `_Step(action, dependency, delay)` records. On launch it subscribes to every action's completion via the existing `AddCompletedEvent` plumbing; when a dependency completes it launches dependents inline (delay 0) or schedules a one-shot `TGTimer` on the already-ticked `g_kTimerManager` (delay > 0). Because `TGEventManager.AddEvent` dispatches inline, zero-delay sequences stay byte-for-byte synchronous; frames are only spanned when a real delay or a deferred completion (a condition flip) exists.

**Tech Stack:** Python (Phase 1 headless engine), pytest. Touches `engine/appc/actions.py` only (plus its existing wiring through `engine/appc/timers.py`, `engine/appc/events.py`, and the `App` shim). No host-loop, `Effects.py`, or particle-backend changes.

**Spec:** `docs/superpowers/specs/2026-06-11-action-sequence-timing-design.md`

---

## File Structure

- **Modify:** `engine/appc/actions.py` — all production changes live here:
  - Private event-type constants for the scheduler.
  - `_Step` record + `_parse_extra` helper.
  - `TGSequence` rewrite: storage, launch engine, `ProcessEvent` routing, timer scheduling, self-completion, `Stop`/`Abort` cleanup.
  - `TGConditionAction.Play` deferred-completion fix.
- **Modify (tests):** `tests/unit/test_actions.py` — new sequence-timing tests.
- **Modify (test, behavior change):** `tests/unit/test_particles_sequence.py` — update the one test that encodes the old "delay ignored" bug.

No other files change. `GetNumActions`/`GetAction`, the `TGActionManager` registry, `TGSoundAction`, `TGCreditAction`, `SubtitleAction`, and the `TGObjPtrEvent` class are untouched except where noted.

---

## Conventions for every task

- Run focused test subsets only — **never** `uv run pytest` over the whole suite (it OOMs the host).
- Run from the project root: `/Users/mward/Documents/Projects/bc_dauntless`.
- `App` is the project-root shim; `import App` inside tests resolves to it.

---

## Task 1: `_Step` storage + type-based arg parsing

Replace `TGSequence`'s bare-action list with ordered `_Step` records and parse `*extra` by type (a `TGAction` is a dependency, a number is a delay). `GetNumActions`/`GetAction` continue to index the member actions so existing tests pass.

**Files:**
- Modify: `engine/appc/actions.py` (class `TGSequence`, lines ~127–169; add `_Step` + `_parse_extra` just above the class)
- Test: `tests/unit/test_actions.py`

- [ ] **Step 1: Write failing tests for storage + parsing**

Add to `tests/unit/test_actions.py`:

```python
# ── TGSequence step model ────────────────────────────────────────────────────

def test_add_action_stores_step_with_no_dependency():
    from engine.appc.actions import TGSequence_Create, _parse_extra
    s = TGSequence_Create()
    a = App.TGAction_CreateNull()
    s.AddAction(a)
    assert s.GetNumActions() == 1
    assert s.GetAction(0) is a
    assert s._steps[0].dependency is None
    assert s._steps[0].delay == 0.0


def test_add_action_parses_dependency_and_delay_by_type():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    dep = App.TGAction_CreateNull()
    a = App.TGAction_CreateNull()
    s.AddAction(a, dep, 1.5)
    step = s._steps[0]
    assert step.dependency is dep
    assert step.delay == 1.5


def test_add_action_delay_only_arg_is_delay_not_dependency():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    a = App.TGAction_CreateNull()
    s.AddAction(a, 2.0)
    assert s._steps[0].dependency is None
    assert s._steps[0].delay == 2.0


def test_append_action_chains_to_previous_action():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    first = App.TGAction_CreateNull()
    second = App.TGAction_CreateNull()
    s.AppendAction(first)
    s.AppendAction(second, 0.25)
    assert s._steps[0].dependency is None           # first chains to start
    assert s._steps[1].dependency is first          # second chains to first
    assert s._steps[1].delay == 0.25


def test_parse_extra_helper():
    from engine.appc.actions import _parse_extra
    dep = App.TGAction_CreateNull()
    assert _parse_extra(()) == (None, 0.0)
    assert _parse_extra((dep,)) == (dep, 0.0)
    assert _parse_extra((3,)) == (None, 3.0)
    assert _parse_extra((dep, 0.5)) == (dep, 0.5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "step or parse_extra or chains_to_previous or delay_only" -v`
Expected: FAIL (`_parse_extra` import error / `_steps` attribute missing).

- [ ] **Step 3: Implement `_Step` + `_parse_extra` + storage refactor**

In `engine/appc/actions.py`, just above `class TGSequence`, add:

```python
class _Step:
    """One scheduled action within a TGSequence.

    `dependency` None means the step is a root (fires at sequence start).
    `delay` is seconds measured from the dependency's completion.
    """
    __slots__ = ("action", "dependency", "delay", "started")

    def __init__(self, action, dependency, delay):
        self.action = action
        self.dependency = dependency
        self.delay = float(delay)
        self.started = False


def _parse_extra(extra):
    """Resolve TGSequence AddAction/AppendAction *extra args by type:
    a TGAction is the dependency; a number is the delay (seconds).
    Returns (dependency_or_None, delay_float)."""
    dependency = None
    delay = 0.0
    for arg in extra:
        if isinstance(arg, TGAction):
            dependency = arg
        elif isinstance(arg, (int, float)):
            delay = float(arg)
    return dependency, delay
```

Then replace the `TGSequence.__init__`, `AddAction`, `AppendAction`, `GetNumActions`, and `GetAction` bodies (leave `_do_play`/`Start`/`Stop` for Task 2):

```python
class TGSequence(TGAction):
    def __init__(self):
        super().__init__()
        self._steps: list[_Step] = []
        self._verb: str = "Play"
        self._completed_actions: set[int] = set()
        self._pending_timers: list = []   # (manager, _Step, TGTimer)

    def AddAction(self, action: TGAction, *extra) -> None:
        """Add a parallel/explicit-dependency step. With no extra args the
        action is a root (fires at sequence start)."""
        dependency, delay = _parse_extra(extra)
        self._steps.append(_Step(action, dependency, delay))

    def AppendAction(self, action: TGAction, *extra) -> None:
        """Append a step chained to the previously added action. An explicit
        dependency arg overrides the implicit chain; a numeric arg is the delay."""
        dependency, delay = _parse_extra(extra)
        if dependency is None and self._steps:
            dependency = self._steps[-1].action
        self._steps.append(_Step(action, dependency, delay))

    def GetNumActions(self) -> int:
        return len(self._steps)

    def GetAction(self, index: int) -> "TGAction | None":
        if 0 <= index < len(self._steps):
            return self._steps[index].action
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "step or parse_extra or chains_to_previous or delay_only" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "refactor(actions): TGSequence stores _Step records with typed arg parsing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Synchronous launch engine (roots, completion subscription, dependency gating, self-completion)

Implement the inline (zero-delay) half of the engine: `Play()`/`Start()` launch roots, subscribe to each action's completion, route completion events back to the sequence, fire zero-delay dependents inline, and self-complete when all steps are done. No timers yet (delay > 0 is Task 3).

**Files:**
- Modify: `engine/appc/actions.py` (class `TGSequence`; add private event constants near the top of the file)
- Test: `tests/unit/test_actions.py`

- [ ] **Step 1: Write failing tests for the synchronous engine**

Add to `tests/unit/test_actions.py`:

```python
# ── TGSequence synchronous launch engine ─────────────────────────────────────

class _RecordingAction(TGAction):
    """Test action that records the order in which it was played."""
    def __init__(self, log, tag):
        super().__init__()
        self._log = log
        self._tag = tag

    def _do_play(self):
        self._log.append(self._tag)


def test_add_action_roots_fire_in_parallel_on_play():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "a"))
    s.AddAction(_RecordingAction(log, "b"))
    s.Play()
    assert log == ["a", "b"]          # both roots fired


def test_append_action_zero_delay_chains_inline():
    log = []
    s = App.TGSequence_Create()
    s.AppendAction(_RecordingAction(log, "a"))
    s.AppendAction(_RecordingAction(log, "b"))   # depends on a, delay 0
    s.Play()
    assert log == ["a", "b"]          # b fired inline after a completed


def test_explicit_dependency_zero_delay_fires_inline():
    log = []
    s = App.TGSequence_Create()
    dep = _RecordingAction(log, "dep")
    s.AddAction(dep)
    s.AddAction(_RecordingAction(log, "next"), dep)
    s.Play()
    assert log == ["dep", "next"]


def test_sequence_not_playing_after_synchronous_completion():
    s = App.TGSequence_Create()
    s.AddAction(App.TGAction_CreateNull())
    s.Play()
    assert not s.IsPlaying()


def test_sequence_fires_own_completed_event_when_all_done():
    import sys, types
    fired = []
    mod = types.ModuleType("_test_seq_done")
    mod.on_done = lambda obj, ev: fired.append(True)
    sys.modules["_test_seq_done"] = mod
    App.g_kTGActionManager.AddPythonFuncHandlerForInstance(
        App.ET_ACTION_COMPLETED, "_test_seq_done.on_done")

    s = App.TGSequence_Create()
    s.AddAction(App.TGAction_CreateNull())
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_ACTION_COMPLETED)
    ev.SetDestination(App.g_kTGActionManager)
    s.AddCompletedEvent(ev)
    s.Play()

    assert fired == [True]
    App.g_kTGActionManager.RemoveHandlerForInstance(
        App.ET_ACTION_COMPLETED, "_test_seq_done.on_done")
    del sys.modules["_test_seq_done"]
```

Add `TGAction` to the existing import block at the top of `tests/unit/test_actions.py` if not already imported (it is, via the existing `from engine.appc.actions import (... TGAction ...)`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "roots_fire or chains_inline or explicit_dependency or not_playing_after or own_completed_event" -v`
Expected: FAIL (roots fire but dependents never do; sequence completes unconditionally / at wrong time).

- [ ] **Step 3: Add private event constants**

Near the top of `engine/appc/actions.py` (just below the existing imports), add:

```python
# Private event types used only by the TGSequence scheduler. They are delivered
# directly to the owning sequence via event destination routing and never reach
# the SDK broadcast bus, so the values only need to be unique within a sequence's
# ProcessEvent. Kept well outside the SDK's ET_* ranges (100s/200s).
_ET_SEQ_STEP_COMPLETED = 0x5E01   # a tracked action finished -> advance dependents
_ET_SEQ_TIMER_FIRED    = 0x5E02   # a delay timer elapsed -> launch the pending step
```

- [ ] **Step 4: Implement the synchronous engine on `TGSequence`**

Replace `TGSequence`'s `_do_play`, `Start`, and `Stop` methods (Task 1 already replaced the rest) with the engine below. (`Stop`/`Abort` timer cleanup is finished in Task 5; `_schedule_timer` is added in Task 3 — for now a delay > 0 step raises nothing because Task 2 tests use only zero-delay, but include the `delay <= 0` branch and a `_schedule_timer` call so the structure is final.)

```python
    # ── launch ──────────────────────────────────────────────────────────────
    def Play(self) -> None:
        self._launch("Play")

    def Start(self) -> None:
        """Particle-effect entry point: launch children with Start() where
        available (plain actions and sub-sequences fall back to Play())."""
        self._launch("Start")

    def _launch(self, verb: str) -> None:
        self._playing = True
        self._verb = verb
        self._completed_actions = set()
        self._pending_timers = []

        # Subscribe to completion of every member action and every dependency
        # (including the throwaway-null idiom used to anchor a delay at t=0).
        tracked = {}
        for step in self._steps:
            tracked[id(step.action)] = step.action
            if step.dependency is not None:
                tracked[id(step.dependency)] = step.dependency
        for action in tracked.values():
            self._subscribe_completion(action)

        # Play non-member dependencies now so they complete at sequence start
        # and anchor their dependents' delays at t=0.
        member_ids = {id(s.action) for s in self._steps}
        for action in list(tracked.values()):
            if id(action) not in member_ids:
                self._fire(action)

        # Fire all root steps (no dependency) immediately.
        for step in self._steps:
            if step.dependency is None:
                self._begin_step(step)

        self._maybe_complete()

    def _subscribe_completion(self, action) -> None:
        ev = TGObjPtrEvent()
        ev.SetEventType(_ET_SEQ_STEP_COMPLETED)
        ev.SetDestination(self)
        ev.SetObjPtr(action)
        action.AddCompletedEvent(ev)

    def _fire(self, action) -> None:
        """Launch an action using the sequence's verb, mirroring the legacy
        Start() routing (Start for non-sequence actions that support it)."""
        if (self._verb == "Start" and hasattr(action, "Start")
                and not isinstance(action, TGSequence)):
            action.Start()
        else:
            action.Play()

    def _begin_step(self, step: "_Step") -> None:
        if step.started:
            return
        step.started = True
        if step.delay <= 0:
            self._fire(step.action)
        else:
            self._schedule_timer(step)

    # ── event routing ───────────────────────────────────────────────────────
    def ProcessEvent(self, event) -> None:
        et = event.GetEventType()
        if et == _ET_SEQ_STEP_COMPLETED:
            self._on_dependency_complete(event.GetObjPtr())
            return
        if et == _ET_SEQ_TIMER_FIRED:
            self._on_timer_fired(event.GetObjPtr())
            return
        super().ProcessEvent(event)

    def _on_dependency_complete(self, action) -> None:
        self._completed_actions.add(id(action))
        for step in self._steps:
            if (not step.started and step.dependency is not None
                    and step.dependency is action):
                self._begin_step(step)
        self._maybe_complete()

    def _on_timer_fired(self, step) -> None:
        self._pending_timers = [
            rec for rec in self._pending_timers if rec[1] is not step
        ]
        self._fire(step.action)
        self._maybe_complete()

    # ── completion ──────────────────────────────────────────────────────────
    def _maybe_complete(self) -> None:
        if not self._playing:
            return
        if self._pending_timers:
            return
        if any(not s.started for s in self._steps):
            return
        member_ids = {id(s.action) for s in self._steps}
        if not member_ids.issubset(self._completed_actions):
            return
        self.Completed()

    def _schedule_timer(self, step: "_Step") -> None:
        # Implemented in Task 3.
        raise NotImplementedError

    def Stop(self) -> None:
        for mgr, _step, timer in self._pending_timers:
            mgr.RemoveTimer(timer)
        self._pending_timers = []
        for step in self._steps:
            action = step.action
            if hasattr(action, "Stop") and not isinstance(action, TGSequence):
                action.Stop()
            else:
                action.Abort()
        self._playing = False
```

Note: the `_ET_SEQ_STEP_COMPLETED` subscription uses `TGObjPtrEvent`, defined later in the file. Because it is only *instantiated* at runtime inside `_subscribe_completion` (not at import time), the forward reference is fine — but to be safe, confirm `TGObjPtrEvent` is module-level (it is, near the bottom of `actions.py`).

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "roots_fire or chains_inline or explicit_dependency or not_playing_after or own_completed_event" -v`
Expected: PASS.

- [ ] **Step 6: Run the full existing actions test file (regression)**

Run: `uv run pytest tests/unit/test_actions.py -v`
Expected: PASS (all pre-existing tests, including `test_sequence_play_runs_all_actions` and `test_sequence_play_completes_self`, stay green).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): event-driven TGSequence engine (synchronous zero-delay path)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Delay timers (cross-frame scheduling)

Implement `_schedule_timer` so a step with `delay > 0` fires after that many game-seconds via a one-shot `TGTimer` on the already-ticked timer manager. Route through `g_kRealtimeTimerManager` when the action declares `IsUseRealTime()`.

**Files:**
- Modify: `engine/appc/actions.py` (`TGSequence._schedule_timer`)
- Test: `tests/unit/test_actions.py`

- [ ] **Step 1: Write failing tests for delayed firing**

Add to `tests/unit/test_actions.py`:

```python
# ── TGSequence delay scheduling ──────────────────────────────────────────────

def _advance_game_time(seconds, step=1.0 / 60.0):
    """Advance g_kTimerManager in 60 Hz ticks for `seconds` of game time."""
    n = int(round(seconds / step))
    for _ in range(n):
        App.g_kTimerManager.tick(step)


def test_delayed_step_does_not_fire_before_delay():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "now"))
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    assert log == ["now"]                 # delayed step not fired yet
    _advance_game_time(0.25)
    assert log == ["now"]                 # still waiting at t=0.25


def test_delayed_step_fires_after_delay():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "now"))
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    _advance_game_time(0.6)               # past the 0.5s delay
    assert log == ["now", "later"]


def test_two_delayed_steps_fire_in_time_order():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "t0"))
    s.AddAction(_RecordingAction(log, "t05"), App.TGAction_CreateNull(), 0.5)
    s.AddAction(_RecordingAction(log, "t15"), App.TGAction_CreateNull(), 1.5)
    s.Play()
    _advance_game_time(0.6)
    assert log == ["t0", "t05"]
    _advance_game_time(1.0)               # total ~1.6s
    assert log == ["t0", "t05", "t15"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "delayed_step or two_delayed" -v`
Expected: FAIL with `NotImplementedError` from `_schedule_timer`.

- [ ] **Step 3: Implement `_schedule_timer`**

Replace the placeholder `_schedule_timer` in `engine/appc/actions.py`:

```python
    def _schedule_timer(self, step: "_Step") -> None:
        import App
        use_real = bool(getattr(step.action, "IsUseRealTime",
                                lambda: False)())
        mgr = App.g_kRealtimeTimerManager if use_real else App.g_kTimerManager
        timer = App.TGTimer_Create()
        timer.SetTimerStart(mgr.get_time() + step.delay)
        timer.SetDelay(-1.0)   # one-shot: fires once, then marks itself done
        ev = TGObjPtrEvent()
        ev.SetEventType(_ET_SEQ_TIMER_FIRED)
        ev.SetDestination(self)
        ev.SetObjPtr(step)     # timer events carry the _Step, not the action
        timer.SetEvent(ev)
        mgr.AddTimer(timer)
        self._pending_timers.append((mgr, step, timer))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "delayed_step or two_delayed" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): TGSequence delay timers via g_kTimerManager

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `TGConditionAction` deferred-completion fix

Stop `TGConditionAction` from auto-completing on `Play()` when its condition has not fired, so a sequence step gated on it waits across frames until the condition actually flips.

**Files:**
- Modify: `engine/appc/actions.py` (class `TGConditionAction`; add a `Play` override)
- Test: `tests/unit/test_actions.py`

- [ ] **Step 1: Write failing tests for condition-gated deferral**

Add to `tests/unit/test_actions.py`:

```python
# ── TGConditionAction deferred completion ────────────────────────────────────

def test_condition_action_play_stays_pending_when_unsatisfied():
    from engine.appc.ai import TGCondition
    ca = App.TGConditionAction_Create()
    cond = TGCondition()
    ca.AddCondition(cond)
    ca.Play()
    assert ca.GetState() == App.TGConditionAction.TGCA_WAIT
    assert ca.IsPlaying()                 # still pending, not completed


def test_sequence_step_waits_for_condition_flip():
    from engine.appc.ai import TGCondition
    log = []
    s = App.TGSequence_Create()
    cond = TGCondition()
    gate = App.TGConditionAction_Create()
    gate.AddCondition(cond)
    s.AddAction(gate)
    s.AddAction(_RecordingAction(log, "after"), gate)
    s.Play()
    assert log == []                      # gate pending -> dependent waits
    cond.SetActive()
    cond.SetStatus(1)                     # condition flips
    assert log == ["after"]              # dependent fires on completion
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "stays_pending or waits_for_condition" -v`
Expected: FAIL (`TGConditionAction.Play` currently completes immediately, so `after` fires at Play time and `IsPlaying()` is False).

- [ ] **Step 3: Add the `Play` override to `TGConditionAction`**

In `engine/appc/actions.py`, add a `Play` method to `class TGConditionAction` (just below `_do_play`):

```python
    def Play(self) -> None:
        # Unlike the base TGAction, a condition action does NOT auto-complete:
        # it completes only when a condition is already satisfied at Play time,
        # otherwise it stays pending until ConditionChanged() flips it on a
        # later frame. This is what lets a sequence step gate on it across
        # frames (the base class's unconditional Completed() masked the gate).
        self._playing = True
        self._do_play()
        if self._state == self.TGCA_COMPLETED:
            self.Completed()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "stays_pending or waits_for_condition" -v`
Expected: PASS.

- [ ] **Step 5: Run the condition-action regression tests**

Run: `uv run pytest tests/unit/test_actions.py -k "condition" -v`
Expected: PASS (including the pre-existing `test_tg_condition_action_play_evaluates_existing_truthy_status` and `test_tg_condition_action_completes_on_condition_change`).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "fix(actions): TGConditionAction defers completion until condition fires

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `Stop`/`Abort` timer cleanup

Ensure abandoning a sequence mid-flight removes its outstanding delay timers from the manager so they never fire later. `Stop` was written in Task 2; this task adds the `Abort` override and a regression test for leak-free teardown.

**Files:**
- Modify: `engine/appc/actions.py` (class `TGSequence`; add `Abort`)
- Test: `tests/unit/test_actions.py`

- [ ] **Step 1: Write failing tests for timer cleanup**

Add to `tests/unit/test_actions.py`:

```python
# ── TGSequence teardown ──────────────────────────────────────────────────────

def test_abort_cancels_pending_delay_timers():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    assert len(s._pending_timers) == 1
    s.Abort()
    assert s._pending_timers == []
    _advance_game_time(1.0)
    assert log == []                      # timer was cancelled; never fired
    assert not s.IsPlaying()


def test_stop_cancels_pending_delay_timers():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    s.Stop()
    assert s._pending_timers == []
    _advance_game_time(1.0)
    assert log == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "abort_cancels or stop_cancels" -v`
Expected: FAIL (`Abort` inherited from base does not clear `_pending_timers`, so the timer still fires).

- [ ] **Step 3: Add the `Abort` override**

In `engine/appc/actions.py`, add to `class TGSequence` (next to `Stop`):

```python
    def Abort(self) -> None:
        for mgr, _step, timer in self._pending_timers:
            mgr.RemoveTimer(timer)
        self._pending_timers = []
        self._playing = False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "abort_cancels or stop_cancels" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): TGSequence Stop/Abort cancel outstanding delay timers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Update particle-sequence test + full regression gate

One existing test (`test_sequence_fires_delayed_child_after_delay`) asserts the *old* buggy behavior (delayed child fires immediately). Update it to assert the new delay-aware behavior, then run the regression gate named in the spec.

**Files:**
- Modify: `tests/unit/test_particles_sequence.py:30-39`

- [ ] **Step 1: Update the delayed-child test to assert delay-aware behavior**

Replace `test_sequence_fires_delayed_child_after_delay` in `tests/unit/test_particles_sequence.py` with:

```python
def test_sequence_fires_delayed_child_after_delay():
    """A child added with a delay does NOT start until the delay elapses on
    the game-time timer manager; the immediate child starts at once."""
    P.reset()
    import App
    seq = App.TGSequence_Create()
    seq.AddAction(EffectAction_Create(_ctrl()))                          # t=0
    seq.AddAction(EffectAction_Create(_ctrl()),
                  App.TGAction_CreateNull(), 0.5)                        # t=0.5
    seq.Start()
    assert P.active_count() == 1          # only the immediate child started
    for _ in range(int(round(0.6 / (1.0 / 60.0)))):
        App.g_kTimerManager.tick(1.0 / 60.0)
    assert P.active_count() == 2          # delayed child started after 0.5s
```

- [ ] **Step 2: Run the particle-sequence tests**

Run: `uv run pytest tests/unit/test_particles_sequence.py -v`
Expected: PASS (`test_sequence_starts_immediate_children_on_start` unchanged at count 2; the updated delayed test passes; `test_create_weapon_explosion_runs_unmodified` still green).

- [ ] **Step 3: Run the full regression gate from the spec**

Run: `uv run pytest tests/unit/test_actions.py tests/unit/test_particles_sequence.py tests/integration/tutorial/test_m3gameflow.py -v`
Expected: PASS (all). If `test_m3gameflow` reveals a dialog/sequence timing assumption, investigate before proceeding — the spec keeps the `PlayDialog` manager-ObjPtr path a no-op, so sound+subtitle still fire together; no `test_m3gameflow` change is expected.

- [ ] **Step 4: Run the broader action/effects-adjacent unit subset**

Run: `uv run pytest tests/unit/test_credit_action_play.py tests/unit/test_phaser_fire_sfx_attach.py tests/unit/test_phaser_fire_sfx_edge_trigger.py tests/unit/test_ai_primitives.py -v`
Expected: PASS (these touch actions/conditions; confirm no collateral regression).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_particles_sequence.py
git commit -m "test(particles): assert delay-aware sequence firing (was: delay ignored)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §1 API semantics → Task 1 (parsing) + Task 2 (root/dependency launch) + Task 3 (delay).
- §2 internal representation (`_Step`) → Task 1.
- §3 execution engine (subscribe, root fire, inline vs timer, ProcessEvent routing) → Task 2 + Task 3.
- §4 deferred completion + condition fix → Task 4.
- §5 sequence self-completion → Task 2 (`_maybe_complete` + own-completed-event test).
- §6 out of scope (PlayDialog no-op, no Effects/host-loop change) → respected; Task 6 Step 3 verifies dialog flow unchanged.
- §7 testing (parallel, append chain, dependency gate, delay timing, condition deferral, sync preservation, self-completion) → Tasks 1–6; regression gate in Task 6.
- Risks: timer leakage on abandon → Task 5.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only deliberate `NotImplementedError` (Task 2 `_schedule_timer`) is replaced with real code in Task 3, and Task 2's tests use only zero-delay paths so it is never hit there.

**Type consistency:** `_Step(action, dependency, delay)` with `.started` flag used consistently; `_parse_extra` returns `(dependency, delay)` everywhere; `_pending_timers` entries are uniformly `(manager, step, timer)` (appended in Task 3, consumed in `_on_timer_fired`/`Stop`/`Abort`); event constants `_ET_SEQ_STEP_COMPLETED`/`_ET_SEQ_TIMER_FIRED` defined in Task 2, used in Task 3; `_fire`/`_begin_step`/`_maybe_complete` signatures stable across tasks. Timer events carry the `_Step` (ObjPtr), completion events carry the action — handled in separate `ProcessEvent` branches.

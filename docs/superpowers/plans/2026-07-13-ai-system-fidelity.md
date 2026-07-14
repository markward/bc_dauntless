# AI System Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the defects found auditing Dauntless's AI system against the reverse-engineered `ai-architecture.md`, in leverage order: revive the condition layer (15 of 33 conditions never update their status), then fix the AI-core fidelity bugs (fuzzy-logic blending, leaf focus lifecycle, weapon-aim stubs, `CodeAISet`, container flags).

**Architecture:** No new subsystems. Every task is a surgical change to an existing engine module — `engine/appc/time_slice.py`, `App.py` (event constants + FuzzyLogic), `engine/appc/ai.py`, `engine/appc/ai_driver.py`, `engine/appc/weapon_subsystems.py`. The SDK scripts are never modified; they are ground truth and they already contain the behaviour we are unblocking. The recurring failure mode being fixed is *silent degradation*: an undefined `App.ET_*` constant resolves to a fresh `_NamedStub` whose `__hash__` is `id()`, so a handler registered under it can never be matched by a later access.

**Tech Stack:** Python 3.11+, pytest, `uv`. C++ is not touched by this plan — no rebuild is required for any task.

## Global Constraints

- **Never modify anything under `sdk/`.** SDK scripts are ground truth (see CLAUDE.md, "SDK drives everything"). If an SDK script appears wrong, the engine surface it calls is what's wrong.
- **Never run destructive git.** Banned: `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec. This tree is shared with concurrent sessions and work is often deliberately uncommitted.
- **Any new `ET_*` constant must be a real, distinct `int` defined at module level in `App.py`.** Never rely on `App.__getattr__`. The private engine block runs `0x1300`–`0x1321`; new values continue at `0x1322`.
- **Test gate before declaring a task done:** `uv run pytest` for the task's own tests during the loop; `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`) before the final commit of the last task. Never call a failure "pre-existing" by eyeball.
- **`hasattr` is not a capability test in this codebase.** `TGObject.__getattr__` returns a truthy `_Stub` for unknown public attributes. Use `engine.core.ids.implements()` or check `__dict__` when probing for a method.
- Run all commands from the project root, `/Users/mward/Documents/Projects/bc_dauntless`.

## Reference

The audit that produced this plan compared our engine against
`/Users/mward/Documents/Projects/STBC-Reverse-Engineering-1/docs/gameplay/ai-architecture.md`
(2026-07-13 corpus audit). Every task below cites the SDK line it is unblocking.

### Corrections to that doc, established 2026-07-14 — READ THIS BEFORE ANY TASK

The RE project re-read the `swig_const_info` table (`0x0090d9ac+`, stride `0x20`; name at `+0x00`,
value at `+0x04`), the `PreprocessingAI::Update` switch (asm at `0x48eab1`), and
`PreprocessingAI::SetContainedAI` (`0x0048E570`). **Four of the doc's claims are wrong.** Trust this
section over the doc; it changes what this plan does.

1. **`UpdateStatus` values — the doc is wrong, our engine is right.**
   `US_ACTIVE=0, US_DONE=1, US_DORMANT=2, US_INVALID=3, US_NUM_STATUSES=4` — sequential declaration
   order, exactly what `engine/appc/ai.py:199-203` already has. The doc's `US_DORMANT=1 / US_DONE=2`
   is a transcription error, and it is what made the preprocess switch appear to invert.
   **Do not "fix" these values.**

2. **`PS_*` values are sequential too** (`PS_NORMAL=0, PS_SKIP_ACTIVE=1, PS_SKIP_DORMANT=2,
   PS_DONE=3, PS_INVALID=4`), and every `PS_` name maps to its identically-named `US_`:

   | `r` (the `+0x58` preprocess result) | | `PreprocessingAI::Update` returns |
   |---|---|---|
   | 0 | `PS_NORMAL` | give the child focus if needed, then `child->Update()` |
   | 1 | `PS_SKIP_ACTIVE` | `US_ACTIVE` (child not run) |
   | 2 | `PS_SKIP_DORMANT` | `US_DORMANT` (child not run) |
   | 3, 4 | `PS_DONE`, `PS_INVALID` | `US_DONE` |

   Our driver gets the first three right and **`PS_DONE` wrong** — see Task 14, which is now the
   most dangerous task in this plan.

3. **`US_DONE`, not `US_DORMANT`, tears an AI down.** `US_DONE` → LostFocus → SetInactive →
   unlink + delete, no guard. `US_DORMANT` merely posts an event and keeps the node alive. The doc's
   §3 has this backwards. **`PS_DONE` is lethal.**

4. **The `GetOptimizedVersion` hook (vtable `+0x34`) — undocumented, and load-bearing.**
   `PreprocessingAI::SetContainedAI` does **not** store the AI it is handed. It calls
   `newAI->GetOptimizedVersion()` (`call dword ptr [edx+0x34]` at `0x0048e586`) and stores the
   **returned** object at `+0x48`. `PreprocessingAI` overrides that slot (`0x0048EB20`): it reads the
   Python preprocessor instance's class name (`instance->in_class->cl_name`), looks it up in a native
   registry (`DAT_00982A1C`) holding **four** entries — `AvoidObstacles`, `FireScript`,
   `ManagePower`, `SelectTarget` — and on a hit allocates a native C++ node, steals the contained
   subtree, and **deletes the Python-backed `PreprocessingAI` outright**. The BaseAI default at
   `0x00470750` is `MOV EAX,ECX; RET` — "return `this`", i.e. *I have no optimized version, use me*.
   (This also closes the doc's OQ5: `+0x34` was never a predicate.)

   **So `AI/Preprocessors.py:ManagePower.Update` never runs in the shipped game.** Its `# Unused.`
   comment is literally true, and its `return PS_DONE` is dead code. The native replacement
   (ctor `0x00486FA0`) drives the power subsystem on a 3.0 s cadence (`[0x0088BEBC] = 3.0f`, matching
   `ManagePower.GetNextUpdateTime`), reads `bConservePower` off the Python instance, and returns
   `PS_NORMAL`. `AlertLevel` is *not* in the registry, which is exactly why it uses the correct
   `PS_NORMAL` pass-through idiom.

   **We have no optimization hook, so we run the Python `ManagePower.Update` and it does return
   `PS_DONE`.** Our incorrect "PS_DONE = stop calling me, keep the child" handling is the only thing
   currently preventing every Federation ship from deleting its own AI. Task 14 fixes both halves
   together; neither half is safe alone.

Minor: the contained-child pointer is `+0x48` (`+0x44` is the cached status), and there are **4**
name-registered CodeAI classes, not 5.

---

# Phase 1 — Condition-layer revival

`ConditionalAI` is only as capable as the `ConditionScript`s wired into it, and 15 of the 33
shipped conditions currently never update their status after construction. The `FedAttack` /
`NonFedAttack` / `CloakAttack` doctrines are built almost entirely out of conditional branches,
so every dead condition is a doctrine branch that silently never fires.

### Task 1: `TimeSliceProcess` self-registration

In real Appc the C++ `TimeSliceProcess` constructor registers the process with the scheduler, and
the destructor unregisters it. Our `TimeSliceProcess.__init__` does not, and **nothing in the
entire repo calls `g_kAIManager.Add()`** outside a unit test — so every `App.PythonMethodProcess()`
an SDK script creates is inert. The manager is constructed and ticked every frame from
`engine/core/loop.py:35` with an empty queue.

Four condition scripts and two bridge modules build one and never call `Add`:
`Conditions/ConditionFacingToward.py:118`, `Conditions/ConditionInPhaserFiringArc.py:113`,
`Conditions/ConditionIncomingTorps.py:190`, `Conditions/FriendliesInPlayerSetStronger.py:67`,
`Bridge/HelmMenuHandlers.py:68`, `Bridge/PowerDisplay.py:91`.

Two details make this non-trivial and must both be honoured:

1. **`SetDelay` is called *after* construction.** `ConditionFacingToward.py:118-121` constructs,
   then `SetInstance`, then `SetFunction`, then `SetDelay`. So the first-fire time cannot be
   computed at registration; it must be computed lazily on the first tick that sees the process.
2. **The SDK stops a process by dropping the reference** (`self.pTimerProcess = None`), relying on
   the C++ refcount to run the destructor and unregister. The manager must therefore hold **weak**
   references, or every condition ever created leaks a live process forever.

**Files:**
- Modify: `engine/appc/time_slice.py:23-29` (self-register in `__init__`), `:99-133` (weakref storage, lazy first-fire)
- Test: `tests/unit/test_time_slice_self_register.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `TimeSliceProcess.__init__` self-registers into `engine.appc.time_slice.g_kAIManager`.
  `TimeSliceProcessManager.Add(proc)` stays public and idempotent (existing callers keep working).
  `TimeSliceProcessManager._procs` becomes a `list[weakref.ref]` — any test or code reading
  `_procs` directly must now deref. `TimeSliceProcessManager.count()` is added as the supported
  way to ask how many live processes are registered.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_time_slice_self_register.py`:

```python
"""A TimeSliceProcess registers itself with g_kAIManager at construction.

Real Appc's C++ ctor self-registers and its dtor unregisters; SDK scripts rely
on both (Conditions/ConditionFacingToward.py:118-121 constructs a
PythonMethodProcess, calls SetDelay AFTER construction, and never calls Add;
it stops the process by dropping the reference).
"""
import gc

from engine.appc.time_slice import PythonMethodProcess, TimeSliceProcessManager


class _Counter:
    def __init__(self):
        self.calls = 0

    def PeriodicCheck(self, dTimeAvailable):
        self.calls += 1


def test_process_self_registers_and_fires_on_its_delay():
    mgr = TimeSliceProcessManager()
    target = _Counter()

    proc = PythonMethodProcess(manager=mgr)
    proc.SetInstance(target)
    proc.SetFunction("PeriodicCheck")
    proc.SetDelay(0.5)          # NOTE: set AFTER construction, as the SDK does

    assert mgr.count() == 1

    mgr.tick(game_time=0.0, real_time=0.0)
    assert target.calls == 0, "must not fire before its delay has elapsed"

    mgr.tick(game_time=0.4, real_time=0.4)
    assert target.calls == 0

    mgr.tick(game_time=0.5, real_time=0.5)
    assert target.calls == 1, "first fire is at construction-time + delay"

    mgr.tick(game_time=1.0, real_time=1.0)
    assert target.calls == 2, "re-arms every delay"


def test_dropping_the_last_reference_unregisters_the_process():
    mgr = TimeSliceProcessManager()
    target = _Counter()

    proc = PythonMethodProcess(manager=mgr)
    proc.SetInstance(target)
    proc.SetFunction("PeriodicCheck")
    proc.SetDelay(0.1)
    assert mgr.count() == 1

    del proc
    gc.collect()

    assert mgr.count() == 0, "manager must hold a weak ref, not pin the process"
    mgr.tick(game_time=5.0, real_time=5.0)
    assert target.calls == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_time_slice_self_register.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'manager'`.

- [ ] **Step 3: Implement**

In `engine/appc/time_slice.py`, add `import weakref` at the top of the module, then replace
`TimeSliceProcess.__init__` (currently lines 23-29) with:

```python
    def __init__(self, manager=None):
        self._priority: int = TimeSliceProcess.NORMAL
        self._delay: float = 0.0
        self._delay_uses_game_time: int = 1
        # None = "not yet scheduled". The manager computes the first fire time
        # on the first tick that sees this process, because the SDK calls
        # SetDelay AFTER construction (Conditions/ConditionFacingToward.py:118).
        self._next_fire = None
        # Real Appc's C++ ctor registers the process with the scheduler; SDK
        # scripts never call Add() themselves. The manager holds a weak ref, so
        # dropping the last Python reference (the SDK's way of stopping a
        # process: `self.pTimerProcess = None`) unregisters it.
        (manager if manager is not None else g_kAIManager).Add(self)
```

`PythonMethodProcess.__init__` must forward the argument — replace its body (currently lines 62-65):

```python
    def __init__(self, manager=None):
        super().__init__(manager)
        self._instance = None
        self._method_name: str = ""
```

Replace `TimeSliceProcessManager` (currently lines 92-133) with:

```python
class TimeSliceProcessManager:
    """Module-level scheduler. One instance lives as g_kAIManager.

    GameLoop ticks the manager once per frame with the current game-time and
    real-time absolute clocks. The manager dispatches every process whose
    next_fire has been reached, lowest priority-int first.

    Processes are held WEAKLY. Real Appc unregisters a process in its C++
    destructor, and SDK scripts rely on that: they stop a periodic check by
    dropping the reference (`self.pTimerProcess = None`,
    Conditions/ConditionFacingToward.py:100). A strong list would keep every
    condition's process firing forever.
    """
    def __init__(self):
        self._procs: list = []          # list[weakref.ref[TimeSliceProcess]]

    def _live(self) -> list:
        """Deref, dropping dead entries. The only way to read the queue."""
        live = []
        keep = []
        for ref in self._procs:
            proc = ref()
            if proc is not None:
                live.append(proc)
                keep.append(ref)
        self._procs = keep
        return live

    def count(self) -> int:
        return len(self._live())

    def Add(self, proc: TimeSliceProcess) -> None:
        if any(p is proc for p in self._live()):
            return
        self._procs.append(weakref.ref(proc))

    def Remove(self, proc: TimeSliceProcess) -> None:
        self._procs = [r for r in self._procs if r() is not None and r() is not proc]

    def tick(self, game_time: float, real_time: float) -> None:
        """Fire every due process in priority order."""
        due = []
        for proc in self._live():
            t = game_time if proc._delay_uses_game_time else real_time
            if proc._next_fire is None:
                # First tick that sees this process: SetDelay has run by now.
                proc._next_fire = t + proc._delay
                continue
            if t >= proc._next_fire:
                due.append((proc._priority, proc))
        due.sort(key=lambda pair: pair[0])
        for _prio, proc in due:
            proc.Update(proc._delay)
            if proc._delay > 0:
                # Advance rather than restamp: no drift under variable ticks.
                proc._next_fire += proc._delay
            else:
                # One-shot: never fires again unless SetDelay re-arms it.
                proc._next_fire = float("inf")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_time_slice_self_register.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the existing suite — this task changes a global scheduler**

Run: `uv run pytest tests/unit tests/integration -x -q`
Expected: all pass. `tests/unit/test_loop.py:61` calls `g_kAIManager.Add()` explicitly; `Add` is
still public and idempotent, so it must keep passing. If any test reads `g_kAIManager._procs`
directly it will now see weakrefs — update it to use `count()` in this same commit (do not leave
an orphaned test; see CLAUDE.md).

This task also wakes up `Bridge/HelmMenuHandlers.py:68` and `Bridge/PowerDisplay.py:91`, whose
periodic processes have never run. If a test fails because one of those now executes, that is a
real behaviour change surfacing, not a flake — read the failure before touching it.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/time_slice.py tests/unit/test_time_slice_self_register.py
git commit -m "fix(ai): TimeSliceProcess self-registers with the scheduler

Real Appc's C++ ctor registers the process and its dtor unregisters it; SDK
scripts never call Add(). Nothing in the repo did either, so every
PythonMethodProcess an SDK script created was inert — killing
ConditionFacingToward, ConditionInPhaserFiringArc, ConditionIncomingTorps and
FriendliesInPlayerSetStronger, plus the HelmMenuHandlers/PowerDisplay periodic
updates. Manager now holds weak refs so the SDK's stop-by-dropping-the-ref
idiom unregisters, and computes first-fire lazily because SetDelay runs after
construction."
```

---

### Task 2: The two watcher event types (`ConditionSystemBelow`, `ConditionSingleShieldBelow`)

These are the two most-used conditions in the whole AI — **31 and 12 SDK uses** — and both are
stone dead. The cause is small: the entire watcher infrastructure already exists and works
(`engine/appc/float_range_watcher.py`; `ConditionPowerBelow` and `ConditionPulseReady` both work
through it), but `App.ET_AI_SYSTEM_STATUS_WATCHER` and `App.ET_AI_SHIELD_WATCHER` are not defined.

The conditions build their *own* event, stamp it with the constant, and hand it to the watcher
(`Conditions/ConditionSystemBelow.py:88-97`); the watcher fires it on a threshold crossing. Because
the constant is undefined, `App.__getattr__` hands back a fresh `_NamedStub` on every access, and
`_NamedStub.__hash__` is `id()` — so the handler registered at
`ConditionSystemBelow.py:57` and the event fired later are keyed on two different objects and can
never match. No emitter work is needed. Only the constants.

This failure is invisible to `docs/stub_heatmap.md`, because the stub dies as a *dict key* rather
than as a later attribute access.

**Files:**
- Modify: `App.py` (private ET block, after `ET_ADD_TO_REPAIR_LIST = 0x1321`)
- Test: `tests/unit/test_condition_watcher_events.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `App.ET_AI_SYSTEM_STATUS_WATCHER = 0x1322`, `App.ET_AI_SHIELD_WATCHER = 0x1323` —
  module-level ints in `App.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_condition_watcher_events.py`:

```python
"""ConditionSystemBelow / ConditionSingleShieldBelow drive their status off a
FloatRangeWatcher event they build themselves and stamp with a fixed ET.

Those two ET constants were undefined, so App.__getattr__ handed back a fresh
_NamedStub per access (hashed by id()) — the handler registered in the
condition's __init__ could never match the event the watcher later fired, and
the two most-used conditions in the AI (31 + 12 SDK uses) never updated.
"""
import App


def test_watcher_event_types_are_stable_distinct_ints():
    assert isinstance(App.ET_AI_SYSTEM_STATUS_WATCHER, int)
    assert isinstance(App.ET_AI_SHIELD_WATCHER, int)
    assert App.ET_AI_SYSTEM_STATUS_WATCHER != App.ET_AI_SHIELD_WATCHER
    # Stable across accesses — the _NamedStub failure mode was that they weren't.
    assert App.ET_AI_SYSTEM_STATUS_WATCHER == App.ET_AI_SYSTEM_STATUS_WATCHER
    assert hash(App.ET_AI_SHIELD_WATCHER) == hash(App.ET_AI_SHIELD_WATCHER)


def test_a_watcher_crossing_reaches_a_handler_registered_on_the_constant():
    """End-to-end: the exact pattern ConditionSystemBelow.py:88-97 uses."""
    from engine.appc.float_range_watcher import FloatRangeWatcher

    received = []

    class _Sink:
        def SystemEvent(self, pFloatEvent):
            received.append(pFloatEvent.GetFloat())

    sink = _Sink()
    handler = App.TGPythonInstanceWrapper()
    handler.SetPyWrapper(sink)
    handler.AddPythonMethodHandlerForInstance(
        App.ET_AI_SYSTEM_STATUS_WATCHER, "SystemEvent")

    watcher = FloatRangeWatcher(initial_value=1.0)
    event = App.TGFloatEvent_Create()
    event.SetEventType(App.ET_AI_SYSTEM_STATUS_WATCHER)
    event.SetDestination(handler)
    watcher.AddRangeCheck(0.5, App.FloatRangeWatcher.FRW_BOTH, event)

    watcher._update(0.2)                 # cross below the threshold
    App.g_kEventManager.DispatchAll()

    assert received == [0.2]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_condition_watcher_events.py -v`
Expected: FAIL — `assert isinstance(App.ET_AI_SYSTEM_STATUS_WATCHER, int)` fails because it is a
`_NamedStub`.

If `App.g_kEventManager.DispatchAll()` does not exist, find the drain method the other event tests
use (`grep -rn "DispatchAll\|_dispatch\|Update()" tests/unit/test_ai_done_event.py engine/appc/events.py`)
and use that instead — do not add a new one.

- [ ] **Step 3: Implement**

In `App.py`, immediately after `ET_ADD_TO_REPAIR_LIST = 0x1321`, add:

```python
# ── AI condition watcher event types ─────────────────────────────────────────
# Stamped by the SDK conditions onto the TGFloatEvent they hand to a
# FloatRangeWatcher, then fired back at them on a threshold crossing:
#   Conditions/ConditionSystemBelow.py:88-97   (subsystem condition fraction)
#   Conditions/ConditionSingleShieldBelow.py:36 (per-face shield fraction)
# These MUST be real distinct ints. App's module-level __getattr__ returns a
# fresh _NamedStub per access and _NamedStub hashes by id(), so a handler
# registered under one access can never match an event fired under another —
# which is exactly how the two most-used conditions in the AI (31 + 12 SDK
# uses) silently never updated their status.
ET_AI_SYSTEM_STATUS_WATCHER       = 0x1322
ET_AI_SHIELD_WATCHER              = 0x1323
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_condition_watcher_events.py -v`
Expected: 2 passed.

- [ ] **Step 5: Verify the conditions themselves now update**

Run this one-off check (not a committed test — it exercises the real SDK condition end to end and
is slow):

```bash
uv run python -c "
import sys, os
sys.path.insert(0, os.path.abspath('build/python'))
import tools.mission_harness as mh; mh.setup_sdk()
import App
print('ET_AI_SYSTEM_STATUS_WATCHER =', App.ET_AI_SYSTEM_STATUS_WATCHER)
print('ET_AI_SHIELD_WATCHER        =', App.ET_AI_SHIELD_WATCHER)
"
```

Expected: two distinct integers printed (4898 and 4899), not `<stub ...>`.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_condition_watcher_events.py
git commit -m "fix(ai): define ET_AI_SYSTEM_STATUS_WATCHER / ET_AI_SHIELD_WATCHER

ConditionSystemBelow (31 SDK uses) and ConditionSingleShieldBelow (12) build
their own TGFloatEvent, stamp it with these constants and hand it to a
FloatRangeWatcher. Both constants were undefined, so App.__getattr__ returned a
fresh id()-hashed _NamedStub per access and the handler could never match the
fired event. The watcher infrastructure was already correct; only the constants
were missing. Invisible to the stub heatmap because the stub died as a dict key."
```

---

### Task 3: `ET_AI_CONDITION_CHANGED` — emit it from `TGCondition.SetStatus`

`Conditions/ConditionCriticalSystemBelow.py` composes child `ConditionSystemBelow` conditions and
listens for `ET_AI_CONDITION_CHANGED` broadcast from them. In real Appc, `ConditionScript::SetStatus`
posts that event. We never define the constant (it is live in `docs/stub_heatmap.md:285`, 8 hits) and
never post it, so the condition is dead even after Task 2 fixes its children.

**Files:**
- Modify: `App.py` (ET block — add `ET_AI_CONDITION_CHANGED = 0x1324`)
- Modify: `engine/appc/ai.py:63-69` (`TGCondition.SetStatus`)
- Test: `tests/unit/test_condition_changed_event.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `App.ET_AI_CONDITION_CHANGED = 0x1324`. `TGCondition.SetStatus` posts a `TGIntEvent`
  with `GetInt()` = the new status, source = the condition, destination = the condition, whenever
  the status value actually changes. Existing handler notification (`ConditionChanged` on
  registered handlers) is unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_condition_changed_event.py`:

```python
"""A condition status change broadcasts ET_AI_CONDITION_CHANGED.

Real Appc posts this from ConditionScript::SetStatus.
Conditions/ConditionCriticalSystemBelow.py composes child conditions and
listens for it; without the broadcast the composite condition never updates.
"""
import App
from engine.appc.ai import TGCondition


def test_status_change_broadcasts_the_event_with_the_new_status():
    received = []

    class _Sink:
        def Changed(self, pEvent):
            received.append(pEvent.GetInt())

    sink = _Sink()
    handler = App.TGPythonInstanceWrapper()
    handler.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_AI_CONDITION_CHANGED, handler, "Changed")

    cond = TGCondition()
    cond.SetStatus(1)
    App.g_kEventManager.DispatchAll()
    assert received == [1]

    # No change -> no event.
    cond.SetStatus(1)
    App.g_kEventManager.DispatchAll()
    assert received == [1]

    cond.SetStatus(0)
    App.g_kEventManager.DispatchAll()
    assert received == [1, 0]
```

Use whatever drain call the other event tests use if `DispatchAll` is not the right name (see Task 2
Step 2).

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_condition_changed_event.py -v`
Expected: FAIL — nothing is ever appended to `received`.

- [ ] **Step 3: Implement**

In `App.py`, directly after `ET_AI_SHIELD_WATCHER = 0x1323`, add:

```python
# Broadcast by TGCondition.SetStatus on every status transition. Composite
# conditions listen for it on their children (Conditions/
# ConditionCriticalSystemBelow.py). Real int for the same reason as above.
ET_AI_CONDITION_CHANGED           = 0x1324
```

In `engine/appc/ai.py`, replace `TGCondition.SetStatus` (currently lines 63-69) with:

```python
    def SetStatus(self, status) -> None:
        new_status = int(status)
        changed = (new_status != self._status)
        self._status = new_status
        if not changed:
            return
        if self._active:
            for h in list(self._handlers):
                h.ConditionChanged(self)
        # Real Appc posts ET_AI_CONDITION_CHANGED from ConditionScript::SetStatus
        # so composite conditions can watch their children
        # (Conditions/ConditionCriticalSystemBelow.py). Fired unconditionally on
        # a real change — NOT gated on _active, which only governs the direct
        # handler list.
        try:
            import App
            evt = App.TGIntEvent_Create()
            evt.SetEventType(App.ET_AI_CONDITION_CHANGED)
            evt.SetInt(new_status)
            evt.SetSource(self)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("condition changed event", _e)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_condition_changed_event.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the AI + condition suites**

Run: `uv run pytest tests/unit -k "ai or condition" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add App.py engine/appc/ai.py tests/unit/test_condition_changed_event.py
git commit -m "fix(ai): broadcast ET_AI_CONDITION_CHANGED on condition status change

Real Appc posts this from ConditionScript::SetStatus; composite conditions
(ConditionCriticalSystemBelow) watch their children through it. The constant was
undefined (stub_heatmap rank 273, 8 live hits) and nothing emitted it."
```

---

### Task 4: `ConditionScript.SetActive` must reach the script's `Activate()`

Real Appc's `ConditionScript::SetActive` forwards to the Python instance's optional `Activate()`
method, and `ConditionalAI`'s C++ side calls `SetActive`/`SetInactive` on every condition in its
list as the node activates and deactivates.

We do neither: `ConditionScript` inherits `TGCondition.SetActive` (`engine/appc/ai.py:79-81`), which
only flips a bool, and `ConditionalAI.AddCondition` (`engine/appc/ai.py:666-668`) never calls it at
all. Five conditions define `Activate()`, and the consequential one is **`ConditionTimer` (65 SDK
uses)**: `Activate()` is what re-arms the timer when `bResetOnActivate` (the default) is set
(`Conditions/ConditionTimer.py:66-81`). Without it, once the timer fires the condition latches
status = 1 forever, and any `ConditionalAI` branch gated on a repeating timer never re-arms.

**Files:**
- Modify: `engine/appc/ai.py` — add `SetActive`/`SetInactive` overrides to `ConditionScript` (after `GetArguments`, ~line 138); `ConditionalAI.AddCondition` (line 666)
- Test: `tests/unit/test_condition_activate.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `ConditionScript.SetActive()` calls `self._instance.Activate()` if the wrapped Python
  instance defines it; `ConditionScript.SetInactive()` calls `self._instance.Deactivate()` if
  defined. `ConditionalAI.AddCondition(cond)` now calls `cond.SetActive()`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_condition_activate.py`:

```python
"""ConditionScript.SetActive forwards to the wrapped script's Activate().

Real Appc's ConditionScript::SetActive calls the Python instance's optional
Activate(); ConditionalAI drives SetActive/SetInactive across its condition
list. ConditionTimer (65 SDK uses) re-arms its timer in Activate() — without
the forward it fires once and latches true forever.
"""
from engine.appc.ai import ConditionScript, ConditionalAI, TGCondition


class _Spy(ConditionScript):
    """A ConditionScript with a hand-installed instance, so the test does not
    depend on any particular SDK condition module being importable."""
    def __init__(self):
        super().__init__()
        self.activated = 0
        self.deactivated = 0

        outer = self

        class _Inst:
            def Activate(self):
                outer.activated += 1

            def Deactivate(self):
                outer.deactivated += 1

        self._instance = _Inst()


def test_set_active_calls_the_scripts_activate():
    cond = _Spy()
    cond.SetActive()
    assert cond.activated == 1
    assert cond.IsActive() == 1

    cond.SetInactive()
    assert cond.deactivated == 1
    assert cond.IsActive() == 0


def test_conditional_ai_activates_the_conditions_it_is_given():
    cond = _Spy()
    ai = ConditionalAI(None, "gate")
    ai.AddCondition(cond)
    assert cond.activated == 1, "ConditionalAI must activate its conditions"


def test_plain_tgcondition_without_an_instance_is_unaffected():
    cond = TGCondition()
    cond.SetActive()          # must not raise
    assert cond.IsActive() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_condition_activate.py -v`
Expected: FAIL — `assert cond.activated == 1` (both of the first two tests); the third passes.

- [ ] **Step 3: Implement**

In `engine/appc/ai.py`, inside `class ConditionScript`, after `GetArguments` (~line 136-138), add:

```python
    # Real Appc's ConditionScript::SetActive / ::SetInactive forward to the
    # wrapped Python instance's optional Activate() / Deactivate(). Five shipped
    # conditions define Activate(); the load-bearing one is ConditionTimer
    # (65 SDK uses), whose Activate() re-arms the timer when bResetOnActivate is
    # set (Conditions/ConditionTimer.py:66-81). Without the forward it fires once
    # and latches true forever.
    def SetActive(self, *args) -> None:
        super().SetActive(*args)
        activate = getattr(self._instance, "Activate", None) if self._instance else None
        if callable(activate):
            try:
                activate()
            except Exception as _e:
                dev_mode.log_swallowed("condition Activate", _e)

    def SetInactive(self, *args) -> None:
        super().SetInactive(*args)
        deactivate = getattr(self._instance, "Deactivate", None) if self._instance else None
        if callable(deactivate):
            try:
                deactivate()
            except Exception as _e:
                dev_mode.log_swallowed("condition Deactivate", _e)
```

In `engine/appc/ai.py`, replace `ConditionalAI.AddCondition` (currently lines 666-668) with:

```python
    def AddCondition(self, cond: TGCondition) -> None:
        self._conditions.append(cond)
        cond.AddHandler(self)
        # Appc's ConditionalAI drives SetActive/SetInactive across its condition
        # list (its C++ side multiply-inherits the condition-handler base and its
        # only confirmed overrides are SetActive / SetInactive / LostFocus).
        # SetActive is what reaches ConditionTimer.Activate() and re-arms it.
        cond.SetActive()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_condition_activate.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the AI + condition suites**

Run: `uv run pytest tests/unit tests/integration -k "ai or condition" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_condition_activate.py
git commit -m "fix(ai): ConditionScript.SetActive forwards to the script's Activate()

Appc's ConditionScript::SetActive calls the wrapped instance's optional
Activate(), and ConditionalAI drives SetActive across its condition list. We did
neither, so ConditionTimer (65 SDK uses) never re-armed: it fired once and
latched true forever, permanently pinning any ConditionalAI branch gated on a
repeating timer."
```

---

# Phase 2 — AI core fidelity

### Task 5: `FuzzyLogic.GetResultBySet` must sum, not max

Ground truth (`ai-architecture.md` §12, impl `0x0047d0b0`): `GetResultBySet(set)` returns the
**unnormalized sum of `confidence × percentage`** over every rule whose *output* set matches. No
normalization, no clamping, no defuzzification. Rules are weighted edges
`inputSet --confidence--> outputSet`.

Ours (`App.py:632-640`) returns the **max** of the input membership over matching rules and ignores
confidence entirely. Its docstring justifies this by claiming every SDK caller uses
single-antecedent rules — that is false. `AI/PlainAI/FollowObject.py:54-59` maps **four** input sets
onto `FS_STOP_AND_TURN_TOWARD`; `AI/PlainAI/FollowWaypoints.py:97-108` maps **five** onto `FS_STOP`.
The real sums form a partition of unity, and `FollowObject.GoForward` (`:150-152`) and
`FollowWaypoints` (`:262`) blend speeds against that. With max, the blend loses mass and impulse
comes out systematically low — followers crawl and stutter instead of flying the intended profile.
`CircleObject` / `IntelligentCircleObject` / `MoveToObjectSide` are correct only by accident (one
rule per output set, so max == sum).

Every SDK caller uses the 2-arg `AddRule(inSet, outSet)` form, so confidence defaults to 1.0.
`GetRule`, `GetMaxRules`, `RemoveRule` (a **swap-remove** in the original — indices are not stable
across removal) and `SetRuleConfidence` are missing entirely and must be added.

**Files:**
- Modify: `App.py:623-661` (`class FuzzyLogic`)
- Test: `tests/unit/test_fuzzy_logic.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `App.FuzzyLogic` with `SetMaxRules(n)`, `GetMaxRules() -> int`,
  `AddRule(in_set, out_set, confidence=1.0) -> int` (returns the rule index, or −1 at capacity),
  `GetRule(idx) -> tuple[int, int, float]`, `RemoveRule(idx)` (swap-remove),
  `SetRuleConfidence(idx, f)`, `SetPercentageInSet(set_id, f)`,
  `GetResultBySet(set_id) -> float`. `App.FuzzyLogic_BreakIntoSets` is unchanged — it already
  matches ground truth exactly.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_fuzzy_logic.py`:

```python
"""FuzzyLogic.GetResultBySet is an unnormalized SUM of confidence x percentage.

Ground truth: STBC-Reverse-Engineering-1/docs/gameplay/ai-architecture.md sec.12
(impl 0x0047d0b0) — "returns the unnormalized weighted sum of confidence x
percentage over every edge targeting that output set. There is no
defuzzification, no centroid, no normalization and no clamping."

We returned a MAX and ignored confidence, which breaks every multi-antecedent
caller: AI/PlainAI/FollowObject.py:54-59 maps 4 input sets onto one output set
and AI/PlainAI/FollowWaypoints.py:97-108 maps 5 onto one, then blend speeds
against sums that are supposed to form a partition of unity.
"""
import App


def test_multiple_rules_onto_one_output_set_sum():
    f = App.FuzzyLogic()
    f.SetMaxRules(4)
    f.AddRule(0, 10)     # in 0 -> out 10
    f.AddRule(1, 10)     # in 1 -> out 10
    f.SetPercentageInSet(0, 0.25)
    f.SetPercentageInSet(1, 0.75)
    # sum, not max: 0.25 + 0.75 == 1.0 (max would give 0.75)
    assert f.GetResultBySet(10) == 1.0


def test_confidence_weights_the_contribution():
    f = App.FuzzyLogic()
    f.SetMaxRules(2)
    f.AddRule(0, 10, 0.5)
    f.SetPercentageInSet(0, 0.4)
    assert f.GetResultBySet(10) == 0.2


def test_add_rule_defaults_confidence_to_one_and_returns_the_index():
    f = App.FuzzyLogic()
    f.SetMaxRules(2)
    assert f.AddRule(0, 10) == 0
    assert f.AddRule(1, 10) == 1
    assert f.AddRule(2, 10) == -1, "at capacity -> -1"
    assert f.GetMaxRules() == 2
    assert f.GetRule(0) == (0, 10, 1.0)


def test_unmatched_output_set_is_zero():
    f = App.FuzzyLogic()
    f.SetMaxRules(1)
    f.AddRule(0, 10)
    f.SetPercentageInSet(0, 1.0)
    assert f.GetResultBySet(99) == 0.0


def test_remove_rule_is_a_swap_remove():
    f = App.FuzzyLogic()
    f.SetMaxRules(3)
    f.AddRule(0, 10)
    f.AddRule(1, 11)
    f.AddRule(2, 12)
    f.RemoveRule(0)
    # The LAST rule is copied over index 0 — indices are not stable.
    assert f.GetRule(0) == (2, 12, 1.0)
    assert f.GetRule(1) == (1, 11, 1.0)


def test_set_rule_confidence():
    f = App.FuzzyLogic()
    f.SetMaxRules(1)
    f.AddRule(0, 10)
    f.SetRuleConfidence(0, 0.25)
    f.SetPercentageInSet(0, 1.0)
    assert f.GetResultBySet(10) == 0.25


def test_follow_object_partition_of_unity():
    """The real shape: FollowObject maps 4 inputs onto FS_STOP_AND_TURN_TOWARD
    and 2 onto FS_FAST_AND_TURN_TOWARD, with memberships that sum to 1.0 across
    all inputs. The two results must therefore also sum to 1.0."""
    NEAR_F, NEAR_L, MID_F, MID_L, FAR_F, FAR_L = range(6)
    STOP, FAST = 100, 101
    f = App.FuzzyLogic()
    f.SetMaxRules(6)
    f.AddRule(NEAR_F, STOP)
    f.AddRule(NEAR_L, STOP)
    f.AddRule(MID_F, FAST)
    f.AddRule(MID_L, STOP)
    f.AddRule(FAR_F, FAST)
    f.AddRule(FAR_L, STOP)

    near, mid, far = 0.0, 0.4, 0.6         # a distance partition
    facing, leaving = 0.75, 0.25           # a facing partition
    f.SetPercentageInSet(NEAR_F, near * facing)
    f.SetPercentageInSet(NEAR_L, near * leaving)
    f.SetPercentageInSet(MID_F, mid * facing)
    f.SetPercentageInSet(MID_L, mid * leaving)
    f.SetPercentageInSet(FAR_F, far * facing)
    f.SetPercentageInSet(FAR_L, far * leaving)

    stop = f.GetResultBySet(STOP)
    fast = f.GetResultBySet(FAST)
    assert abs(stop + fast - 1.0) < 1e-9, "the blend must preserve total mass"
    assert abs(fast - 0.75) < 1e-9
    assert abs(stop - 0.25) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_fuzzy_logic.py -v`
Expected: FAIL — `test_multiple_rules_onto_one_output_set_sum` returns 0.75 (the max) instead of
1.0; `GetMaxRules` / `GetRule` / `RemoveRule` / `SetRuleConfidence` raise `AttributeError`.

- [ ] **Step 3: Implement**

Replace `class FuzzyLogic` in `App.py` (currently lines 623 through the end of the class) with:

```python
class FuzzyLogic:
    """Weighted-edge fuzzy inference — a faithful port of Appc's FuzzyLogic.

    Ground truth: STBC-Reverse-Engineering-1/docs/gameplay/ai-architecture.md
    sec.12 (ctor 0x0047cd10, GetResultBySet 0x0047d0b0). A "rule" is literally a
    weighted edge `inputSet --confidence--> outputSet` carrying a runtime
    percentage-in-set scratch value. A script fuzzifies its inputs with
    FuzzyLogic_BreakIntoSets, pushes the memberships in with SetPercentageInSet,
    and reads back the UNNORMALIZED weighted sum of confidence x percentage over
    every edge targeting an output set. There is no defuzzification, no centroid,
    no normalization and no clamping — all blending is done in Python by the
    caller, which compares the raw sums against each other
    (AI/PlainAI/FollowObject.py:150-152).

    Every SDK caller uses the 2-arg AddRule(in, out) form, so confidence
    defaults to 1.0.
    """

    def __init__(self):
        self._max_rules: int = 0
        # Each rule: [input_set, output_set, confidence, percentage].
        self._rules: list = []

    def SetMaxRules(self, n) -> None:
        self._max_rules = int(n)

    def GetMaxRules(self) -> int:
        return self._max_rules

    def AddRule(self, input_set, output_set, confidence: float = 1.0) -> int:
        """Append a rule; return its index, or -1 at capacity."""
        if self._max_rules and len(self._rules) >= self._max_rules:
            return -1
        self._rules.append([int(input_set), int(output_set), float(confidence), 0.0])
        return len(self._rules) - 1

    def GetRule(self, index):
        i = int(index)
        if not (0 <= i < len(self._rules)):
            return None
        in_set, out_set, conf, _pct = self._rules[i]
        return (in_set, out_set, conf)

    def RemoveRule(self, index) -> None:
        """SWAP-REMOVE — the last rule is copied over `index`. Rule indices are
        NOT stable across removal (ai-architecture.md sec.12, 0x0047cdf0)."""
        i = int(index)
        if not (0 <= i < len(self._rules)):
            return
        last = self._rules.pop()
        if i < len(self._rules):
            self._rules[i] = last

    def SetRuleConfidence(self, index, confidence) -> None:
        i = int(index)
        if 0 <= i < len(self._rules):
            self._rules[i][2] = float(confidence)

    def SetPercentageInSet(self, set_id, value) -> None:
        """Write the percentage onto every rule whose INPUT set matches."""
        sid = int(set_id)
        v = float(value)
        for rule in self._rules:
            if rule[0] == sid:
                rule[3] = v

    def GetResultBySet(self, set_id) -> float:
        """Unnormalized sum of confidence x percentage over every rule whose
        OUTPUT set matches."""
        sid = int(set_id)
        return sum(rule[2] * rule[3] for rule in self._rules if rule[1] == sid)
```

Leave `FuzzyLogic_BreakIntoSets` (App.py:584-620) exactly as it is — it already matches ground
truth. Delete the now-false "Phase 1 implementation favours plausible behaviour" note at
App.py:580-582 only if it refers solely to FuzzyLogic; if it covers other symbols in that block,
leave it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_fuzzy_logic.py -v`
Expected: 7 passed.

- [ ] **Step 5: Run the AI suites — follow/waypoint speeds change**

Run: `uv run pytest tests/unit tests/integration -k "ai or follow or waypoint or circle" -q`
Expected: all pass. Any smoke test asserting a specific follower speed may now legitimately see a
*higher* (correct) impulse — if one fails, verify the new number against the SDK blend by hand
before touching the assertion, and update the test in the same commit.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_fuzzy_logic.py
git commit -m "fix(ai): FuzzyLogic.GetResultBySet sums confidence x percentage

Appc returns the unnormalized SUM over every rule targeting the output set
(ai-architecture.md sec.12, 0x0047d0b0). We returned a MAX and ignored
confidence. The docstring's claim that every SDK caller is single-antecedent is
false: FollowObject maps 4 input sets onto one output and FollowWaypoints maps 5,
then blend speeds against sums that are meant to be a partition of unity — so max
lost mass and impulse came out systematically low. Also adds the missing
GetRule/GetMaxRules/SetRuleConfidence and RemoveRule (swap-remove)."
```

---

### Task 6: Dispatch `GotFocus` / `LostFocus` to `PlainAI` leaves

`ai_driver` only dispatches the focus lifecycle to `PreprocessingAI` nodes
(`_tick_preprocessing:471`, `_reconcile_focus:90`). Four shipped leaf scripts define these hooks and
their bodies are all *cleanup that must run*:

- `AI/PlainAI/Warp.py:217-223` — `LostFocus` stops towing **and re-enables collisions it disabled**.
  An interrupted warp currently leaves the ship permanently non-collidable.
- `AI/PlainAI/RunAction.py:50-54` — `LostFocus` aborts the running action.
- `AI/PlainAI/Intercept.py:70-75` — `LostFocus` calls `StopInSystemWarp()`.
- `AI/PlainAI/StarbaseAttack.py:54-61` — `GotFocus` starts firing, `LostFocus` stops. A starbase
  that loses focus currently keeps firing forever.

The fix generalises the existing machinery: `_reconcile_focus` already tracks "which nodes were
reached this root tick" and dispatches `LostFocus` to the ones that dropped off. It just needs to
track `PlainAI` nodes too, and to read the hook off the right instance for each node type
(`_script_instance` for `PlainAI`, `_preprocessing_instance` for `PreprocessingAI`).

**Files:**
- Modify: `engine/appc/ai_driver.py:103-111` (`_dispatch_lost_focus`), `:114-139` (`_tick_plain`)
- Test: `tests/unit/test_ai_driver_leaf_focus.py` (create)

**Interfaces:**
- Consumes: `_reached_this_tick` / `_reconcile_focus` from `ai_driver` (unchanged shape — it now
  also receives `PlainAI` nodes).
- Produces: `_focus_instance_of(node)` — a module-level helper in `ai_driver` returning the Python
  script instance for either node type (`node._script_instance` for `PlainAI`,
  `node._preprocessing_instance` for `PreprocessingAI`, else `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ai_driver_leaf_focus.py`:

```python
"""PlainAI leaves get GotFocus() on entering the active path and LostFocus()
on leaving it — not just PreprocessingAI nodes.

Four shipped leaf scripts define these, and every body is cleanup that MUST run:
AI/PlainAI/Warp.py:217 (stop towing + RE-ENABLE COLLISIONS it disabled),
RunAction.py:50 (abort the action), Intercept.py:70 (StopInSystemWarp),
StarbaseAttack.py:54/58 (start/stop firing).
"""
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PriorityListAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _Leaf:
    """Stand-in for a PlainAI script: records the focus lifecycle."""
    def __init__(self, status=ArtificialIntelligence.US_ACTIVE):
        self.got = 0
        self.lost = 0
        self._status = status

    def GotFocus(self):
        self.got += 1

    def LostFocus(self):
        self.lost += 1

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        return self._status


def test_plain_ai_gets_got_focus_once_on_entering_the_path():
    ai = PlainAI_Create(None, "leaf")
    leaf = _Leaf()
    ai._script_instance = leaf

    tick_ai(ai, 0.0)
    tick_ai(ai, 0.1)
    assert leaf.got == 1, "GotFocus fires once, not every tick"
    assert leaf.lost == 0


def test_plain_ai_gets_lost_focus_when_a_sibling_takes_over():
    """A priority list whose high-priority child goes DORMANT hands focus to the
    next child; the incumbent must be told it lost focus."""
    plist = PriorityListAI_Create(None, "root")

    hi = PlainAI_Create(None, "hi")
    hi_leaf = _Leaf(status=ArtificialIntelligence.US_ACTIVE)
    hi._script_instance = hi_leaf

    lo = PlainAI_Create(None, "lo")
    lo_leaf = _Leaf(status=ArtificialIntelligence.US_ACTIVE)
    lo._script_instance = lo_leaf

    plist.AddAI(hi, 0)
    plist.AddAI(lo, 1)

    tick_ai(plist, 0.0)
    assert hi_leaf.got == 1
    assert lo_leaf.got == 0

    # The high-priority leaf goes dormant: focus must move to `lo`, and `hi`
    # must get LostFocus().
    hi_leaf._status = ArtificialIntelligence.US_DORMANT
    tick_ai(plist, 0.1)          # hi reports DORMANT and is skipped from here on
    tick_ai(plist, 0.2)          # lo now runs

    assert lo_leaf.got == 1, "the new incumbent gains focus"
    assert hi_leaf.lost == 1, "the displaced leaf loses focus exactly once"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_ai_driver_leaf_focus.py -v`
Expected: FAIL — `assert leaf.got == 1` (got 0): `PlainAI` never receives the focus lifecycle.

- [ ] **Step 3: Implement**

In `engine/appc/ai_driver.py`, replace `_dispatch_lost_focus` (currently lines 103-111) with:

```python
def _focus_instance_of(node):
    """The Python script instance that carries a node's focus hooks.

    PlainAI keeps it in _script_instance; PreprocessingAI in
    _preprocessing_instance. Read from __dict__ so TGObject.__getattr__ can't
    hand back a truthy _Stub for a node type that has neither.
    """
    d = getattr(node, "__dict__", {})
    return d.get("_script_instance") or d.get("_preprocessing_instance")


def _dispatch_lost_focus(node) -> None:
    """Call the node's script instance's LostFocus() (if any) and clear the
    focus latches so a later re-entry re-fires GotFocus()."""
    inst = _focus_instance_of(node)
    lost = getattr(inst, "LostFocus", None) if inst is not None else None
    if callable(lost):
        lost()
    node._has_focus = False
    node.__dict__["_got_focus_called"] = False


def _dispatch_got_focus(node) -> None:
    """Call the node's script instance's GotFocus() once per activation.

    SDK leaves put real work here: StarbaseAttack.GotFocus starts firing
    (AI/PlainAI/StarbaseAttack.py:54). Guarded by a sentinel in __dict__ so
    repeat ticks don't re-fire; _dispatch_lost_focus clears it.
    """
    if node.__dict__.get("_got_focus_called", False):
        return
    inst = _focus_instance_of(node)
    got = getattr(inst, "GotFocus", None) if inst is not None else None
    if callable(got):
        got()
    node.__dict__["_got_focus_called"] = True
```

In `_tick_preprocessing`, replace the inline GotFocus block (currently lines 471-475):

```python
    if not ai.__dict__.get("_got_focus_called", False):
        got_focus = getattr(inst, "GotFocus", None)
        if callable(got_focus):
            got_focus()
        ai._got_focus_called = True
```

with:

```python
    _dispatch_got_focus(ai)
```

In `_tick_plain`, replace the whole function (currently lines 114-139) with:

```python
def _tick_plain(ai: PlainAI, game_time: float) -> int:
    if ai._status != US_ACTIVE:
        return ai._status

    # A PlainAI reached on the active dispatch path holds focus this tick — the
    # same surrogate the PreprocessingAI path uses. Four shipped leaf scripts put
    # real work in these hooks, and every LostFocus body is cleanup that MUST
    # run: Warp.py:217 re-enables the collisions it disabled (an interrupted warp
    # otherwise leaves the ship permanently non-collidable), RunAction.py:50
    # aborts the running action, Intercept.py:70 stops the in-system warp,
    # StarbaseAttack.py:58 stops firing.
    ai._has_focus = True
    _reached_this_tick.append(ai)
    _dispatch_got_focus(ai)

    if game_time < ai._next_update_time:
        return ai._status
    inst = ai.GetScriptInstance()
    # Script-instance Update is the per-AI heartbeat. Leaves registered purely
    # for external-function dispatch (SetTarget callbacks under a SelectTarget
    # preprocessor, e.g.) may legitimately omit it; treat a missing Update as
    # "no work this tick".
    update_fn = getattr(inst, "Update", None)
    if update_fn is None or not callable(update_fn):
        return ai._status
    status = update_fn()
    if status is None:
        status = US_ACTIVE
    ai._status = int(status)
    # Reschedule from the script's reported interval. Appc's PlainAI::Update
    # bridge returns 0.0 when the Python call fails, which makes the AI run every
    # tick (ai-architecture.md sec.3: "There is no default interval in C++").
    next_update_fn = getattr(inst, "GetNextUpdateTime", None)
    next_update = next_update_fn() if callable(next_update_fn) else None
    interval = float(next_update) if next_update is not None else 0.0
    ai._next_update_time = game_time + interval
    return ai._status
```

Note the second change folded in here: the missing-`GetNextUpdateTime` fallback goes from `1.0` to
`0.0`, matching `PlainAI::GetNextUpdateTime` (`0x0048d320`), which returns 0.0 on Python failure so
the AI runs every tick.

Finally, `_reconcile_focus`'s docstring (line 91) says "preprocessors"; update it to say "nodes",
since it now reconciles `PlainAI` leaves too.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_ai_driver_leaf_focus.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the AI suites**

Run: `uv run pytest tests/unit tests/integration -k "ai" -q`
Expected: all pass. `tests/unit/test_ai_driver_focus_loss.py` and `test_ai_driver_got_focus.py`
cover the preprocessor path and must stay green — the refactor routes them through the same two
helpers.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai_driver.py tests/unit/test_ai_driver_leaf_focus.py
git commit -m "fix(ai): dispatch GotFocus/LostFocus to PlainAI leaves

Only PreprocessingAI nodes got the focus lifecycle. Four shipped leaf scripts
define these hooks and every LostFocus body is required cleanup — most sharply
Warp.LostFocus, which re-enables the collisions the warp disabled, so an
interrupted warp left the ship permanently non-collidable. Also drops the
missing-GetNextUpdateTime fallback from 1.0s to 0.0 (run every tick), matching
PlainAI::GetNextUpdateTime, which has no C++ default interval."
```

---

### Task 7: `Weapon_Cast` and `PulseWeaponSystem_Cast`

Live stub hits, ranks 10 and 15 in `docs/stub_heatmap.md` (250 and 151 hits/session), both squarely
in the AI's weapon path:

- `App.Weapon_Cast` is undefined. `AI/PlainAI/IntelligentCircleObject.py:62-64` does
  `pWeapon = App.Weapon_Cast(pSystem.GetChildSubsystem(i))` then `if pWeapon:` — the stub is truthy,
  so the script builds its whole weapon list out of stubs and its shield/weapon-angle caching
  operates on garbage.
- `App.PulseWeaponSystem_Cast` is undefined. `AI/Preprocessors.py:771-778` does
  `pPulseSystem = App.PulseWeaponSystem_Cast(pWeaponSystem)`, `if (pPulseSystem != None):` — truthy
  stub — then `range(pPulseSystem.GetNumChildSubsystems())`, which coerces a stub to `int() == 0`.
  **The AI therefore never enumerates pulse-weapon firing directions at all.**

Both are ordinary downcasts. Find the existing `*_Cast` block in `App.py`
(`grep -n "_Cast = \|def .*_Cast" App.py`) and follow its established pattern exactly.

**Files:**
- Modify: `App.py` (the `*_Cast` block)
- Test: `tests/unit/test_weapon_casts.py` (create)

**Interfaces:**
- Consumes: `engine.appc.weapon_subsystems` class names — confirm them first with
  `grep -n "^class " engine/appc/weapon_subsystems.py`.
- Produces: `App.Weapon_Cast(obj)` returns `obj` if it is a `Weapon` (the per-emitter leaf
  subsystem: phaser emitter, torpedo tube, pulse weapon), else `None`.
  `App.PulseWeaponSystem_Cast(obj)` returns `obj` if it is a `PulseWeaponSystem`, else `None`.

- [ ] **Step 1: Confirm the class names**

Run: `grep -n "^class " engine/appc/weapon_subsystems.py`
Note the exact names of the pulse-weapon system class and of the common weapon base class (the one
`PhaserEmitter` / `TorpedoTube` / `PulseWeapon` all derive from). Use those exact names below. If no
common weapon base class exists, add one in this task — `Weapon` — and make the emitter classes
derive from it; that is what `Weapon_Cast` is casting to.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_weapon_casts.py`, using the class names confirmed in Step 1:

```python
"""App.Weapon_Cast / App.PulseWeaponSystem_Cast are real downcasts.

Both were undefined, so App.__getattr__ returned a truthy _NamedStub:
- AI/PlainAI/IntelligentCircleObject.py:62-64 built its weapon list out of stubs
  (heatmap rank 10, 250 hits/session).
- AI/Preprocessors.py:771-778 took the pulse branch on every weapon system, then
  int()-coerced the stub to 0 in range(GetNumChildSubsystems()) — so the AI never
  enumerated pulse-weapon firing directions at all (heatmap ranks 15/17, 151 hits).
"""
import App
from engine.appc.weapon_subsystems import PulseWeaponSystem, PhaserSystem


def test_pulse_weapon_system_cast_accepts_a_pulse_system():
    sys_ = PulseWeaponSystem()
    assert App.PulseWeaponSystem_Cast(sys_) is sys_


def test_pulse_weapon_system_cast_rejects_a_phaser_system():
    assert App.PulseWeaponSystem_Cast(PhaserSystem()) is None


def test_pulse_weapon_system_cast_rejects_none_and_arbitrary_objects():
    assert App.PulseWeaponSystem_Cast(None) is None
    assert App.PulseWeaponSystem_Cast(object()) is None


def test_weapon_cast_rejects_a_weapon_system():
    """A *System* is a container of weapons, not a weapon."""
    assert App.Weapon_Cast(PhaserSystem()) is None
```

Add one positive `Weapon_Cast` case constructing whatever the concrete leaf weapon class is (from
Step 1) and asserting the cast returns it.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_weapon_casts.py -v`
Expected: FAIL — the casts return `_NamedStub`s, not `None`/the object.

- [ ] **Step 4: Implement**

In `App.py`, in the `*_Cast` block, following the existing pattern exactly:

```python
def PulseWeaponSystem_Cast(obj):
    return obj if isinstance(obj, PulseWeaponSystem) else None


def Weapon_Cast(obj):
    """The per-emitter leaf subsystem (phaser emitter / torpedo tube / pulse
    weapon), NOT the containing WeaponSystem. AI/PlainAI/
    IntelligentCircleObject.py:62-64 walks a system's children through this."""
    return obj if isinstance(obj, Weapon) else None
```

with the imports added to the existing `from engine.appc.weapon_subsystems import (...)` block.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_weapon_casts.py -v`
Expected: all pass.

- [ ] **Step 6: Run the AI + weapon suites**

Run: `uv run pytest tests/unit tests/integration -k "ai or weapon or fire" -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add App.py engine/appc/weapon_subsystems.py tests/unit/test_weapon_casts.py
git commit -m "fix(ai): implement Weapon_Cast and PulseWeaponSystem_Cast

Both were undefined, so App.__getattr__ handed back a truthy _NamedStub.
IntelligentCircleObject built its weapon list out of stubs, and FireScript's
pulse branch int()-coerced GetNumChildSubsystems to 0 — the AI never enumerated
pulse-weapon firing directions at all. Heatmap ranks 10/15/17."
```

---

### Task 8: `WeaponSystem.ShouldBeAimed` — resolve the default from evidence, then implement

`AI/Preprocessors.py:642-647` (`FireScript.CheckGoodShot`) opens with:

```python
if not pWeaponSystem.ShouldBeAimed():
    # Nope.  It can be fired from any direction.  We have a good shot anytime.
    return 1
```

`ShouldBeAimed` is unimplemented on both `PhaserSystem` and `TorpedoSystem` (heatmap ranks 16 and
18, 151 hits each). The stub is truthy, so the AI never takes the free-fire fast path and runs the
full aim check on every weapon.

**This task must not guess the default.** Ground truth (`weapon-firing-mechanics.md:711`):
`WeaponSystem::ShouldBeAimed` (`0x00584070`) reads **`WeaponSystemProperty + 0x51`** — it is an
*authored property flag*, not a per-class constant. No SDK hardpoint file sets it
(`grep -rn ShouldBeAimed sdk/` returns only the Preprocessors call site), so the value comes from
whatever the C++ `WeaponSystemProperty` constructor initialises `+0x51` to, possibly overridden per
system type.

- [ ] **Step 1: Establish the truth before writing any code**

Read `/Users/mward/Documents/Projects/STBC-Reverse-Engineering-1/reference/decompiled/` for the
`WeaponSystemProperty` constructor and find the initialiser for offset `+0x51`, and for any
per-subclass (`PhaserSystemProperty`, `TorpedoSystemProperty`, `PulseWeaponSystemProperty`)
override. Record the finding — the address, the byte, and the resulting default — in the commit
message.

**If the corpus does not settle it, STOP and report BLOCKED.** Do not implement a guessed default:
getting this backwards inverts the AI's firing gate for an entire weapon class, and CLAUDE.md's
evidence rules (three tiers: SDK / SWIG / RE'd binary) put the decompiled binary above inference.
Write the open question up for the RE project instead, in the same shape as the `PS_*` question
already sent, and move on to Task 9.

- [ ] **Step 2: Write the failing test** (only once Step 1 has settled the default)

Create `tests/unit/test_should_be_aimed.py` asserting the *evidenced* defaults per system type, plus
that `SetShouldBeAimed` on the property round-trips through `WeaponSystem.ShouldBeAimed()`.

- [ ] **Step 3: Run it, verify it fails, implement, verify it passes**

Add `_should_be_aimed` to `WeaponSystemProperty` (`engine/appc/properties.py:760`) with the evidenced
default, `SetShouldBeAimed` / `ShouldBeAimed` accessors on the property, and a
`ShouldBeAimed()` method on `WeaponSystem` that reads `self.GetProperty().ShouldBeAimed()`.

- [ ] **Step 4: Run the AI + weapon suites**

Run: `uv run pytest tests/unit tests/integration -k "ai or weapon or fire" -q`
Expected: all pass. NPC firing cadence may change — that is the point — but nothing should error.

- [ ] **Step 5: Commit**, citing the decompiled address that established the default.

---

### Task 9: Call `CodeAISet()` at bind time

Ground truth (`ai-architecture.md` §4, `PreprocessingAI::SetPreprocessingMethod` `0x0048e400`): the
engine binds the C++ node to an already-existing Python instance by writing the `pCodeAI` attribute
onto it, then **calls `CodeAISet()` on the instance if it exists**.

We never call it. Instead `ai_driver` hand-reimplements two specific cases with duck-typed hacks
(`_ensure_fire_script_initialized`, `_ensure_select_target_initialized`, lines 572-645). The result
is that the preprocessors with a *real* `CodeAISet` that we do not special-case never initialise:
`UpdateAIStatus.CodeAISet` (`AI/Preprocessors.py:2171` — registers the `QueryAIStatus` external
function) and `UseShipTarget.CodeAISet` (`:2345` — installs the target-changed handler and grabs the
initial target), plus `AI/Compound/ChainFollowThroughWarp.py:25` and
`AI/Compound/TractorDockTargets.py:12`.

Two things must **not** change:

- `FireScript.CodeAISet` (`AI/Preprocessors.py:137-145`) is real and does exactly what
  `_ensure_fire_script_initialized` does by hand. Calling `CodeAISet()` generically makes that hack
  redundant — **delete it.**
- `SelectTarget.CodeAISet` is **commented out** (`AI/Preprocessors.py:1133-1157`) because the native
  `OptimizedSelectTarget` constructor did that work. So `_ensure_select_target_initialized` is
  standing in for the *C++* class, not for dead Python — **keep it.**

**Files:**
- Modify: `engine/appc/ai.py:559-591` (`SetPreprocessingMethod`)
- Modify: `engine/appc/ai_driver.py` — delete `_ensure_fire_script_initialized` (624-645) and its call site (439-440)
- Test: `tests/unit/test_codeaiset_bind.py` (create)

**Interfaces:**
- Consumes: `PreprocessingAI._preprocessing_instance`, `.pCodeAI` binding (unchanged).
- Produces: `PreprocessingAI.SetPreprocessingMethod(instance, method_name)` calls
  `instance.CodeAISet()` after binding `pCodeAI`, if the instance defines it.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_codeaiset_bind.py`:

```python
"""SetPreprocessingMethod calls CodeAISet() on the bound instance.

Appc's PreprocessingAI::SetPreprocessingMethod (0x0048e400) writes pCodeAI onto
the Python instance and then calls its CodeAISet() hook. Four shipped
preprocessors have a real one; ours never fired, so UpdateAIStatus never
registered QueryAIStatus and UseShipTarget never installed its target handler.
"""
from engine.appc.ai import PreprocessingAI_Create


class _Preproc:
    def __init__(self):
        self.code_ai_set_calls = 0
        self.pCodeAI_at_call = "unset"

    def CodeAISet(self):
        self.code_ai_set_calls += 1
        # pCodeAI MUST already be bound when the hook runs — the shipped hooks
        # dereference it (FireScript.CodeAISet calls
        # self.pCodeAI.RegisterExternalFunction).
        self.pCodeAI_at_call = self.pCodeAI

    def Update(self, dEndTime):
        return None


class _NoHook:
    def Update(self, dEndTime):
        return None


def test_code_ai_set_is_called_after_pcodeai_is_bound():
    node = PreprocessingAI_Create(None, "wrap")
    inst = _Preproc()
    node.SetPreprocessingMethod(inst, "Update")

    assert inst.code_ai_set_calls == 1
    assert inst.pCodeAI_at_call is node


def test_an_instance_without_the_hook_binds_cleanly():
    node = PreprocessingAI_Create(None, "wrap")
    inst = _NoHook()
    node.SetPreprocessingMethod(inst, "Update")   # must not raise
    assert node.GetPreprocessingInstance() is inst
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_codeaiset_bind.py -v`
Expected: FAIL — `assert inst.code_ai_set_calls == 1` (got 0).

- [ ] **Step 3: Implement**

In `engine/appc/ai.py`, in `SetPreprocessingMethod`, immediately after the existing
`args[0].pCodeAI = self` try/except block (currently ending at line 591), add:

```python
            # Appc's SetPreprocessingMethod calls the instance's CodeAISet() hook
            # once pCodeAI is bound (ai-architecture.md sec.4, 0x0048e400). Four
            # shipped preprocessors define a real one: FireScript (registers the
            # SetTarget external function), UpdateAIStatus (registers
            # QueryAIStatus), UseShipTarget (installs the target-changed handler)
            # and the ChainFollowThroughWarp / TractorDockTargets compounds.
            # SelectTarget's is commented out in the SDK because the native
            # OptimizedSelectTarget ctor did that work — ai_driver's
            # _ensure_select_target_initialized still stands in for the C++ class.
            code_ai_set = getattr(args[0], "CodeAISet", None)
            if callable(code_ai_set):
                try:
                    code_ai_set()
                except Exception as _e:
                    dev_mode.log_swallowed("CodeAISet", _e)
```

In `engine/appc/ai_driver.py`, delete the `_ensure_fire_script_initialized` function (lines 624-645)
and its call site in `_tick_preprocessing` (lines 439-440):

```python
    if hasattr(inst, "lWeapons") and getattr(inst, "pCodeAI", None) is not None:
        _ensure_fire_script_initialized(inst)
```

`FireScript.CodeAISet` now does that same registration through the generic path.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_codeaiset_bind.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the AI suites — the FireScript path just changed owner**

Run: `uv run pytest tests/unit tests/integration -k "ai or fire" -q`
Expected: all pass. `tests/unit/test_ai_driver_fire_script_init.py` specifically covers the deleted
hack. It must either still pass through the generic path (best) or be rewritten in this same commit
to assert the same end state via `SetPreprocessingMethod` — do not delete it, and do not leave it
asserting a function that no longer exists.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py engine/appc/ai_driver.py tests/unit/test_codeaiset_bind.py tests/unit/test_ai_driver_fire_script_init.py
git commit -m "fix(ai): call CodeAISet() on the instance at bind time

Appc's PreprocessingAI::SetPreprocessingMethod calls the Python instance's
CodeAISet() hook once pCodeAI is bound. We never did — we hand-reimplemented two
cases in the driver instead — so UpdateAIStatus never registered QueryAIStatus
and UseShipTarget never installed its target handler. The generic call subsumes
_ensure_fire_script_initialized (an exact copy of FireScript.CodeAISet), which is
deleted. _ensure_select_target_initialized stays: SelectTarget's own CodeAISet is
commented out in the SDK because the native OptimizedSelectTarget ctor did it."
```

---

### Task 10: `GetFocusAIs` and `GetStatusInfo` — the AI status-report path

`AI/Preprocessors.py:2230` (`FelixReportStatus.Update`) calls `self.pCodeAI.GetFocusAIs()`.
`ArtificialIntelligence` is a plain Python class with no such method, so this raises
`AttributeError` straight out of `_tick_preprocessing`, which has no guard. Every one of the 28
`AI/Player/*` trees roots a `FelixReportStatus` (e.g. `AI/Player/Defense.py:222`), so wiring the
player-order menu without this **will crash the AI tick**.

Ground truth (`ai-architecture.md` §4, hand-registered method table): `GetFocusAIs` is
`0x00470f70` on `ArtificialIntelligence`. It returns the AIs along the current **focus path** —
i.e. the nodes actually holding focus — which after Task 6 is exactly the set every node type now
latches in `_has_focus`.

`GetStatusInfo` is the paired half: `UpdateAIStatus.QueryAIStatus` (`:2178`) appends its status
string to a list passed through `CallExternalFunction`, and `FelixReportStatus` reads the last entry.
Once `GetFocusAIs` exists and Task 9 makes `UpdateAIStatus.CodeAISet` register `QueryAIStatus`, that
whole path works with no further change.

**Files:**
- Modify: `engine/appc/ai.py` — add `GetFocusAIs` to `ArtificialIntelligence` (near `GetAllAIsInTree`, ~line 248)
- Test: `tests/unit/test_get_focus_ais.py` (create)

**Interfaces:**
- Consumes: `ArtificialIntelligence._has_focus` (set by `ai_driver` for both `PlainAI` and
  `PreprocessingAI` after Task 6), `GetAllAIsInTree()`.
- Produces: `ArtificialIntelligence.GetFocusAIs() -> list` — the subset of `GetAllAIsInTree()` whose
  `HasFocus()` is true, in the same order.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_get_focus_ais.py`:

```python
"""GetFocusAIs returns the AIs on the current focus path.

AI/Preprocessors.py:2230 (FelixReportStatus.Update) calls
self.pCodeAI.GetFocusAIs(). We didn't define it, and ArtificialIntelligence is a
plain class — so it raised AttributeError straight out of the AI tick. All 28
AI/Player trees root a FelixReportStatus.
"""
from engine.appc.ai import PlainAI_Create, PriorityListAI_Create


def test_get_focus_ais_returns_only_the_focused_nodes_in_tree_order():
    root = PriorityListAI_Create(None, "root")
    a = PlainAI_Create(None, "a")
    b = PlainAI_Create(None, "b")
    root.AddAI(a, 0)
    root.AddAI(b, 1)

    assert root.GetFocusAIs() == []

    a._has_focus = True
    assert root.GetFocusAIs() == [a]

    b._has_focus = True
    assert root.GetFocusAIs() == [a, b]


def test_get_focus_ais_includes_self_when_self_has_focus():
    root = PriorityListAI_Create(None, "root")
    root._has_focus = True
    assert root.GetFocusAIs() == [root]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_get_focus_ais.py -v`
Expected: FAIL — `AttributeError: 'PriorityListAI' object has no attribute 'GetFocusAIs'`.

- [ ] **Step 3: Implement**

In `engine/appc/ai.py`, in `class ArtificialIntelligence`, directly after `GetAllAIsInTree`
(~line 275), add:

```python
    def GetFocusAIs(self) -> list:
        """The AIs on the current focus path, self first if self has focus.

        Appc hand-registers this on ArtificialIntelligence (0x00470f70;
        ai-architecture.md sec.4). AI/Preprocessors.py:2230
        (FelixReportStatus.Update) walks it and calls CallExternalFunction(
        "QueryAIStatus", lStatus) on each node, which is how the crew report
        what the AI is currently doing. Every AI/Player tree roots one of these.

        The focus latch is written by ai_driver for every node it reaches on the
        active dispatch path, so "reached this tick" == "has focus".
        """
        return [ai for ai in self.GetAllAIsInTree() if ai.HasFocus()]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_get_focus_ais.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the AI suites**

Run: `uv run pytest tests/unit tests/integration -k "ai" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_get_focus_ais.py
git commit -m "feat(ai): implement ArtificialIntelligence.GetFocusAIs

FelixReportStatus.Update (AI/Preprocessors.py:2230) calls it, and every one of
the 28 AI/Player trees roots a FelixReportStatus — so the method's absence would
raise AttributeError straight out of the AI tick the moment player orders are
wired. With Task 9's CodeAISet call registering QueryAIStatus on UpdateAIStatus,
the whole AI-status-report path now works."
```

---

### Task 11: `SequenceAI` flags and finite loop counts

`SequenceAI` stores `_skip_dormant`, `_double_check_all_done` and `_reset_if_interrupted` and
**never reads any of them** (`engine/appc/ai.py:455-480`; `ai_driver._tick_sequence:206-274`). All
nine E7 mission AI trees set all three explicitly (e.g. `Maelstrom/Episode7/E7M2/EnemyAI.py:60-63`:
`SetLoopCount(1)`, `SetResetIfInterrupted(1)`, `SetDoubleCheckAllDone(0)`, `SetSkipDormant(0)`).
Finite loop counts above 1 are also unsupported: `_tick_sequence` treats any non-negative count as
"one pass, then DONE".

Ground truth (`ai-architecture.md` §2, `SequenceAI::Update` `0x00492d00`): a child returning
`US_ACTIVE` blocks the sequence (immediate ACTIVE return). `US_DORMANT` — or `US_DONE` with the
double-check flag set — advances the cursor. Wrapping decrements the loop counter at `+0x34`
(**−1 = loop forever**). All children done → `US_DONE`.

Our current code *blocks* on a dormant child, with a comment citing `SetSkipDormant(0)`. Reconcile
the two by making the flag actually drive the behaviour, and keep the current
blocking behaviour as what `SetSkipDormant(0)` means — which is what those nine trees ask for.

**Files:**
- Modify: `engine/appc/ai.py:449-480` (`SequenceAI` — add `_loops_remaining`)
- Modify: `engine/appc/ai_driver.py:206-274` (`_tick_sequence`)
- Test: `tests/unit/test_sequence_ai_flags.py` (create)

**Interfaces:**
- Consumes: `SequenceAI._ais`, `._loop_count`, `._skip_dormant`, `._double_check_all_done`,
  `._reset_if_interrupted`.
- Produces: `SequenceAI._loops_remaining: int` — initialised to `_loop_count` and decremented on
  each wrap; `-1` means forever. `SetLoopCount(n)` resets it.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sequence_ai_flags.py`:

```python
"""SequenceAI honours SetSkipDormant / SetLoopCount.

Ground truth: ai-architecture.md sec.2 (SequenceAI::Update 0x00492d00) — an
ACTIVE child blocks the sequence; a DORMANT child advances the cursor; wrapping
decrements the loop counter (-1 = forever). All nine E7 mission AI trees set the
flags explicitly (Maelstrom/Episode7/E7M2/EnemyAI.py:60-63), and we stored all
three and read none of them.
"""
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, SequenceAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _Leaf:
    def __init__(self, status):
        self.status = status
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return self.status


def _leaf(name, status):
    ai = PlainAI_Create(None, name)
    ai._script_instance = _Leaf(status)
    return ai


def test_skip_dormant_1_advances_past_a_dormant_child():
    seq = SequenceAI_Create(None, "seq")
    seq.SetSkipDormant(1)
    dormant = _leaf("dormant", ArtificialIntelligence.US_DORMANT)
    runner = _leaf("runner", ArtificialIntelligence.US_ACTIVE)
    seq.AddAI(dormant)
    seq.AddAI(runner)

    tick_ai(seq, 0.0)
    tick_ai(seq, 0.1)
    assert runner._script_instance.updates >= 1, "dormant child must be skipped"


def test_skip_dormant_0_blocks_on_a_dormant_child():
    seq = SequenceAI_Create(None, "seq")
    seq.SetSkipDormant(0)          # what all nine E7 trees ask for
    dormant = _leaf("dormant", ArtificialIntelligence.US_DORMANT)
    runner = _leaf("runner", ArtificialIntelligence.US_ACTIVE)
    seq.AddAI(dormant)
    seq.AddAI(runner)

    tick_ai(seq, 0.0)
    tick_ai(seq, 0.1)
    assert runner._script_instance.updates == 0, "dormant child must block"


def test_finite_loop_count_runs_that_many_passes():
    seq = SequenceAI_Create(None, "seq")
    seq.SetLoopCount(2)
    only = _leaf("only", ArtificialIntelligence.US_DONE)
    seq.AddAI(only)

    for t in range(10):
        tick_ai(seq, float(t))

    assert only._script_instance.updates == 2, "two passes, then done"
    assert seq._status == ArtificialIntelligence.US_DONE


def test_loop_count_minus_one_loops_forever():
    seq = SequenceAI_Create(None, "seq")
    seq.SetLoopCount(-1)
    only = _leaf("only", ArtificialIntelligence.US_DONE)
    seq.AddAI(only)

    for t in range(6):
        tick_ai(seq, float(t))

    assert only._script_instance.updates >= 3
    assert seq._status != ArtificialIntelligence.US_DONE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_sequence_ai_flags.py -v`
Expected: FAIL — `test_skip_dormant_1_advances_past_a_dormant_child` (the flag is ignored and the
sequence blocks) and `test_finite_loop_count_runs_that_many_passes` (only one pass runs).

- [ ] **Step 3: Implement**

In `engine/appc/ai.py`, in `SequenceAI.__init__`, after `self._loop_count: int = 1`, add:

```python
        # Passes remaining. -1 = forever (ai-architecture.md sec.2: the C++ node
        # keeps the remaining-loop count at +0x34 and decrements it on wrap).
        self._loops_remaining: int = 1
```

and replace `SetLoopCount` with:

```python
    def SetLoopCount(self, n) -> None:
        self._loop_count = int(n)
        self._loops_remaining = int(n)
```

In `engine/appc/ai_driver.py`, replace `_wrap_or_finish` inside `_tick_sequence` (currently lines
231-242) with:

```python
    def _wrap_or_finish(i):
        """Index walked off the end: consume a loop, wrap + re-arm, else finish.

        Returns the new index to keep scanning from, or None if the sequence is
        finished (status already set to US_DONE). ai-architecture.md sec.2:
        wrapping decrements the remaining-loop counter; -1 = loop forever.
        """
        remaining = int(getattr(ai, "_loops_remaining", 1))
        if remaining > 0:
            remaining -= 1
            ai._loops_remaining = remaining
        if remaining == 0:
            ai._current_index = i
            ai._status = US_DONE
            return None
        # Forever (-1) or passes still owed: re-arm the children and wrap.
        for child in ai._ais:
            child._status = US_ACTIVE
        return 0
```

and delete the now-unused `looping` local (line 228), replacing its two other uses (lines 273) with
a check on `_loops_remaining != 0`.

Replace the dormant branch (currently lines 253-256) with:

```python
        if child._status == US_DORMANT:
            if int(getattr(ai, "_skip_dormant", 0)):
                # SetSkipDormant(1): a dormant child is stepped over.
                idx += 1
                continue
            # SetSkipDormant(0) — what all nine E7 trees ask for
            # (Maelstrom/Episode7/E7M2/EnemyAI.py:63): a dormant child HOLDS the
            # sequence in place rather than being skipped.
            ai._current_index = idx
            ai._status = US_ACTIVE
            return ai._status
```

Leave `_double_check_all_done` and `_reset_if_interrupted` stored-but-unused for now, and say so in
a comment on each setter in `ai.py` naming the RE doc section that describes them — they are not
load-bearing for any tree we currently run, and inventing semantics for them without evidence is
exactly what CLAUDE.md forbids.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_sequence_ai_flags.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the AI suites — CloakAttack's forever-loops run through this**

Run: `uv run pytest tests/unit tests/integration -k "ai or cloak or sequence" -q`
Expected: all pass. `tests/unit/test_cloak_ai_doctrine.py` exercises the `SetLoopCount(-1)` path.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py engine/appc/ai_driver.py tests/unit/test_sequence_ai_flags.py
git commit -m "fix(ai): SequenceAI honours SetSkipDormant and finite loop counts

All three sequence flags were stored and never read, and any non-negative loop
count ran exactly one pass. All nine E7 mission trees set the flags explicitly.
SetSkipDormant now drives whether a dormant child blocks (0, what those trees
ask for) or is stepped over (1); SetLoopCount(n>1) runs n passes; -1 still loops
forever. DoubleCheckAllDone / ResetIfInterrupted remain stored-only and are
documented as such — no tree we run depends on them and their exact semantics are
not established by the RE corpus."
```

---

### Task 12: `RandomAI` draws without replacement

Ground truth (`ai-architecture.md` §2, `RandomAI::Update` `0x004917f0`; layout §1): the node keeps a
per-child **"already tried" byte array** (`+0x2C`) and draws a new child from the *un-tried* entries,
clearing the flag and re-drawing on `DORMANT`/`DONE`. Ours (`ai_driver._tick_random:277-302`) calls
`random.choice` over *all* children every time, so the same maneuver can repeat back-to-back — the
opposite of what a shuffle-style maneuver picker is for. `AI/Compound/Parts/NoSensorsEvasive.py:47-52`
and `QuickBattle/QuickBattleAI.py:51-58` are the users.

Note the docstring at `engine/appc/ai.py:494` currently cites the RE doc as saying "picks another on
completion" — the doc actually specifies draw-without-replacement. Fix the docstring too.

**Files:**
- Modify: `engine/appc/ai.py:489-518` (`RandomAI` — add `_untried`)
- Modify: `engine/appc/ai_driver.py:277-302` (`_tick_random`)
- Test: `tests/unit/test_random_ai_without_replacement.py` (create)

**Interfaces:**
- Consumes: `RandomAI._ais`, `._current_child`.
- Produces: `RandomAI._untried: list` — the children not yet drawn in the current cycle; refilled
  from `_ais` when it empties.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_random_ai_without_replacement.py`:

```python
"""RandomAI draws from the UN-TRIED children, not from all of them.

Ground truth: ai-architecture.md sec.1/sec.2 — the C++ node keeps a per-child
"already tried" byte array (+0x2C) and draws a new child from the un-tried
entries, re-drawing on DORMANT/DONE. Drawing with replacement lets the same
evasive maneuver repeat back-to-back, which is precisely what the shuffle is
there to prevent (AI/Compound/Parts/NoSensorsEvasive.py:47-52).
"""
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, RandomAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _DoneLeaf:
    """Completes immediately, so RandomAI re-draws on every tick."""
    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return ArtificialIntelligence.US_DONE


def test_every_child_runs_once_before_any_child_repeats():
    rnd = RandomAI_Create(None, "rnd")
    children = []
    for i in range(4):
        ai = PlainAI_Create(None, f"c{i}")
        ai._script_instance = _DoneLeaf()
        rnd.AddAI(ai)
        children.append(ai)

    # Four draws must cover all four children exactly once.
    for t in range(4):
        tick_ai(rnd, float(t))

    counts = [c._script_instance.updates for c in children]
    assert sorted(counts) == [1, 1, 1, 1], f"expected a full shuffle, got {counts}"

    # The fifth draw refills the pool and starts a new cycle.
    tick_ai(rnd, 4.0)
    counts = [c._script_instance.updates for c in children]
    assert sum(counts) == 5
    assert max(counts) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_random_ai_without_replacement.py -v`
Expected: FAIL — `random.choice` over all children gives an uneven distribution
(`assert sorted(counts) == [1, 1, 1, 1]` fails for almost any seed).

- [ ] **Step 3: Implement**

In `engine/appc/ai.py`, in `RandomAI.__init__`, after `self._current_child = None`, add:

```python
        # Children not yet drawn this cycle. The C++ node keeps this as an
        # "already tried" byte array (+0x2C) and draws only from the un-tried
        # entries, refilling when they run out — so every maneuver runs before any
        # repeats (ai-architecture.md sec.1/sec.2).
        self._untried: list = []
```

and make `AddAI` keep it in sync:

```python
    def AddAI(self, ai) -> None:
        """SDK Appc.RandomAI_AddAI — append a child AI."""
        self._ais.append(ai)
        self._untried.append(ai)
```

Fix the class docstring (line 490-499) to describe draw-without-replacement rather than "picks
another on completion".

In `engine/appc/ai_driver.py`, replace `_tick_random` (currently lines 277-302) with:

```python
def _tick_random(ai: RandomAI, game_time: float) -> int:
    """Draw a child from the un-tried pool and tick it; re-draw when it finishes.

    Ground truth (ai-architecture.md sec.2, RandomAI::Update 0x004917f0): the node
    keeps a per-child "already tried" array and draws from the un-tried entries,
    clearing the flag and re-drawing on DORMANT/DONE. Drawing with replacement
    would let the same evasive maneuver repeat back-to-back.

    RandomAI is used as an infinite maneuver picker inside a forever-looping
    SequenceAI (AI/Compound/Parts/NoSensorsEvasive.py:47-52,
    QuickBattle/QuickBattleAI.py:51-58), so it stays US_ACTIVE while a child runs
    and does not terminate just because one child finished.
    """
    if not ai._ais:
        ai._status = US_DONE
        return ai._status
    child = ai._current_child
    if child is None or child._status in (US_DONE, US_DORMANT):
        if not ai._untried:
            ai._untried = list(ai._ais)       # cycle exhausted: refill
        child = random.choice(ai._untried)
        ai._untried.remove(child)
        # Re-arm the freshly-drawn child so a previously-finished one runs again.
        child._status = US_ACTIVE
        ai._current_child = child
    tick_ai(child, game_time)
    ai._status = US_ACTIVE
    return ai._status
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_random_ai_without_replacement.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the AI suites**

Run: `uv run pytest tests/unit tests/integration -k "ai or random or quickbattle" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py engine/appc/ai_driver.py tests/unit/test_random_ai_without_replacement.py
git commit -m "fix(ai): RandomAI draws without replacement

The C++ node keeps an already-tried array and draws only from the un-tried
children, refilling when exhausted (ai-architecture.md sec.1/sec.2). We drew with
replacement, so the same evasive maneuver could repeat back-to-back — exactly
what the shuffle exists to prevent."
```

---

### Task 13: `ArtificialIntelligence.Reset` re-arms the node and reaches the script

> **The `UpdateStatus` enum swap that this task originally called for is DELETED.** The 2026-07-14
> constant-table dump (Reference §1 above) proves our values are already correct. **Do not touch
> `engine/appc/ai.py:199-203`.** The test below pins them so nobody "fixes" them against the doc again.

**Reset.** Ours (`engine/appc/ai.py:283`) only sets `_status = US_ACTIVE`. Appc's `Reset` zeroes
`nextUpdateTime` — forcing an update on the very next tick (`ai-architecture.md` §3: "`Reset` zeroes
`nextUpdateTime`, forcing an update on the next tick") — and the four PlainAI scripts that define a
script-side `Reset()` (`FollowWaypoints`, `Warp`, `ManeuverLoop`, `IntelligentCircleObject`) expect
it to reach them. `AI/Compound/TractorDockTargets.py:20` calls `pContained.Reset()`.

**Files:**
- Modify: `engine/appc/ai.py:283` (`Reset`) — **the enum block at 199-203 is NOT modified**
- Test: `tests/unit/test_ai_reset_and_status_values.py` (create)

**Interfaces:**
- Consumes: `ArtificialIntelligence._next_update_time`, `PlainAI._script_instance`,
  `PreprocessingAI._preprocessing_instance`.
- Produces: `ArtificialIntelligence.Reset()` sets `_status = US_ACTIVE`, sets
  `_next_update_time = 0.0`, and calls the bound script instance's `Reset()` if it defines one.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ai_reset_and_status_values.py`:

```python
"""Reset re-arms the node and reaches the script; UpdateStatus values match Appc.

Values read out of the binary's swig_const_info table (0x0090d9ac+) on
2026-07-14: US_ACTIVE=0, US_DONE=1, US_DORMANT=2, US_INVALID=3. These are the
values this engine has always had. ai-architecture.md sec.2 lists DORMANT/DONE
swapped — that is a doc transcription error. This test exists to stop anyone
"correcting" our (right) values to match the (wrong) doc.

Appc's Reset zeroes nextUpdateTime, forcing an update on the next tick. Four
PlainAI scripts define a script-side Reset() and
AI/Compound/TractorDockTargets.py:20 calls it.
"""
from engine.appc.ai import ArtificialIntelligence, PlainAI_Create


def test_update_status_values_match_the_binary():
    # DO NOT "fix" these against ai-architecture.md sec.2 — the doc is wrong.
    assert ArtificialIntelligence.US_ACTIVE == 0
    assert ArtificialIntelligence.US_DONE == 1
    assert ArtificialIntelligence.US_DORMANT == 2
    assert ArtificialIntelligence.US_INVALID == 3
    assert ArtificialIntelligence.US_NUM_STATUSES == 4


def test_reset_zeroes_the_cadence_and_reaches_the_script():
    class _Script:
        def __init__(self):
            self.resets = 0

        def Reset(self):
            self.resets += 1

    ai = PlainAI_Create(None, "leaf")
    script = _Script()
    ai._script_instance = script

    ai._status = ArtificialIntelligence.US_DONE
    ai._next_update_time = 99.0

    ai.Reset()

    assert ai._status == ArtificialIntelligence.US_ACTIVE
    assert ai._next_update_time == 0.0, "must run on the very next tick"
    assert script.resets == 1


def test_reset_on_a_node_with_no_script_does_not_raise():
    ai = PlainAI_Create(None, "bare")
    ai.Reset()
    assert ai._next_update_time == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_ai_reset_and_status_values.py -v`
Expected: `test_update_status_values_match_the_binary` PASSES already (our values are correct);
`test_reset_zeroes_the_cadence_and_reaches_the_script` FAILS on
`assert ai._next_update_time == 0.0` (it is 99.0).

- [ ] **Step 3: Implement**

Leave `engine/appc/ai.py:199-203` alone. Add a comment above the enum block recording where the
values came from, so the next reader doesn't "fix" them against the doc:

```python
    # Values read from the binary's swig_const_info table (0x0090d9ac+), 2026-07-14.
    # ai-architecture.md sec.2 lists DORMANT/DONE swapped — the DOC is wrong, and
    # that error is what made its PreprocessingAI::Update switch look inverted.
    # Pinned by tests/unit/test_ai_reset_and_status_values.py.
```

Replace `Reset` (currently line 283) with:

```python
    def Reset(self) -> None:
        """Re-arm this node: ACTIVE, due immediately, and tell the script.

        Appc's Reset zeroes nextUpdateTime so the node updates on the very next
        tick (ai-architecture.md sec.3). Four PlainAI scripts define a script-side
        Reset() — FollowWaypoints (rewinds the waypoint cursor), Warp,
        ManeuverLoop, IntelligentCircleObject — and
        AI/Compound/TractorDockTargets.py:20 calls it on its contained AI.
        """
        self._status = self.US_ACTIVE
        self._next_update_time = 0.0
        d = getattr(self, "__dict__", {})
        inst = d.get("_script_instance") or d.get("_preprocessing_instance")
        reset = getattr(inst, "Reset", None) if inst is not None else None
        if callable(reset):
            try:
                reset()
            except Exception as _e:
                dev_mode.log_swallowed("AI script Reset", _e)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_ai_reset_and_status_values.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the FULL gate — the status values are used everywhere**

Run: `scripts/check_tests.sh`
Expected: exits 0. It builds C++, runs pytest + ctest, and diffs failures against
`tests/known_failures.txt` (whose only entries are the 7 headless-GL scorch/heat-glow `FrameTest`s).
Any failure it names that is not in that list is a regression this plan introduced.

Grep for any place comparing an AI status to a raw integer before assuming green:
`grep -rn "_status == 1\|_status == 2\|status == 1\|status == 2" engine/ tests/`

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_ai_reset_and_status_values.py
git commit -m "fix(ai): Reset re-arms the node and reaches the script

Reset now zeroes nextUpdateTime (so the node updates on the very next tick, per
Appc) and forwards to the script's own Reset() — FollowWaypoints, Warp,
ManeuverLoop and IntelligentCircleObject all define one, and TractorDockTargets
calls it. Also pins the UpdateStatus values with a test: they were always right
(US_DONE=1, US_DORMANT=2, per the binary's constant table) and
ai-architecture.md sec.2 has them swapped."
```

---

### Task 14: `PS_DONE` is lethal — and `ManagePower` must never return it

> **This is the most dangerous task in the plan. Both halves must land in one commit. Neither is
> safe alone.** Do not split it, and do not let a reviewer talk you into splitting it.

**Half A — the mapping is wrong.** `PreprocessingAI::Update` maps `PS_DONE` (3) and `PS_INVALID` (4)
to **`US_DONE`**, and `US_DONE` is what *destroys* the node (LostFocus → SetInactive → unlink +
delete). Our `ai_driver._tick_preprocessing` (lines 508-516, 540-543) instead treats `PS_DONE` as
"stop calling the preprocessor, keep dispatching the child", carried on a `_preprocess_done` latch.
That is wrong.

**Half B — why Half A alone would break the game.** In the shipped engine
`PreprocessingAI::SetContainedAI` swaps the Python `ManagePower` node for a native C++ one via the
`GetOptimizedVersion` hook (Reference §4), so **`AI/Preprocessors.py:2148` `ManagePower.Update` — the
one that returns `PS_DONE` — never executes.** We have no such hook, so we *do* run it. Fix Half A
alone and every `FedAttack` / `NonFedAttack` / `CloakAttack` ship deletes its own AI within one
preprocess cadence. `ManagePower` sits in the live chain (AlertLevel → PowerManagement →
FleeAttackOrFollow) and the interruptable bypass can't save it, because `FleeAttackOrFollow` calls
`SetInterruptable(1)`.

So Half B builds the hook, with the one entry that matters. `AI/Compound/NonFedAttack.py:928` (and
the FedAttack / CloakAttack equivalents) construct `AI.Preprocessors.ManagePower(bConservePower)`;
at bind time we swap in an engine-side replacement mirroring the native class (ctor `0x00486FA0`):
3.0 s cadence, reads `bConservePower`, drives the power subsystem, **returns `PS_NORMAL`**.

We do **not** register `FireScript`, `SelectTarget` or `AvoidObstacles`, even though the shipped
engine replaces those three too. Their SDK Python bodies are full working implementations that our
driver already runs correctly, and we have no native versions to swap in. The registry is where they
would go if that ever changes; say so in the comment, and do not silently imply we are faithful here.

**Files:**
- Create: `engine/appc/ai_optimized.py` (the registry + our `ManagePower` replacement)
- Modify: `engine/appc/ai.py` — `PreprocessingAI.SetPreprocessingMethod` (consult the registry)
- Modify: `engine/appc/ai_driver.py:508-516, 540-543, 551-564` (`_tick_preprocessing` — `PS_DONE` → `US_DONE`, delete the `_preprocess_done` latch)
- Modify: `engine/appc/ai.py:546` (delete `PreprocessingAI._preprocess_done`)
- Test: `tests/unit/test_preprocess_done_is_lethal.py` (create)

**Interfaces:**
- Consumes: `PreprocessingAI._preprocessing_instance`, `._last_preprocess_status`; the existing power
  system (find it: `grep -rn "class .*Power\|power_management" engine/appc/`).
- Produces: `engine.appc.ai_optimized.OPTIMIZED_PREPROCESSORS: dict[str, type]` — maps a Python
  preprocessor class *name* to its engine-side replacement class, mirroring the binary's
  `DAT_00982A1C` registry. `engine.appc.ai_optimized.optimized_version_of(instance) -> object` —
  returns the replacement instance (constructed from the original's parameter block) or the original
  instance unchanged, mirroring `GetOptimizedVersion`'s "return `this`" default.
  `engine.appc.ai_optimized.ManagePower` — the replacement: `GetNextUpdateTime()` → `3.0`,
  `Update(dEndTime)` → `App.PreprocessingAI.PS_NORMAL`, holding `bConservePower`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_preprocess_done_is_lethal.py`:

```python
"""PS_DONE means "this node is finished" -> US_DONE, which tears the AI down.

Established 2026-07-14 from the binary: PreprocessingAI::Update maps PS_DONE (3)
and PS_INVALID (4) to US_DONE, and US_DONE (not US_DORMANT) is what unlinks and
deletes the node.

We previously treated PS_DONE as "stop calling the preprocessor, keep running the
child". That was the wrong lesson drawn from AI/Preprocessors.py:ManagePower,
whose `# Unused. return PS_DONE` body NEVER RUNS in the shipped game: the engine
swaps the Python ManagePower node for a native C++ one at bind time via the
GetOptimizedVersion hook (vtable +0x34).

So both halves are tested here: the mapping is now faithful, AND the ManagePower
swap keeps the shipped Compound doctrines alive.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PreprocessingAI_Create,
)
from engine.appc.ai_driver import tick_ai
from engine.appc import ai_optimized


class _Child:
    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return ArtificialIntelligence.US_ACTIVE


class _DonePreproc:
    """A preprocessor that reports PS_DONE, like a naive port of ManagePower."""
    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_DONE


class _NormalPreproc:
    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_NORMAL


def _wrap(inst):
    node = PreprocessingAI_Create(None, "wrap")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    node.SetPreprocessingMethod(inst, "Update")
    return node, child


def test_ps_done_reports_us_done_and_stops_the_child():
    node, child = _wrap(_DonePreproc())
    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_DONE
    assert child.updates == 0, "PS_DONE must NOT fall through to the child"


def test_ps_normal_runs_the_child():
    node, child = _wrap(_NormalPreproc())
    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_ACTIVE
    assert child.updates == 1


def test_the_sdk_manage_power_is_swapped_for_the_engine_replacement():
    """The shipped Compound doctrines build AI.Preprocessors.ManagePower, whose
    Update returns PS_DONE. Unswapped, that would delete every Federation ship's
    AI on the first preprocess tick."""
    import AI.Preprocessors

    sdk_inst = AI.Preprocessors.ManagePower(0)
    assert sdk_inst.Update(0.0) == App.PreprocessingAI.PS_DONE, (
        "sanity: the SDK stub really does return the lethal value")

    node = PreprocessingAI_Create(None, "PowerManagement")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    node.SetPreprocessingMethod(sdk_inst, "Update")

    # The bound instance must be OUR replacement, not the SDK stub.
    bound = node.GetPreprocessingInstance()
    assert isinstance(bound, ai_optimized.ManagePower)
    assert bound.GetNextUpdateTime() == 3.0
    assert bound.Update(0.0) == App.PreprocessingAI.PS_NORMAL

    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_ACTIVE
    assert child.updates == 1, "the combat subtree must keep running"


def test_conserve_power_argument_is_carried_across_the_swap():
    import AI.Preprocessors
    node = PreprocessingAI_Create(None, "PowerManagement")
    node.SetPreprocessingMethod(AI.Preprocessors.ManagePower(1), "Update")
    assert node.GetPreprocessingInstance().bConservePower == 1


def test_an_unregistered_preprocessor_is_left_alone():
    """GetOptimizedVersion's default is "return this" — no registry hit, no swap.
    AlertLevel is deliberately NOT registered (it isn't in the binary's registry
    either, which is why its Python body correctly returns PS_NORMAL)."""
    inst = _NormalPreproc()
    node = PreprocessingAI_Create(None, "wrap")
    node.SetPreprocessingMethod(inst, "Update")
    assert node.GetPreprocessingInstance() is inst
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_preprocess_done_is_lethal.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.ai_optimized`, and
`test_ps_done_reports_us_done_and_stops_the_child` fails because our driver returns `US_ACTIVE` and
runs the child.

- [ ] **Step 3: Implement Half B first — the swap (so the game never sees the lethal path)**

Create `engine/appc/ai_optimized.py`:

```python
"""Engine-side replacements for the Python preprocessors the original engine
compiled into C++ ("CodeAI"), and the registry that swaps them in.

Mechanism, from the binary (2026-07-14): PreprocessingAI::SetContainedAI
(0x0048E570) does not store the AI it is handed — it calls
newAI->GetOptimizedVersion() (vtable +0x34) and stores the RETURNED object.
PreprocessingAI overrides that slot (0x0048EB20): it reads the bound Python
preprocessor's class name, looks it up in a native registry (DAT_00982A1C), and
on a hit allocates a native node, steals the contained subtree, and deletes the
Python-backed node outright. The BaseAI default is `MOV EAX,ECX; RET` — return
`this`, i.e. "I have no optimized version, use me".

Four classes are registered in the binary: AvoidObstacles, FireScript,
ManagePower, SelectTarget.

WE REGISTER ONLY ManagePower, and the reason matters:

* ManagePower MUST be swapped. Its SDK Python body (AI/Preprocessors.py:2148) is
  `# Unused.  return PS_DONE` — dead code in the shipped game, because the native
  class always replaced it. PS_DONE maps to US_DONE, which DESTROYS the AI node.
  It sits in the live FedAttack / NonFedAttack / CloakAttack chain
  (AlertLevel -> PowerManagement -> FleeAttackOrFollow), so running the Python
  body would delete every Federation ship's AI within one 3-second cadence.
* FireScript, SelectTarget and AvoidObstacles are NOT registered here, even though
  the shipped engine replaces them too. Their SDK Python bodies are full working
  implementations that our driver already runs correctly, and we have no native
  versions to swap in. This is a deliberate, documented divergence — not
  faithfulness. If native versions ever land, they go in the registry below.
"""

import App


class ManagePower:
    """Mirror of the native ManagePower CodeAI (ctor 0x00486FA0).

    The native node drives the ship's power subsystem on a 3.0 s cadence
    ([0x0088BEBC] = 3.0f, byte-for-byte the SDK's ManagePower.GetNextUpdateTime)
    and returns PS_NORMAL, so the wrapped combat subtree keeps running. It reads
    bConservePower off the Python instance to carry the ctor arg across the swap;
    we do the same.
    """

    def __init__(self, bConservePower=0):
        self.bConservePower = bConservePower

    def GetNextUpdateTime(self):
        return 3.0

    def Update(self, dEndTime):
        # PS_NORMAL: run the contained AI. NEVER PS_DONE — that is lethal.
        return App.PreprocessingAI.PS_NORMAL


# Python preprocessor class NAME -> engine-side replacement class. Mirrors the
# binary's DAT_00982A1C name registry; see the module docstring for why only one
# entry is present.
OPTIMIZED_PREPROCESSORS: dict = {
    "ManagePower": ManagePower,
}


def optimized_version_of(instance):
    """Appc's GetOptimizedVersion, by class name.

    Returns the engine-side replacement (constructed from the original's
    parameter block) on a registry hit, or the original instance unchanged
    otherwise — matching the C++ default, which returns `this`.
    """
    if instance is None:
        return instance
    replacement = OPTIMIZED_PREPROCESSORS.get(type(instance).__name__)
    if replacement is None:
        return instance
    return replacement(getattr(instance, "bConservePower", 0))
```

If `ManagePower` should actually *drive* our power system rather than being an inert pass-through,
that is a separate follow-up: the native node writes to the ship's power subsystem (`ship+0x2B0`),
and we already have a merged power-management system. Do **not** wire that here — this task's job is
to stop the AI deleting itself. Returning `PS_NORMAL` on a 3 s cadence is exactly what the native
node returns; the power *behaviour* it also performs is additive and belongs in its own task. Note
that as a TODO in the class docstring, naming the power module you found.

In `engine/appc/ai.py`, in `PreprocessingAI.SetPreprocessingMethod`, replace the two-arg branch's
first line so the instance is run through the registry **before** anything else touches it:

```python
        elif len(args) >= 2:
            # Appc's SetContainedAI runs the node through GetOptimizedVersion
            # (vtable +0x34) and stores what comes back, swapping four Python
            # preprocessors for compiled C++ ones. We do the equivalent at bind
            # time, by class name. Critically this replaces the SDK's ManagePower,
            # whose `# Unused. return PS_DONE` body never runs in the shipped game
            # and would otherwise delete the ship's whole AI (PS_DONE -> US_DONE).
            from engine.appc.ai_optimized import optimized_version_of
            instance = optimized_version_of(args[0])
            self._preprocessing_instance = instance
            self._preprocessing_method = args[1]
```

and update the rest of that branch to use the local `instance` in place of `args[0]` — including the
`pCodeAI` binding and the `CodeAISet()` call from Task 9. (Order matters: swap, then bind `pCodeAI`
onto the *replacement*, then call its `CodeAISet` if it has one.)

- [ ] **Step 4: Run the swap tests**

Run: `uv run pytest tests/unit/test_preprocess_done_is_lethal.py -v -k "manage_power or conserve or unregistered"`
Expected: 3 passed. The two mapping tests still fail — that's Half A, next.

- [ ] **Step 5: Implement Half A — the faithful mapping**

In `engine/appc/ai_driver.py`, in `_tick_preprocessing`:

Delete the `_preprocess_done` gate on the cadence check (line 514) so it reads:

```python
    if game_time >= ai._next_update_time:
```

Replace the result dispatch (lines 540-549) with:

```python
        if result == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
            return ai._status
        if result == PS_SKIP_DORMANT:
            ai._status = US_DORMANT
            return ai._status
        if result != PS_NORMAL:
            # PS_DONE (3) and PS_INVALID (4) both map to US_DONE — "this node is
            # finished" — and US_DONE is what tears an AI down. Verified in the
            # binary 2026-07-14 (PreprocessingAI::Update switch at 0x48eab1).
            # No SDK preprocessor we run reaches here: the only one that returned
            # PS_DONE was ManagePower, and engine/appc/ai_optimized.py swaps it out
            # exactly as the original engine did.
            ai._status = US_DONE
            return ai._status
        # PS_NORMAL falls through to the contained AI below.
```

Replace the cadence-skipped branch (lines 551-564) with the same three-way reproduction of the last
status, keeping `PS_NORMAL` (and never-run) as the fall-through:

```python
    else:
        last = ai._last_preprocess_status
        if last == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
            return ai._status
        if last == PS_SKIP_DORMANT:
            ai._status = US_DORMANT
            return ai._status
        if last != PS_NORMAL:
            ai._status = US_DONE
            return ai._status
```

In `engine/appc/ai.py`, delete `PreprocessingAI._preprocess_done` (line 546) and its comment block —
the latch has no remaining reader.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_preprocess_done_is_lethal.py -v`
Expected: 5 passed.

- [ ] **Step 7: Prove a real Federation ship survives — this is the whole point of the task**

The unit tests use fakes. Run a real `NonFedAttack` / `FedAttack` tree for several seconds of game
time and assert the ship still has an AI at the end. The integration harness pattern is in
`tests/integration/` (`grep -rln "NonFedAttack\|BasicAttack" tests/`). If no such test exists, write
one in this task: build a ship, `BasicAttack.CreateAI(pShip)`, tick 10 seconds of game time, and
assert `ship.GetAI() is not None` and its status is not `US_DONE`. **A green unit suite does not
discharge this step** — the failure mode being guarded against is precisely one that fakes cannot
reproduce.

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0, modulo `tests/known_failures.txt`.

- [ ] **Step 9: Commit — both halves together**

```bash
git add engine/appc/ai_optimized.py engine/appc/ai.py engine/appc/ai_driver.py tests/unit/test_preprocess_done_is_lethal.py
git commit -m "fix(ai): PS_DONE is lethal; swap ManagePower like the original engine did

Two halves that MUST land together.

(a) PreprocessingAI::Update maps PS_DONE and PS_INVALID to US_DONE, and US_DONE
    is what unlinks and deletes an AI node. We treated PS_DONE as 'stop calling
    the preprocessor, keep running the child'.

(b) That wrong reading was the only thing keeping Federation ships alive. The
    shipped engine never runs AI/Preprocessors.py's ManagePower.Update — its
    '# Unused. return PS_DONE' body is dead code, because SetContainedAI swaps
    the node for a compiled C++ one through the GetOptimizedVersion hook (vtable
    +0x34, registry DAT_00982A1C: AvoidObstacles, FireScript, ManagePower,
    SelectTarget). We have no such hook, so we DID run it. Fixing (a) alone would
    have every Fed ship delete its own AI within one 3s cadence.

engine/appc/ai_optimized.py adds the registry with the one entry that matters.
FireScript/SelectTarget/AvoidObstacles are deliberately NOT registered — their
SDK Python bodies work and we have no native versions; documented as a divergence.

Binary evidence via the STBC-RE project, 2026-07-14."
```

---

### Task 15: `IsInterruptable` bypasses the preprocess gate

Established 2026-07-14: `IsInterruptable` is vtable slot `+0x04` (the doc's "unidentified `char`
predicate", queried on children by `PriorityListAI::Update` and `PreprocessingAI::Update`), and the
BaseAI ctor (`0x00470520`) defaults it to **1**. The whole `PreprocessingAI::Update` preprocess
switch is **bypassed — the child runs unconditionally — when the child is active and NOT
interruptable.**

We store `SetInterruptable` (`engine/appc/ai.py:284`) and never read it. Ten SDK nodes set it
explicitly (`AI/Compound/Defend.py:61,81,92,100`, `AI/Compound/CallDamageAI.py:81,112`, …), and a
node that sets `SetInterruptable(0)` is asking to not be pre-empted mid-action by its parent's
preprocessor. Today we pre-empt it anyway.

**Files:**
- Modify: `engine/appc/ai_driver.py` (`_tick_preprocessing` — guard the preprocess step)
- Test: `tests/unit/test_interruptable_bypass.py` (create)

**Interfaces:**
- Consumes: `ArtificialIntelligence.IsInterruptable()` (already exists, `ai.py:285`),
  `PreprocessingAI._contained_ai`.
- Produces: no new surface — `_tick_preprocessing` gains an early bypass.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_interruptable_bypass.py`:

```python
"""A PreprocessingAI does not preprocess over an active, non-interruptable child.

Established 2026-07-14: IsInterruptable is BaseAI vtable +0x04 (default 1), and
PreprocessingAI::Update bypasses its preprocess switch entirely — running the
child unconditionally — when the child is active and NOT interruptable. Ten SDK
nodes call SetInterruptable (AI/Compound/Defend.py:61,81,92,100;
AI/Compound/CallDamageAI.py:81,112). We stored the flag and never read it.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PreprocessingAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _Child:
    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return ArtificialIntelligence.US_ACTIVE


class _Blocker:
    """A preprocessor that would suppress the child (PS_SKIP_ACTIVE)."""
    def __init__(self):
        self.updates = 0

    def Update(self, dEndTime):
        self.updates += 1
        return App.PreprocessingAI.PS_SKIP_ACTIVE


def _build(interruptable: int):
    node = PreprocessingAI_Create(None, "wrap")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    child_ai.SetInterruptable(interruptable)
    node.SetContainedAI(child_ai)
    pre = _Blocker()
    node.SetPreprocessingMethod(pre, "Update")
    return node, pre, child, child_ai


def test_interruptable_child_is_suppressed_by_the_preprocessor():
    node, pre, child, _ = _build(interruptable=1)     # the default
    tick_ai(node, 0.0)
    assert pre.updates == 1
    assert child.updates == 0, "PS_SKIP_ACTIVE suppresses an interruptable child"


def test_active_non_interruptable_child_bypasses_the_preprocessor_entirely():
    node, pre, child, _ = _build(interruptable=0)
    tick_ai(node, 0.0)
    assert child.updates == 1, "the child runs unconditionally"
    assert pre.updates == 0, "the preprocess step is BYPASSED, not just ignored"


def test_a_non_active_non_interruptable_child_does_not_bypass():
    """The bypass requires the child to be ACTIVE. A done/dormant child must not
    shield the node from its own preprocessor."""
    node, pre, child, child_ai = _build(interruptable=0)
    child_ai._status = ArtificialIntelligence.US_DONE
    tick_ai(node, 0.0)
    assert pre.updates == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_interruptable_bypass.py -v`
Expected: FAIL — `test_active_non_interruptable_child_bypasses_the_preprocessor_entirely`: the
preprocessor runs and suppresses the child.

- [ ] **Step 3: Implement**

In `engine/appc/ai_driver.py`, in `_tick_preprocessing`, immediately **before** the cadence gate
(the `if game_time >= ai._next_update_time:` line, after the focus-dispatch block), insert:

```python
    # Appc bypasses the preprocess switch entirely — running the child
    # unconditionally — when the child is ACTIVE and NOT interruptable
    # (IsInterruptable is BaseAI vtable +0x04, default 1; verified 2026-07-14).
    # A node that calls SetInterruptable(0) is asking not to be pre-empted
    # mid-action by its parent's preprocessor (AI/Compound/Defend.py,
    # AI/Compound/CallDamageAI.py).
    child = ai._contained_ai
    if (child is not None
            and child._status == US_ACTIVE
            and not child.IsInterruptable()):
        ai._status = US_ACTIVE
        tick_ai(child, game_time)
        return ai._status
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_interruptable_bypass.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the AI suites — Defend and CallDamageAI go through this**

Run: `uv run pytest tests/unit tests/integration -k "ai or defend or damage" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai_driver.py tests/unit/test_interruptable_bypass.py
git commit -m "feat(ai): honour IsInterruptable — bypass the preprocess gate

IsInterruptable is BaseAI vtable +0x04 (default 1), and PreprocessingAI::Update
bypasses its preprocess switch entirely, running the child unconditionally, when
the child is active and not interruptable. We stored SetInterruptable and never
read it, so the ten SDK nodes that ask not to be pre-empted mid-action
(Compound/Defend, Compound/CallDamageAI) were pre-empted anyway.

Binary evidence via the STBC-RE project, 2026-07-14."
```

---

## Phase 3 — deferred to a follow-up plan

The remaining dead conditions each need an **event emitter** built on the engine side, which is a
different kind of work from everything above (Phase 1 and 2 are corrections to existing code; these
are new engine behaviour). They should be scoped and planned separately once Phase 1 lands and we
can see which of them still matter. Recorded here so they are not lost:

| Condition(s) | What's missing |
|---|---|
| `ConditionFiringTractorBeam` | `ET_TRACTOR_BEAM_STARTED_FIRING` / `_STOPPED_FIRING` constants + emitters on the tractor subsystem |
| `ConditionIncomingTorps` | `ET_TORPEDO_ENTERED_SET` / `_EXITED_SET` constants + emitters, and `AIScriptAssist_GetIncomingTorpIDsInSet` (currently returns `()`, `App.py:680`) |
| `ConditionWarpingToSet`, `ConditionWarpingToMission` | `ET_SET_WARP_SEQUENCE` constant + emitter; `WarpSequence.GetDestinationMission` (live stub, heatmap rank 351) |
| `ConditionPlayerOrbitting` | `ET_AI_ORBITTING` is defined (`App.py:856`) but nothing ever fires it |
| `ConditionExists`, `ConditionAllInSameSet`, `ConditionAnyInSameSet` | `ET_OBJECT_GROUP_OBJECT_ENTERED_SET` / `_EXITED_SET` / `ET_OBJECT_GROUP_CHANGED` are defined but never emitted — the conditions freeze at their construction-time value |
| `ConditionInLineOfSight` | `ProximityManager.GetLineIntersectObjects` returns `()` (`engine/appc/planet.py:269`), so the condition can never find a blocker. 10 SDK uses |
| `ConditionUsingWeapon` + retargeting | Nobody calls the conditions' `RegisterExternalFunctions(pAI)` — in the binary `ConditionalAI` does. Needs a `CodeID` → condition-instance resolution path in `CallExternalFunction`, which currently `getattr`s the name off the AI's own instance and ignores `CodeID` |
| `ConditionAttackedBy` (partial) | `ET_CONDITION_ATK_REMOVE_DAMAGE` — damage never ages out of its memory |

Two further items belong in that plan:

- **Stub-telemetry blind spot.** `docs/stub_heatmap.md` cannot see a stub used as a **dict key** —
  which is exactly how the two most-used conditions in the AI died silently (Task 2). Teach
  `engine/core/stub_telemetry.py` to record `_NamedStub.__hash__` / `__eq__`, so this class of bug
  becomes visible instead of invisible.
- **`AvoidObstacles` double-drive.** `engine/appc/collision_avoidance.py` is a faithful port of the
  SDK preprocessor but runs as a global per-tick routine after `tick_all_ai`, not as a
  `PreprocessingAI` node. Any tree that contains a real SDK `AvoidObstacles` node
  (`AI/Compound/TractorDockTargets.py:133`, the E7M2 mission AIs) would have both driving the same
  ship. Suppress one.

## Docs to update when Phase 1 + 2 land

`docs/engine/aieditor-ai-surface-and-gaps.md` is stale and should be corrected in the final commit:

- Gap A1 ("`RandomAI` is never ticked") is **closed** — `ai_driver._tick_random` exists.
- "`GetCloakingSubsystem` stubbed `None`" is **closed** — `engine/appc/ships.py:770` implements it.
- "34 Condition classes" → **33**.
- §6's prioritized gap list should be replaced by a pointer to this plan.
- The class hierarchy in that doc and in `engine/appc/ai.py:19-35` omits `RandomAI` and
  `ConditionalAI`, and predates the RE finding that the binary has **four** name-registered native
  "CodeAI" accelerators — `AvoidObstacles`, `FireScript`, `ManagePower`, `SelectTarget` — swapped in
  through the `GetOptimizedVersion` hook (the doc says five; the fifth, unnamed node is not in the
  registry). Record the registry mechanism itself: it is the reason `ManagePower`'s Python body can
  be a lethal stub without breaking the shipped game, and the reason our `AvoidObstacles` divergence
  (`engine/appc/collision_avoidance.py`, a global routine rather than an AI node) is a *substitution*
  rather than a *gap*.

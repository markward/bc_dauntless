# Real-Duration Completion Gating for Timed Action Sequences — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SDK-defined timed cutscene sequences honor real audio durations so comm-hail dialogue plays in sync and the comm viewscreen holds for the dialogue then reverts — and remove the interim `SetRemoteCam` hold hack.

**Architecture:** Add one shared primitive (`TGAction._complete_after`) that posts `Completed()` after N wall-clock seconds via `g_kRealtimeTimerManager`. Wire the three leaf audio actions to it: `CharacterAction` speak-types and `TGSoundAction` gate on real audio duration (exposed from the native backend, estimate fallback); `TGScriptAction` honors the SDK return-value completion convention; `g_kTGActionManager` routes `ET_ACTION_COMPLETED` to the owner action. Zero duration completes inline, preserving the synchronous behavior the headless test suite relies on.

**Tech Stack:** Python 3 (engine shim), pybind11 + C++ (native audio), pytest, CMake.

**Design doc:** `docs/superpowers/specs/2026-06-18-action-sequence-real-duration-completion-design.md`

## Global Constraints

- One build tree only: `cmake -B build -S . && cmake --build build -j` → `build/dauntless`. Never build from inside `native/`.
- Native audio changes (`native/src/audio/...`) require a full rebuild from `build/`; a stale binary exposes no `get_duration`. Pure-Python changes need NO rebuild.
- Loop is single-threaded from Python's view; never block — drive completion via timer-posted events on `g_kRealtimeTimerManager` (the unscaled/wall-clock stream), NOT `g_kTimerManager` (game time, scales with time-scale).
- Zero duration ⇒ inline `Completed()`. This is load-bearing: the null/absent test audio backend reports 0, so existing zero-delay sequence tests stay byte-for-byte synchronous.
- `App.ET_ACTION_COMPLETED == 101`. `App.g_kTGActionManager` is the `TGActionManager` singleton. `App.g_kRealtimeTimerManager` / `App.g_kTimerManager` are `TGTimerManager`s ticked each frame by `GameLoop.tick`.
- Run focused test subsets; full suite only via `scripts/run_tests.sh` (memory: full `uv run pytest` was OOM, now capped).
- SDK scripts are ground truth; do not special-case comm timing — honor the timing primitives the SDK uses.
- Commit after each task. Branch already created: `feat/action-sequence-real-duration-completion`.

---

## File Structure

- `native/src/audio/include/audio/audio_system.h` — add `get_duration(name)` + duration storage in the sound record.
- `native/src/audio/src/audio_system.cc` — compute duration at `load_sound`; implement `get_duration`.
- `native/src/audio/src/python_binding.cc` — expose `audio.get_duration`.
- `engine/audio/tg_sound.py` — `TGSound.GetDuration()` + `TGSoundManager.duration_for(name)`.
- `engine/appc/actions.py` — `TGAction._complete_after` + `ProcessEvent` + teardown; `TGScriptAction` return-value honoring; `TGSoundAction` deferral; `TGActionManager.ProcessEvent` handler.
- `engine/appc/crew_speech.py` — `bus.speak`/`emit` return one duration sourced from real audio (estimate fallback).
- `engine/appc/ai.py` — `CharacterAction` speak-types defer on the returned duration.
- `engine/appc/bridge_set.py` — delete the `SetRemoteCam` hold hack.
- `tests/unit/test_actions.py` — primitive + action deferral + manager tests.
- `tests/unit/test_crew_speech.py` — duration-return test (locate/confirm path in Task 6).
- `tests/unit/test_viewscreen_remote_cam_latch.py` — DELETE.

---

## Task 1: Native — expose decoded audio duration

**Files:**
- Modify: `native/src/audio/include/audio/audio_system.h`
- Modify: `native/src/audio/src/audio_system.cc`
- Modify: `native/src/audio/src/python_binding.cc`
- Modify: `engine/audio/tg_sound.py`
- Test: `tests/unit/test_tg_sound_duration.py` (create)

**Interfaces:**
- Produces: `_dauntless_host.audio.get_duration(name: str) -> float` (seconds, 0.0 if unknown); `engine.audio.tg_sound.TGSoundManager.duration_for(name: str) -> float`; `engine.audio.tg_sound.TGSound.GetDuration() -> float`.

- [ ] **Step 1: Read the current sound record + load path**

Read `native/src/audio/include/audio/audio_system.h` and `native/src/audio/src/audio_system.cc` (the `sounds_` map value type and `load_sound`). Confirm `WavData` has `sample_rate`, `channels`, `bits_per_sample`, and `pcm` (a byte vector) — seen in `native/src/audio/src/wav.cc` / `mp3.cc`.

- [ ] **Step 2: Add duration to the sound record + a getter (header)**

In `native/src/audio/include/audio/audio_system.h`, add a `double duration_sec` field to the per-sound struct stored in `sounds_` (the struct currently holding `{BufferHandle buf; bool positional;}`), and declare:

```cpp
double get_duration(const std::string& name) const;
```

- [ ] **Step 3: Compute duration at load + implement getter (cc)**

In `native/src/audio/src/audio_system.cc`, inside `load_sound`, after `decode_*` succeeds and before/at storing the record, compute:

```cpp
double duration_sec = 0.0;
const uint32_t bytes_per_sample = wav.bits_per_sample / 8;
const uint64_t denom =
    static_cast<uint64_t>(wav.sample_rate) * wav.channels * bytes_per_sample;
if (denom > 0)
    duration_sec = static_cast<double>(wav.pcm.size()) / static_cast<double>(denom);
```

Store `duration_sec` in the record (alongside `buf`, `positional`). Then implement:

```cpp
double AudioSystem::get_duration(const std::string& name) const {
    auto it = name_to_id_.find(name);
    if (it == name_to_id_.end()) return 0.0;
    auto sit = sounds_.find(it->second);
    return sit == sounds_.end() ? 0.0 : sit->second.duration_sec;
}
```

- [ ] **Step 4: Expose via the Python binding**

In `native/src/audio/src/python_binding.cc`, add near the other `static` impls:

```cpp
static double get_duration_impl(const std::string& name) {
    return g_system ? g_system->get_duration(name) : 0.0;
}
```

and register it in the submodule (next to `m.def("get_sound", ...)`):

```cpp
m.def("get_duration", &get_duration_impl);
```

- [ ] **Step 5: Rebuild the one build tree**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds `build/dauntless` and the audio module with no errors. (Reconfigure is required because a new source symbol is referenced.)

- [ ] **Step 6: Add the Python wrappers**

In `engine/audio/tg_sound.py`, add to `class TGSound` (near `GetSoundName`):

```python
    def GetDuration(self) -> float:
        if _audio is None:
            return 0.0
        try:
            return float(_audio.get_duration(self._name))
        except Exception:
            return 0.0
```

and to `class TGSoundManager` (near `GetSound`):

```python
    def duration_for(self, name: str) -> float:
        """Real decoded length (seconds) of a loaded sound, else 0.0.

        0.0 covers: no audio backend (tests), sound not loaded, or a
        zero-length/undecodable buffer. Callers treat 0.0 as 'complete inline'.
        """
        if _audio is None:
            return 0.0
        try:
            return float(_audio.get_duration(name))
        except Exception:
            return 0.0
```

- [ ] **Step 7: Write the failing wrapper test**

Create `tests/unit/test_tg_sound_duration.py`:

```python
"""duration_for returns 0.0 without an audio backend / unloaded sound."""
from engine.audio.tg_sound import TGSoundManager


def test_duration_for_unloaded_is_zero():
    mgr = TGSoundManager.instance()
    assert mgr.duration_for("DefinitelyNotLoadedSfx") == 0.0
```

- [ ] **Step 8: Run the test**

Run: `uv run pytest tests/unit/test_tg_sound_duration.py -v`
Expected: PASS (0.0 for an unloaded name — the synchronous-fallback contract).

- [ ] **Step 9: Commit**

```bash
git add native/src/audio engine/audio/tg_sound.py tests/unit/test_tg_sound_duration.py
git commit -m "feat(audio): expose decoded sound duration (get_duration / duration_for)"
```

---

## Task 2: `_complete_after` primitive on `TGAction`

**Files:**
- Modify: `engine/appc/actions.py` (`TGAction`, near lines 26-86; add a private event type near 22-23)
- Test: `tests/unit/test_actions.py`

**Interfaces:**
- Consumes: `App.g_kRealtimeTimerManager` (`get_time`, `AddTimer`, `RemoveTimer`), `App.TGTimer_Create`, `App.TGEvent_Create`.
- Produces: `TGAction._complete_after(duration_real_s: float) -> None`; `TGAction.ProcessEvent` handling of the private deferred-complete event; `TGAction._cancel_deferred_timer()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_actions.py`:

```python
def _advance_real_time(seconds, step=1.0 / 60.0):
    """Advance g_kRealtimeTimerManager in 60 Hz ticks for `seconds`."""
    n = int(round(seconds / step))
    for _ in range(n):
        App.g_kRealtimeTimerManager.tick(step)


def test_complete_after_zero_completes_inline():
    a = TGAction()
    done = []
    a.Completed = lambda: done.append(True)  # type: ignore
    a._playing = True
    a._complete_after(0.0)
    assert done == [True]                      # inline, no timer


def test_complete_after_duration_defers_until_timer():
    a = TGAction()
    done = []
    real_completed = a.Completed
    a.Completed = lambda: (done.append(True), real_completed())  # type: ignore
    a._playing = True
    a._complete_after(0.5)
    assert done == []                          # not yet
    _advance_real_time(0.25)
    assert done == []                          # still waiting at t=0.25
    _advance_real_time(0.4)                    # past 0.5s total
    assert done == [True]                      # completed exactly once
    _advance_real_time(1.0)
    assert done == [True]                      # one-shot: no re-fire


def test_cancel_deferred_timer_prevents_completion():
    a = TGAction()
    done = []
    a.Completed = lambda: done.append(True)    # type: ignore
    a._playing = True
    a._complete_after(0.5)
    a._cancel_deferred_timer()
    _advance_real_time(1.0)
    assert done == []                          # cancelled before firing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "complete_after or cancel_deferred" -v`
Expected: FAIL with `AttributeError: 'TGAction' object has no attribute '_complete_after'`.

- [ ] **Step 3: Implement the primitive**

In `engine/appc/actions.py`, add a private event type near the existing ones (lines 22-23):

```python
_ET_ACTION_DEFERRED_COMPLETE = 0x5E03  # realtime timer elapsed -> self.Completed()
```

In `class TGAction.__init__`, add after `self._playing = False`:

```python
        self._deferred_timer = None   # (manager, TGTimer) while a deferral is pending
```

Add these methods to `TGAction` (after `Completed`):

```python
    def _complete_after(self, duration_real_s) -> None:
        """Complete this action after duration_real_s wall-clock seconds via
        g_kRealtimeTimerManager. duration <= 0 (or None) completes inline,
        preserving synchronous behavior when there is no audio to wait on."""
        if not duration_real_s or duration_real_s <= 0:
            self.Completed()
            return
        import App
        mgr = App.g_kRealtimeTimerManager
        timer = App.TGTimer_Create()
        timer.SetTimerStart(mgr.get_time() + float(duration_real_s))
        timer.SetDelay(-1.0)            # one-shot
        ev = App.TGEvent_Create()
        ev.SetEventType(_ET_ACTION_DEFERRED_COMPLETE)
        ev.SetDestination(self)
        timer.SetEvent(ev)
        mgr.AddTimer(timer)
        self._deferred_timer = (mgr, timer)

    def _cancel_deferred_timer(self) -> None:
        rec = self._deferred_timer
        if rec is not None:
            mgr, timer = rec
            mgr.RemoveTimer(timer)
            self._deferred_timer = None
```

Override `ProcessEvent` on `TGAction` (it currently inherits the base handler):

```python
    def ProcessEvent(self, event) -> None:
        if event.GetEventType() == _ET_ACTION_DEFERRED_COMPLETE:
            self._deferred_timer = None
            self.Completed()
            return
        super().ProcessEvent(event)
```

Update `Abort` to cancel any pending deferral:

```python
    def Abort(self) -> None:
        self._playing = False
        self._cancel_deferred_timer()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "complete_after or cancel_deferred" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full actions suite (no regressions)**

Run: `uv run pytest tests/unit/test_actions.py -v`
Expected: PASS (all existing tests still green — `TGAction.ProcessEvent` only intercepts the private type and otherwise defers to `super()`).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): add TGAction._complete_after realtime deferred-completion primitive"
```

---

## Task 3: `TGScriptAction` honors the return-value completion convention

**Files:**
- Modify: `engine/appc/actions.py` (`TGScriptAction`, lines 108-133)
- Test: `tests/unit/test_actions.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `TGScriptAction` no longer auto-completes when its target function returns a truthy value (deferred); still auto-completes on falsy/`None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_actions.py`:

```python
def test_script_action_truthy_return_defers_completion():
    import sys, types
    mod = types.ModuleType("_test_script_defer")
    mod.deferred = lambda pAction: 1          # truthy => "I'll complete later"
    sys.modules["_test_script_defer"] = mod

    a = App.TGScriptAction_Create("_test_script_defer", "deferred")
    a.Play()
    assert a.IsPlaying()                       # deferred: NOT auto-completed
    del sys.modules["_test_script_defer"]


def test_script_action_falsy_return_auto_completes():
    import sys, types
    mod = types.ModuleType("_test_script_instant")
    mod.instant = lambda pAction: 0           # falsy => auto-complete
    sys.modules["_test_script_instant"] = mod

    a = App.TGScriptAction_Create("_test_script_instant", "instant")
    a.Play()
    assert not a.IsPlaying()                   # completed inline
    del sys.modules["_test_script_instant"]


def test_script_action_none_return_auto_completes():
    import sys, types
    mod = types.ModuleType("_test_script_none")
    mod.noret = lambda pAction: None
    sys.modules["_test_script_none"] = mod

    a = App.TGScriptAction_Create("_test_script_none", "noret")
    a.Play()
    assert not a.IsPlaying()
    del sys.modules["_test_script_none"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "script_action_truthy or script_action_falsy or script_action_none" -v`
Expected: `test_script_action_truthy_return_defers_completion` FAILS (currently auto-completes); the falsy/none ones may already pass.

- [ ] **Step 3: Implement return-value honoring**

In `engine/appc/actions.py`, change `TGScriptAction` to capture the return value and add a `Play()` override that skips auto-completion when deferred. Replace `_do_play` (lines 115-132) with a version that records the result, and add `Play`:

```python
    def Play(self) -> None:
        self._playing = True
        self._deferred = False
        self._do_play()
        if not self._deferred:
            self.Completed()

    def _do_play(self) -> None:
        key = (self._module_name, self._func_name)
        if _script_action_depth.get(key, 0) >= _SCRIPT_ACTION_MAX_DEPTH:
            return
        _script_action_depth[key] = _script_action_depth.get(key, 0) + 1
        try:
            mod = sys.modules.get(self._module_name)
            if mod is None:
                try:
                    import importlib
                    mod = importlib.import_module(self._module_name)
                except (ImportError, ModuleNotFoundError):
                    return
            fn = getattr(mod, self._func_name, None)
            if fn is not None:
                # SDK convention: a script-action function returns falsy/None
                # ("Return: 0 - Action completed") => auto-complete; truthy
                # (e.g. ViewscreenOn/PlayDialog return 1) => the function wired
                # a deferred completion, so we must NOT auto-complete here.
                ret = fn(self, *self._args)
                if ret:
                    self._deferred = True
        finally:
            _script_action_depth[key] -= 1
```

Add `self._deferred = False` to `TGScriptAction.__init__` (after `self._args = args`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "script_action_truthy or script_action_falsy or script_action_none" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full actions suite**

Run: `uv run pytest tests/unit/test_actions.py -v`
Expected: PASS. (Existing tests use script-action callbacks that return `None`/append to a list → falsy → auto-complete, unchanged.)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): TGScriptAction honors SDK return-value completion convention"
```

---

## Task 4: `g_kTGActionManager` routes `ET_ACTION_COMPLETED` to the owner action

**Files:**
- Modify: `engine/appc/actions.py` (`TGActionManager`, lines 489-511)
- Test: `tests/unit/test_actions.py`

**Interfaces:**
- Consumes: `TGObjPtrEvent.GetObjPtr()`.
- Produces: `TGActionManager.ProcessEvent` calls `event.GetObjPtr().Completed()` on `App.ET_ACTION_COMPLETED`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_actions.py`:

```python
def test_action_manager_completes_objptr_on_action_completed():
    owner = TGAction()
    done = []
    owner.Completed = lambda: done.append(True)   # type: ignore

    ev = App.TGObjPtrEvent_Create()
    ev.SetEventType(App.ET_ACTION_COMPLETED)
    ev.SetObjPtr(owner)
    App.g_kTGActionManager.ProcessEvent(ev)

    assert done == [True]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_actions.py::test_action_manager_completes_objptr_on_action_completed -v`
Expected: FAIL (owner.Completed never called — base `ProcessEvent` only runs python-func handlers).

- [ ] **Step 3: Implement the handler**

In `engine/appc/actions.py`, add to `class TGActionManager` (after `IsRegistered`):

```python
    def ProcessEvent(self, event) -> None:
        # SDK manager-ObjPtr deferred-completion pattern: ViewscreenOn /
        # ViewscreenOff / PlayDialog wire a leaf action's completion to post
        # ET_ACTION_COMPLETED here with the OWNER action as the ObjPtr. Route it
        # to the owner so the sequence step gated on the owner advances.
        import App
        if event.GetEventType() == App.ET_ACTION_COMPLETED:
            owner = event.GetObjPtr() if hasattr(event, "GetObjPtr") else None
            if owner is not None and hasattr(owner, "Completed"):
                owner.Completed()
                return
        super().ProcessEvent(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_actions.py::test_action_manager_completes_objptr_on_action_completed -v`
Expected: PASS.

- [ ] **Step 5: Guard the existing handler path (no regression)**

Run: `uv run pytest tests/unit/test_actions.py -k "action_completed" -v`
Expected: PASS — including the pre-existing `test_action_completed_fires_registered_events`, which posts `ET_ACTION_COMPLETED` to the manager with a registered python-func handler but **no ObjPtr**. Confirm it still fires: that event is a plain `TGEvent` (no `GetObjPtr`), so `owner` is `None` and we fall through to `super().ProcessEvent(event)`.

> If `test_action_completed_fires_registered_events` regresses: the cause is the ObjPtr branch swallowing a no-ObjPtr event. The guard `hasattr(event, "GetObjPtr")` + `owner is not None` prevents this — verify both conditions are present.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): g_kTGActionManager routes ET_ACTION_COMPLETED to owner action"
```

---

## Task 5: `TGSoundAction` gates on real audio duration

**Files:**
- Modify: `engine/appc/actions.py` (`TGSoundAction`, lines 384-408)
- Test: `tests/unit/test_actions.py`

**Interfaces:**
- Consumes: `TGSoundManager.duration_for(name)` (Task 1); `TGAction._complete_after` (Task 2).
- Produces: `TGSoundAction.Play()` defers `Completed()` by the sound's real duration; zero duration completes inline.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_actions.py`:

```python
def test_sound_action_defers_by_real_duration(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 0.5, raising=True)
    a = App.TGSoundAction_Create("AnySfx")
    a.Play()
    assert a.IsPlaying()                       # gated on the 0.5s duration
    _advance_real_time(0.6)
    assert not a.IsPlaying()                    # completed after duration


def test_sound_action_zero_duration_completes_inline(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 0.0, raising=True)
    a = App.TGSoundAction_Create("AnySfx")
    a.Play()
    assert not a.IsPlaying()                    # inline (synchronous preserved)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "sound_action_defers or sound_action_zero" -v`
Expected: `test_sound_action_defers_by_real_duration` FAILS (currently completes inline regardless of duration).

- [ ] **Step 3: Implement deferral**

In `engine/appc/actions.py`, add a `Play()` override to `class TGSoundAction` (keep `_do_play` as-is — it plays the sound):

```python
    def Play(self) -> None:
        # Override (not _do_play) so completion is gated on the sound's real
        # wall-clock length: a sequence step chained after this action advances
        # only when the audio actually finishes. Zero duration (no backend /
        # unloaded) completes inline, preserving synchronous behavior.
        self._playing = True
        self._do_play()
        from engine.audio.tg_sound import TGSoundManager
        dur = TGSoundManager.instance().duration_for(self._sound_name)
        self._complete_after(dur)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "sound_action_defers or sound_action_zero" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Verify the inline-completion regression test still passes**

Run: `uv run pytest tests/unit/test_actions.py::test_sound_action_completes_inline_so_chain_advances -v`
Expected: PASS — the test's `"ProbeLaunchTestSfx"` is unloaded, so `duration_for` returns 0.0 → inline, chain advances. (This is the synchronous-preservation property in action.)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_actions.py
git commit -m "feat(actions): TGSoundAction gates sequence advancement on real audio duration"
```

---

## Task 6: `crew_speech` returns one duration sourced from real audio

**Files:**
- Modify: `engine/appc/crew_speech.py` (`CrewSpeechBus.speak`, `_play_voice`, `emit`, lines 43-101)
- Test: `tests/unit/test_crew_speech.py` (locate; create if absent)

**Interfaces:**
- Consumes: `TGSoundManager.duration_for` (Task 1).
- Produces: `CrewSpeechBus.speak(...) -> float` (duration seconds; 0.0 if dropped); `emit(...) -> float`; subtitle dwell + bus expiry use the SAME duration.

- [ ] **Step 1: Locate the crew_speech test file**

Run: `ls tests/unit/test_crew_speech.py 2>/dev/null || grep -rl "crew_speech" tests/`
Use the existing file if present; otherwise create `tests/unit/test_crew_speech.py`. Confirm whether any existing test asserts `speak(...)` returns a bool (truthiness is preserved: `dur>0` truthy = accepted, `0.0` falsy = dropped).

- [ ] **Step 2: Write the failing test**

Add to the crew_speech test file:

```python
def test_speak_returns_estimate_duration_for_text_only():
    from engine.appc.crew_speech import CrewSpeechBus
    bus = CrewSpeechBus()
    # Text-only line (no wav): duration is the word-estimate, > 0.
    dur = bus.speak("Liu", "Captain, welcome to Starbase 12.", None, 1, now=0.0)
    assert dur > 0.0
    assert bus._active_expiry == dur           # bus expiry uses the same value


def test_speak_dropped_line_returns_zero():
    from engine.appc.crew_speech import CrewSpeechBus
    bus = CrewSpeechBus()
    assert bus.speak("Liu", None, None, 1, now=0.0) == 0.0   # nothing to say
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_crew_speech.py -k "returns_estimate or dropped_line" -v`
Expected: FAIL (`speak` currently returns `True`/`False`, not a float; `_active_expiry` assert fails).

- [ ] **Step 4: Implement single-duration return**

In `engine/appc/crew_speech.py`, rewrite `CrewSpeechBus.speak` (lines 43-60) so one duration — real audio when available, estimate otherwise — drives subtitle, expiry, and the return:

```python
    def speak(self, speaker, text, wav, priority, now=None) -> float:
        """Arbitrate one line. Returns its duration in seconds (0.0 if dropped).
        The returned value also drives the subtitle dwell and the bus free-up,
        so they can never disagree, and is what gates the owning action's
        completion."""
        if now is None:
            now = time.monotonic()
        if text is None and wav is None:
            return 0.0  # nothing to say — don't occupy the channel
        priority = int(priority)
        line_live = now < self._active_expiry
        if line_live and priority < self._active_priority:
            return 0.0  # a higher-priority line is still talking
        self._active_priority = priority
        # Real decoded length when the voice is loadable; estimate otherwise.
        real = self._play_voice(str(wav)) if wav else 0.0
        duration = real if real > 0.0 else _estimate_duration(text, wav)
        self._active_expiry = now + duration
        if text:
            self._route_subtitle(str(speaker), str(text), duration)
        return duration
```

Change `_play_voice` (lines 72-85) to return the real duration (0.0 on any failure):

```python
    def _play_voice(self, wav) -> float:
        try:
            from engine.audio.tg_sound import TGSoundManager, TGSound
            mgr = TGSoundManager.instance()
            snd = mgr.GetSound(wav)
            if snd is None:
                snd = mgr.LoadSound(wav, wav, TGSound.LS_STREAMED)
            if snd is None:
                return 0.0
            snd.SetVoice()
            snd.Play()
            return mgr.duration_for(wav)
        except Exception as _e:
            dev_mode.log_swallowed("play crew speech sound", _e)
            return 0.0
```

Change `emit` (lines 88-101) to return the duration:

```python
    bus().speak(speaker, text, wav, int(priority))
```
becomes
```python
    return bus().speak(speaker, text, wav, int(priority))
```

(Leave `acknowledge` as-is; it ignores the return value.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_crew_speech.py -k "returns_estimate or dropped_line" -v`
Expected: PASS.

- [ ] **Step 6: Run the full crew_speech suite**

Run: `uv run pytest tests/unit/test_crew_speech.py -v`
Expected: PASS (truthiness-preserved return keeps any accepted/dropped assertions valid).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/crew_speech.py tests/unit/test_crew_speech.py
git commit -m "feat(crew_speech): speak/emit return one real-audio-or-estimate duration"
```

---

## Task 7: `CharacterAction` speak-types gate on the returned duration

**Files:**
- Modify: `engine/appc/ai.py` (`CharacterAction`, lines 1096-1119)
- Test: `tests/unit/test_actions.py` (or `tests/unit/test_ai.py` — use whichever holds CharacterAction tests; default to `test_actions.py`)

**Interfaces:**
- Consumes: `crew_speech.emit(...) -> float` (Task 6); `TGAction._complete_after` (Task 2).
- Produces: `CharacterAction.Play()` defers `Completed()` by the line's duration for speak-types; non-speak types complete inline.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_actions.py` (imports `App`; `CharacterAction` via `App`):

```python
def test_character_speak_action_defers_by_duration(monkeypatch):
    import engine.appc.crew_speech as crew_speech
    monkeypatch.setattr(crew_speech, "emit",
                        lambda *a, **k: 0.5, raising=True)
    from engine.appc.ai import CharacterAction
    a = CharacterAction(None, CharacterAction.AT_SAY_LINE, "AnyLine")
    a.Play()
    assert a.IsPlaying()                       # gated on 0.5s line duration
    _advance_real_time(0.6)
    assert not a.IsPlaying()


def test_character_speak_zero_duration_inline(monkeypatch):
    import engine.appc.crew_speech as crew_speech
    monkeypatch.setattr(crew_speech, "emit",
                        lambda *a, **k: 0.0, raising=True)
    from engine.appc.ai import CharacterAction
    a = CharacterAction(None, CharacterAction.AT_SAY_LINE, "AnyLine")
    a.Play()
    assert not a.IsPlaying()                    # inline


def test_character_nonspeak_action_completes_inline():
    from engine.appc.ai import CharacterAction
    a = CharacterAction(None, CharacterAction.AT_TURN, None)
    a.Play()
    assert not a.IsPlaying()                    # non-speak: unchanged, inline
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_actions.py -k "character_speak or character_nonspeak" -v`
Expected: `test_character_speak_action_defers_by_duration` FAILS (currently inline).

- [ ] **Step 3: Implement deferral**

In `engine/appc/ai.py`, change `CharacterAction._do_play` to RETURN the duration for speak-types (0.0 otherwise) and add a `Play()` override. Replace the `_do_play` body (lines 1096-1119) so its final line is `return ...`:

```python
    def Play(self) -> None:
        # Speak-types complete after the voice line's real duration so a
        # sequence step chained after the line advances when the line finishes.
        # Non-speak types (MOVE/TURN/GLANCE/...) complete inline as before.
        self._playing = True
        dur = self._do_play()
        self._complete_after(dur or 0.0)

    def _do_play(self):
        at = self._action_type
        if at in (self.AT_SPEAK_LINE, self.AT_SPEAK_LINE_NO_FLAP_LIPS):
            voice_only = False
        elif at in (self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
            voice_only = True
        else:
            return 0.0
        from engine.appc import crew_speech
        from engine.appc.characters import CharacterClass_Cast
        cc = CharacterClass_Cast(self._character) if self._character is not None else None
        if cc is not None:
            name = cc.GetCharacterName()
        elif isinstance(self._character, str):
            name = self._character
        else:
            name = ""
        return crew_speech.emit(name, self._database, self._detail,
                                self._priority, voice_only=voice_only) or 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_actions.py -k "character_speak or character_nonspeak" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_actions.py
git commit -m "feat(ai): CharacterAction speak-types gate sequence advancement on line duration"
```

---

## Task 8: Remove the interim `SetRemoteCam` hold hack

**Files:**
- Modify: `engine/appc/bridge_set.py` (`ViewScreenObject.SetRemoteCam`, lines 93-107)
- Delete: `tests/unit/test_viewscreen_remote_cam_latch.py`
- Test: `tests/unit/test_bridge_set.py` (add a plain-passthrough test; create if the file is absent — confirm in Step 1)

**Interfaces:**
- Produces: `ViewScreenObject.SetRemoteCam(cam)` unconditionally stores `cam` (no hold).

- [ ] **Step 1: Confirm the comm-feed revert path is camera-identity based**

Read `engine/host_loop.py:2478-2499` (`_active_comm_feed`): it returns `None` (→ forward-view fallback) for any remote cam that is not a comm-set `maincamera`. So `ViewscreenOff` setting the player-camera stub naturally reverts to the forward view once timing is correct. Locate the bridge_set test file: `ls tests/unit/test_bridge_set.py 2>/dev/null || grep -rl "ViewScreenObject" tests/`.

- [ ] **Step 2: Write the failing test (plain passthrough)**

Add to the bridge_set test file (create `tests/unit/test_bridge_set.py` if none):

```python
def test_set_remote_cam_is_plain_passthrough():
    from engine.appc.bridge_set import ViewScreenObject, CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3
    vs = ViewScreenObject("x.nif")
    cam = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                            _NiFrustum(), 1.0, 800.0)
    vs.SetRemoteCam(cam)

    class _PlayerCamStub:  # ViewscreenOff reverts to a non-camera player stub
        pass
    stub = _PlayerCamStub()
    vs.SetRemoteCam(stub)                       # no hold: revert is honored
    assert vs.GetRemoteCam() is stub
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_set.py::test_set_remote_cam_is_plain_passthrough -v`
Expected: FAIL — the current hold ignores the non-camera revert, so `GetRemoteCam()` is still `cam`.

- [ ] **Step 4: Remove the hold**

In `engine/appc/bridge_set.py`, replace `ViewScreenObject.SetRemoteCam` (lines 93-107) with:

```python
    def SetRemoteCam(self, cam):
        # ViewscreenOn sets a comm set's maincamera; ViewscreenOff reverts to the
        # player camera. The host's _active_comm_feed identity-matches the remote
        # cam back to a comm set, falling back to the forward view for anything
        # else — so a plain store gives the correct comm-then-revert behavior now
        # that action-sequence timing holds the comm scene for the dialogue.
        self._remote_cam = cam
```

- [ ] **Step 5: Delete the obsolete latch test**

```bash
git rm tests/unit/test_viewscreen_remote_cam_latch.py
```

- [ ] **Step 6: Run tests to verify pass + deletion**

Run: `uv run pytest tests/unit/test_bridge_set.py -v`
Expected: PASS. The latch test no longer exists.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set.py
git commit -m "refactor(bridge): remove interim SetRemoteCam hold hack (timing now gates the comm scene)"
```

---

## Task 9: Audit, integration regression, and live verification

**Files:**
- Read-only audit: `sdk/Build/scripts/**` (TGScriptAction targets), `engine/`
- Test: `tests/integration/tutorial/test_m3gameflow.py` and any comm/dialogue integration test

**Interfaces:**
- Consumes: all prior tasks.
- Produces: confidence that no sequence hangs and existing cutscenes are intact.

- [ ] **Step 1: Audit TGScriptAction target functions for return-truthy-without-deferral**

Run:
```bash
grep -rn "TGScriptAction_Create" sdk/Build/scripts/ | sed -E 's/.*TGScriptAction_Create\(([^,]+),\s*("[^"]+"|[^,)]+).*/\1 \2/' | sort -u
```
For each `(module, function)` target, confirm the function either returns falsy (auto-complete) or returns truthy AND wires a deferred completion (manager-ObjPtr or its own `Completed()`). The known truthy-deferred functions are `MissionLib.ViewscreenOn` and `MissionLib.PlayDialog`. Flag any function that returns truthy without wiring completion — that would hang a sequence (in BC too). Record findings in the commit message; if a real offender exists in a code path we exercise, treat it as a defect to handle (not in scope to fix every mission, but document).

- [ ] **Step 2: Run the action + sequence + crew_speech unit suites together**

Run: `uv run pytest tests/unit/test_actions.py tests/unit/test_crew_speech.py tests/unit/test_tg_sound_duration.py tests/unit/test_bridge_set.py -v`
Expected: PASS (all).

- [ ] **Step 3: Run the mission gameflow integration regression**

Run: `uv run pytest tests/integration/tutorial/test_m3gameflow.py -v`
Expected: PASS — no sequence hangs from the TGScriptAction return-value change or the manager activation. If a hang/timeout appears, the audit in Step 1 missed a truthy-without-deferral target on this path; investigate that function specifically.

- [ ] **Step 4: Run the broader suite under the watchdog**

Run: `scripts/run_tests.sh`
Expected: PASS within the memory cap (full `uv run pytest` directly is unsafe — use the script).

- [ ] **Step 5: Live verification (Mark drives the GUI)**

Provide these steps for the user to run and report (no synthetic desktop interaction):
1. `cmake --build build -j` (ensure the Task 1 native rebuild is in `build/dauntless`).
2. `./build/dauntless --developer` → dev "Load Mission…" → E1M1.
3. Trigger the Starbase 12 hail.
- Expected: Admiral Liu speaks; the comm viewscreen holds for each line; after the last line the view returns to the forward external view (no instant revert, no overlap).
4. Also confirm: the bridge walk-on cutscene plays (camera path + crew intros), and normal-play crew acknowledgements still sound once each (no self-overlap).

- [ ] **Step 6: Commit the audit notes**

```bash
git commit --allow-empty -m "test(actions): audit TGScriptAction targets + integration regression for real-duration gating

Audited all TGScriptAction_Create targets: only ViewscreenOn/PlayDialog return
truthy and both wire deferred completion. m3gameflow + watchdog suite green."
```

---

## Self-Review

**Spec coverage:**
- §1 shared primitive → Task 2. ✓
- §2 native real duration → Task 1. ✓
- §3 CharacterAction speak → Task 7; TGSoundAction → Task 5; TGScriptAction return-value → Task 3; manager handler → Task 4. ✓
- §3 crew_speech single-duration source → Task 6. ✓
- §4 remove hold hack + delete latch test → Task 8. ✓
- §5 unit boundaries → each task is independently testable. ✓
- §6 risks: TGScriptAction-hang audit → Task 9 Step 1; PlayDialog pacing → Task 9 Step 3; torn-down world → Task 2's guarded `Completed`/`Abort`; walk-on regression → Task 9 Step 5. ✓
- §7 tests → Tasks 1-8 unit tests + Task 9 integration/live. ✓
- §8 out-of-scope respected (no lip-sync, no save/load of mid-flight sequences, no host/renderer change beyond hack removal). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command + expected result.

**Type consistency:** `duration_for(name) -> float` (Task 1) consumed identically in Tasks 5 & 6; `emit(...) -> float` (Task 6) consumed in Task 7; `_complete_after(duration_real_s)` (Task 2) consumed in Tasks 5 & 7; `_advance_real_time` helper defined in Task 2, reused in Tasks 5 & 7 (same file). `_ET_ACTION_DEFERRED_COMPLETE` defined once (Task 2). Manager `ProcessEvent` (Task 4) uses `App.ET_ACTION_COMPLETED == 101` (Global Constraints).

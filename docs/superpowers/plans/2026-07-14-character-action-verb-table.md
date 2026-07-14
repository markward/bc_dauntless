# CharacterAction Verb Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in the six unimplemented `CharacterAction` verbs and restore the two SDK re-entrancy gates, so bridge officers turn to the captain when they speak and use their consoles on every order.

**Architecture:** No new subsystems. `CharacterAction.Play()` (`engine/appc/ai.py:1386-1432`) is a verb-dispatch table where everything unmatched falls through to an immediate silent `Completed()`. We add the missing branches, each reusing one of two existing primitives: `bridge_placement._resolve_builder_sequence` (name → SDK Python builder → `TGSequence`) and `BridgeCharacterAnimController.submit` (clip list → renderer). We also give `CharacterClass` real animation-category and speaking state so the SDK's own guards work.

**Tech Stack:** Python 3.11+, pytest, `uv`. **No C++ change; no rebuild required.**

**Spec:** `docs/superpowers/specs/2026-07-14-character-action-verb-table-design.md`

## Global Constraints

- **Never modify anything under `sdk/`.** SDK scripts are ground truth. If an SDK script looks wrong, the engine surface it calls is what's wrong.
- **Never run destructive git.** Banned: `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec — this tree is shared with concurrent sessions and work is often deliberately uncommitted.
- **`Play()` must never raise and must never stall.** Every new branch wraps its work in `try/except` and calls `self.Completed()` on any failure or unresolved lookup. A mission `TGSequence` that stalls is worse than a missing gesture.
- **`hasattr` is not a capability test in this codebase** — `TGObject.__getattr__` returns a truthy `_Stub` for unknown public attributes. Use `engine.core.ids.implements()` or check `__dict__`.
- **Test gate:** `uv run pytest` during the loop; `scripts/check_tests.sh` before the final commit (Task 9).
- Run all commands from `/Users/mward/Documents/Projects/bc_dauntless`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `engine/appc/characters.py` | `CharacterClass` | Modify: telemetry on `__getattr__`; `CAT_` ordinals; current-animation state; `IsAnimating*` / `IsSpeaking` predicates |
| `engine/appc/crew_speech.py` | speech bus | Modify: track the active speaker; add `is_speaking(name)` |
| `engine/appc/bridge_placement.py` | name → SDK builder resolution | Modify: extract a literal-key resolver; add the `PushButtons` alias |
| `engine/bridge_character_anim.py` | transient clip runner | Modify: add a `_SCRIPTED` priority band and `request_default()` |
| `engine/appc/ai.py` | `CharacterAction` verb table | Modify: 6 new verb branches + `AT_SAY_LINE` turn args |
| `tests/unit/test_character_action_verbs.py` | verb-table tests | **Create** |
| `tests/unit/test_character_animation_state.py` | gate tests | **Create** |

---

### Task 1: Make `CharacterClass`'s silent data-bag visible to the stub heatmap

`CharacterClass.__getattr__` absorbs every unknown `Set*`/`Add*` into `self._data` and everything else into `lambda: None`, recording nothing. That is why `docs/stub_heatmap.md` has **zero `CharacterClass` rows** and always would have. Fix the instrument before trusting any reading.

**Files:**
- Modify: `engine/appc/characters.py:769-786` (the `__getattr__` data-bag)
- Test: `tests/unit/test_character_animation_state.py` (create)

**Interfaces:**
- Consumes: `engine.core.stub_telemetry.record_attr(owner_type: str, attr_name: str) -> None`
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_character_animation_state.py`:

```python
from engine.appc.characters import CharacterClass
from engine.core import stub_telemetry


def test_unknown_setter_is_recorded_in_stub_telemetry():
    stub_telemetry.reset()
    stub_telemetry.set_enabled(True)
    try:
        ch = CharacterClass("body.nif", "head.nif")
        ch.SetLookAtAdj(0, 0, 51)          # real SDK call (Felix.py:247), unimplemented
        snap = stub_telemetry.snapshot()
    finally:
        stub_telemetry.set_enabled(False)
        stub_telemetry.reset()
    assert any("LookAtAdj" in str(k) for k in snap), snap
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_character_animation_state.py -v`
Expected: FAIL — the snapshot has no `LookAtAdj` entry (the setter is silently absorbed).

- [ ] **Step 3: Record the misses**

In `engine/appc/characters.py`, in `__getattr__`, record each fallback before returning it. Keep the existing behaviour identical — this observes, it does not change semantics:

```python
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        from engine.core import stub_telemetry
        stub_telemetry.record_attr("CharacterClass", name)
        data = self._data
        if name.startswith("Set") or name.startswith("Add"):
            field = name[3:]
            def setter(*args, **kwargs):
                data[field] = args[0] if len(args) == 1 else args
            return setter
        if name.startswith("Get"):
            field = name[3:]
            return lambda *args, **kwargs: data.get(field)
        if name.startswith("Is"):
            field = name[2:]
            return lambda *args, **kwargs: 1 if data.get(field) else 0
        return lambda *args, **kwargs: None
```

- [ ] **Step 4: Give the numeric getters real defaults**

The `Get*` fallback returns `None` for a never-set field, so any SDK caller doing arithmetic on one raises a swallowed `TypeError` — the same bug the `GetLastTalkTime` comment (`characters.py:659-666`) exists to prevent. The four the SDK actually sets are numeric; give them real explicit getters with BC's defaults, next to the other `Get*` methods:

```python
    # Explicit numeric getters. WITHOUT these the __getattr__ data-bag returns
    # None for a never-set field, and `GetGameTime() - GetBlinkChance()` becomes
    # `float - None` (TypeError, swallowed by event dispatch). BC's defaults:
    # BlinkChance 0.1f (ctor), RandomAnimationChance per-character (0.75 for
    # station officers, 0.01 for guests/extras — MissionLib.py:1578).
    def GetBlinkChance(self) -> float:
        return float(self._data.get("BlinkChance", 0.1))

    def GetRandomAnimationChance(self) -> float:
        return float(self._data.get("RandomAnimationChance", 0.0))
```

- [ ] **Step 5: Add a test for the defaults**

```python
def test_numeric_getters_return_floats_not_none():
    ch = CharacterClass("body.nif", "head.nif")
    assert ch.GetBlinkChance() == 0.1              # BC's ctor default
    assert isinstance(ch.GetRandomAnimationChance(), float)
    ch.SetRandomAnimationChance(0.75)
    assert ch.GetRandomAnimationChance() == 0.75
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_character_animation_state.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite — this touches a hot path**

Run: `uv run pytest -q`
Expected: no new failures vs. `tests/known_failures.txt`.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_animation_state.py
git commit -m "feat(characters): record CharacterClass stub misses in telemetry"
```

---

### Task 2: Back `IsSpeaking()` with real per-character state

`IsSpeaking()` is hardcoded `return 0` (`characters.py:668`). **23 SDK sites** use it as a guard. The bus already knows when a line is live (`_active_expiry`) but not *who* is speaking — add that.

**Files:**
- Modify: `engine/appc/crew_speech.py` (`CrewSpeechBus.__init__`, `reset`, `speak`, module-level helpers)
- Modify: `engine/appc/characters.py:668` (`IsSpeaking`)
- Test: `tests/unit/test_character_animation_state.py`

**Interfaces:**
- Produces: `engine.appc.crew_speech.is_speaking(name: str) -> bool` — True while `name`'s line still holds the channel.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_character_animation_state.py`:

```python
from engine.appc import crew_speech


def test_is_speaking_tracks_the_active_speaker():
    bus = crew_speech.bus()
    bus.reset()
    # speak() takes (speaker, text, wav, priority, now); a text-only line gets an
    # estimated duration >= _MIN_DURATION_S (2.0s).
    dur = bus.speak("Kiska", "Aye, Captain.", None, 1, now=100.0)
    assert dur > 0.0
    assert crew_speech.is_speaking("Kiska", now=100.5) is True
    assert crew_speech.is_speaking("Felix", now=100.5) is False   # no cross-talk
    assert crew_speech.is_speaking("Kiska", now=100.0 + dur + 0.1) is False
    bus.reset()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_character_animation_state.py::test_is_speaking_tracks_the_active_speaker -v`
Expected: FAIL — `module 'engine.appc.crew_speech' has no attribute 'is_speaking'`.

- [ ] **Step 3: Track the speaker on the bus**

In `engine/appc/crew_speech.py`, add the field in `CrewSpeechBus.__init__` beside `_active_priority`:

```python
        self._active_speaker: str = ""
```

Clear it in `reset()` (beside `self._active_priority = -1`):

```python
        self._active_speaker = ""
```

And set it in `speak()`, immediately after the existing `self._active_priority = priority` line:

```python
        self._active_speaker = str(speaker)
```

Then add the module-level query beside `bus()`:

```python
def is_speaking(name, now=None) -> bool:
    """True while *name*'s line still holds the speech channel.

    Backs CharacterClass.IsSpeaking, which the SDK uses as a re-entrancy guard
    (`if (pOfficer.IsHidden() or ... or pOfficer.IsSpeaking()): return`, e.g.
    Bridge/EngineerCharacterHandlers.py:514 and 22 more sites).

    NOTE this reports the CURRENT bus, which serialises all crew speech. BC gives
    every character its own speaking queue and lets two officers talk over each
    other; that divergence is tracked separately (the speech-architecture spec)
    and does not change this predicate's contract.
    """
    if now is None:
        now = time.monotonic()
    b = bus()
    return bool(name) and b._active_speaker == str(name) and now < b._active_expiry
```

- [ ] **Step 4: Wire `CharacterClass.IsSpeaking`**

Replace `engine/appc/characters.py:668` (`def IsSpeaking(self) -> int: return 0`) with:

```python
    def IsSpeaking(self) -> int:
        from engine.appc import crew_speech
        return 1 if crew_speech.is_speaking(self._character_name) else 0
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_character_animation_state.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/crew_speech.py engine/appc/characters.py tests/unit/test_character_animation_state.py
git commit -m "feat(speech): back CharacterClass.IsSpeaking with real per-speaker state"
```

---

### Task 3: `CAT_` ordinals + current-animation state + the interruptability gate

`IsAnimatingNonInterruptable()` is hardcoded `0` (`characters.py:673`) and **20 SDK sites** guard on it. Give `CharacterClass` a "what am I playing" field, and correct the `CAT_` values while we're in there: ours are a bitmask (`characters.py:376-383`), BC's are plain ordinals `0..6`.

**Files:**
- Modify: `engine/appc/characters.py:376-383` (`CAT_` constants), `:518-519` (`ClearAnimationsOfType`), `:670-673` (`IsAnimating*`)
- Test: `tests/unit/test_character_animation_state.py`

**Interfaces:**
- Produces, on `CharacterClass`:
  - `set_current_animation(name: str, category: int) -> None`
  - `clear_current_animation() -> None`
  - `GetCurrentAnimation() -> str` (`""` when idle)
  - `IsAnimating() -> int`, `IsGoingToAnimate() -> int`, `IsAnimatingInterruptable() -> int`, `IsAnimatingNonInterruptable() -> int`
- Consumed by: Tasks 6 and 7 (the verb branches set and clear this state).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_character_animation_state.py`:

```python
def test_cat_constants_are_bc_ordinals():
    # BC's CAT_ values are plain ordinals 0..6, proven from the binary's own
    # predicates: IsAnimatingInterruptable accepts {0,1,5,6}; IsAnimatingNon-
    # Interruptable tests == 2.
    assert CharacterClass.CAT_BREATHE == 0
    assert CharacterClass.CAT_INTERRUPTABLE == 1
    assert CharacterClass.CAT_NON_INTERRUPTABLE == 2
    assert CharacterClass.CAT_TURN == 3
    assert CharacterClass.CAT_TURN_BACK == 4
    assert CharacterClass.CAT_GLANCE == 5
    assert CharacterClass.CAT_GLANCE_BACK == 6


def test_non_interruptable_animation_closes_the_sdk_gate():
    ch = CharacterClass("body.nif", "head.nif")
    assert ch.IsAnimating() == 0
    assert ch.IsAnimatingNonInterruptable() == 0

    ch.set_current_animation("PushingButtons", CharacterClass.CAT_NON_INTERRUPTABLE)
    assert ch.IsAnimating() == 1
    assert ch.IsGoingToAnimate() == 1
    assert ch.IsAnimatingNonInterruptable() == 1
    assert ch.IsAnimatingInterruptable() == 0
    assert ch.GetCurrentAnimation() == "PushingButtons"

    ch.clear_current_animation()
    assert ch.IsAnimating() == 0
    assert ch.IsAnimatingNonInterruptable() == 0


def test_interruptable_categories_match_the_binary():
    ch = CharacterClass("body.nif", "head.nif")
    for cat in (CharacterClass.CAT_BREATHE, CharacterClass.CAT_INTERRUPTABLE,
                CharacterClass.CAT_GLANCE, CharacterClass.CAT_GLANCE_BACK):
        ch.set_current_animation("x", cat)
        assert ch.IsAnimatingInterruptable() == 1, cat
        assert ch.IsAnimatingNonInterruptable() == 0, cat
    ch.set_current_animation("x", CharacterClass.CAT_NON_INTERRUPTABLE)
    assert ch.IsAnimatingInterruptable() == 0
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_character_animation_state.py -v`
Expected: FAIL — `CAT_BREATHE == 1` (bitmask), and `set_current_animation` does not exist. (Careful: `set_current_animation` would otherwise be swallowed by `__getattr__`'s no-op fallback — but it does not start with `Set`/`Add`/`Get`/`Is`, so it returns `lambda: None` and the assertion still fails. Good.)

- [ ] **Step 3: Correct the constants**

Replace `engine/appc/characters.py:376-383`:

```python
    # Animation-category constants. BC's are plain ordinals, NOT a bitmask —
    # proven from the binary's own predicates: IsAnimatingInterruptable
    # (0x0066A5D0) accepts {0,1,5,6}; IsAnimatingNonInterruptable (0x0066A630)
    # tests == 2. (BC's CS_ state flags ARE a bitmask; we had the two backwards.)
    CAT_BREATHE             = 0
    CAT_INTERRUPTABLE       = 1
    CAT_NON_INTERRUPTABLE   = 2
    CAT_TURN                = 3
    CAT_TURN_BACK           = 4
    CAT_GLANCE              = 5
    CAT_GLANCE_BACK         = 6

    _INTERRUPTABLE_CATEGORIES = (CAT_BREATHE, CAT_INTERRUPTABLE,
                                 CAT_GLANCE, CAT_GLANCE_BACK)
```

- [ ] **Step 4: Add the state and the predicates**

In `engine/appc/characters.py`, initialise the field in `__init__` (beside the other `self._…` fields):

```python
        self._current_anim: tuple | None = None   # (name, CAT_) while playing
```

Add the mutators near the other animation methods (e.g. after `ClearExtraAnimations`):

```python
    def set_current_animation(self, name, category) -> None:
        """Mark this character as playing *name* in category *category* (a CAT_).

        BC keeps the playing animation in a record on the character; the SDK
        reads it back through IsAnimatingNonInterruptable() to refuse a second
        gesture on a busy officer. The verb dispatch (CharacterAction) is the
        only thing that starts these, so it owns setting and clearing this.
        """
        self._current_anim = (str(name), int(category))

    def clear_current_animation(self) -> None:
        self._current_anim = None

    def GetCurrentAnimation(self) -> str:
        return self._current_anim[0] if self._current_anim else ""
```

Replace the four hardcoded predicates at `characters.py:670-673`:

```python
    def IsAnimating(self) -> int:                 return 1 if self._current_anim else 0
    def IsGoingToAnimate(self) -> int:            return 1 if self._current_anim else 0
    def IsAnimatingInterruptable(self) -> int:
        if not self._current_anim:
            return 0
        return 1 if self._current_anim[1] in self._INTERRUPTABLE_CATEGORIES else 0
    def IsAnimatingNonInterruptable(self) -> int:
        if not self._current_anim:
            return 0
        return 1 if self._current_anim[1] == self.CAT_NON_INTERRUPTABLE else 0
```

- [ ] **Step 5: Fix `ClearAnimationsOfType`, which can never match**

`characters.py:518-519` compares a `CAT_` int against the animation *name* (`a[0]` is the name string from `AddAnimation(name, path)`), so it can never match anything. The registry holds no category, so the honest fix is to drop the filter and record the miss:

```python
    def ClearAnimationsOfType(self, anim_type) -> None:
        # BC keys this on the animation's CAT_ category, which our AddAnimation
        # registry (name -> python path) does not carry. Zero SDK call sites, so
        # rather than invent a category per registration we record it and no-op.
        from engine.core import stub_telemetry
        stub_telemetry.record_attr("CharacterClass", "ClearAnimationsOfType")
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_character_animation_state.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite — the `CAT_` value change is not local**

Run: `uv run pytest -q`
Expected: no new failures. If a test asserted the old bitmask values, update it in this commit (never orphan a test).

- [ ] **Step 8: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_animation_state.py
git commit -m "feat(characters): BC CAT_ ordinals + real interruptability gate"
```

---

### Task 4: A literal-key resolver, and the `PushButtons` alias

`bridge_placement._resolve_builder_sequence` always composes `location + suffix`. `AT_PLAY_ANIMATION` is the one verb whose key is **literal** (`"PushingButtons"`, no prefix). Extract the literal core; keep the composing wrapper on top.

**Files:**
- Modify: `engine/appc/bridge_placement.py:73-103`
- Test: `tests/unit/test_character_action_verbs.py` (create)

**Interfaces:**
- Produces: `bridge_placement.resolve_builder(character, key: str)` → `TGSequence | None`
- Produces: `bridge_placement.registered_module_path(character, key: str) -> str | None`
- Preserves: `bridge_placement._resolve_builder_sequence(character, suffix)` (unchanged signature — Tasks 6/8 and the existing callers rely on it)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_character_action_verbs.py`:

```python
from engine.appc import bridge_placement
from engine.appc.characters import CharacterClass


def _character_with(key, module_path, location="DBTactical"):
    ch = CharacterClass("body.nif", "head.nif")
    ch.SetLocation(location)
    ch.AddAnimation(key, module_path)
    return ch


def test_registered_module_path_uses_the_literal_key():
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    # literal — NOT prefixed with the location
    assert bridge_placement.registered_module_path(ch, "PushingButtons") == \
        "Some.Module.DBTConsoleInteraction"
    assert bridge_placement.registered_module_path(ch, "DBTacticalPushingButtons") is None


def test_push_buttons_misspelling_is_aliased():
    # BC ships a bug: MissionLib.PushButtons and 40 other sites ask for
    # "PushButtons", but all 14 registrations spell it "PushingButtons", so those
    # calls are silent no-ops in the original. We deliberately FIX the typo.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    assert bridge_placement.registered_module_path(ch, "PushButtons") == \
        "Some.Module.DBTConsoleInteraction"


def test_unregistered_key_resolves_to_none():
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    assert bridge_placement.registered_module_path(ch, "Nonexistent") is None
    assert bridge_placement.resolve_builder(ch, "Nonexistent") is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: FAIL — `module 'engine.appc.bridge_placement' has no attribute 'registered_module_path'`.

- [ ] **Step 3: Refactor the resolver**

In `engine/appc/bridge_placement.py`, add above `_resolve_builder_sequence`:

```python
# BC ships a real bug: MissionLib.PushButtons (MissionLib.py:5092) and 40 other
# call sites request animation key "PushButtons", but all 14 character
# registrations spell it "PushingButtons" — so in the original those calls are
# SILENT NO-OPS. The 18 correctly-spelled sites (all of EngineerCharacterHandlers,
# ScienceCharacterHandlers and HelmMenuHandlers) do work.
#
# We deliberately DIVERGE and fix the typo: the authors plainly meant them to
# fire. Consequence to know about: officers now gesture in ~41 mission beats
# where BC left them still. If a scripted scene looks over-animated, this is the
# first suspect — it is one entry, here.
_KEY_ALIASES = {"PushButtons": "PushingButtons"}


def registered_module_path(character, key):
    """The dotted Python builder path the character registered under *key*, or None.

    This is BC's core indirection (RE bridge-character-system.md §4): an animation
    NAME resolves to a Python FUNCTION PATH, never to an asset.
    """
    key = _KEY_ALIASES.get(str(key), str(key))
    for entry in getattr(character, "_animations", []):
        if entry and len(entry) >= 2 and str(entry[0]) == key:
            return entry[1]
    return None


def resolve_builder(character, key):
    """Call the SDK builder registered under the literal *key* and return its
    TGSequence, or None (unregistered / import error / empty sequence).

    The builder RETURNS the sequence; it does not play it. That is BC's contract.
    """
    import importlib
    import App  # noqa: F401 — side-effects: registers path_for entries

    module_path = registered_module_path(character, key)
    if not module_path:
        return None
    try:
        mod_name, func_name = module_path.rsplit(".", 1)
        func = getattr(importlib.import_module(mod_name), func_name)
        seq = func(character)
    except Exception:
        return None
    if seq is None or seq.GetNumActions() == 0:
        return None
    return seq
```

Then reduce `_resolve_builder_sequence` to the location-composing wrapper (same signature, same behaviour):

```python
def _resolve_builder_sequence(character, suffix):
    """Look up the SDK-registered builder for ``<location>+suffix`` and call it.

    The composed-key form (AT_MOVE / AT_TURN / AT_BREATHE / hit reactions).
    AT_PLAY_ANIMATION uses resolve_builder() with a LITERAL key instead.
    """
    location = character.GetLocation()
    if not location:
        return None
    return resolve_builder(character, str(location) + suffix)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: PASS.

- [ ] **Step 5: Run the suite — `_resolve_builder_sequence` has existing callers**

Run: `uv run pytest -q`
Expected: no new failures. Existing callers (`capture_registered_clip`, `capture_chair_clip`, `ai._queue_move`) must be unaffected.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/bridge_placement.py tests/unit/test_character_action_verbs.py
git commit -m "feat(bridge): literal-key builder resolver + PushButtons alias"
```

---

### Task 5: A scripted priority band and a default-pose request

Scripted gestures must outrank idle fidgets (`_IDLE = 0`) and hit reactions (`_REACTION = 1`), or `submit`'s equal-or-higher guard (`bridge_character_anim.py:76`) will silently drop them. `AT_BREATHE`/`AT_DEFAULT` need a way to say "drop whatever you're playing and go back to the rest pose".

**Files:**
- Modify: `engine/bridge_character_anim.py:14-16` (priority bands), and add `request_default`
- Test: `tests/unit/test_character_action_verbs.py`

**Interfaces:**
- Produces: `engine.bridge_character_anim._SCRIPTED: int = 2`
- Produces: `BridgeCharacterAnimController.request_default(character) -> None` — cancel any active transient clip and restore the officer's rest pose.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_character_action_verbs.py`:

```python
from engine import bridge_character_anim


def test_scripted_priority_outranks_idle_and_reactions():
    assert bridge_character_anim._SCRIPTED > bridge_character_anim._REACTION
    assert bridge_character_anim._SCRIPTED > bridge_character_anim._IDLE


def test_request_default_clears_the_active_action():
    ctrl = bridge_character_anim.BridgeCharacterAnimController()
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    # submit() keys off the render-instance id and refuses a hidden character
    # (bridge_character_anim.py:70-73), so a bare CharacterClass would be dropped.
    ch._render_instance = 7
    ch.SetHidden(0)
    assert ctrl.submit(ch, [("some/clip.nif", 1.0)],
                       priority=bridge_character_anim._SCRIPTED) is True
    assert ctrl.is_busy(ch) is True
    ctrl.request_default(ch)
    assert ctrl.is_busy(ch) is False
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: FAIL — `_SCRIPTED` does not exist.

- [ ] **Step 3: Add the band and the request**

In `engine/bridge_character_anim.py`, beside the existing bands (line 14-16):

```python
_IDLE = 0
_REACTION = 1
_TURN = 1       # turn-to-captain preempts idle (0); same band as reactions
_SCRIPTED = 2   # AT_PLAY_ANIMATION: a scripted mission beat outranks both —
                # submit() drops an equal-or-lower priority onto a busy officer,
                # and a scripted gesture must never lose to an idle fidget.
```

Add the method on `BridgeCharacterAnimController` (beside `request_glance`). Note `_return_to_default` needs a `renderer`, which only `update()` has — so `request_default` drops the active clip and **queues** the restore, exactly as `request_turn_to` queues into `_pending_turns`:

```python
    def request_default(self, character) -> None:
        """AT_DEFAULT / AT_BREATHE: drop any transient clip and restore the
        officer's rest pose — which IS the breathe idle (capture_breathing feeds
        set_idle). The restore itself needs the renderer, so it is queued for the
        next update() tick, the same way turns and glances are. Never raises."""
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            return
        self._active.pop(iid, None)          # cancel the transient clip
        self._pending_defaults.append(iid)   # restore the rest pose next tick
```

Initialise the queue in `__init__` and clear it in `reset()` beside `_pending_turns` / `_pending_glances`:

```python
        self._pending_defaults = []
```

Drain it at the top of `update()` (`bridge_character_anim.py:134`), beside the existing pending queues:

```python
        if self._pending_defaults:
            pending, self._pending_defaults = self._pending_defaults, []
            for iid in pending:
                self._return_to_default(renderer, iid)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_character_anim.py tests/unit/test_character_action_verbs.py
git commit -m "feat(bridge): scripted animation priority band + request_default"
```

---

### Task 6: `AT_PLAY_ANIMATION` and `AT_PLAY_ANIMATION_FILE`

The big one: **58 SDK sites**, currently a silent no-op that completes instantly. Note a character-node `TGAnimAction` does **not** play (`actions.py:655-657`) — gestures reach the renderer only through `BridgeCharacterAnimController.submit`, exactly as the idle scheduler does (`bridge_idle_gestures.py:99-101`). So we resolve the builder, flatten it to clips, and submit.

BC's mode argument is the `CharacterAction`'s **`flag`** (arg 5). Evidence: `MissionLib.py:3543` passes `("PushingButtons", None, 1)` while the bare handler calls (`EngineerCharacterHandlers.py:531`) default it to `0` — which maps onto the RE doc's §4.3 table: `> 0` ⇒ `CAT_INTERRUPTABLE`, `== 0` ⇒ `CAT_NON_INTERRUPTABLE`.

**Files:**
- Modify: `engine/appc/ai.py:1386-1432` (`Play`), add `_queue_play_animation`
- Test: `tests/unit/test_character_action_verbs.py`

**Interfaces:**
- Consumes: `bridge_placement.registered_module_path`, `bridge_idle_gestures.build_sequence_clips`, `bridge_character_anim.get_controller().submit`, `CharacterClass.set_current_animation` / `clear_current_animation`, `bridge_character_anim._SCRIPTED`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_character_action_verbs.py`:

```python
from engine.appc.ai import CharacterAction


class _FakeController:
    def __init__(self, accept=True):
        self.accept = accept
        self.submitted = []

    def is_busy(self, character):
        return False

    def submit(self, character, clips, priority, hold=False, on_complete=None):
        self.submitted.append((character, list(clips), priority, on_complete))
        return self.accept

    def request_default(self, character):
        self.submitted.append((character, "DEFAULT", None, None))


def test_play_animation_submits_the_registered_gesture(monkeypatch):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("clip.nif", 1.0)])

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "PushingButtons")
    action.Play()

    assert len(ctrl.submitted) == 1
    _c, clips, priority, _cb = ctrl.submitted[0]
    assert clips == [("clip.nif", 1.0)]
    assert priority == bridge_character_anim._SCRIPTED
    # flag defaults to 0 => BC's non-interruptable mode => the SDK gate closes
    assert ch.IsAnimatingNonInterruptable() == 1


def test_play_animation_flag_1_is_interruptable(monkeypatch):
    # MissionLib.py:3543 passes flag=1 explicitly.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("clip.nif", 1.0)])

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION,
                             "PushingButtons", None, 1)
    action.Play()
    assert ch.IsAnimatingInterruptable() == 1
    assert ch.IsAnimatingNonInterruptable() == 0


def test_play_animation_unregistered_key_completes_immediately(monkeypatch):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "Nonexistent")
    action.Play()

    assert ctrl.submitted == []          # nothing submitted
    assert action.IsPlaying() == 0       # completed inline — never stalls a sequence
    assert ch.IsAnimating() == 0         # and left no state behind
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: FAIL — nothing is submitted; `AT_PLAY_ANIMATION` falls through to the instant-complete path.

- [ ] **Step 3: Add the branch to `Play()`**

In `engine/appc/ai.py`, in `CharacterAction.Play()`, insert **before** the final `dur = self._do_play()` fall-through:

```python
        if at in (self.AT_PLAY_ANIMATION, self.AT_PLAY_ANIMATION_FILE):
            self._queue_play_animation(from_file=(at == self.AT_PLAY_ANIMATION_FILE))
            return
```

- [ ] **Step 4: Implement `_queue_play_animation`**

Add the method to `CharacterAction` (beside `_queue_glance`):

```python
    def _queue_play_animation(self, *, from_file: bool) -> None:
        """AT_PLAY_ANIMATION / AT_PLAY_ANIMATION_FILE — BC's scripted gesture.

        The key is LITERAL (no location prefix): "PushingButtons", registered by
        every officer. The registered value is a dotted PYTHON PATH; calling it
        returns a TGSequence, which we flatten to clips and hand to the character
        anim controller — a character-node TGAnimAction does not play by itself
        (actions.py:655), gestures reach the renderer only via the controller.

        Interruptability comes from the action's `flag` (BC's PlayAnimation mode
        arg): flag > 0 => CAT_INTERRUPTABLE; flag == 0 => CAT_NON_INTERRUPTABLE.
        Evidence: MissionLib.py:3543 passes flag=1; the bare handler call sites
        (EngineerCharacterHandlers.py:531 et al) leave it 0. BC's mode 0 also
        disables the UI for the duration — that interlock needs the CS_ flag
        rework and is deliberately not implemented here.

        Best-effort: any failure or unresolved key completes inline so a mission
        TGSequence can never stall on a gesture.
        """
        from engine.appc.characters import CharacterClass, CharacterClass_Cast
        from engine import bridge_character_anim
        from engine.bridge_idle_gestures import build_sequence_clips
        from engine.appc import bridge_placement
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is None or ctrl is None or self._detail is None:
                self.Completed()
                return

            if from_file:
                # BC's escape hatch: a raw NIF name, no registry lookup.
                clips = [(str(self._detail), 0.0)]
            else:
                module_path = bridge_placement.registered_module_path(cc, self._detail)
                if not module_path:
                    self.Completed()   # unregistered key (BC no-ops here too)
                    return
                import App
                clips = build_sequence_clips(module_path, cc, App.g_kAnimationManager)
            if not clips:
                self.Completed()
                return

            category = (CharacterClass.CAT_INTERRUPTABLE if self._flag > 0
                        else CharacterClass.CAT_NON_INTERRUPTABLE)
            cc.set_current_animation(str(self._detail), category)

            def _done():
                cc.clear_current_animation()
                self.Completed()

            if not ctrl.submit(cc, clips,
                               priority=bridge_character_anim._SCRIPTED,
                               on_complete=_done):
                _done()                # dropped by the priority guard
        except Exception:
            try:
                if cc is not None:
                    cc.clear_current_animation()
            except Exception:
                pass
            self.Completed()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_verbs.py
git commit -m "feat(characters): implement AT_PLAY_ANIMATION and AT_PLAY_ANIMATION_FILE"
```

---

### Task 7: `AT_BREATHE`, `AT_FORCE_BREATHE`, `AT_DEFAULT`

27 SDK sites, all silent no-ops. All three mean "stop the transient clip and go back to the resting/breathing pose" — and the controller's own docstring already names `restore_rest_pose` as *"the SDK's AT_DEFAULT"*. The rest pose **is** the breathe idle (`capture_breathing` feeds `set_idle`), so all three route to `request_default`.

**Files:**
- Modify: `engine/appc/ai.py` (`Play`), add `_queue_default`
- Test: `tests/unit/test_character_action_verbs.py`

**Interfaces:**
- Consumes: `BridgeCharacterAnimController.request_default` (Task 5), `CharacterClass.clear_current_animation` (Task 3)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_character_action_verbs.py`:

```python
import pytest


@pytest.mark.parametrize("verb", [
    CharacterAction.AT_DEFAULT,
    CharacterAction.AT_BREATHE,
    CharacterAction.AT_FORCE_BREATHE,
])
def test_default_and_breathe_restore_the_rest_pose(monkeypatch, verb):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.set_current_animation("PushingButtons", CharacterClass.CAT_NON_INTERRUPTABLE)
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, verb)
    action.Play()

    assert ctrl.submitted == [(ch, "DEFAULT", None, None)]
    assert action.IsPlaying() == 0          # completes inline
    assert ch.IsAnimating() == 0            # gate reopens
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: FAIL — nothing reaches the controller; the verbs fall through to instant-complete.

- [ ] **Step 3: Add the branch**

In `CharacterAction.Play()`, before the `dur = self._do_play()` fall-through:

```python
        if at in (self.AT_DEFAULT, self.AT_BREATHE, self.AT_FORCE_BREATHE):
            self._queue_default()
            return
```

- [ ] **Step 4: Implement `_queue_default`**

```python
    def _queue_default(self) -> None:
        """AT_DEFAULT / AT_BREATHE / AT_FORCE_BREATHE — return the officer to rest.

        The rest pose IS the breathe idle (bridge_placement.capture_breathing feeds
        BridgeCharacterAnimController.set_idle), which is why all three verbs land
        here: BC's AT_DEFAULT restores the default pose, and an officer at rest is
        an officer breathing. Completes INLINE — restoring a pose is instant, and
        sequences supply their own delays.
        """
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is not None:
                cc.clear_current_animation()
                if ctrl is not None:
                    ctrl.request_default(cc)
        except Exception:
            pass
        self.Completed()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_verbs.py
git commit -m "feat(characters): implement AT_DEFAULT, AT_BREATHE, AT_FORCE_BREATHE"
```

---

### Task 8: `AT_SAY_LINE` — honour `turnTo` / `turnBack`

**3977 SDK sites.** The single highest-leverage change in the plan. `CharacterAction_Create(pKiska, AT_SAY_LINE, "IncomingMsg6", "Captain", 1, pDatabase)` means *turn to the captain, speak, turn back* — with the chair swivelling under her. Args 4 and 5 land in `self._set_name` and `self._flag` and are **never read** today.

`_queue_turn` already does the turn (and the chair, via the SDK's builder). We reuse it: turn → speak → turn back.

**Files:**
- Modify: `engine/appc/ai.py` (`Play`), add `_queue_say_line`
- Test: `tests/unit/test_character_action_verbs.py`

**Interfaces:**
- Consumes: `BridgeCharacterAnimController.request_turn_to(character, detail, *, back, now, on_complete)`, `CharacterAction._do_play()` (the existing speak path), `CharacterAction._complete_after(dur)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_character_action_verbs.py`:

```python
class _TurnRecordingController(_FakeController):
    def __init__(self):
        super().__init__()
        self.turns = []

    def request_turn_to(self, character, detail, *, back=False, now=False,
                        hold=True, on_complete=None):
        self.turns.append(("back" if back else "to", detail))
        if on_complete is not None:
            on_complete()          # settle immediately, so the test is synchronous


def test_say_line_turns_to_the_captain_and_back(monkeypatch):
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", "Captain", 1)
    action.Play()

    assert ctrl.turns == [("to", "Captain"), ("back", "Captain")]
    assert spoken == ["IncomingMsg6"]


def test_say_line_without_a_turn_target_just_speaks(monkeypatch):
    # (None, 0) — speaks with no turn at all. The regression guard.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", None, 0)
    action.Play()

    assert ctrl.turns == []
    assert spoken == ["IncomingMsg6"]


def test_say_line_turns_to_but_does_not_turn_back(monkeypatch):
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr(CharacterAction, "_do_play", lambda self: 1.5)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", "Captain", 0)
    action.Play()

    assert ctrl.turns == [("to", "Captain")]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: FAIL — `ctrl.turns == []`; the turn args are ignored.

- [ ] **Step 3: Add the branch**

In `CharacterAction.Play()`, before the `dur = self._do_play()` fall-through:

```python
        if at in (self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
            self._queue_say_line()
            return
```

Leave `AT_SPEAK_LINE` / `AT_SPEAK_LINE_NO_FLAP_LIPS` on the existing fall-through — those never turn.

- [ ] **Step 4: Implement `_queue_say_line`**

```python
    def _queue_say_line(self) -> None:
        """AT_SAY_LINE / AT_SAY_LINE_AFTER_TURN — the SDK's workhorse (3977 sites).

        Args 4 and 5 are turnTo / turnBack: ("Captain", 1) means turn to the
        captain, speak, and turn back — with the chair swivelling under the
        officer, because the SDK's turn builder animates the body clip and the
        chair clip as parallel siblings of one sequence. (None, 0) speaks with no
        turn at all.

        The line still BLOCKS the sequence for its real duration (BC does), via
        the existing _do_play/_complete_after path.
        """
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim

        turn_to = self._set_name
        turn_back = self._flag > 0

        def _speak_then_turn_back():
            dur = 0.0
            try:
                dur = self._do_play() or 0.0
            except Exception:
                dur = 0.0
            if not (turn_to and turn_back):
                self._complete_after(dur)
                return
            # Turn back once the line has finished, then complete.
            def _turn_back_now():
                try:
                    cc = CharacterClass_Cast(self._character)
                    ctrl = bridge_character_anim.get_controller()
                    if cc is not None and ctrl is not None:
                        ctrl.request_turn_to(cc, str(turn_to), back=True, now=False,
                                             on_complete=self.Completed)
                        return
                except Exception:
                    pass
                self.Completed()
            self._complete_after(dur, on_elapsed=_turn_back_now)

        if not turn_to:
            _speak_then_turn_back()
            return
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is None or ctrl is None:
                _speak_then_turn_back()      # headless: speak without turning
                return
            ctrl.request_turn_to(cc, str(turn_to), back=False, now=False,
                                 on_complete=_speak_then_turn_back)
        except Exception:
            _speak_then_turn_back()
```

> **Implementer note — `_complete_after` needs an `on_elapsed` hook.** `TGAction._complete_after(dur)` currently schedules `self.Completed()` after `dur` (`actions.py:67-83`). Add an optional `on_elapsed=None` parameter: when supplied, it is called **instead of** `Completed()` when the timer fires (the callback becomes responsible for completing). Do not change the existing default behaviour, and do not duplicate the timer logic — one scheduler, one code path.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_character_action_verbs.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite — `_complete_after` is shared by every speak action**

Run: `uv run pytest -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ai.py engine/appc/actions.py tests/unit/test_character_action_verbs.py
git commit -m "feat(characters): AT_SAY_LINE honours turnTo/turnBack"
```

---

### Task 9: Full gate, then live verification

Unit tests cannot see the thing this plan exists for: an officer actually using his console. Verify it in the running game.

**Files:** none modified (fix-forward only if the gate is red).

- [ ] **Step 1: Run the machine-checked gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. It builds C++, runs pytest + ctest, and diffs every failure against `tests/known_failures.txt` (whose only entries are the 7 headless-GL scorch/heat-glow `FrameTest`s). **Any failure it names that is not in that list is a regression this branch introduced — never call one "pre-existing" by eyeball.**

- [ ] **Step 2: Live-verify the gesture**

Run: `./build/dauntless --developer`

Load a mission with a bridge, then give an order that routes through a bridge handler — a sensor scan (Science), a repair (Engineer), or a course change (Helm). Each of those handlers ends in `AT_PLAY_ANIMATION "PushingButtons"` (`ScienceCharacterHandlers.py:407`, `EngineerCharacterHandlers.py:531`, `HelmMenuHandlers.py`).

Expected: **the officer reaches out and works the console.** Before this branch he sat motionless.

- [ ] **Step 3: Live-verify the turn**

Watch any scripted dialogue beat (E1M1's opening is dense with them).

Expected: the speaking officer **turns to face the captain, delivers the line, and turns back**, with the chair swivelling under a seated officer. Before this branch the bridge was frozen through every line.

- [ ] **Step 4: Sanity-check the gates**

Expected: officers do **not** fidget mid-sentence, and a second gesture does not stomp one already playing. **Some scenes will look calmer than before — that is the gates working as BC intended, not a regression.**

- [ ] **Step 5: Confirm the heatmap can now see `CharacterClass`**

Run: `uv run python tools/stub_heatmap.py` after a `--developer` session.
Expected: `docs/stub_heatmap.md` now contains `CharacterClass` rows (`SetLookAtAdj`, `SetBlinkChance`, `SetRandomAnimationChance`, …) — the gaps this plan deliberately leaves for the follow-on specs are now *visible* instead of silently absorbed.

- [ ] **Step 6: Commit any heatmap regeneration**

```bash
git add docs/stub_heatmap.md
git commit -m "chore(stubs): regenerate heatmap with CharacterClass rows"
```

---

## Deliberately out of scope

Each is its own spec; do not let them creep into this branch.

- **Speech architecture** — per-character queues, reject-if-busy for `CSP_SPONTANEOUS`, deleting the global cross-character arbiter, the inverted `CSP_*` constants. (Task 2 gives `IsSpeaking` a correct *contract* against the bus we have; it does not fix the bus.)
- **`AT_SPEAK_LINE_NO_FLAP_LIPS` flapping the lips anyway** (29 sites) — belongs with the speech spec.
- **Bridge damage feedback** — `bridgeeffects` unwired; seated officers get no hit clip; the guest chair never moves.
- **Animation layering on skinned characters** — one clip slot in C++; a gesture cannot layer over a sit.
- **`CS_` as a real bitfield**, BC's write-only `CS_HIDDEN`/`CS_VISIBLE` cull commands, and the UI interlock (a non-interruptable animation disabling the UI while it plays). Task 6 records the category; the interlock needs the `CS_` rework.
- Idle-gesture weights and `SetRandomAnimationChance` (extras currently fidget as often as officers), head look-at, blink chance, the officer-picking dot-product contest, the low-detail gate.

# E1M1 "Press 's' to skip introduction" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make E1M1's opening-cutscene skip prompt appear and function — the banner "Press 's' to skip introduction" and the `s` key that aborts the character intros and jumps straight to the undock cutscene.

**Architecture:** BC's mechanism is entirely SDK-side ([E1M1.py:1950-1972](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L1950-L1972) and [E1M1.py:1761-1779](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L1761-L1779)). Nothing about the feature needs new design — it needs five pieces of missing Appc surface. Four are small, self-contained additions to `engine/appc/`; the fifth is a raw-keyboard dispatch path from `TGInputManager` down BC's window chain, which is the only structural change and which unblocks any SDK script that hooks `App.ET_KEYBOARD` (not just this one).

**Tech Stack:** Python 3.11, pytest. No C++ / renderer changes — no `cmake` rebuild is required by any task in this plan.

**Spec:** No separate spec document. The root-cause trace that produced this plan is reproduced verbatim in "Background: the five breaks" below; that section is the spec. Executors should read it before Task 1.

---

## Global Constraints

- **Shared checkout — NEVER run destructive git.** Banned: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, `cp` it to `/tmp`, mutate, restore by `cp`, and `diff` to prove the restore.
- **Test gate is `scripts/check_tests.sh`**, not `scripts/run_tests.sh` (which is pytest-only and cannot see C++ regressions). Run the gate before the final commit. Never call a failure "pre-existing" by eyeball — `cat tests/known_failures.txt`.
- **Never grep `def <Name>(` to decide whether Appc surface exists.** SWIG binds most of the surface at module level; that grep can never match and has produced ~10 false gaps historically.
- **Do not modify anything under `sdk/`.** The SDK is ground truth. Every fix in this plan lands in `engine/`, `App.py`, or `tests/`.
- **Event-type constants must be real `int`s.** An `ET_*` name absent from `App.py` resolves to a `_NamedStub` whose `__hash__` is `id(self)` and which is *not* memoized — every access mints a fresh dict key, so a handler registered under it is unreachable forever. See [events.py:329-346](../../../engine/appc/events.py#L329-L346).
- **Game units:** not touched by this plan, but if you add any spatial variable, name it `*_gu` / `*_gups`. 1 GU = 175 m.

---

## Background: the five breaks

The SDK code, in execution order.

`CrewIntros` ([E1M1.py:1950-1972](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L1950-L1972)):

```python
if (App.g_kVarManager.GetFloatVariable ("global", "PlayedTutorial") == 1.0):
    pTop = App.TopWindow_GetTopWindow()
    pSubtitle = pTop.FindMainWindow(App.MWT_SUBTITLE)
    pSubtitle.SetVisible()
    pFontGroup = App.g_kFontManager.GetDefaultFont ()
    fFontSize = pFontGroup.GetFontSize ()
    pTextBanner = App.TGCreditAction_Create(g_pMissionDatabase.GetString("CutsceneTextBar"), pSubtitle,
                        0, 0.05, 10, 0.25, 0.5, fFontSize, App.TGCreditAction.JUSTIFY_CENTER, App.TGCreditAction.JUSTIFY_TOP)
    global g_idTextBanner
    g_idTextBanner = pTextBanner.GetObjID()
    pTextBanner.Play()
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD, __name__ + ".SkipOpeningSequence")
```

`SkipOpeningSequence` ([E1M1.py:1761-1779](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L1761-L1779)):

```python
def SkipOpeningSequence(TGObject, pEvent):
    iUnicode = pEvent.GetUnicode()
    kDisplayString = App.g_kInputManager.GetDisplayStringFromUnicode(iUnicode)
    kSkipKey = g_pMissionDatabase.GetString("SkipKey")
    if (kDisplayString.GetCString() == kSkipKey.GetCString()):
        App.TGActionManager_KillActions("CharacterIntros")
        UndockCutscene(TRUE)
        pTextBannerAction = App.TGAction_Cast(App.TGObject_GetTGObjectPtr(g_idTextBanner))
        if (pTextBannerAction != None):
            pTextBannerAction.Completed()
    TGObject.CallNextHandler(pEvent)
```

The TGL data is present and correct — verified by loading it:

```
data/TGL/Maelstrom/Episode 1/E1M1.TGL    SkipKey         -> 's'
data/TGL/Maelstrom/Episode 1/E1M1.TGL    CutsceneTextBar -> "Press 's' to skip introduction"
data/TGL/Keyboard Mapping.tgl            s               -> 's'
```

`TGCreditAction` is implemented ([actions.py:860](../../../engine/appc/actions.py#L860)). `KeyConfig.MapScancodes()` already runs at boot ([host_loop.py:275-276](../../../engine/host_loop.py#L275-L276)) and registers `WC_S (0x53) → (KY_S, <Keyboard Mapping.tgl>, "s")` via [UKConfig.py:70](../../../sdk/Build/scripts/UKConfig.py#L70). So the data and the banner half are fine. What is broken:

| # | Break | Evidence |
|---|---|---|
| 1 | `pEvent.GetUnicode()` — our `TGKeyboardEvent` only has `GetUnicodeKey`. `GetUnicode` falls through `TGObject.__getattr__` to a `_Stub`. | `sdk/Build/scripts/App.py:1062` binds `TGKeyboardEvent.GetUnicode`; `grep -rn "def GetUnicode" engine/` returns nothing |
| 2 | `App.ET_KEYBOARD` is undefined → `<App._NamedStub 'ET_KEYBOARD'>` → fresh hash key per access → the handler is permanently unreachable. | `sdk/Build/scripts/App.py:13224` defines it; probing our `App` returns the stub |
| 3 | Nothing routes raw keystrokes to `g_kRootWindow`. Our pipeline is `TGInputManager` → `ET_KEYBOARD_EVENT` (0x1000) broadcast → `KeyboardBinding` only. | [input.py:310-322](../../../engine/appc/input.py#L310-L322) |
| 4 | `TGInputManager.GetDisplayStringFromUnicode` is unimplemented → `_Stub`; `.GetCString()` → another `_Stub`; `== 's'` is False. | rank 57 in [docs/stub_heatmap.md](../../stub_heatmap.md), **342 live hits** |
| 5 | `App.TGActionManager_KillActions` is undefined → `_NamedStub` → silent no-op, so the intro sequence keeps playing underneath the undock cutscene. | `sdk/Build/scripts/App.py:10105` defines it; absent from our `App.py` |

Plus the gate: `PlayedTutorial` is set by `SaveTheGame` ([E1M1.py:2659](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L2659)) at the *end* of the opening, so BC's prompt is replay-only. Our `TGVarManager` is in-memory and only round-trips through savegames ([save_load.py:181](../../../engine/appc/save_load.py#L181)), so a cold-launched E1M1 always reads 0.0 and the whole block is skipped.

**Decisions taken (from the scoping conversation):**
- The `PlayedTutorial` gate gets a **`--developer`-gated force only, for now**. Real persistence is deferred until persistent-save support lands. Task 5 includes the follow-up note.
- The keyboard fix is the **general** raw-keyboard dispatch (Task 2), not a root-window-only special case and not a Dauntless-side keybinding that forks E1M1 away from the script.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `engine/appc/events.py` | Add `GetUnicode`/`SetUnicode` to `TGKeyboardEvent`; declare the `ET_KEYBOARD` constant | 1, 2 |
| `App.py` | Re-export `ET_KEYBOARD` and `TGActionManager_KillActions` | 2, 4 |
| `engine/appc/input.py` | `_raw_keyboard_destination()` + `TGInputManager._dispatch_raw_keyboard`; `GetDisplayStringFromUnicode` | 2, 3 |
| `engine/appc/actions.py` | `TGActionManager.KillActions` + name→list registry; module-level `TGActionManager_KillActions` | 4 |
| `engine/dev_tutorial_flag.py` (new) | Dev-only `PlayedTutorial` force — mirrors the `dev_combat_cheats.py` seam pattern | 5 |
| `engine/host_loop.py` | Call the dev force at the end of `reset_sdk_globals()` | 5 |
| `tests/unit/test_keyboard_event_unicode.py` (new) | `GetUnicode`/`SetUnicode` alias behaviour | 1 |
| `tests/unit/test_raw_keyboard_dispatch.py` (new) | Raw `ET_KEYBOARD` delivery down the window chain | 2 |
| `tests/unit/test_tg_input_manager.py` | `GetDisplayStringFromUnicode` cases | 3 |
| `tests/unit/test_actions.py` | `KillActions` cases | 4 |
| `tests/unit/test_dev_tutorial_flag.py` (new) | Dev-gating of the `PlayedTutorial` force | 5 |
| `tests/missions/test_e1m1_skip_intro.py` (new) | End-to-end: the SDK's own `SkipOpeningSequence` fires from a simulated `s` press | 6 |
| `docs/engine/e1m1-skip-intro.md` (new) | Feature note + the deferred-persistence follow-up | 5, 6 |

---

### Task 1: `TGKeyboardEvent.GetUnicode` / `SetUnicode`

BC's published accessor pair is `GetUnicode`/`SetUnicode` (`sdk/Build/scripts/App.py:1062-1063`). Our class named them `GetUnicodeKey`/`SetUnicodeKey`. Both names must work: our own engine code and tests call the `*Key` forms in many places, and SDK scripts call the bare forms.

**Files:**
- Modify: `engine/appc/events.py:178-205` (class `TGKeyboardEvent`)
- Test: `tests/unit/test_keyboard_event_unicode.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TGKeyboardEvent.GetUnicode() -> int` and `TGKeyboardEvent.SetUnicode(k) -> None`, exact aliases of the existing `GetUnicodeKey`/`SetUnicodeKey`. Task 2's test and Task 6 rely on `GetUnicode`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_keyboard_event_unicode.py`:

```python
"""TGKeyboardEvent exposes BC's published GetUnicode/SetUnicode names.

sdk/Build/scripts/App.py:1062-1063 binds TGKeyboardEvent.GetUnicode and
SetUnicode. E1M1.SkipOpeningSequence calls pEvent.GetUnicode(); without the
alias it falls through TGObject.__getattr__ to a truthy _Stub and the skip-key
comparison can never match.
"""
from engine.appc.events import TGKeyboardEvent


def test_get_unicode_returns_the_key_code():
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(0x53)
    assert evt.GetUnicode() == 0x53


def test_set_unicode_writes_the_same_slot_as_set_unicode_key():
    evt = TGKeyboardEvent()
    evt.SetUnicode(0x41)
    assert evt.GetUnicodeKey() == 0x41
    assert evt.GetUnicode() == 0x41


def test_get_unicode_is_an_int_not_a_stub():
    evt = TGKeyboardEvent()
    evt.SetUnicode(0x53)
    assert isinstance(evt.GetUnicode(), int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_keyboard_event_unicode.py -v`
Expected: FAIL. `test_get_unicode_returns_the_key_code` fails on the assert because `GetUnicode()` returns a `_Stub`, not `0x53`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/events.py`, inside `class TGKeyboardEvent`, immediately after `GetUnicodeKey` (around line 198), add:

```python
    # BC's published names (sdk/Build/scripts/App.py:1062-1063). SDK scripts
    # call the bare forms (E1M1.SkipOpeningSequence, CinematicInterfaceHandlers
    # .HandleKeyboard); our own engine code and tests use the *Key forms. Both
    # must resolve or one side silently gets a _Stub.
    def SetUnicode(self, k) -> None:
        self.SetUnicodeKey(k)

    def GetUnicode(self) -> int:
        return self.GetUnicodeKey()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_keyboard_event_unicode.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/events.py tests/unit/test_keyboard_event_unicode.py
git commit -m "feat(input): add BC's TGKeyboardEvent.GetUnicode/SetUnicode aliases"
```

---

### Task 2: `ET_KEYBOARD` + raw keyboard dispatch down the window chain

BC delivers every keystroke to the window chain as a raw `ET_KEYBOARD` event, which is what `AddPythonFuncHandlerForInstance(App.ET_KEYBOARD, ...)` hooks. We only ever produced the internal `ET_KEYBOARD_EVENT` broadcast consumed by `KeyboardBinding`. This task adds the raw path.

Two design points, both deliberate:

1. **The dispatch keeps the existing `_registered_codes` gate.** `_emit` already returns early for keys `KeyConfig.MapScancodes()` never registered; the raw path inherits that. `WC_S` *is* registered, so E1M1 is covered, and the gate keeps the blast radius on the input pipeline small.
2. **The raw event is posted for every key state `_emit` handles** (`KS_KEYDOWN`, `KS_KEYUP`, `KS_NORMAL`) — BC delivers all three to windows, which is why `CinematicInterfaceHandlers.HandleKeyboard` inspects `GetKeyState()`. E1M1's handler doesn't check state, but `UndockCutscene` calls `RemoveSkipHandler()` ([E1M1.py:2513](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L2513)) before the key-up arrives, so it cannot double-fire.

**Files:**
- Modify: `engine/appc/events.py` (constant block near line 9-11)
- Modify: `App.py:6` (the `engine.appc.events` import block)
- Modify: `engine/appc/input.py` (`TGInputManager._emit` around line 168, plus a new module-level helper)
- Test: `tests/unit/test_raw_keyboard_dispatch.py` (create)

**Interfaces:**
- Consumes: `TGKeyboardEvent.GetUnicode` (Task 1).
- Produces:
  - `engine.appc.events.ET_KEYBOARD: int` — value `0x1001`, re-exported as `App.ET_KEYBOARD`.
  - `engine.appc.input._raw_keyboard_destination() -> TGEventHandlerObject | None` — first object in the window chain carrying an `ET_KEYBOARD` instance handler.
  - `TGInputManager._dispatch_raw_keyboard(wc_code: int, key_state: int) -> None`.
  - Task 6's integration test relies on a handler registered on `App.g_kRootWindow` for `App.ET_KEYBOARD` receiving a `TGKeyboardEvent` when `App.g_kInputManager.OnKeyDown(WC_S)` is called.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_raw_keyboard_dispatch.py`:

```python
"""TGInputManager posts BC's raw ET_KEYBOARD event down the window chain.

BC delivers every keystroke to the window chain as ET_KEYBOARD; SDK scripts
hook it with g_kRootWindow.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD,
...)  (E1M1.CrewIntros:1971). Our pipeline previously produced only the
internal ET_KEYBOARD_EVENT broadcast consumed by KeyboardBinding, so every
such handler was dead.
"""
import sys
import types

import App
from engine.appc.events import TGEventManager, TGEventHandlerObject
from engine.appc.input import (
    TGInputManager, _raw_keyboard_destination,
    WC_S, KY_S, KS_KEYDOWN, KS_KEYUP,
)

_HELPER = "_test_raw_keyboard_dispatch_helper"


def _capture_module():
    """Register a module exposing capture(obj, evt) -> appends to .captured."""
    mod = types.ModuleType(_HELPER)
    mod.captured = []
    mod.capture = lambda _obj, evt: mod.captured.append(evt)
    sys.modules[_HELPER] = mod
    return mod


def _root_with_handler(mod):
    """Register the capture handler on the real g_kRootWindow, return it."""
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(
        App.ET_KEYBOARD, _HELPER + ".capture")
    return App.g_kRootWindow


def _remove(root):
    root.RemoveHandlerForInstance(App.ET_KEYBOARD, _HELPER + ".capture")


def test_et_keyboard_is_a_real_int():
    # A _NamedStub here makes every registration unreachable: _Stub.__hash__
    # is id(self) and ET_* names are not memoized, so each access is a new key.
    assert isinstance(App.ET_KEYBOARD, int)
    assert App.ET_KEYBOARD != App.ET_KEYBOARD_EVENT


def test_keydown_reaches_a_root_window_et_keyboard_handler():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        em = TGEventManager()
        im = TGInputManager(em)
        im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
        im.OnKeyDown(WC_S)
        assert len(mod.captured) == 1
        evt = mod.captured[0]
        assert evt.GetUnicode() == WC_S
        assert evt.GetKeyState() == KS_KEYDOWN
        assert evt.GetEventType() == App.ET_KEYBOARD
    finally:
        _remove(root)


def test_keyup_also_reaches_the_handler():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        em = TGEventManager()
        im = TGInputManager(em)
        im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
        im.OnKeyUp(WC_S)
        assert [e.GetKeyState() for e in mod.captured] == [KS_KEYUP]
    finally:
        _remove(root)


def test_unregistered_key_does_not_dispatch():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        em = TGEventManager()
        im = TGInputManager(em)
        # WC_S deliberately NOT registered on this manager.
        im.OnKeyDown(WC_S)
        assert mod.captured == []
    finally:
        _remove(root)


def test_no_destination_when_nothing_registered_a_handler():
    # With no ET_KEYBOARD handler anywhere, the helper returns None and _emit
    # must not post a raw event (and must not raise).
    assert _raw_keyboard_destination() is None
    em = TGEventManager()
    im = TGInputManager(em)
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    im.OnKeyDown(WC_S)  # no exception


def test_internal_keyboard_event_broadcast_still_fires():
    # Regression guard: the raw path is additive, not a replacement.
    from engine.appc.events import ET_KEYBOARD_EVENT
    mod = types.ModuleType(_HELPER + "_bcast")
    mod.captured = []
    mod.capture = lambda _obj, evt: mod.captured.append(evt)
    sys.modules[_HELPER + "_bcast"] = mod
    em = TGEventManager()
    im = TGInputManager(em)
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, _HELPER + "_bcast.capture")
    im.OnKeyDown(WC_S)
    assert len(mod.captured) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_raw_keyboard_dispatch.py -v`
Expected: FAIL. `test_et_keyboard_is_a_real_int` fails the isinstance assert (`App.ET_KEYBOARD` is `<App._NamedStub 'ET_KEYBOARD'>`); the import of `_raw_keyboard_destination` fails with `ImportError`.

- [ ] **Step 3a: Declare the constant**

In `engine/appc/events.py`, in the constant block after `ET_KEYBOARD_EVENT` (line 9), add:

```python
# BC's raw per-key window event (sdk/Build/scripts/App.py:13224). Distinct from
# ET_KEYBOARD_EVENT above: that one is our internal broadcast into
# KeyboardBinding; this one is what BC delivers down the window chain and what
# SDK scripts hook via AddPythonFuncHandlerForInstance (E1M1.CrewIntros:1971,
# E1M1.RemoveSkipHandler:2479).
ET_KEYBOARD: int = 0x1001
```

- [ ] **Step 3b: Re-export it from `App.py`**

In `App.py`, extend the `engine.appc.events` import at line 6:

```python
    TGKeyboardEvent, ET_KEYBOARD_EVENT, ET_KEYBOARD,
```

- [ ] **Step 3c: Add the dispatch helper and wire it into `_emit`**

In `engine/appc/input.py`, add this module-level function immediately *above* `class TGInputManager` (before line 116):

```python
def _raw_keyboard_destination():
    """First object in BC's window chain with an ET_KEYBOARD instance handler.

    BC bubbles a raw keyboard event up the window chain; our ProcessEvent
    dispatches on exactly one object, so we pick the first candidate that
    actually registered a handler. Order mirrors BC: the root window (where
    mission scripts hook — E1M1.CrewIntros:1971) before the TopWindow.

    Returns None when nothing registered, which is the common case; callers
    must treat that as "post nothing".
    """
    import App  # deferred: input is imported during App bootstrap
    et = App.ET_KEYBOARD
    if not isinstance(et, int):
        # Defensive: a regressed export would make every registration a fresh
        # unreachable key. Post nothing rather than pretend to dispatch.
        return None
    candidates = []
    root = getattr(App, "g_kRootWindow", None)
    if root is not None:
        candidates.append(root)
    top = App.TopWindow_GetTopWindow()
    if top is not None:
        # _TopWindow keeps its handler chain by COMPOSITION on `_events`
        # rather than inheriting one; route through it so both the probe
        # below and AddEvent's destination check land on the same object.
        # (Same reasoning as KeyboardBinding._resolve_destination.)
        events_obj = getattr(top, "_events", None)
        candidates.append(events_obj if events_obj is not None else top)
    for cand in candidates:
        handlers = getattr(cand, "_handlers", None)
        if isinstance(handlers, dict) and handlers.get(et):
            return cand
    return None
```

Then, inside `class TGInputManager`, replace `_emit` (currently at line ~168) with:

```python
    def _emit(self, wc_code: int, key_state: int) -> None:
        if wc_code not in self._registered_codes:
            return
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc_code)
        evt.SetKeyState(key_state)
        self._event_manager.AddEvent(evt)
        self._dispatch_raw_keyboard(wc_code, key_state)

    def _dispatch_raw_keyboard(self, wc_code: int, key_state: int) -> None:
        """Post BC's raw ET_KEYBOARD event to the window chain.

        Additive to the ET_KEYBOARD_EVENT broadcast above, not a replacement:
        KeyboardBinding still translates bound keys into ET_INPUT_* events.
        Gated by _registered_codes via the caller, so unmapped keys stay
        silent. All three key states are posted — BC delivers down, up and
        character events to windows, which is why
        CinematicInterfaceHandlers.HandleKeyboard inspects GetKeyState().
        """
        dest = _raw_keyboard_destination()
        if dest is None:
            return
        import App
        raw = TGKeyboardEvent()
        raw.SetUnicodeKey(wc_code)
        raw.SetKeyState(key_state)
        raw.SetEventType(App.ET_KEYBOARD)
        raw.SetDestination(dest)
        self._event_manager.AddEvent(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_raw_keyboard_dispatch.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the neighbouring input suites for regressions**

Run: `uv run pytest tests/unit/test_tg_input_manager.py tests/unit/test_keyboard_binding.py tests/unit/test_fire_key_input_chain.py tests/unit/test_fkey_input_chain.py tests/unit/test_input_event_constants.py tests/unit/test_keyboard_constant_table.py -v`
Expected: all pass. If a test fails because it now sees a second event, the raw path is leaking into a broadcast handler — check that `SetDestination` is set before `AddEvent`.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/events.py engine/appc/input.py App.py tests/unit/test_raw_keyboard_dispatch.py
git commit -m "feat(input): dispatch BC's raw ET_KEYBOARD event down the window chain"
```

---

### Task 3: `TGInputManager.GetDisplayStringFromUnicode`

Rank 57 in the stub heatmap with 342 live hits. `RegisterUnicodeKey(wc, ky, pDatabase, name)` already stores everything needed: the 4th argument *is* the display name and the 3rd is the TGL database to localize it through ([UKConfig.py:13-70](../../../sdk/Build/scripts/UKConfig.py#L13-L70)). UKConfig's own comment states the fallback: *"If pDatabase fails to load, it will manage by creating a string from the input character."*

Beyond the skip prompt this also fixes E1M1's tactical-view help text, which builds its "press W/S/A/D" lines from six `GetDisplayStringFromUnicode` calls ([E1M1.py:3324-3339](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L3324-L3339)).

**Files:**
- Modify: `engine/appc/input.py` (class `TGInputManager`, after `RegisterUnicodeKey`)
- Test: `tests/unit/test_tg_input_manager.py` (append)

**Interfaces:**
- Consumes: `TGInputManager._registered` (existing), `engine.appc.localization._TGString` (existing).
- Produces: `TGInputManager.GetDisplayStringFromUnicode(wc_code) -> _TGString`. Callers use `.GetCString()` on the result, so the return type must carry that method — `_TGString` does. Task 6 relies on this returning `"s"` for `WC_S`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_tg_input_manager.py`:

```python
# ── GetDisplayStringFromUnicode ────────────────────────────────────────────
#
# BC returns the printable label for a key so scripts can build help text
# ("Press 's' to skip introduction", E1M1's W/S/A/D tactical help). The label
# comes from the 4th RegisterUnicodeKey argument, localized through the 3rd
# (a TGL database). Rank 57 in docs/stub_heatmap.md, 342 live hits.

class _FakeDatabase:
    """Minimal TGL database stand-in: GetString(key) -> localized text."""
    def __init__(self, mapping):
        self._mapping = mapping

    def GetString(self, key):
        from engine.appc.localization import _TGString
        return _TGString(self._mapping.get(str(key), str(key)))


def test_display_string_uses_the_registered_name():
    from engine.appc.input import WC_S, KY_S
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    assert im.GetDisplayStringFromUnicode(WC_S).GetCString() == "s"


def test_display_string_is_localized_through_the_database():
    from engine.appc.input import WC_ESCAPE, KY_ESCAPE
    im, _ = _fresh_manager()
    db = _FakeDatabase({"ESC": "Esc"})
    im.RegisterUnicodeKey(WC_ESCAPE, KY_ESCAPE, db, "ESC")
    assert im.GetDisplayStringFromUnicode(WC_ESCAPE).GetCString() == "Esc"


def test_display_string_falls_back_to_the_name_when_db_lacks_the_key():
    from engine.appc.input import WC_S, KY_S
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_S, KY_S, _FakeDatabase({}), "s")
    assert im.GetDisplayStringFromUnicode(WC_S).GetCString() == "s"


def test_display_string_for_unregistered_key_is_empty_not_a_stub():
    from engine.appc.input import WC_S
    im, _ = _fresh_manager()
    result = im.GetDisplayStringFromUnicode(WC_S)
    assert result.GetCString() == ""


def test_display_string_result_compares_equal_to_a_plain_str():
    # E1M1.SkipOpeningSequence compares
    #   kDisplayString.GetCString() == kSkipKey.GetCString()
    # where the right side comes from a TGL lookup. Both must be str-comparable.
    from engine.appc.input import WC_S, KY_S
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    lhs = im.GetDisplayStringFromUnicode(WC_S).GetCString()
    assert lhs == "s"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_input_manager.py -k display_string -v`
Expected: FAIL. `GetDisplayStringFromUnicode` resolves through `TGObject.__getattr__` to a `_Stub`, so `.GetCString()` returns another `_Stub` and the `== "s"` assert fails.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/input.py`, inside `class TGInputManager`, after `RegisterUnicodeKey`, add:

```python
    def GetDisplayStringFromUnicode(self, wc_code):
        """Printable label for a key — BC's help-text primitive.

        RegisterUnicodeKey already carries both halves: the 4th argument is
        the label ("s", "ESC", "F1") and the 3rd is the TGL database to
        localize it through. UKConfig.py:14 documents the fallback — with no
        database, the label itself is the answer.

        Returns _TGString so callers can chain .GetCString(), which is how
        every SDK call site consumes it (E1M1.SkipOpeningSequence:1764,
        E1M1's tactical help text:3324-3339).
        """
        from engine.appc.localization import _TGString
        entry = self._registered.get(int(wc_code))
        if entry is None:
            # Unregistered key: an empty label, NOT a stub. A truthy stub here
            # would make every "is this the skip key?" comparison ambiguous.
            return _TGString("")
        _ky, database, name = entry
        if database is None:
            return _TGString(name)
        return _TGString(str(database.GetString(name)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tg_input_manager.py -v`
Expected: all pass, including the 5 new cases.

- [ ] **Step 5: Verify against the real registration table**

Run:

```bash
uv run python -c "
import sys; sys.path.insert(0, 'build/python')
import App, KeyConfig
KeyConfig.MapScancodes()
from engine.appc.input import WC_S, WC_ESCAPE
print(repr(App.g_kInputManager.GetDisplayStringFromUnicode(WC_S).GetCString()))
print(repr(App.g_kInputManager.GetDisplayStringFromUnicode(WC_ESCAPE).GetCString()))
"
```

Expected output:

```
's'
'ESC'
```

- [ ] **Step 6: Commit**

```bash
git add engine/appc/input.py tests/unit/test_tg_input_manager.py
git commit -m "feat(input): implement TGInputManager.GetDisplayStringFromUnicode"
```

---

### Task 4: `TGActionManager_KillActions`

`App.TGActionManager_KillActions` (`sdk/Build/scripts/App.py:10105`) takes an optional name: with one, it kills the actions registered under that name; with none, it kills everything. Call sites: E1M1's skip (`"CharacterIntros"`), `MissionLib.py:4104` (`"FriendlyFireWarning"`), E6M1/E6M2 (both forms).

**One subtlety that must not be missed:** E1M1 registers **six different sequences under the same name** `"CharacterIntros"` (lines 2052, 2145, 2213, 2291, 2390, 2463). Our registry is `name -> action` and overwrites, so `KillActions("CharacterIntros")` would kill only the last one. The registry has to become `name -> [action, ...]`. `FindAction` must keep returning the *most recent* — `tests/unit/test_actions.py:255` asserts exactly that and must keep passing.

"Kill" maps to `Abort()`, not `Skip()`: `Skip()` completes the action and advances dependents, which would let the intro sequence run its completion chain after the player asked for it to stop. `Abort()` stops it dead. Note the consequence, which is BC's too: the aborted `CrewIntros` sequence never posts its `ET_ACTION_COMPLETED`, so the outer sequence stalls there — `UndockCutscene(TRUE)` is what drives the mission forward from that point. Task 6's live check is where this gets confirmed.

**Files:**
- Modify: `engine/appc/actions.py:740-755` (class `TGActionManager`) and the module-level wrappers at 778-791
- Modify: `App.py:163` (the `engine.appc.actions` import block)
- Test: `tests/unit/test_actions.py` (append)

**Interfaces:**
- Consumes: `TGAction.Abort()` ([actions.py:127](../../../engine/appc/actions.py#L127)), `TGSequence.Abort()` ([actions.py:472](../../../engine/appc/actions.py#L472)) — both existing.
- Produces:
  - `TGActionManager.KillActions(name: str | None = None) -> None`
  - module-level `TGActionManager_KillActions(name: str | None = None) -> None`, re-exported as `App.TGActionManager_KillActions`
  - `TGActionManager.FindAction(name)` unchanged in behaviour (most-recent registration)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_actions.py`:

```python
# ── TGActionManager.KillActions ────────────────────────────────────────────
#
# App.TGActionManager_KillActions (sdk/Build/scripts/App.py:10105) aborts the
# actions registered under a name, or every registered action when called with
# no name. E1M1.SkipOpeningSequence:1772 uses the named form; E6M1/E6M2 use
# both. E1M1 registers SIX sequences under "CharacterIntros" (lines 2052, 2145,
# 2213, 2291, 2390, 2463) -- killing only the last one would leave five intro
# sequences playing under the undock cutscene.

class _RecordingAction(TGAction):
    def __init__(self):
        super().__init__()
        self.aborted = 0

    def Abort(self):
        self.aborted += 1
        super().Abort()


def test_kill_actions_aborts_every_action_under_the_name():
    mgr = TGActionManager()
    a, b, c = _RecordingAction(), _RecordingAction(), _RecordingAction()
    mgr.RegisterAction(a, "CharacterIntros")
    mgr.RegisterAction(b, "CharacterIntros")
    mgr.RegisterAction(c, "CharacterIntros")
    mgr.KillActions("CharacterIntros")
    assert (a.aborted, b.aborted, c.aborted) == (1, 1, 1)


def test_kill_actions_unregisters_the_name():
    mgr = TGActionManager()
    mgr.RegisterAction(_RecordingAction(), "CharacterIntros")
    mgr.KillActions("CharacterIntros")
    assert mgr.IsRegistered("CharacterIntros") == 0
    assert mgr.FindAction("CharacterIntros") is None


def test_kill_actions_leaves_other_names_alone():
    mgr = TGActionManager()
    keep = _RecordingAction()
    mgr.RegisterAction(_RecordingAction(), "CharacterIntros")
    mgr.RegisterAction(keep, "FriendlyFireWarning")
    mgr.KillActions("CharacterIntros")
    assert keep.aborted == 0
    assert mgr.IsRegistered("FriendlyFireWarning") == 1


def test_kill_actions_with_no_name_kills_everything():
    mgr = TGActionManager()
    a, b = _RecordingAction(), _RecordingAction()
    mgr.RegisterAction(a, "One")
    mgr.RegisterAction(b, "Two")
    mgr.KillActions()
    assert (a.aborted, b.aborted) == (1, 1)
    assert mgr.IsRegistered("One") == 0
    assert mgr.IsRegistered("Two") == 0


def test_kill_actions_on_unknown_name_is_a_no_op():
    mgr = TGActionManager()
    mgr.KillActions("NeverRegistered")  # must not raise


def test_find_action_still_returns_the_most_recent_registration():
    # Regression guard for the name -> list registry change.
    mgr = TGActionManager()
    a, b = TGAction(), TGAction()
    mgr.RegisterAction(a, "X")
    mgr.RegisterAction(b, "X")
    assert mgr.FindAction("X") is b


def test_module_level_wrapper_routes_to_the_app_singleton():
    import App
    from engine.appc.actions import TGActionManager_KillActions
    a = _RecordingAction()
    App.g_kTGActionManager.RegisterAction(a, "PlanTaskFour")
    TGActionManager_KillActions("PlanTaskFour")
    assert a.aborted == 1
    assert App.g_kTGActionManager.IsRegistered("PlanTaskFour") == 0


def test_app_exports_kill_actions_as_a_callable_not_a_stub():
    import App
    assert callable(App.TGActionManager_KillActions)
    assert type(App.TGActionManager_KillActions).__name__ != "_NamedStub"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_actions.py -k kill_actions -v`
Expected: FAIL. `AttributeError: 'TGActionManager' object has no attribute 'KillActions'` on the first four; `ImportError` on the module-level wrapper test; the `App` export test fails the `_NamedStub` assert.

- [ ] **Step 3a: Convert the registry to name → list**

In `engine/appc/actions.py`, replace the body of `class TGActionManager`'s registry methods (lines ~740-755) with:

```python
    def __init__(self):
        super().__init__()
        # name -> [action, ...] in registration order. A LIST, not a single
        # slot: E1M1 registers six separate sequences under "CharacterIntros"
        # (E1M1.py:2052, 2145, 2213, 2291, 2390, 2463) and KillActions must
        # take out all of them, not just the last.
        self._registered: dict = {}

    def RegisterAction(self, action, name: str) -> None:
        self._registered.setdefault(str(name), []).append(action)

    def UnregisterAction(self, name: str) -> None:
        self._registered.pop(str(name), None)

    def FindAction(self, name: str):
        # Most-recent registration wins — MissionLib's FriendlyFireWarning
        # pattern re-fetches the action it just posted.
        actions = self._registered.get(str(name))
        return actions[-1] if actions else None

    def IsRegistered(self, name: str) -> int:
        return 1 if self._registered.get(str(name)) else 0

    def KillActions(self, name: str | None = None) -> None:
        """Abort registered actions — BC's TGActionManager_KillActions.

        With a name, aborts every action registered under it and drops the
        name. With no name, aborts everything (E6M1.py:894, E6M2.py:1043).

        Abort, not Skip: Skip() COMPLETES the action and advances its
        dependents, which would run the very sequence the caller asked to
        stop. The caller is expected to drive the mission forward itself —
        E1M1.SkipOpeningSequence calls UndockCutscene(TRUE) right after.
        """
        if name is None:
            groups = list(self._registered.values())
            self._registered.clear()
        else:
            groups = [self._registered.pop(str(name), [])]
        for group in groups:
            for action in group:
                abort = getattr(action, "Abort", None)
                if callable(abort):
                    abort()
```

- [ ] **Step 3b: Add the module-level wrapper**

In `engine/appc/actions.py`, after `TGActionManager_UnregisterAction` (line ~791), add:

```python
def TGActionManager_KillActions(name: str | None = None) -> None:
    """Module-level wrapper — sdk/Build/scripts/App.py:10105.

    Called by E1M1.SkipOpeningSequence:1772, MissionLib.py:4104, and E6M1 /
    E6M2 (both the named and the kill-everything forms).
    """
    import App
    App.g_kTGActionManager.KillActions(name)
```

- [ ] **Step 3c: Re-export from `App.py`**

In `App.py`, extend the `engine.appc.actions` import at line 163:

```python
    TGActionManager_RegisterAction, TGActionManager_UnregisterAction,
    TGActionManager_KillActions,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_actions.py -v`
Expected: all pass, including the 8 new cases and the pre-existing `FindAction`/`IsRegistered` cases at lines 243-261.

- [ ] **Step 5: Check for other readers of the registry shape**

Run: `grep -rn "_registered" engine/appc/actions.py engine/ tests/ | grep -v "_registered_codes"`
Expected: no call site outside `TGActionManager` reads `_registered` as a `name -> action` dict. If one turns up, update it to the list shape in this same commit.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py App.py tests/unit/test_actions.py
git commit -m "feat(actions): implement TGActionManager_KillActions with multi-registration names"
```

---

### Task 5: Dev-mode `PlayedTutorial` force

BC's prompt is replay-only by design: `SaveTheGame` sets the flag at the *end* of the opening ([E1M1.py:2659](../../../sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py#L2659)), so a genuine first play shows nothing. Our `TGVarManager` is in-memory and only round-trips through savegames, so a cold-launched E1M1 always reads 0.0 and the feature is unreachable.

**This task is deliberately a stopgap.** Real behaviour needs the `"global"` scope persisted across launches, which belongs with persistent-save support. Until then, `--developer` forces the flag so the path is reachable and testable, and the follow-up is written down where it will be found.

The seam mirrors `engine/dev_combat_cheats.py`: a tiny module neither side imports the other through, with the `dev_mode.is_enabled()` gate *inside* the accessor so production behaviour cannot change even if the flag were somehow set.

**Files:**
- Create: `engine/dev_tutorial_flag.py`
- Modify: `engine/host_loop.py` (end of `reset_sdk_globals()`, which is called once at start-of-mission and again on every swap — the single seam covering both load paths)
- Create: `docs/engine/e1m1-skip-intro.md`
- Test: `tests/unit/test_dev_tutorial_flag.py` (create)

**Interfaces:**
- Consumes: `engine.dev_mode.is_enabled()` (existing), `App.g_kVarManager.SetFloatVariable` (existing).
- Produces: `engine.dev_tutorial_flag.apply_played_tutorial_flag() -> None`. Task 6's integration test calls it directly.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dev_tutorial_flag.py`:

```python
"""Dev-only force for E1M1's PlayedTutorial gate.

E1M1.CrewIntros:1954 only builds the skip banner + keyboard handler when
g_kVarManager's global PlayedTutorial == 1.0, which BC sets at the END of the
opening (E1M1.SaveTheGame:2659) and persists. Our TGVarManager is in-memory and
only round-trips through savegames, so a cold launch always reads 0.0.

Stopgap until persistent saves land -- see docs/engine/e1m1-skip-intro.md.
"""
import App
from engine import dev_mode, dev_tutorial_flag


def _read():
    return App.g_kVarManager.GetFloatVariable("global", "PlayedTutorial")


def test_flag_is_forced_when_developer_mode_is_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 0.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert _read() == 1.0


def test_flag_is_untouched_when_developer_mode_is_off(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 0.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert _read() == 0.0


def test_an_existing_true_flag_is_not_clobbered_in_production(monkeypatch):
    # A savegame that legitimately carries the flag must survive with dev off.
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 1.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert _read() == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_dev_tutorial_flag.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.dev_tutorial_flag'`.

- [ ] **Step 3a: Create the module**

Create `engine/dev_tutorial_flag.py`:

```python
"""Developer-only force for E1M1's PlayedTutorial gate.

E1M1.CrewIntros:1954 gates the "Press 's' to skip introduction" banner and its
keyboard handler on g_kVarManager's global PlayedTutorial == 1.0. BC sets that
at the END of the opening (E1M1.SaveTheGame:2659) and persists it, making the
prompt replay-only. Our TGVarManager is in-memory and only round-trips through
savegames (engine/appc/save_load.py:181), so a cold-launched E1M1 always reads
0.0 and the skip path is unreachable.

STOPGAP. The correct fix is to persist the "global" scope across launches; that
belongs with persistent-save support. See docs/engine/e1m1-skip-intro.md for
the follow-up.

Gating lives inside the function, mirroring dev_combat_cheats: even if this were
somehow called in a production build, mission behaviour cannot change.
"""
from engine import dev_mode


def apply_played_tutorial_flag() -> None:
    """Force PlayedTutorial=1.0 under --developer; otherwise do nothing."""
    if not dev_mode.is_enabled():
        return
    import App
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 1.0)
```

- [ ] **Step 3b: Call it from `reset_sdk_globals()`**

In `engine/host_loop.py`, at the very end of `reset_sdk_globals()` (the function starting at line 3150), add:

```python
    # Re-apply the dev-only PlayedTutorial force after the clear. This function
    # runs once at start-of-mission and again on every swap, so it is the one
    # seam that covers both load paths (host_loop.py:4550 and :6240).
    from engine import dev_tutorial_flag
    dev_tutorial_flag.apply_played_tutorial_flag()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_dev_tutorial_flag.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write the feature note with the follow-up**

Create `docs/engine/e1m1-skip-intro.md`:

```markdown
# E1M1 "Press 's' to skip introduction"

BC's opening-cutscene skip. Entirely SDK-driven — `E1M1.CrewIntros` (line 1950)
builds a `TGCreditAction` banner over the subtitle window and registers
`E1M1.SkipOpeningSequence` on `g_kRootWindow` for `App.ET_KEYBOARD`; pressing
the key kills the `"CharacterIntros"` sequences and calls
`UndockCutscene(TRUE)`.

Strings come from `data/TGL/Maelstrom/Episode 1/E1M1.TGL`:
`SkipKey` = `s`, `CutsceneTextBar` = `Press 's' to skip introduction`.
The key label is resolved via `TGInputManager.GetDisplayStringFromUnicode`,
which reads the name registered by `KeyConfig.MapScancodes()`
(`UKConfig.py:70` registers `WC_S` as `"s"`).

## Engine surface this needs

| Surface | Where |
|---|---|
| `TGKeyboardEvent.GetUnicode` / `SetUnicode` | `engine/appc/events.py` |
| `App.ET_KEYBOARD` (real int, `0x1001`) | `engine/appc/events.py`, re-exported by `App.py` |
| Raw `ET_KEYBOARD` dispatch down the window chain | `engine/appc/input.py` — `_raw_keyboard_destination`, `TGInputManager._dispatch_raw_keyboard` |
| `TGInputManager.GetDisplayStringFromUnicode` | `engine/appc/input.py` |
| `TGActionManager_KillActions` (name → **list** registry) | `engine/appc/actions.py` |

## ⚠️ Open follow-up: PlayedTutorial persistence

`E1M1.CrewIntros:1954` gates the whole feature on
`g_kVarManager.GetFloatVariable("global", "PlayedTutorial") == 1.0`. BC sets it
in `E1M1.SaveTheGame:2659` — *"sets the config flag that will allow them to skip
the next time through"* — so the prompt is **replay-only**.

Our `TGVarManager` is in-memory. It round-trips through savegames
(`engine/appc/save_load.py:181`) but starts empty on every launch, so a
cold-launched E1M1 never shows the prompt.

**Current stopgap:** `engine/dev_tutorial_flag.py` forces the flag to 1.0 under
`--developer`, applied from the end of `host_loop.reset_sdk_globals()`.

**When persistent-save support lands, revisit this:** persist the `"global"`
VarManager scope across launches and delete the dev force (or keep it purely as
a testing shortcut). Until then the feature is dev-only, and a production
playthrough will not show the prompt on a replay the way BC does.
```

- [ ] **Step 6: Commit**

```bash
git add engine/dev_tutorial_flag.py engine/host_loop.py docs/engine/e1m1-skip-intro.md tests/unit/test_dev_tutorial_flag.py
git commit -m "feat(dev): force PlayedTutorial under --developer so E1M1's skip prompt is reachable"
```

---

### Task 6: End-to-end verification, docs, and the gate

Tasks 1-5 each fix one break in isolation. This task proves they compose: a simulated `s` press must actually reach the SDK's own unmodified `SkipOpeningSequence` and take the skip branch.

**Files:**
- Create: `tests/missions/test_e1m1_skip_intro.py`
- Modify: `docs/stub_heatmap.md` (annotate the two rows this plan closes)
- Modify: `CLAUDE.md` (add the feature to the reference table)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: no new API.

- [ ] **Step 1: Write the failing integration test**

Create `tests/missions/test_e1m1_skip_intro.py`:

```python
"""E1M1's skip prompt, end to end.

Five independent breaks had to be fixed for this to work (see
docs/engine/e1m1-skip-intro.md). This test drives the SDK's OWN
SkipOpeningSequence through the real input pipeline: nothing in E1M1.py is
stubbed or reimplemented, so it fails if any one of the five regresses.
"""
import sys
import types

import pytest

import App
from engine import dev_mode, dev_tutorial_flag
from engine.appc.actions import TGAction
from engine.appc.input import WC_S, WC_ESCAPE


@pytest.fixture
def skip_module(monkeypatch):
    """A stand-in for the E1M1 module exposing the real SkipOpeningSequence.

    We import the SDK function itself rather than copying it, so the test
    tracks the SDK. Its two mission-side collaborators (UndockCutscene and the
    banner lookup) are replaced with recorders -- they need a live mission,
    and what we are asserting is that the handler REACHES the skip branch.
    """
    import Maelstrom.Episode1.E1M1.E1M1 as e1m1

    calls = {"undock": [], "killed": []}
    monkeypatch.setattr(e1m1, "UndockCutscene",
                        lambda skipped: calls["undock"].append(skipped))

    db = App.g_kLocalizationManager.Load(
        "data/TGL/Maelstrom/Episode 1/E1M1.TGL")
    monkeypatch.setattr(e1m1, "g_pMissionDatabase", db)
    monkeypatch.setattr(e1m1, "g_idTextBanner", 0)

    real_kill = App.TGActionManager_KillActions

    def recording_kill(name=None):
        calls["killed"].append(name)
        real_kill(name)

    monkeypatch.setattr(App, "TGActionManager_KillActions", recording_kill)
    return e1m1, calls


def _register(e1m1):
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(
        App.ET_KEYBOARD,
        "Maelstrom.Episode1.E1M1.E1M1.SkipOpeningSequence")


def _unregister(e1m1):
    App.g_kRootWindow.RemoveHandlerForInstance(
        App.ET_KEYBOARD,
        "Maelstrom.Episode1.E1M1.E1M1.SkipOpeningSequence")


def test_tgl_strings_are_the_ones_the_feature_depends_on():
    db = App.g_kLocalizationManager.Load(
        "data/TGL/Maelstrom/Episode 1/E1M1.TGL")
    assert str(db.GetString("SkipKey")) == "s"
    assert str(db.GetString("CutsceneTextBar")) == \
        "Press 's' to skip introduction"


def test_pressing_s_reaches_the_sdk_skip_branch(skip_module):
    e1m1, calls = skip_module
    import KeyConfig
    KeyConfig.MapScancodes()
    _register(e1m1)
    try:
        App.g_kInputManager.OnKeyDown(WC_S)
    finally:
        _unregister(e1m1)
    assert calls["undock"] == [1], "UndockCutscene(TRUE) was not called"
    assert calls["killed"] == ["CharacterIntros"]


def test_pressing_a_different_key_does_not_skip(skip_module):
    e1m1, calls = skip_module
    import KeyConfig
    KeyConfig.MapScancodes()
    _register(e1m1)
    try:
        App.g_kInputManager.OnKeyDown(WC_ESCAPE)
    finally:
        _unregister(e1m1)
    assert calls["undock"] == []
    assert calls["killed"] == []


def test_the_played_tutorial_gate_opens_under_developer_mode(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 0.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert App.g_kVarManager.GetFloatVariable(
        "global", "PlayedTutorial") == 1.0
```

- [ ] **Step 2: Run test to verify it fails on a clean tree, passes with Tasks 1-5**

Run: `uv run pytest tests/missions/test_e1m1_skip_intro.py -v`
Expected: PASS with Tasks 1-5 applied.

To prove the test has teeth, temporarily break one break and watch it fail — **back up by copy, never with git**:

```bash
cp engine/appc/input.py /tmp/input_bak.py
# Edit engine/appc/input.py: make GetDisplayStringFromUnicode return _TGString("")
uv run pytest tests/missions/test_e1m1_skip_intro.py::test_pressing_s_reaches_the_sdk_skip_branch -v
# Expected: FAIL -- "UndockCutscene(TRUE) was not called"
cp /tmp/input_bak.py engine/appc/input.py
diff engine/appc/input.py /tmp/input_bak.py && echo "restore is byte-identical"
```

- [ ] **Step 3: Annotate the closed stub-heatmap rows**

In `docs/stub_heatmap.md`, add a note to the rank-57 row (`TGInputManager | GetDisplayStringFromUnicode`) in its trailing notes column:

```
✅ FIXED 2026-08-16 — engine/appc/input.py; see docs/engine/e1m1-skip-intro.md
```

Do the same for the rank-56 row (`KeyboardBinding | FindKey`) **only if** it now resolves — check first:

```bash
uv run python -c "
import sys; sys.path.insert(0,'build/python')
import App
print(type(App.g_kKeyboardBinding.FindKey).__name__)
"
```

If it prints a stub type name, leave that row alone — `FindKey` is a separate gap and is **not** in this plan's scope. Note it in `docs/engine/e1m1-skip-intro.md` under a "Still open" heading instead.

- [ ] **Step 4: Add the feature to `CLAUDE.md`**

In `CLAUDE.md`, append a row to the "Key reference material" table:

```
| E1M1 intro skip | `docs/engine/e1m1-skip-intro.md`, `engine/appc/input.py`, `engine/dev_tutorial_flag.py` | BC's "Press 's' to skip introduction" prompt. Needed FIVE pieces of missing surface: `TGKeyboardEvent.GetUnicode`, a real `App.ET_KEYBOARD` int, raw `ET_KEYBOARD` dispatch down the window chain (`_raw_keyboard_destination`), `TGInputManager.GetDisplayStringFromUnicode` (heatmap rank 57, 342 hits), and `TGActionManager_KillActions` — whose registry had to become name→**list** because E1M1 registers six sequences under `"CharacterIntros"`. ⚠️ The `PlayedTutorial` gate is only forced under `--developer` for now; persisting the `"global"` VarManager scope is deferred to persistent-save work. |
```

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. It builds C++, runs pytest + ctest, and diffs failures against `tests/known_failures.txt`. Any failure it names that is not in that ledger is a regression from this plan — fix it, do not baseline it. As of the last update the ledger holds zero ctest entries and exactly one pytest entry (`test_engineer_emitters.py::test_shield_level_change_announces`, order-dependent).

- [ ] **Step 6: Commit**

```bash
git add tests/missions/test_e1m1_skip_intro.py docs/stub_heatmap.md docs/engine/e1m1-skip-intro.md CLAUDE.md
git commit -m "test(e1m1): end-to-end coverage for the intro skip prompt"
```

- [ ] **Step 7: Live verification — REQUIRED before calling this done**

Green tests cannot see asset paths, CEF layout, or the renderer. This feature must be confirmed in-game by Mark before it is reported as working.

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

Then: pause menu → **Load Mission…** → Maelstrom → Episode 1 → E1M1.

Check, in order:

1. During the crew introductions, a centred banner reading **"Press 's' to skip introduction"** appears near the top of the screen, below any letterbox bars.
2. Pressing **`s`** removes the banner and cuts immediately to the undock cutscene.
3. The character-intro dialogue **stops** — no crew voice lines continue underneath the undock camera. (This is the `Abort`-vs-`Skip` question from Task 4. If lines keep playing, `KillActions` reached the wrong actions; if the mission hangs instead of undocking, the aborted sequence's completion chain matters after all and Task 4 needs revisiting.)
4. Pressing any other key during the intro does nothing.
5. Letting the intro play out without pressing `s` still reaches the undock cutscene normally.

Record the outcome in `docs/engine/e1m1-skip-intro.md`. **Do not mark this plan complete on green tests alone.**

---

## Self-Review

**Spec coverage** — all five breaks plus the gate map to tasks: break 1 → Task 1; breaks 2 and 3 → Task 2; break 4 → Task 3; break 5 → Task 4; `PlayedTutorial` gate → Task 5; composition + live check → Task 6.

**Type consistency** — `GetDisplayStringFromUnicode` returns `_TGString` in Task 3 and is consumed via `.GetCString()` in Tasks 3 and 6. `ET_KEYBOARD` is declared `int` in Task 2 and asserted `isinstance(..., int)` in Tasks 2 and 6. `KillActions(name=None)` has the same signature in the class, the module wrapper, and the Task 6 recorder. `apply_played_tutorial_flag()` takes no arguments in Tasks 5 and 6.

**Known risks carried forward, not hidden:**
- Task 4's `Abort()` choice is reasoned from `Skip()`'s completion semantics, not from the original binary. Step 7 check 3 is what settles it.
- Task 2 keeps the `_registered_codes` gate, so raw `ET_KEYBOARD` never fires for a key `KeyConfig.MapScancodes()` did not register. That covers every SDK case found, but it is a narrowing relative to BC.
- Task 5 is explicitly a stopgap; the follow-up is written into `docs/engine/e1m1-skip-intro.md` rather than left in conversation.
- `KeyboardBinding.FindKey` (heatmap rank 56, same 342 hits) is the same class of gap and blocks the *generic* Backspace skip in `CinematicInterfaceHandlers`. It is **out of scope** here and Task 6 Step 3 records it as still open.

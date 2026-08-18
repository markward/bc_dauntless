# Cinematic Mode Focus Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BC's cinematic mode (F9) reachable, so its F1–F6 camera keys route to the cinematic window instead of the bridge crew menus.

**Architecture:** Keep the existing single-destination keyboard model. `engine/appc/input.py:_resolve_destination` already scans a fixed candidate list for the first object with a registered handler; this prepends the *focused main window* to that list. Focus is BC's own `TopWindow.GetFocus()`, set by `ToggleCinematicWindow()`. Because the scan is unchanged, any event type the cinematic window did not register falls through to today's candidates — so the bridge crew menus keep F1–F5 whenever cinematic mode is not focused, by construction rather than by special case.

**Tech Stack:** Python 3.11, pytest. No C++ changes, no rebuild required.

**Spec:** `docs/superpowers/specs/2026-08-18-cinematic-mode-input-focus-design.md`

## Global Constraints

- **Shared checkout.** Never run `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, `cp` it to `/tmp`, mutate, restore by `cp`, and `diff` to prove the restore.
- **Branch:** `feat/camera-named-modes-bc-convention` (already checked out).
- **Test gate:** `scripts/check_tests.sh`. Baseline is **0 ctest failures and exactly 1 known pytest failure** (`tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`). Any other failure is a regression introduced by this work.
- **Do not** add BC's bubbling chain (`SetHandled` / `CallNextHandler` veto). Out of scope.
- **Do not** implement mouse-look, the camera-mode-name overlay, or letterbox in cinematic mode. Out of scope.
- Game units throughout; column-vector right-handed rotations (CLAUDE.md).

---

### Task 1: Make F6 and F9 reachable

Found during plan self-review, and **not in the spec** — a fifth blocker. `engine/appc/input.py:53-54` generates `WC_F1`..`WC_F12`, but `App.py:23` re-exports only F1–F5. So `App.WC_F9` is absent, and BC's `BindKey(App.WC_F9, ...)` (`DefaultKeyboardBinding.py:128`) receives a truthy `_NamedStub` — F9 can never register. Nothing else in this plan is keyboard-reachable until this is fixed.

Separately, `host_loop._poll_function_keys` only forwards F1–F5 into `g_kInputManager`, so even a bound F6/F9 would never be seen.

**Files:**
- Modify: `App.py:23` (the `from engine.appc.input import (...)` list)
- Modify: `engine/host_loop.py:476-498` (`_poll_function_keys`)
- Test: `tests/unit/test_fkey_poll.py`

**Interfaces:**
- Consumes: `WC_F6`/`WC_F9` already generated in `engine/appc/input.py:53-54` (values `0x75`/`0x78` — VK codes, matching the existing F1–F5 scheme).
- Produces: `App.WC_F6`, `App.WC_F9` importable; `_poll_function_keys` forwards physical F6/F9 to those codes.

> **Note on values:** ours are Windows VK codes (`WC_F1 == 112`); the real game's probes record `App.WC_F1 == 57365` (`tools/probes/results/q13_constants_battle.txt`). That divergence is pre-existing and harmless — our engine both produces and consumes these codes, so only internal consistency matters. **Do not "fix" it here**; changing the scheme would break the GLFW→WC mapping at `host_loop.py:492`.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_fkey_poll.py`, first extend the existing `_FakeKeys` at the top of the file — it stops at F5, and
the implementation reads `host_io._h.keys.KEY_F6`/`KEY_F9`, so without this the
poller raises `AttributeError` (GLFW `KEY_F1 == 290`, so F6 is 295 and F9 is 298):

```python
class _FakeKeys:
    KEY_F1, KEY_F2, KEY_F3, KEY_F4, KEY_F5 = 290, 291, 292, 293, 294
    KEY_F6, KEY_F9 = 295, 298
```

Then append:

```python
def test_f9_and_f6_are_exported(monkeypatch):
    """WC_F1..F12 are generated in engine/appc/input.py:53-54; the App
    re-export list was what stopped at F5, so App.WC_F9 was a _NamedStub and
    BC's BindKey(App.WC_F9, ...) could never register."""
    import App
    assert App.__dict__.get("WC_F6") == 0x75
    assert App.__dict__.get("WC_F9") == 0x78


def test_f9_and_f6_edges_are_forwarded(monkeypatch):
    """F9 toggles cinematic mode and F6 selects FreeOrbit, so both must reach
    g_kInputManager. They are fixed keys, not input_map actions."""
    im = InputMap()
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(("down", wc)))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp",
                        lambda wc: calls.append(("up", wc)))
    host = _FakeHost()
    monkeypatch.setattr(host_io, "_h", host)

    host.down.add(298)                         # F9 down
    _poll_function_keys(host, im)
    assert calls == [("down", App.WC_F9)]

    host.down.clear()
    host.down.add(295)                         # F9 up, F6 down
    _poll_function_keys(host, im)
    assert calls == [("down", App.WC_F9), ("up", App.WC_F9),
                     ("down", App.WC_F6)]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_fkey_poll.py -q -k f9_and_f6`
Expected: both FAIL — `test_f9_and_f6_are_exported` with `assert None == 117`, and
`test_f9_and_f6_edges_are_forwarded` with `assert [] == [('down', ...)]` (the
poller never looks at F6/F9). The first is fixed by Step 3, the second by Step 5.

- [ ] **Step 3: Implement the re-export**

In `App.py:23`, extend the F-key line (leave `KY_F1..KY_F5` alone — the `KY_` codes have no consumer in `engine/` or `tests/`, so adding more would be dead surface):

```python
    WC_F1, WC_F2, WC_F3, WC_F4, WC_F5, WC_F6, WC_F9,
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_fkey_poll.py -q -k f9_and_f6`
Expected: `test_f9_and_f6_are_exported` PASSES.
`test_f9_and_f6_edges_are_forwarded` still FAILS — Step 5 fixes it.

- [ ] **Step 5: Extend the poller**

In `engine/host_loop.py:_poll_function_keys`, add F6 and F9 to the table. They are **not** remappable through `input_map` (BC's cinematic keys are fixed), so they use the physical codes directly:

```python
    from engine import host_io
    _keys = host_io._h.keys
    _poll_key_table((
        (input_map.code("talk_helm"),        App.WC_F1),
        (input_map.code("talk_tactical"),    App.WC_F2),
        (input_map.code("talk_xo"),          App.WC_F3),
        (input_map.code("talk_science"),     App.WC_F4),
        (input_map.code("talk_engineering"), App.WC_F5),
        # Cinematic mode: F9 toggles it, F6 selects FreeOrbit. Fixed keys, not
        # input_map actions. F7/F8 are deliberately absent — dev keybindings
        # own those (engine/dev_keybindings.py).
        (_keys.KEY_F6,                       App.WC_F6),
        (_keys.KEY_F9,                       App.WC_F9),
    ), suppress=suppress)
```

Update the function's docstring first line to: `"""Forward the crew-talk keys (F1-F5 by default) plus the fixed cinematic keys (F6, F9) into g_kInputManager.`

- [ ] **Step 6: Run the poller tests**

Run: `uv run pytest tests/unit/test_fkey_poll.py tests/unit/test_fkey_input_chain.py tests/unit/test_fire_key_input_chain.py -q`
Expected: PASS. If `test_fire_key_input_chain.py:29` asserts an exact set of forwarded WC codes, update that set to include the two new codes — that is a deliberate change, not a regression.

- [ ] **Step 7: Commit**

```bash
git add App.py engine/host_loop.py tests/unit/test_fkey_poll.py
git commit -m "feat(input): export and poll WC_F6/WC_F9 for cinematic mode"
```

---

### Task 2: Cinematic window state + toggle

Makes `_CinematicWindow` carry real interactive/active state and `ToggleCinematicWindow()` actually move focus. These are one task because `IsWindowActive()` reads the focus that the toggle writes — they cannot be tested apart.

**Files:**
- Modify: `engine/appc/windows.py:448-452` (the `IsWindowActive`/`IsInteractive` stubs)
- Modify: `engine/appc/top_window.py:293` (`ToggleCinematicWindow`)
- Test: `tests/unit/test_top_window.py`

**Interfaces:**
- Consumes: `_TopWindow.GetFocus()` / `SetFocus()` (`engine/appc/top_window.py:210-213`), `_TopWindow.FindMainWindow(mwt)` (`:171`), `MWT_CINEMATIC = 7` (`:27`).
- Produces:
  - `_TopWindow.ToggleCinematicWindow() -> None`
  - `_TopWindow.is_cinematic_active() -> bool`
  - `_CinematicWindow.SetInteractive(value) -> None`
  - `_CinematicWindow.IsInteractive() -> int` (1/0)
  - `_CinematicWindow.IsWindowActive() -> int` (1/0)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
# ── Cinematic mode ──────────────────────────────────────────────────────────
# BC enters cinematic mode by focusing the MWT_CINEMATIC main window
# (Actions/CameraScriptActions.py:StartCinematicMode compares GetFocus()
# against it). Focus is the single source of truth — there is no second flag.

def test_toggle_cinematic_window_focuses_and_unfocuses():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    assert tw.GetFocus() is None
    assert tw.is_cinematic_active() is False

    tw.ToggleCinematicWindow()
    assert tw.GetFocus() is cine
    assert tw.is_cinematic_active() is True
    assert cine.IsWindowActive() == 1

    tw.ToggleCinematicWindow()
    assert tw.GetFocus() is None
    assert tw.is_cinematic_active() is False
    assert cine.IsWindowActive() == 0


def test_cinematic_window_interactive_state_round_trips():
    from engine.appc import top_window
    top_window.reset_for_tests()
    cine = top_window.TopWindow_GetTopWindow().FindMainWindow(
        top_window.MWT_CINEMATIC)
    assert cine.IsInteractive() == 1        # BC normal-state default, unchanged
    cine.SetInteractive(0)
    assert cine.IsInteractive() == 0
    cine.SetInteractive(1)
    assert cine.IsInteractive() == 1


def test_is_cinematic_active_false_when_another_child_holds_focus():
    """QuickBattle's OpenConfigDialog focuses a config pane. That must not read
    as cinematic mode."""
    from engine.appc import top_window
    from engine.appc.events import TGEventHandlerObject
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.SetFocus(TGEventHandlerObject())
    assert tw.is_cinematic_active() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -q -k cinematic`
Expected: FAIL — `AttributeError: '_TopWindow' object has no attribute 'is_cinematic_active'`.

- [ ] **Step 3: Implement the window state**

In `engine/appc/windows.py`, replace the `_CinematicWindow` body's two methods:

```python
    def __init__(self):
        super().__init__()
        # BC's normal-state default is interactive; StartCinematicMode passes
        # bInteractive explicitly when a script wants it non-interactive.
        self._interactive = 1

    def SetInteractive(self, value):
        self._interactive = 1 if value else 0

    def IsInteractive(self):
        return self._interactive

    def IsWindowActive(self):
        """Active == holds TopWindow focus. Derived, never stored: a second
        flag could disagree with focus, and focus is what routing reads."""
        import App
        top = App.TopWindow_GetTopWindow()
        return 1 if (top is not None and top.GetFocus() is self) else 0
```

- [ ] **Step 4: Implement the toggle**

In `engine/appc/top_window.py`, replace `def ToggleCinematicWindow(self) -> None: pass` with:

```python
    def ToggleCinematicWindow(self) -> None:
        """Enter/leave BC's cinematic mode by moving focus to the
        MWT_CINEMATIC main window. Focus is the whole state — see
        is_cinematic_active."""
        cine = self._main_windows.get(MWT_CINEMATIC)
        if cine is None:
            return
        self._focus = None if self._focus is cine else cine

    def is_cinematic_active(self) -> bool:
        """True while the cinematic main window holds focus. Derived rather
        than stored so it cannot drift out of sync with GetFocus()."""
        cine = self._main_windows.get(MWT_CINEMATIC)
        return cine is not None and self._focus is cine
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -q`
Expected: PASS, all tests in the file.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/windows.py engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(cinematic): real cinematic window state and focus toggle"
```

---

### Task 3: Focus-aware destination resolution

**Files:**
- Modify: `engine/appc/input.py:374-409` (`_resolve_destination`)
- Test: `tests/unit/test_keyboard_binding.py`

**Interfaces:**
- Consumes: `_TopWindow.GetFocus()`, `_TopWindow._main_windows` (Task 2 leaves both unchanged in shape).
- Produces: no new public names. `_resolve_destination(event_type)` keeps its signature and return contract (an object with a `_handlers` dict, or the default destination).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_keyboard_binding.py`:

```python
# ── Focus-aware routing ─────────────────────────────────────────────────────
# BC routes keyboard input to the focused window first; we prepend the focused
# MAIN window to the candidate scan. The bridge crew menus (F1-F5 ->
# ET_INPUT_TALK_TO_*) register on the TCW, so they keep those keys whenever
# cinematic mode is not focused.

def test_focused_main_window_wins_when_it_handles_the_event():
    import App
    from engine.appc import top_window
    from engine.appc.input import KS_NORMAL

    del _resolver_hits[:]
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)
    cine.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CINEMATIC_CHASE, __name__ + "._resolver_probe")
    tw.ToggleCinematicWindow()                 # focus it

    em = TGEventManager()
    kb = KeyboardBinding(em)
    kb.SetDefaultDestination(TGEventHandlerObject())
    kb.BindKey(App.WC_F2, KS_NORMAL, App.ET_INPUT_CINEMATIC_CHASE)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_F2)
    evt.SetKeyState(KS_NORMAL)
    kb.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [cine]


def test_bridge_menu_keeps_f1_while_cinematic_is_unfocused():
    """THE regression guard: F1 must still reach the crew-menu handler on the
    TCW when cinematic mode is not active."""
    import App
    from engine.appc import top_window
    from engine.appc.input import KS_NORMAL

    del _resolver_hits[:]
    top_window.reset_for_tests()                # nothing focused
    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_HELM, __name__ + "._resolver_probe")

    em = TGEventManager()
    kb = KeyboardBinding(em)
    kb.SetDefaultDestination(tcw)
    kb.BindKey(App.WC_F1, KS_NORMAL, App.ET_INPUT_TALK_TO_HELM)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_F1)
    evt.SetKeyState(KS_NORMAL)
    kb.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [tcw]


def test_focused_window_without_a_handler_falls_through():
    """A focused cinematic window must not swallow event types it never
    registered — those still reach the TCW."""
    import App
    from engine.appc import top_window
    from engine.appc.input import KS_NORMAL

    del _resolver_hits[:]
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()                 # focused, but no handlers
    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_HELM, __name__ + "._resolver_probe")

    em = TGEventManager()
    kb = KeyboardBinding(em)
    kb.SetDefaultDestination(tcw)
    kb.BindKey(App.WC_F1, KS_NORMAL, App.ET_INPUT_TALK_TO_HELM)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_F1)
    evt.SetKeyState(KS_NORMAL)
    kb.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [tcw]


def test_focused_non_main_window_is_not_a_candidate():
    """QuickBattle focuses config panes. Those must not capture keyboard
    events as a side effect of focus-aware routing."""
    import App
    from engine.appc import top_window
    from engine.appc.input import KS_NORMAL

    del _resolver_hits[:]
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    pane = TGEventHandlerObject()
    pane.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_HELM, __name__ + "._resolver_probe")
    tw.SetFocus(pane)                          # focused, but NOT a main window

    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_HELM, __name__ + "._resolver_probe2")

    em = TGEventManager()
    kb = KeyboardBinding(em)
    kb.SetDefaultDestination(tcw)
    kb.BindKey(App.WC_F1, KS_NORMAL, App.ET_INPUT_TALK_TO_HELM)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_F1)
    evt.SetKeyState(KS_NORMAL)
    kb.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [tcw]
```

Also append this second probe used by the last test:

```python
def _resolver_probe2(pObject, pEvent):
    _resolver_hits.append(pObject)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_keyboard_binding.py -q -k "focused or bridge_menu_keeps"`
Expected: `test_focused_main_window_wins_when_it_handles_the_event` FAILS with `assert [] == [cine]` (the cinematic window is never scanned). The other three PASS already — they are regression guards for behaviour that must survive Step 3.

- [ ] **Step 3: Implement**

In `engine/appc/input.py:_resolve_destination`, insert the focused main window at the head of `candidates`. Replace the line `candidates = []` with:

```python
        candidates = []
        # BC routes keyboard input to the focused window first. Only a focused
        # MAIN window counts: QuickBattle's OpenConfigDialog focuses config
        # panes, which must not start capturing keyboard events. An event type
        # the focused window did not register falls through to the scan below
        # unchanged — that is what keeps the bridge crew menus on F1-F5.
        import App as _App
        _top = _App.TopWindow_GetTopWindow()
        _focus = _top.GetFocus() if _top is not None else None
        if _focus is not None:
            _mains = getattr(_top, "_main_windows", None)
            if isinstance(_mains, dict) and any(w is _focus for w in _mains.values()):
                candidates.append(_focus)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_keyboard_binding.py -q`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Run the neighbouring input suites**

Run: `uv run pytest tests/unit/test_fkey_input_chain.py tests/unit/test_fire_key_input_chain.py tests/unit/test_raw_keyboard_dispatch.py tests/unit/test_input_event_constants.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/input.py tests/unit/test_keyboard_binding.py
git commit -m "feat(input): route keyboard events to the focused main window first"
```

---

### Task 4: Register the cinematic handlers on first toggle

**Files:**
- Modify: `engine/appc/top_window.py` (`ToggleCinematicWindow`, from Task 1)
- Test: `tests/unit/test_top_window.py`

**Interfaces:**
- Consumes: `_TopWindow.ToggleCinematicWindow()` (Task 2).
- Produces: no new public names. After the first toggle, the `MWT_CINEMATIC` window's `_handlers` dict contains `App.ET_INPUT_CINEMATIC_CHASE` among others.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_top_window.py`:

```python
def test_first_toggle_registers_the_sdk_cinematic_handlers():
    """CinematicInterfaceHandlers.Initialize(pWindow) is what binds F1-F6 to
    camera modes. BC's engine runs it at window construction; we run it lazily
    on first toggle, because the module imports Camera and must not be pulled
    into App bootstrap."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    assert cine._handlers == {}
    tw.ToggleCinematicWindow()
    assert cine._handlers.get(App.ET_INPUT_CINEMATIC_CHASE)
    assert cine._handlers.get(App.ET_INPUT_CINEMATIC_FREEORBIT)


def test_handlers_are_registered_once_not_per_toggle():
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)
    for _ in range(4):
        tw.ToggleCinematicWindow()
    assert len(cine._handlers[App.ET_INPUT_CINEMATIC_CHASE]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -q -k "registers_the_sdk or registered_once"`
Expected: FAIL — `assert None` / `KeyError`, because nothing registers the handlers.

- [ ] **Step 3: Implement**

In `engine/appc/top_window.py`, add the lazy init to `ToggleCinematicWindow` (before the focus flip):

```python
    def ToggleCinematicWindow(self) -> None:
        cine = self._main_windows.get(MWT_CINEMATIC)
        if cine is None:
            return
        self._init_cinematic_handlers(cine)
        self._focus = None if self._focus is cine else cine

    def _init_cinematic_handlers(self, cine) -> None:
        """Run the SDK's CinematicInterfaceHandlers.Initialize once, on first
        toggle. Deferred (not done at construction) because the module imports
        Camera, which must not enter App bootstrap.

        A failure here must not wedge the toggle — cinematic mode without its
        F-key handlers is degraded, not broken — but it must not be silent
        either, or a missing-surface gap would look like a working feature.
        """
        if getattr(cine, "_handlers_initialized", False):
            return
        cine._handlers_initialized = True
        try:
            import CinematicInterfaceHandlers
            CinematicInterfaceHandlers.Initialize(cine)
        except Exception as exc:  # noqa: BLE001 - see docstring
            print("[cinematic] CinematicInterfaceHandlers.Initialize failed:", exc)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -q`
Expected: PASS. If `Initialize` printed a failure, treat it as a real gap: read the traceback, and record the missing surface rather than widening the `except`.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(cinematic): register the SDK cinematic key handlers on first toggle"
```

---

### Task 5: Hide the tactical HUD in cinematic mode

**Files:**
- Modify: `engine/host_loop.py:2381-2393` (`_tactical_hud_visible`)
- Modify: `engine/host_loop.py:6990` (the call site)
- Test: `tests/unit/test_tactical_hud_visible.py`

**Interfaces:**
- Consumes: `_TopWindow.is_cinematic_active()` (Task 2).
- Produces: `_tactical_hud_visible(*, is_exterior, spv_open, cutscene_active, bridge_tactical_active=False, cinematic_active=False) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_tactical_hud_visible.py`:

```python
def test_hud_hidden_in_cinematic_mode():
    """BC's cinematic mode is a clean camera view — no tactical HUD. It is NOT
    a cutscene, so the letterbox stays off; only the HUD goes."""
    from engine.host_loop import _tactical_hud_visible
    assert _tactical_hud_visible(
        is_exterior=True, spv_open=False, cutscene_active=False,
        cinematic_active=True) is False


def test_hud_visible_outside_cinematic_mode():
    from engine.host_loop import _tactical_hud_visible
    assert _tactical_hud_visible(
        is_exterior=True, spv_open=False, cutscene_active=False,
        cinematic_active=False) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_tactical_hud_visible.py -q -k cinematic`
Expected: FAIL — `TypeError: _tactical_hud_visible() got an unexpected keyword argument 'cinematic_active'`.

- [ ] **Step 3: Implement**

In `engine/host_loop.py`, extend the signature and the return:

```python
def _tactical_hud_visible(*, is_exterior: bool, spv_open: bool,
                          cutscene_active: bool,
                          bridge_tactical_active: bool = False,
                          cinematic_active: bool = False) -> bool:
```

and change the return to:

```python
    return (is_exterior or bridge_tactical_active) and not spv_open \
        and not cutscene_active and not cinematic_active
```

Add to the docstring, after the existing cutscene sentence:

```
    Also hidden in BC's cinematic mode (F9), which is a clean camera view.
    Unlike a cutscene it applies no letterbox — only the HUD goes.
```

- [ ] **Step 4: Wire the call site**

At `engine/host_loop.py:6990`, add the new argument to the existing call (the `TopWindow_GetTopWindow` import is already in scope two lines above):

```python
                _tac_visible = _tactical_hud_visible(
                    is_exterior=view_mode.is_exterior,
                    spv_open=ship_property_viewer.is_open(),
                    cutscene_active=TopWindow_GetTopWindow().IsCutsceneMode(),
                    bridge_tactical_active=_bridge_tactical_active,
                    cinematic_active=TopWindow_GetTopWindow().is_cinematic_active())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_tactical_hud_visible.py tests/host/test_view_mode.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_tactical_hud_visible.py
git commit -m "feat(cinematic): hide the tactical HUD while cinematic mode is active"
```

---

## After the plan

**Live verification is required before this is called done.** The change touches
the dispatch path the bridge crew menus run through, and those are
live-verified. On the bridge, confirm F1–F5 still open the officer menus. In
space, confirm F9 hides the HUD and F2/F3/F5 change the camera.

**Expect three dead keys.** F1 DropAndWatch, F4 TorpCam and F6 FreeOrbit resolve
to mode classes that do not exist yet, so those keys will do nothing. That is
known and specified, not a defect in this work. `MapCameraMode` (which powers
F6 FreeOrbit) is the highest-value follow-on.

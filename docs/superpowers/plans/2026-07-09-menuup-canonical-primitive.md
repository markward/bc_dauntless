# `MenuUp()` Canonical Primitive + `AT_MENU_UP`/`AT_MENU_DOWN` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CharacterClass.MenuUp()`/`MenuDown()` the canonical primitive that raises/lowers a bridge officer's menu (as in BC), turn the crew-menu panel into a consumer of it, and wire the SDK `AT_MENU_UP`/`AT_MENU_DOWN` `CharacterAction`s onto it — so scripted menu beats work and the currently-dead direct `MenuUp()` callers (QuickBattle's `g_pXO.MenuUp()`, `BridgeHandlers`' click seam) come alive.

**Architecture:** Today the layering is inverted — the CEF panel opens the menu (`toggle_menu`) and calls `officer.MenuUp()` downstream as a flag+turn notification, so `MenuUp()` opens nothing. We flip it: the panel gains **pure** view primitives (`show_menu`/`hide_menu`) that never call back into `MenuUp`; `MenuUp()`/`MenuDown()` become the primitive that drives those, sets the flag, requests the turn, and fires the tutorial event; `toggle_menu`/`close_open_menu` delegate to them. The spoken "Yes sir" acknowledgement stays on the **click path only** (BC plays it in `CharacterInteraction` *after* `MenuUp()`, never inside it), so a scripted `AT_MENU_UP` is silent.

**Tech Stack:** Python 3 (engine); pytest. No native/renderer change — no `dauntless` rebuild.

## Global Constraints

- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs `tests/known_failures.txt`). A failure is "pre-existing" ONLY if that ledger says so — never eyeball it.
- **Pure Python only** — do not edit `native/`.
- **No recursion, by construction:** `show_menu`/`hide_menu` must NEVER call `MenuUp`/`MenuDown` and must never acknowledge. `MenuUp`/`MenuDown` are the only things that call them.
- **Acknowledgement rule (BC-faithful):** the "Yes sir" line lives in `CharacterInteraction` (`BridgeHandlers.py:640`), which BC calls on the **click** path after `MenuUp()`. It must NOT be inside `MenuUp()`. A **scripted** `AT_MENU_UP` fires **no** acknowledgement.
- **Best-effort:** `Play()` must never raise; any dispatch miss (no cast / no menu / no panel / exception) completes the action inline so a mission `TGSequence` never stalls. Headless (no panel) → flag + turn + event only, never raise.
- **Never orphan tests:** existing crew-menu tests encode the OLD layering. Update them in the same change; do not delete or skip them.
- `MenuUp()` returns `int` (`1` raised / `0` not) — `BridgeHandlers` branches on it.

---

## File Structure

- **Modify** `engine/ui/crew_menu_panel.py` — add pure view primitives (`show_menu`, `hide_menu`, `open_officer`, `_officer_for_menu`); rewrite `toggle_menu`/`close_open_menu` to delegate; retire `_reconcile_turn`; keep `_acknowledge` click-path-only.
- **Modify** `engine/ui/crew_menu_hotkeys.py` — add `get_panel()` over the existing `_wired_panel`.
- **Modify** `engine/appc/characters.py` — `MenuUp`/`MenuDown` become canonical; add `_get_menu_panel()` seam.
- **Modify** `engine/appc/ai.py` — `AT_MENU_UP`/`AT_MENU_DOWN` dispatch.
- **Create** `tests/unit/test_crew_menu_view_primitives.py` — the pure view primitives + `get_panel`.
- **Create** `tests/unit/test_character_menu_primitive.py` — `MenuUp`/`MenuDown` as the canonical primitive.
- **Create** `tests/unit/test_character_action_menu.py` — `AT_MENU_UP`/`AT_MENU_DOWN` dispatch + the no-ack rule.
- **Modify** `tests/unit/test_crew_menu_turn.py` — its fake officers must now drive the view (that is what the real `MenuUp` does).

---

## Task 1: Panel view primitives + `get_panel()` seam

Purely **additive** — nothing calls these yet, so no behaviour changes.

**Files:**
- Modify: `engine/ui/crew_menu_panel.py` (add methods near `_menu_officer`, ~line 224)
- Modify: `engine/ui/crew_menu_hotkeys.py` (add `get_panel` near `wire`, ~line 71)
- Test: `tests/unit/test_crew_menu_view_primitives.py`

**Interfaces:**
- Produces:
  - `CrewMenuPanel.show_menu(menu) -> None` — pure view open (sets `_open_menu_id`, clears `_expanded_ids`, `menu.SendActivationEvent()`). Idempotent. Never calls `MenuUp`/`MenuDown`, never acknowledges.
  - `CrewMenuPanel.hide_menu() -> None` — pure view close. Idempotent.
  - `CrewMenuPanel.open_officer()` — the `CharacterClass` owning the currently-open menu, or `None` (public promotion of `_menu_officer`).
  - `CrewMenuPanel._officer_for_menu(menu)` — the `CharacterClass` owning `menu` (by its label), or `None`.
  - `crew_menu_hotkeys.get_panel()` — the wired `CrewMenuPanel`, or `None` (headless).
- Consumes: existing `ensure_widget_id`, `_menu_officer`, `crew_menu_hotkeys.resolve_character`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_crew_menu_view_primitives.py`:

```python
"""Pure view primitives: show_menu/hide_menu set view state ONLY.

They must never call MenuUp/MenuDown and never acknowledge — CharacterClass.MenuUp
is the canonical primitive that drives them (BC layering). That one-way rule is
what makes recursion impossible.
"""
from __future__ import annotations

import engine.ui.crew_menu_panel as cmp_mod
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


def _panel() -> CrewMenuPanel:
    p = CrewMenuPanel.__new__(CrewMenuPanel)   # bypass heavy __init__ (CEF/TCW)
    p._open_menu_id = None
    p._expanded_ids = set()
    return p


def _patch_ids(monkeypatch):
    ids: dict[int, int] = {}
    nxt = [1]

    def _ensure(m):
        if id(m) not in ids:
            ids[id(m)] = nxt[0]
            nxt[0] += 1
        return ids[id(m)]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure)
    return _ensure


def test_show_menu_opens_and_is_idempotent(monkeypatch):
    ensure = _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    p._expanded_ids.add(99)

    p.show_menu(helm)
    assert p._open_menu_id == ensure(helm)
    assert p._expanded_ids == set()      # reopened menu starts collapsed

    p._expanded_ids.add(7)
    p.show_menu(helm)                    # already open -> no-op (does NOT reset)
    assert p._open_menu_id == ensure(helm)
    assert p._expanded_ids == {7}


def test_show_menu_switches(monkeypatch):
    ensure = _patch_ids(monkeypatch)
    p, helm, tac = _panel(), STMenu("Helm"), STMenu("Tactical")
    p.show_menu(helm)
    p.show_menu(tac)
    assert p._open_menu_id == ensure(tac)     # single-open view state


def test_hide_menu_closes_and_is_idempotent(monkeypatch):
    _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    p.show_menu(helm)
    p.hide_menu()
    assert p._open_menu_id is None
    assert p._expanded_ids == set()
    p.hide_menu()                        # idempotent
    assert p._open_menu_id is None


def test_show_menu_fires_activation_event(monkeypatch):
    _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    fired = []
    monkeypatch.setattr(helm, "SendActivationEvent",
                        lambda: fired.append(True), raising=False)
    p.show_menu(helm)
    assert fired == [True]               # BC broadcasts activation on open


def test_show_hide_never_touch_menuup(monkeypatch):
    """The one-way rule: view primitives must not call back into MenuUp/MenuDown."""
    _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    calls = []
    monkeypatch.setattr(p, "_officer_for_menu",
                        lambda m: (_ for _ in ()).throw(AssertionError(
                            "show_menu must not resolve/notify officers")),
                        raising=False)
    p.show_menu(helm)      # must not raise -> proves it never resolved an officer
    p.hide_menu()
    assert calls == []


def test_get_panel_returns_wired_panel(monkeypatch):
    from engine.ui import crew_menu_hotkeys
    monkeypatch.setattr(crew_menu_hotkeys, "_wired_panel", None, raising=False)
    assert crew_menu_hotkeys.get_panel() is None
    sentinel = object()
    monkeypatch.setattr(crew_menu_hotkeys, "_wired_panel", sentinel, raising=False)
    assert crew_menu_hotkeys.get_panel() is sentinel
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_crew_menu_view_primitives.py -v
```
Expected: FAIL — `CrewMenuPanel` has no `show_menu`; `crew_menu_hotkeys` has no `get_panel`.

- [ ] **Step 3: Add the panel view primitives**

In `engine/ui/crew_menu_panel.py`, immediately after `_menu_officer` (~line 233):

```python
    def open_officer(self):
        """The CharacterClass owning the currently-open top-level menu, or None.
        Public reader — CharacterClass.MenuUp needs it to enforce single-open."""
        return self._menu_officer()

    def _officer_for_menu(self, menu):
        """The CharacterClass owning `menu` (resolved by its label), or None.
        Unlike _menu_officer (which resolves the menu that is ALREADY open), this
        resolves an arbitrary target menu — what toggle_menu needs before opening."""
        try:
            from engine.ui import crew_menu_hotkeys
            return crew_menu_hotkeys.resolve_character(menu.GetLabel())
        except Exception:
            return None

    def show_menu(self, menu) -> None:
        """PURE view open: make `menu` the open top-level menu. Idempotent.

        Never calls MenuUp/MenuDown and never acknowledges. CharacterClass.MenuUp
        is BC's canonical primitive and the ONLY caller that should drive this —
        that one-way rule is what makes recursion impossible."""
        wid = ensure_widget_id(menu)
        if self._open_menu_id == wid:
            return                       # already open
        self._open_menu_id = wid
        self._expanded_ids.clear()       # a reopened menu starts collapsed
        try:
            menu.SendActivationEvent()   # BC broadcasts activation on open
        except Exception:
            _logger.debug("crew-menu: activation event failed", exc_info=True)

    def hide_menu(self) -> None:
        """PURE view close. Idempotent. Never calls MenuUp/MenuDown."""
        if self._open_menu_id is None:
            return
        self._open_menu_id = None
        self._expanded_ids.clear()
```

- [ ] **Step 4: Add the `get_panel()` seam**

In `engine/ui/crew_menu_hotkeys.py`, immediately after `wire()` (~line 81):

```python
def get_panel():
    """The CrewMenuPanel wired by wire(), or None (headless / no UI).
    The seam CharacterClass.MenuUp uses to reach the view."""
    return _wired_panel
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/unit/test_crew_menu_view_primitives.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 6: Confirm nothing regressed (these are additive)**

```bash
uv run pytest tests/unit/test_crew_menu_panel.py tests/unit/test_crew_menu_turn.py tests/unit/test_crew_menu_hotkeys.py -q 2>&1 | tail -5
```
Expected: PASS (unchanged — nothing calls the new methods yet).

- [ ] **Step 7: Commit**

```bash
git add engine/ui/crew_menu_panel.py engine/ui/crew_menu_hotkeys.py tests/unit/test_crew_menu_view_primitives.py
git commit -m "feat(menu): pure panel view primitives (show_menu/hide_menu) + get_panel seam"
```

---

## Task 2: The layering flip — `MenuUp()`/`MenuDown()` become canonical

This is **atomic**: the panel must stop owning the view-open at the same moment `MenuUp` starts owning it, or the tutorial event would fire twice. Do not split.

**Files:**
- Modify: `engine/appc/characters.py` (`MenuUp` ~626, `MenuDown` ~634; add `_get_menu_panel`)
- Modify: `engine/ui/crew_menu_panel.py` (`toggle_menu` ~252, `close_open_menu` ~305; delete `_reconcile_turn` ~235-250)
- Test: `tests/unit/test_character_menu_primitive.py`
- Modify: `tests/unit/test_crew_menu_turn.py` (fakes must now drive the view)

**Interfaces:**
- Consumes: `panel.show_menu/hide_menu/open_officer/_officer_for_menu` and `crew_menu_hotkeys.get_panel()` (Task 1); existing `_notify_menu(turn)`, `dispatch_character_menu(character, is_open)`, `GetMenu()` (returns falsy `_NULL_MENU` when unset), `menu.IsEnabled()`.
- Produces:
  - `CharacterClass.MenuUp() -> int` — raises this officer's menu: closes any other officer's menu, drives `panel.show_menu(GetMenu())`, sets the flag, requests the turn-to-captain, fires `dispatch_character_menu(open)`. Returns `1` raised / `0` nothing to raise. **Never acknowledges.**
  - `CharacterClass.MenuDown() -> None` — hides its menu if open, clears the flag, requests the turn-back, fires `dispatch_character_menu(close)`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_character_menu_primitive.py`:

```python
"""CharacterClass.MenuUp/MenuDown are BC's canonical menu primitive.

BC: `if (pCharacter.MenuUp()): CharacterInteraction(pCharacter)` (BridgeHandlers:612)
and `g_pXO.MenuUp()` (QuickBattle:3368) -- MenuUp RAISES the menu. It must drive the
panel, set the flag, turn the officer, and fire the tutorial event -- and must NOT
acknowledge (BC plays "Yes sir" in CharacterInteraction, click path only).
"""
from __future__ import annotations

import engine.appc.characters as chars


class _Menu:
    def __init__(self, enabled=True):
        self._enabled = enabled
    def IsEnabled(self):
        return 1 if self._enabled else 0


class _Panel:
    """Records the pure view calls MenuUp/MenuDown are supposed to make."""
    def __init__(self):
        self.shown = []
        self.hidden = 0
        self._officer = None
    def open_officer(self):
        return self._officer
    def show_menu(self, menu):
        self.shown.append(menu)
    def hide_menu(self):
        self.hidden += 1


def _officer(monkeypatch, menu, panel, turns, events):
    """A real CharacterClass with GetMenu/_notify_menu/dispatch stubbed."""
    c = chars.CharacterClass.__new__(chars.CharacterClass)
    c._data = {}
    c._menu = menu
    monkeypatch.setattr(type(c), "GetMenu", lambda self: self._menu, raising=False)
    monkeypatch.setattr(type(c), "_notify_menu",
                        lambda self, turn: turns.append(turn), raising=False)
    monkeypatch.setattr(chars, "dispatch_character_menu",
                        lambda character, is_open: events.append(is_open))
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: panel)
    return c


def test_menu_up_raises_menu_sets_flag_turns_and_signals(monkeypatch):
    panel, turns, events = _Panel(), [], []
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)

    assert c.MenuUp() == 1              # BridgeHandlers branches on this
    assert panel.shown == [menu]        # drove the view (the whole point)
    assert c._data["MenuUp"] is True
    assert turns == [True]              # turn-to-captain
    assert events == [True]             # tutorial signal


def test_menu_up_returns_zero_when_no_menu(monkeypatch):
    panel, turns, events = _Panel(), [], []
    c = _officer(monkeypatch, menu=chars._NULL_MENU, panel=panel,
                 turns=turns, events=events)
    assert c.MenuUp() == 0              # falsy _NULL_MENU -> nothing to raise
    assert panel.shown == []
    assert turns == [] and events == []


def test_menu_up_returns_zero_when_disabled(monkeypatch):
    panel, turns, events = _Panel(), [], []
    c = _officer(monkeypatch, _Menu(enabled=False), panel, turns, events)
    assert c.MenuUp() == 0              # stock BC: disabled menus don't raise
    assert panel.shown == []


def test_menu_up_closes_the_other_officers_menu(monkeypatch):
    """Single-open: raising B closes A (and turns A back)."""
    panel, turns, events = _Panel(), [], []
    other_down = []

    class _Other:
        def MenuDown(self):
            other_down.append(True)

    other = _Other()
    panel._officer = other
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)

    assert c.MenuUp() == 1
    assert other_down == [True]         # previous officer closed + turned back
    assert panel.shown == [menu]


def test_menu_down_hides_clears_turns_back(monkeypatch):
    panel, turns, events = _Panel(), [], []
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)
    panel._officer = c                  # this officer's menu is the open one

    c.MenuDown()
    assert panel.hidden == 1
    assert c._data["MenuUp"] is False
    assert turns == [False]             # turn-back
    assert events == [False]


def test_menu_down_does_not_hide_someone_elses_menu(monkeypatch):
    panel, turns, events = _Panel(), [], []
    panel._officer = object()           # a DIFFERENT officer is open
    c = _officer(monkeypatch, _Menu(), panel, turns, events)
    c.MenuDown()
    assert panel.hidden == 0            # must not close another officer's menu


def test_headless_no_panel_is_safe(monkeypatch):
    turns, events = [], []
    c = _officer(monkeypatch, _Menu(), panel=None, turns=turns, events=events)
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: None)
    assert c.MenuUp() == 1              # flag + turn + event still fire
    assert turns == [True] and events == [True]
    c.MenuDown()                        # must not raise
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_character_menu_primitive.py -v
```
Expected: FAIL — `characters._get_menu_panel` does not exist; `MenuUp` returns `1` without driving any panel.

- [ ] **Step 3: Make `MenuUp`/`MenuDown` canonical**

In `engine/appc/characters.py`, replace `MenuUp`/`MenuDown` (~626-636) with:

```python
    def MenuUp(self, *args) -> int:
        """Raise this officer's menu. BC's canonical primitive: BridgeHandlers'
        click seam does `if (pCharacter.MenuUp()): CharacterInteraction(...)` and
        QuickBattle does `g_pXO.MenuUp()` to bring Saffi's menu up. It drives the
        panel view, sets the state flag, and turns the officer to the captain.

        It does NOT acknowledge — BC plays the "Yes sir" line in
        CharacterInteraction, on the CLICK path only, so a scripted AT_MENU_UP
        stays silent. Returns 1 when the menu was raised, 0 when there was
        nothing to raise (no menu / disabled)."""
        menu = self.GetMenu()
        if not menu or not menu.IsEnabled():
            return 0                         # stock BC: nothing to raise
        panel = _get_menu_panel()
        if panel is not None and panel.open_officer() is not self:
            other = panel.open_officer()
            if other is not None:
                other.MenuDown()             # single-open: close + turn them back
            panel.show_menu(menu)
        self._data["MenuUp"] = True
        self._notify_menu(turn=True)         # turn-to-captain (None-ctrl guarded)
        dispatch_character_menu(self, is_open=True)
        return 1

    def MenuDown(self, *args) -> None:
        """Lower this officer's menu (BC's MenuDown). Hides the view only if this
        officer's menu is the open one, clears the flag, turns them back, and
        fires the tutorial close signal."""
        panel = _get_menu_panel()
        if panel is not None and panel.open_officer() is self:
            panel.hide_menu()
        self._data["MenuUp"] = False
        self._notify_menu(turn=False)
        dispatch_character_menu(self, is_open=False)
```

Add the seam helper at module level in `engine/appc/characters.py` (near `dispatch_character_menu`, ~line 700):

```python
def _get_menu_panel():
    """The wired CrewMenuPanel, or None (headless / no UI). The seam MenuUp uses
    to reach the view without engine.appc importing the UI at module load."""
    try:
        from engine.ui import crew_menu_hotkeys
        return crew_menu_hotkeys.get_panel()
    except Exception:
        return None
```

- [ ] **Step 4: Make the panel delegate (retire the inversion)**

In `engine/ui/crew_menu_panel.py`, **delete** `_reconcile_turn` (~235-250) and replace `toggle_menu` (~252-279) and `close_open_menu` (~305-320) with:

```python
    def toggle_menu(self, menu) -> None:
        """Open `menu` (closing any other), or close it if already open.
        Single-open invariant shared by hotkeys and CEF title clicks.
        Disabled menus stay closed (stock BC); non-menus are ignored.

        DELEGATES to the officer's MenuUp()/MenuDown() — BC's canonical primitive,
        which drives the view, the turn, and the tutorial event. The spoken
        acknowledgement fires HERE, on the click path only, mirroring BC's
        `if (pCharacter.MenuUp()): CharacterInteraction(pCharacter)` — a SCRIPTED
        AT_MENU_UP must stay silent."""
        if not isinstance(menu, STMenu) or not menu.IsEnabled():
            return
        wid = ensure_widget_id(menu)
        if self._open_menu_id == wid:                 # already open -> close it
            officer = self.open_officer()
            if officer is not None:
                officer.MenuDown()
            else:
                self.hide_menu()                      # unowned menu: view only
            return
        officer = self._officer_for_menu(menu)
        if officer is not None:
            if officer.MenuUp():                      # raises + turns + signals
                self._acknowledge(menu)               # BC: CharacterInteraction
            return
        # Unowned menu (no officer resolves): honour single-open + the view.
        other = self.open_officer()
        if other is not None:
            other.MenuDown()
        self.show_menu(menu)
        self._acknowledge(menu)

    def close_open_menu(self) -> bool:
        """Close any open menu; True if one was open (ESC consumes the press in
        that case — see host_loop's modal ladder). Delegates to the officer's
        MenuDown() (which hides the view, turns them back, and signals)."""
        if self._open_menu_id is None:
            return False
        officer = self.open_officer()
        if officer is not None:
            officer.MenuDown()
        else:
            self.hide_menu()
        return True
```

- [ ] **Step 5: Update `tests/unit/test_crew_menu_turn.py` to the new layering**

These tests encode the OLD layering: their fake officers only *record* `MenuUp`, so with the flip nothing would open the view. The real `MenuUp` drives the view — so the fakes must too. Replace the `_Officer` class and `_patch_panel` helper with:

```python
class _Officer:
    """Fake officer that behaves like the REAL CharacterClass.MenuUp: it drives
    the panel view (that is the whole point of the canonical primitive)."""
    def __init__(self, name: str, panel=None, menu=None):
        self.name = name
        self._up = False
        self.up_calls = 0
        self.down_calls = 0
        self.menu_events: list[int] = []
        self._panel = panel
        self._menu = menu

    def MenuUp(self) -> int:
        self._up = True
        self.up_calls += 1
        if self._panel is not None and self._menu is not None:
            other = self._panel.open_officer()
            if other is not None and other is not self:
                other.MenuDown()
            self._panel.show_menu(self._menu)
        self.menu_events.append(1)
        return 1

    def MenuDown(self) -> None:
        self._up = False
        self.down_calls += 1
        if self._panel is not None and self._panel.open_officer() is self:
            self._panel.hide_menu()
        self.menu_events.append(0)

    @property
    def is_up(self) -> bool:
        return self._up


def _patch_panel(monkeypatch, panel, officers_by_menu: dict):
    """Wire ensure_widget_id + officer resolution for the DELEGATING toggle_menu.

    officers_by_menu: {menu_object: _Officer|None}. toggle_menu now resolves the
    TARGET menu's officer (_officer_for_menu) before opening, and the OPEN menu's
    officer (open_officer) to close/switch."""
    ids: dict[int, int] = {}
    nxt = [1]

    def _ensure(m):
        if id(m) not in ids:
            ids[id(m)] = nxt[0]
            nxt[0] += 1
        return ids[id(m)]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure)

    def _officer_for_menu(menu, _p=panel):
        return officers_by_menu.get(menu)

    def _open_officer(_p=panel):
        for m, off in officers_by_menu.items():
            if panel._open_menu_id == _ensure(m):
                return off
        return None

    monkeypatch.setattr(panel, "_officer_for_menu", _officer_for_menu, raising=False)
    monkeypatch.setattr(panel, "open_officer", _open_officer, raising=False)
    monkeypatch.setattr(panel, "_acknowledge", lambda menu: None, raising=False)
```

Then update each test to build officers with their panel+menu and to key `officers_by_menu` by the **menu object** (not widget id). For example `test_open_calls_menu_up` becomes:

```python
def test_open_calls_menu_up(monkeypatch):
    """Opening a menu calls MenuUp() on the resolved officer."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)  # open

    assert officer.is_up, "MenuUp() should have been called on open"
    assert officer.up_calls == 1
    assert officer.down_calls == 0
```

Work through the rest of the file the same way, **preserving each test's behavioural intent** (open→MenuUp; toggle-same→MenuDown; switch A→B→MenuDown(A)+MenuUp(B); `close_open_menu`→MenuDown; no-officer menus still toggle cleanly; disabled menus never call MenuUp; the `dispatch_character_menu` open/close signals). Do NOT delete or skip any test. If a test asserted `dispatch_character_menu` was called *by the panel*, it now fires from `MenuUp`/`MenuDown` — assert it via the officer's `menu_events` recorder.

- [ ] **Step 6: Run the primitive tests + all crew-menu regressions**

```bash
uv run pytest tests/unit/test_character_menu_primitive.py tests/unit/test_crew_menu_turn.py tests/unit/test_crew_menu_panel.py tests/unit/test_crew_menu_hotkeys.py tests/unit/test_character_menu_dispatch.py tests/integration/test_crew_menu_ack.py tests/integration/test_bridge_menu_hotkeys.py tests/unit/test_bridge_officer_picking.py -v 2>&1 | tail -25
```
Expected: PASS. The click path must be observably unchanged (open + turn + ack + activation + tutorial signal). If a test fails because it asserted the OLD layering, fix the test to the new layering — never weaken the assertion.

- [ ] **Step 7: Run the FULL GATE (this touches the live bridge UI path)**

```bash
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: green (pytest 0 / ctest 0, no new `known_failures` entries).

- [ ] **Step 8: Commit**

```bash
git add engine/appc/characters.py engine/ui/crew_menu_panel.py tests/unit/test_character_menu_primitive.py tests/unit/test_crew_menu_turn.py
git commit -m "refactor(menu): MenuUp/MenuDown become BC's canonical menu primitive; panel delegates"
```

---

## Task 3: `AT_MENU_UP` / `AT_MENU_DOWN` dispatch

**Files:**
- Modify: `engine/appc/ai.py` (`CharacterAction.Play`, add the branch + `_menu_action` helper next to `_queue_turn`)
- Test: `tests/unit/test_character_action_menu.py`

**Interfaces:**
- Consumes: `CharacterClass.MenuUp()`/`MenuDown()` (Task 2), `characters.CharacterClass_Cast`.
- Produces: `CharacterAction.Play()` — `AT_MENU_UP` calls `cc.MenuUp()`, `AT_MENU_DOWN` calls `cc.MenuDown()`; both complete **inline**; every miss (no cast / exception) completes inline. **No acknowledgement.**

- [ ] **Step 1: Write the failing test**

`tests/unit/test_character_action_menu.py`:

```python
"""AT_MENU_UP / AT_MENU_DOWN are the sequenceable wrappers around BC's
CharacterClass.MenuUp()/MenuDown() (E1M1 crew-intro, E8M2 Liu, QB intro).

A SCRIPTED menu-up must NOT acknowledge -- BC plays "Yes sir" in
CharacterInteraction on the click path only; otherwise officers would bark over
the mission's own dialogue.
"""
from engine.appc.ai import CharacterAction


class _Char:
    def __init__(self):
        self.up_calls = 0
        self.down_calls = 0
    def GetCharacterName(self):
        return "Brex"
    def MenuUp(self):
        self.up_calls += 1
        return 1
    def MenuDown(self):
        self.down_calls += 1


def _patch_cast(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast", lambda c: c)


def test_at_menu_up_raises_menu_and_completes_inline(monkeypatch):
    _patch_cast(monkeypatch)
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_MENU_UP)
    act.Play()
    assert ch.up_calls == 1
    assert act.IsPlaying() is False          # inline: open/close is instant


def test_at_menu_down_lowers_menu_and_completes_inline(monkeypatch):
    _patch_cast(monkeypatch)
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_MENU_DOWN)
    act.Play()
    assert ch.down_calls == 1
    assert act.IsPlaying() is False


def test_scripted_menu_up_does_not_acknowledge(monkeypatch):
    """The ack trap: BC acks in CharacterInteraction (click path), NOT MenuUp."""
    _patch_cast(monkeypatch)
    acks = []
    from engine.appc import crew_speech
    monkeypatch.setattr(crew_speech, "acknowledge",
                        lambda char: acks.append(char), raising=False)
    ch = _Char()
    CharacterAction(ch, CharacterAction.AT_MENU_UP).Play()
    assert acks == []                        # silent under a mission sequence


def test_at_menu_up_completes_inline_when_cast_fails(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: None)
    act = CharacterAction(_Char(), CharacterAction.AT_MENU_UP)
    act.Play()
    assert act.IsPlaying() is False          # never stalls the sequence


def test_at_menu_up_does_not_raise_when_menuup_raises(monkeypatch):
    _patch_cast(monkeypatch)

    class _Boom(_Char):
        def MenuUp(self):
            raise RuntimeError("boom")

    act = CharacterAction(_Boom(), CharacterAction.AT_MENU_UP)
    act.Play()                                # must not propagate
    assert act.IsPlaying() is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_character_action_menu.py -v
```
Expected: FAIL — `AT_MENU_UP` currently falls through to the inline no-op, so `up_calls` stays 0.

- [ ] **Step 3: Add the dispatch**

In `engine/appc/ai.py` `Play()`, add after the `AT_GLANCE_AT`/`AT_GLANCE_AWAY` block:

```python
        if at in (self.AT_MENU_UP, self.AT_MENU_DOWN):
            self._menu_action(up=(at == self.AT_MENU_UP))
            return
```

Add the helper next to `_queue_glance`:

```python
    def _menu_action(self, *, up: bool) -> None:
        # AT_MENU_UP/AT_MENU_DOWN are the sequenceable wrappers around BC's
        # CharacterClass.MenuUp()/MenuDown() (E1M1 crew-intro raises Brex's menu
        # then points the tutorial cursor at its buttons; E8M2 raises Liu's).
        # Completes INLINE — raising/lowering a menu is instant; sequences supply
        # their own delays. No acknowledgement: BC plays "Yes sir" in
        # CharacterInteraction on the CLICK path only, so a scripted menu-up must
        # stay silent. Best-effort: Play() must never raise.
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            if cc is not None:
                if up:
                    cc.MenuUp()
                else:
                    cc.MenuDown()
        except Exception:
            pass
        self.Completed()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/unit/test_character_action_menu.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_menu.py
git commit -m "feat(menu): AT_MENU_UP/AT_MENU_DOWN dispatch onto CharacterClass.MenuUp/MenuDown"
```

---

## Task 4: End-to-end integration + full gate

**Files:**
- Test: `tests/unit/test_menu_primitive_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3. No new production code expected — if the integration reveals a gap, fix it in the owning module, not the test.

- [ ] **Step 1: Write the integration test**

`tests/unit/test_menu_primitive_integration.py`:

```python
"""End-to-end (headless): the two entry points both work through the ONE primitive.

  scripted:  AT_MENU_UP  -> CharacterClass.MenuUp() -> panel view opens, NO ack
  click:     toggle_menu -> CharacterClass.MenuUp() -> panel view opens, ACK fires

This is the layering the SDK demands (BridgeHandlers: `if (pCharacter.MenuUp()):
CharacterInteraction(...)`), and the ack asymmetry is the whole point.
"""
from __future__ import annotations

import engine.appc.characters as chars
import engine.ui.crew_menu_panel as cmp_mod
from engine.appc.ai import CharacterAction
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


def _panel():
    p = CrewMenuPanel.__new__(CrewMenuPanel)
    p._open_menu_id = None
    p._expanded_ids = set()
    return p


def _setup(monkeypatch):
    panel, menu = _panel(), STMenu("Engineering")
    ids = {}
    nxt = [1]

    def _ensure(m):
        if id(m) not in ids:
            ids[id(m)] = nxt[0]
            nxt[0] += 1
        return ids[id(m)]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure)

    officer = chars.CharacterClass.__new__(chars.CharacterClass)
    officer._data = {}
    officer._menu = menu
    monkeypatch.setattr(type(officer), "GetMenu", lambda self: self._menu,
                        raising=False)
    monkeypatch.setattr(type(officer), "_notify_menu",
                        lambda self, turn: None, raising=False)
    monkeypatch.setattr(chars, "dispatch_character_menu",
                        lambda character, is_open: None)
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: panel)

    monkeypatch.setattr(panel, "_officer_for_menu", lambda m: officer,
                        raising=False)
    monkeypatch.setattr(panel, "open_officer",
                        lambda: officer if panel._open_menu_id is not None else None,
                        raising=False)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    acks = []
    monkeypatch.setattr(panel, "_acknowledge", lambda m: acks.append(m),
                        raising=False)
    return panel, menu, officer, acks, _ensure


def test_scripted_at_menu_up_raises_menu_silently(monkeypatch):
    panel, menu, officer, acks, ensure = _setup(monkeypatch)

    CharacterAction(officer, CharacterAction.AT_MENU_UP).Play()

    assert panel._open_menu_id == ensure(menu)   # the menu is UP
    assert officer._data["MenuUp"] is True
    assert acks == []                            # scripted -> silent

    CharacterAction(officer, CharacterAction.AT_MENU_DOWN).Play()
    assert panel._open_menu_id is None           # and back DOWN
    assert officer._data["MenuUp"] is False


def test_click_raises_menu_and_acknowledges(monkeypatch):
    panel, menu, officer, acks, ensure = _setup(monkeypatch)

    panel.toggle_menu(menu)                      # the CEF click / hotkey path

    assert panel._open_menu_id == ensure(menu)   # same primitive raised it
    assert officer._data["MenuUp"] is True
    assert acks == [menu]                        # click -> "Yes sir"
```

- [ ] **Step 2: Run the integration test**

```bash
uv run pytest tests/unit/test_menu_primitive_integration.py -v
```
Expected: PASS (2 tests). If either fails, the entry points are not sharing the one primitive — fix the owning module.

- [ ] **Step 3: Run the FULL GATE**

```bash
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: green (pytest 0 / ctest 0 / 0 baselined).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_menu_primitive_integration.py
git commit -m "test(menu): scripted vs click entry points share the one primitive (ack asymmetry)"
```

---

## Task 5: GUI verification (manual, final sign-off)

**Files:** none (manual; the CEF/render path cannot be asserted headlessly).

- [ ] **Step 1: Launch and verify the click path is unchanged**

```bash
./build/dauntless
```
Click a bridge officer: their menu opens, they **turn to face the captain**, and they say **"Yes sir"**. ESC closes it and they turn back. Hotkeys (F1-F5) behave the same. Switching directly from one officer's menu to another closes the first and turns that officer back.

- [ ] **Step 2: Verify the scripted beats (the new behaviour)**

- **QuickBattle**: the win-sequence `g_pXO.MenuUp()` now brings **Saffi's menu up** (dead before this change).
- **E8M2**: Liu's Battle Group menu **raises on its scripted beat** and lowers on `AT_MENU_DOWN`.
- **E1M1 crew-intro**: each officer's menu **raises and lowers** on their intro beat — and **no officer says "Yes sir"** over the scripted dialogue (the ack must stay silent under a mission sequence). The tutorial's cursor-move/highlight is still absent — that is the deferred choreography slice, not a regression.

- [ ] **Step 3: Record the result**

Update the memory (`project_crew_menu_panel` / a new `project_menuup_canonical_primitive`) with the merge state and GUI findings. Note the layering: `MenuUp()` is BC's canonical menu primitive; the panel is a consumer; the ack is click-path-only.

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch`. Carry the follow-ups forward: the E1M1 crew-intro **choreography** actions (`MoveMouseToButton`, `SetUIObjectHighlighted`, `HoldMouseAtButton`, `MoveMouseToCenter`, `HoldMouseAtCenter`) that this unblocks; the QB XO **setup** menu (`g_pXOMenu`) if it is not reachable as the XO's `GetMenu()`; plus the still-open SP-A bug #7, SP-B other-mission `AT_MOVE` sweep, SP-D lift-door, and the orientation-family leftovers (`CS_TURNED` home, `_NOW` snap, snap-fallback edge).

---

## Self-Review

**Spec coverage:**
- Pure view primitives (`show_menu`/`hide_menu`, never call `MenuUp`) → Task 1. ✓
- `open_officer()` public reader + `_officer_for_menu` → Task 1. ✓
- `get_panel()` seam → Task 1. ✓
- `MenuUp()`/`MenuDown()` canonical (drive panel, single-open, flag, turn, tutorial event, `int` return, no ack) → Task 2. ✓
- Panel delegates; `_reconcile_turn` retired → Task 2. ✓
- Acknowledgement moves to the click path only → Task 2 (`toggle_menu`) + asserted in Tasks 3 & 4. ✓
- Headless (no panel) → flag + turn + event, no raise → Task 2. ✓
- `AT_MENU_UP`/`AT_MENU_DOWN` dispatch, inline completion, best-effort → Task 3. ✓
- Existing crew-menu tests updated, not orphaned → Task 2 Step 5. ✓
- Gate + GUI verify → Tasks 2, 4, 5. ✓
- Out-of-scope (crew-intro choreography; QB setup menu) → carried in Task 5 Step 4. ✓

**Placeholder scan:** No TBD/TODO. Task 2 Step 5 is the one place the implementer must adapt existing tests rather than transcribe — it names every behaviour to preserve and supplies the two helpers (`_Officer`, `_patch_panel`) verbatim plus a worked example, because rewriting all ~260 lines here would be noise.

**Type consistency:**
- `show_menu(menu) -> None`, `hide_menu() -> None`, `open_officer() -> CharacterClass|None`, `_officer_for_menu(menu) -> CharacterClass|None` — Task 1 defs; used in Tasks 2, 4.
- `crew_menu_hotkeys.get_panel()` — Task 1 def; consumed by `characters._get_menu_panel()` (Task 2).
- `CharacterClass.MenuUp() -> int` / `MenuDown() -> None` — Task 2 defs; called by `toggle_menu`/`close_open_menu` (Task 2) and `_menu_action` (Task 3).
- `_menu_action(*, up: bool)` — Task 3 def + call.
- `dispatch_character_menu(character, is_open)` — existing signature, unchanged.

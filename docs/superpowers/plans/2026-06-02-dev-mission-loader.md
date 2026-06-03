# Dev Mission Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the auto-listed dev-keybinding rows in the `--developer` pause menu with an actionable "Load Mission…" entry that opens a CEF-rendered centred-modal mission picker; selecting a mission swaps it in-process via `HostController.swap_mission`.

**Architecture:** Three layers stacked on the existing `developer-flag` branch:
(1) A new `dev_pause_menu_entries` registry in `engine/dev_mode.py` decoupled from keybindings, with the pause menu rewired to read it; the auto-listed keybinding rows and the "— DEVELOPER —" separator are removed.
(2) A new `MissionPicker(Panel)` in `engine/dev_mission_picker.py` that fits the existing PanelRegistry pump — `render_payload()` emits `setMissionPicker({tree, visible})` JS on state change; `dispatch_event(action)` handles `pick:<module>` and `cancel`; lazy registry walk on first `open()`.
(3) CEF assets (HTML section, JS renderer, CSS chrome) + host-loop wiring: construct picker, register with PanelRegistry, register dev pause-menu entry, extend `_apply_pause_menu_side_effects` to AND `not picker.is_open()` into pause visibility, give ESC picker-priority.

**Tech Stack:** Python 3.13, pybind11/CPython embed, CEF (off-screen rendering), HTML/CSS/JS, pytest, cmake. Reuses the surviving `engine/missions/` package (`MissionRegistry`, `discover`, `name_resolver`, `tgl_reader`) and `HostController.swap_mission`.

**Reference spec:** [docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md](../specs/2026-06-02-dev-mission-loader-design.md).

---

## File Structure

**New files:**
- `engine/dev_mission_picker.py` — `MissionPicker(Panel)` class.
- `native/assets/ui-cef/js/mission_picker.js` — `setMissionPicker({tree, visible})` JS renderer.
- `tests/unit/test_dev_mission_picker.py` — unit tests for the picker (no CEF required).

**Modified files:**
- `engine/dev_mode.py` — adds `_dev_pause_menu_entries: list`, `register_dev_pause_menu_entry(label, handler)`, `dev_pause_menu_entries() -> list[tuple[str, Callable]]`.
- `engine/ui/pause_menu.py` — `default_pause_menu` reads from `dev_pause_menu_entries()` instead of `keybinding_descriptions()`. Removes "— DEVELOPER —" header row, removes per-keybinding rows.
- `engine/host_loop.py` — construct picker on startup (gated by `dev_mode.is_enabled()`); register with PanelRegistry; register dev pause-menu entry; extend `_apply_pause_menu_side_effects(pause, view_mode, h)` → `(pause, view_mode, h, picker)`; route ESC to picker first when open; remove the `default_pause_menu`-time pre-register of dev keybindings (no longer needed for menu listing — the per-tick `register_for_frame` still keeps F10 working).
- `tests/unit/test_dev_mode.py` — append tests for `register_dev_pause_menu_entry` + `dev_pause_menu_entries`; extend `reset_dev_mode` fixture to clean the new list.
- `tests/unit/test_pause_menu_model.py` — add tests for the new dev-aware behaviour.
- `native/assets/ui-cef/hello.html` — new `<section id="mission-picker" class="dev-only">` plus `<script src="js/mission_picker.js">` tag.
- `native/assets/ui-cef/css/hello.css` — chrome rules for `#mission-picker`.

---

## Task 1: Add `dev_pause_menu_entries` registry to `engine/dev_mode.py`

**Files:**
- Modify: `engine/dev_mode.py` (add registry list + two functions)
- Modify: `tests/unit/test_dev_mode.py` (extend fixture; add tests)

- [ ] **Step 1: Extend the `reset_dev_mode` fixture and add failing tests.**

In `tests/unit/test_dev_mode.py`, locate the `reset_dev_mode` fixture and change it to also save/restore `_dev_pause_menu_entries`:

```python
@pytest.fixture
def reset_dev_mode():
    """Reset the developer_mode attribute and registries around each test."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original = getattr(_dauntless_host, "developer_mode", False)
    original_keybindings = dict(dev_mode._dev_keybindings)
    original_menu_entries = list(dev_mode._dev_pause_menu_entries)
    try:
        yield
    finally:
        _dauntless_host.developer_mode = original
        dev_mode._dev_keybindings.clear()
        dev_mode._dev_keybindings.update(original_keybindings)
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_menu_entries)
```

Then append these tests at the end of the file:

```python
def test_dev_pause_menu_entries_empty_by_default(reset_dev_mode):
    import engine.dev_mode as dev_mode
    assert dev_mode.dev_pause_menu_entries() == []


def test_register_dev_pause_menu_entry_appends(reset_dev_mode):
    import engine.dev_mode as dev_mode
    handler_a = lambda: None
    handler_b = lambda: None
    dev_mode.register_dev_pause_menu_entry("Foo", handler_a)
    dev_mode.register_dev_pause_menu_entry("Bar", handler_b)
    assert dev_mode.dev_pause_menu_entries() == [
        ("Foo", handler_a),
        ("Bar", handler_b),
    ]


def test_register_dev_pause_menu_entry_allows_duplicate_labels(reset_dev_mode):
    """Caller-controlled list; we do not de-dup on label."""
    import engine.dev_mode as dev_mode
    h1 = lambda: None
    h2 = lambda: None
    dev_mode.register_dev_pause_menu_entry("Same", h1)
    dev_mode.register_dev_pause_menu_entry("Same", h2)
    entries = dev_mode.dev_pause_menu_entries()
    assert len(entries) == 2
    assert entries[0] == ("Same", h1)
    assert entries[1] == ("Same", h2)
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v -k "dev_pause_menu_entries"
```

Expected: 3 tests FAIL with `AttributeError: module 'engine.dev_mode' has no attribute '_dev_pause_menu_entries'` (the fixture itself touches the missing list).

- [ ] **Step 3: Implement the new registry.**

Append to `engine/dev_mode.py`:

```python
# Ordered list of dev-mode pause-menu entries. Distinct from
# _dev_keybindings — a keybinding fires on key press and is not
# inherently a menu row; a menu entry has a clickable label and a
# handler. Caller-controlled order; duplicates not de-duped.
_dev_pause_menu_entries: list[tuple[str, Callable]] = []


def register_dev_pause_menu_entry(label: str, handler: Callable) -> None:
    """Register a dev-only pause-menu row.

    Rows added here appear in default_pause_menu when dev_mode is on.
    They appear in registration order, after the normal Exit / Cancel
    rows, with no visible separator between sections.
    """
    _dev_pause_menu_entries.append((label, handler))


def dev_pause_menu_entries() -> list[tuple[str, Callable]]:
    """Return registered (label, handler) pairs in registration order.

    Read by default_pause_menu when dev mode is enabled. Callers must
    not mutate the returned list — it is a live reference to the
    registry.
    """
    return _dev_pause_menu_entries
```

- [ ] **Step 4: Re-run tests to verify they pass.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v
```

Expected: all tests PASS (originally 10 + 3 new = 13 tests).

- [ ] **Step 5: Commit.**

```bash
git add engine/dev_mode.py tests/unit/test_dev_mode.py
git commit -m "feat(engine): dev_mode pause-menu entry registry"
```

---

## Task 2: Rewire `default_pause_menu` to read the new registry

**Files:**
- Modify: `engine/ui/pause_menu.py` (replace keybinding enumeration with registry read)
- Modify: `tests/unit/test_pause_menu_model.py` (add dev-aware tests)

- [ ] **Step 1: Write failing tests for the new behaviour.**

Append to `tests/unit/test_pause_menu_model.py`:

```python
# ---- dev-mode aware rows -------------------------------------------------

@pytest.fixture
def reset_dev_mode_for_pause_menu():
    """Local fixture so test_pause_menu_model doesn't depend on the
    one in test_dev_mode.py (different test files; pytest does not
    cross-import fixtures unless declared in conftest)."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original_attr = getattr(_dauntless_host, "developer_mode", False)
    original_entries = list(dev_mode._dev_pause_menu_entries)
    try:
        yield
    finally:
        _dauntless_host.developer_mode = original_attr
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_entries)


def test_default_pause_menu_dev_off_has_only_exit_and_cancel(reset_dev_mode_for_pause_menu):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    dev_mode._dev_pause_menu_entries.clear()
    dev_mode.register_dev_pause_menu_entry("Should Not Appear", lambda: None)
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    assert [it.action_id for it in m.items] == ["exit", "cancel"]


def test_default_pause_menu_dev_on_appends_registered_entries(reset_dev_mode_for_pause_menu):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode._dev_pause_menu_entries.clear()
    dev_mode.register_dev_pause_menu_entry("Load Mission…", lambda: None)
    dev_mode.register_dev_pause_menu_entry("Other Dev Thing", lambda: None)
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    labels = [it.label for it in m.items]
    assert labels == ["Exit Program", "Cancel", "Load Mission…", "Other Dev Thing"]


def test_default_pause_menu_dev_on_with_empty_registry_omits_dev_rows(reset_dev_mode_for_pause_menu):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode._dev_pause_menu_entries.clear()
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    assert [it.action_id for it in m.items] == ["exit", "cancel"]


def test_default_pause_menu_dev_on_no_separator_row(reset_dev_mode_for_pause_menu):
    """Regression: no auto-inserted '— DEVELOPER —' header row."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode._dev_pause_menu_entries.clear()
    dev_mode.register_dev_pause_menu_entry("Foo", lambda: None)
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    labels = [it.label for it in m.items]
    assert "— DEVELOPER —" not in labels
    assert all("DEVELOPER" not in lab for lab in labels)


def test_default_pause_menu_dev_on_entry_handler_invoked_via_dispatch(reset_dev_mode_for_pause_menu):
    """Action IDs for dev entries are unprefixed so PanelRegistry's
    legacy fallback routes them to PauseMenuModel.dispatch_event."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode._dev_pause_menu_entries.clear()
    fired = []
    dev_mode.register_dev_pause_menu_entry("Load Mission…", lambda: fired.append(1))
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    # action_ids for dev rows are slugified labels — no slashes.
    dev_row = m.items[-1]
    assert "/" not in dev_row.action_id
    handled = m.dispatch_event(dev_row.action_id)
    assert handled is True
    assert fired == [1]
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
uv run pytest tests/unit/test_pause_menu_model.py -v -k "dev"
```

Expected: 5 new tests FAIL because the current `default_pause_menu` still enumerates `keybinding_descriptions()` and emits the "— DEVELOPER —" header, so `labels` won't match.

- [ ] **Step 3: Rewrite `default_pause_menu`.**

In `engine/ui/pause_menu.py`, locate the current `default_pause_menu` function and replace its body. The dev-row block changes from "header + per-keybinding rows" to "per-`dev_pause_menu_entries` rows". Action IDs are slugged from labels so they remain unprefixed (no slash).

```python
def default_pause_menu(*, on_exit: _Handler, on_cancel: _Handler) -> PauseMenuModel:
    """Build the dauntless default pause menu: Exit Program + Cancel.

    Handlers are injected so the model has no compile-time dependency
    on the host loop. The host loop wires `on_exit` to a quit flag and
    `on_cancel` to the pause-controller toggle.

    When dev_mode.is_enabled(), appends one row per entry in
    dev_pause_menu_entries() — in registration order, no separator.
    Dev row action_ids are slugified from the label and remain
    unprefixed so PanelRegistry's legacy-handler fallback routes the
    click back to this model's dispatch_event.
    """
    m = PauseMenuModel()
    m.add_item("Exit Program", "exit",   on_exit)
    m.add_item("Cancel",       "cancel", on_cancel)

    if dev_mode.is_enabled():
        used: set[str] = {"exit", "cancel"}
        for label, handler in dev_mode.dev_pause_menu_entries():
            action_id = _slugify_action_id(label, used)
            used.add(action_id)
            m.add_item(label, action_id, handler)

    return m


def _slugify_action_id(label: str, used: set[str]) -> str:
    """Convert a label to a lowercase, hyphenated, no-slash action ID
    suitable for PanelRegistry's legacy-handler fallback. Disambiguates
    collisions by appending a numeric suffix."""
    import re
    base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if not base:
        base = "dev-entry"
    candidate = base
    n = 2
    while candidate in used:
        candidate = base + "-" + str(n)
        n += 1
    return candidate
```

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
uv run pytest tests/unit/test_pause_menu_model.py -v
```

Expected: all tests PASS (existing 11 + 5 new = 16). The original
`test_default_pause_menu_has_exit_and_cancel` still passes because
`_dauntless_host.developer_mode` defaults to False in pytest.

- [ ] **Step 5: Commit.**

```bash
git add engine/ui/pause_menu.py tests/unit/test_pause_menu_model.py
git commit -m "refactor(pause_menu): read dev rows from registry, drop separator and keybinding enumeration"
```

---

## Task 3: Create `engine/dev_mission_picker.py` — `MissionPicker(Panel)`

**Files:**
- Create: `engine/dev_mission_picker.py`
- Create: `tests/unit/test_dev_mission_picker.py`

This task is substantial — a few sub-cycles of TDD. We build the picker incrementally: panel scaffold first, then state transitions, then payload generation including the skip-episode-level flattening.

### Sub-task 3A — Panel scaffold + lazy walk

- [ ] **Step 1: Write failing tests for the construction contract.**

Create `tests/unit/test_dev_mission_picker.py`:

```python
"""Tests for MissionPicker — the dev-only mission loader panel.

The picker subclasses engine.ui.panel.Panel and is pumped by
PanelRegistry like the other panels. These tests cover construction,
state transitions, payload emission, and dispatch — without touching
CEF or _dauntless_host.
"""
import json
from unittest.mock import Mock

import pytest

from engine.dev_mission_picker import MissionPicker
from engine.missions import FamilyEntry, EpisodeEntry, MissionEntry, MissionRegistry


# ---- construction --------------------------------------------------------

def test_constructor_does_not_call_registry_getter():
    getter = Mock()
    on_pick = Mock()
    MissionPicker(registry_getter=getter, on_pick=on_pick)
    assert getter.call_count == 0


def test_name_is_mission_picker():
    p = MissionPicker(registry_getter=Mock(), on_pick=Mock())
    assert p.name == "mission-picker"


def test_initially_closed():
    p = MissionPicker(registry_getter=Mock(), on_pick=Mock())
    assert p.is_open() is False
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
uv run pytest tests/unit/test_dev_mission_picker.py -v
```

Expected: all 3 tests FAIL with `ModuleNotFoundError: No module named 'engine.dev_mission_picker'`.

- [ ] **Step 3: Create the picker scaffold.**

Create `engine/dev_mission_picker.py`:

```python
"""MissionPicker — dev-only mission loader panel for the CEF overlay.

Subclasses engine.ui.panel.Panel so the host loop's PanelRegistry
pumps render_payload() each tick and routes mission-picker/* events
to dispatch_event. Lazy on registry walk: the constructor receives a
getter that is not invoked until the first open(). The picker carries
one external callback (on_pick); pause-menu visibility arbitration is
the host loop's responsibility — see _apply_pause_menu_side_effects.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from engine.missions import FamilyEntry, MissionRegistry
from engine.ui.panel import Panel

# Episode-level directories that the original SDK layout uses as a
# pass-through wrapper when a family has only one episode; we collapse
# those into the family row so the tree feels less noisy.
_SKIP_EPISODE_LEVEL = {"Episode", "."}


class MissionPicker(Panel):
    def __init__(self,
                 registry_getter: Callable[[], MissionRegistry],
                 on_pick: Callable[[str], None]):
        super().__init__()
        self._registry_getter = registry_getter
        self._on_pick = on_pick
        self._visible: bool = False
        self._registry: Optional[MissionRegistry] = None
        self._cached_tree: Optional[list] = None
        # render_payload snapshot — tuple of (visible, tree_built_flag)
        # so the first open emits with the tree and the first close
        # emits the hide message; subsequent ticks with no change emit
        # None.
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "mission-picker"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        if self._registry is None:
            self._registry = self._registry_getter()
            self._cached_tree = _build_tree(self._registry)
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, self._cached_tree is not None)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if self._visible:
            payload = {"tree": self._cached_tree, "visible": True}
        else:
            payload = {"visible": False}
        return "setMissionPicker(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("pick:"):
            module = action[len("pick:"):]
            self._on_pick(module)
            self.close()
            return True
        return False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()


def _build_tree(registry: MissionRegistry) -> list:
    """Convert a MissionRegistry to the JSON-serialisable tree the JS
    side renders. Implementation in sub-task 3C."""
    return []  # placeholder; will be filled in next sub-task
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
uv run pytest tests/unit/test_dev_mission_picker.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/dev_mission_picker.py tests/unit/test_dev_mission_picker.py
git commit -m "feat(dev_mission_picker): Panel scaffold and lazy registry contract"
```

### Sub-task 3B — State transitions, dispatch, ESC handling

- [ ] **Step 1: Append failing tests for transitions and dispatch.**

Append to `tests/unit/test_dev_mission_picker.py`:

```python
# ---- transitions and dispatch -------------------------------------------

def _empty_registry() -> MissionRegistry:
    return MissionRegistry()


def test_open_resolves_registry_exactly_once():
    getter = Mock(return_value=_empty_registry())
    p = MissionPicker(registry_getter=getter, on_pick=Mock())
    p.open()
    p.open()
    p.open()
    assert getter.call_count == 1
    assert p.is_open() is True


def test_close_flips_visible():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.open()
    p.close()
    assert p.is_open() is False


def test_dispatch_pick_calls_on_pick_and_closes():
    on_pick = Mock()
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=on_pick)
    p.open()
    handled = p.dispatch_event("pick:Custom.Foo.Bar")
    assert handled is True
    on_pick.assert_called_once_with("Custom.Foo.Bar")
    assert p.is_open() is False


def test_dispatch_cancel_closes_without_calling_on_pick():
    on_pick = Mock()
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=on_pick)
    p.open()
    handled = p.dispatch_event("cancel")
    assert handled is True
    assert on_pick.call_count == 0
    assert p.is_open() is False


def test_dispatch_unknown_returns_false_and_does_not_close():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.open()
    handled = p.dispatch_event("bogus")
    assert handled is False
    assert p.is_open() is True


def test_handle_key_esc_when_open_closes():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_handle_key_esc_when_closed_is_noop():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.handle_key_esc()
    assert p.is_open() is False
```

- [ ] **Step 2: Run tests to verify they pass.**

```bash
uv run pytest tests/unit/test_dev_mission_picker.py -v
```

Expected: all tests PASS. The picker scaffold from 3A already implements these transitions; no new code needed in this sub-task — these tests **lock in** the contract.

- [ ] **Step 3: Commit (test-only).**

```bash
git add tests/unit/test_dev_mission_picker.py
git commit -m "test(dev_mission_picker): pin state transitions and dispatch contracts"
```

### Sub-task 3C — Tree payload + render_payload + skip-episode flattening

- [ ] **Step 1: Append failing tests for tree shape and render output.**

Append to `tests/unit/test_dev_mission_picker.py`:

```python
# ---- tree payload and render -------------------------------------------

def _registry(families: list[FamilyEntry]) -> MissionRegistry:
    reg = MissionRegistry()
    reg.families = families
    return reg


def _mission(module: str, dir_name: str, display: str) -> MissionEntry:
    return MissionEntry(module_name=module, dir_name=dir_name, display_name=display)


def _episode(dir_name: str, display: str, missions: list[MissionEntry]) -> EpisodeEntry:
    return EpisodeEntry(dir_name=dir_name, display_name=display, missions=missions)


def _family(dir_name: str, display: str, episodes: list[EpisodeEntry]) -> FamilyEntry:
    return FamilyEntry(dir_name=dir_name, display_name=display, episodes=episodes)


def test_render_payload_emits_tree_after_open():
    fam = _family("Tutorial", "Tutorial",
                  [_episode("Ep1", "Episode 1",
                            [_mission("Custom.Tutorial.Ep1.M1Basic.M1Basic",
                                      "M1Basic", "M1Basic")])])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    assert payload is not None
    assert payload.startswith("setMissionPicker(")
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body["visible"] is True
    assert body["tree"] == [
        {
            "kind": "family",
            "label": "Tutorial",
            "children": [
                {
                    "kind": "episode",
                    "label": "Episode 1",
                    "children": [
                        {"kind": "mission",
                         "label": "M1Basic",
                         "module": "Custom.Tutorial.Ep1.M1Basic.M1Basic"},
                    ],
                },
            ],
        },
    ]


def test_render_payload_emits_hide_after_close():
    p = MissionPicker(registry_getter=lambda: _registry([]), on_pick=Mock())
    p.open()
    p.render_payload()  # consume the open emit
    p.close()
    payload = p.render_payload()
    assert payload is not None
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body == {"visible": False}


def test_render_payload_returns_none_when_state_unchanged():
    p = MissionPicker(registry_getter=lambda: _registry([]), on_pick=Mock())
    p.open()
    first = p.render_payload()
    second = p.render_payload()
    assert first is not None
    assert second is None


def test_render_payload_skip_episode_level_when_single_episode_named_Episode():
    """When a family has exactly one episode named 'Episode', flatten
    so family.children contains the mission rows directly."""
    fam = _family("Multiplayer", "Multiplayer",
                  [_episode("Episode", "Episode",
                            [_mission("Custom.Multiplayer.Episode.MpA.MpA",
                                      "MpA", "Multiplayer A")])])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body["tree"] == [
        {
            "kind": "family",
            "label": "Multiplayer",
            "children": [
                {"kind": "mission",
                 "label": "Multiplayer A",
                 "module": "Custom.Multiplayer.Episode.MpA.MpA"},
            ],
        },
    ]


def test_render_payload_skip_episode_level_when_single_episode_named_dot():
    """Same flatten heuristic when the episode dir is '.'."""
    fam = _family("QuickBattle", "QuickBattle",
                  [_episode(".", ".",
                            [_mission("Custom.QuickBattle.QB1.QB1",
                                      "QB1", "QB1")])])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body["tree"][0]["children"] == [
        {"kind": "mission",
         "label": "QB1",
         "module": "Custom.QuickBattle.QB1.QB1"},
    ]


def test_render_payload_does_not_flatten_when_multiple_episodes():
    """Two episodes — keep the episode level even if one is named 'Episode'."""
    fam = _family("Family", "Family", [
        _episode("Episode", "Episode",
                 [_mission("a", "A", "A")]),
        _episode("Other", "Other",
                 [_mission("b", "B", "B")]),
    ])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setMissionPicker("):-2])
    family_children = body["tree"][0]["children"]
    # Both children are episode-kind, not flattened to mission rows.
    assert all(c["kind"] == "episode" for c in family_children)
    assert len(family_children) == 2
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
uv run pytest tests/unit/test_dev_mission_picker.py -v
```

Expected: the 6 new render tests FAIL because `_build_tree` is a stub that returns `[]`.

- [ ] **Step 3: Implement `_build_tree`.**

Replace the placeholder `_build_tree` in `engine/dev_mission_picker.py` with:

```python
def _build_tree(registry: MissionRegistry) -> list:
    """Convert a MissionRegistry to the JSON-serialisable tree the JS
    side renders. Applies the skip-episode-level heuristic: when a
    family has exactly one episode whose dir_name is in
    _SKIP_EPISODE_LEVEL, the episode wrapper is dropped and the
    family's children list contains mission rows directly. Display
    names come from the registry's resolved display_name (with the
    name_resolver's dir-name fallback already applied)."""
    out: list = []
    for family in registry.families:
        family_node = {
            "kind": "family",
            "label": family.display_name or family.dir_name,
            "children": [],
        }
        skip = (
            len(family.episodes) == 1
            and family.episodes[0].dir_name in _SKIP_EPISODE_LEVEL
        )
        if skip:
            ep = family.episodes[0]
            for mission in ep.missions:
                family_node["children"].append({
                    "kind": "mission",
                    "label": mission.display_name or mission.dir_name,
                    "module": mission.module_name,
                })
        else:
            for episode in family.episodes:
                ep_node = {
                    "kind": "episode",
                    "label": episode.display_name or episode.dir_name,
                    "children": [],
                }
                for mission in episode.missions:
                    ep_node["children"].append({
                        "kind": "mission",
                        "label": mission.display_name or mission.dir_name,
                        "module": mission.module_name,
                    })
                family_node["children"].append(ep_node)
        out.append(family_node)
    return out
```

- [ ] **Step 4: Re-run tests to verify they pass.**

```bash
uv run pytest tests/unit/test_dev_mission_picker.py -v
```

Expected: all picker tests PASS (3 + 7 + 6 = 16).

- [ ] **Step 5: Commit.**

```bash
git add engine/dev_mission_picker.py tests/unit/test_dev_mission_picker.py
git commit -m "feat(dev_mission_picker): tree payload with skip-episode-level flattening"
```

---

## Task 4: CEF UI assets — HTML section, JS renderer, CSS chrome

**Files:**
- Modify: `native/assets/ui-cef/hello.html` (add section + script tag)
- Create: `native/assets/ui-cef/js/mission_picker.js`
- Modify: `native/assets/ui-cef/css/hello.css` (append picker rules)

CEF assets have no automated test until the binary runs; verification is "the binary still launches, the new HTML parses, and `setMissionPicker({tree:[], visible:true})` evaluated in DevTools renders an empty picker." Interactive verification deferred to Task 6.

- [ ] **Step 1: Add the JS renderer.**

Create `native/assets/ui-cef/js/mission_picker.js`:

```javascript
// Mission picker render fn. Driven by Python via cef_execute_javascript:
//   setMissionPicker({tree: [...], visible: true});
//   setMissionPicker({visible: false});
// Tree node shape: {kind, label, children?, module?}.
//   kind === 'family' or 'episode' → collapsible row with .children
//   kind === 'mission' → actionable button with .module
// See docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md.

function escapeHtmlMP(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeJsLiteralMP(s) {
    // Embedded in onclick="dauntlessEvent('...')". Backslash-escape
    // single quotes and backslashes; HTML-escape the result.
    return escapeHtmlMP(String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

function renderMissionTreeMP(nodes, depth) {
    let html = '';
    for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        const indent = 'mp-indent-' + depth;
        if (n.kind === 'mission') {
            const mod = escapeJsLiteralMP(n.module);
            html += '<div class="mp-row mp-mission ' + indent + '"'
                  +   ' onclick="dauntlessEvent(\'mission-picker/pick:'
                  +     mod + '\')">'
                  +     escapeHtmlMP(n.label)
                  + '</div>';
        } else {
            // family or episode: collapsible group. We render it
            // collapsed by default; clicking the row toggles the
            // 'mp-expanded' class on this and its children container.
            const collapsibleId = 'mp-grp-' + depth + '-' + i + '-' + Math.random().toString(36).slice(2, 7);
            html += '<div class="mp-row mp-' + n.kind + ' ' + indent + '"'
                  +   ' onclick="document.getElementById(\'' + collapsibleId
                  +     '\').classList.toggle(\'mp-collapsed\')">'
                  +     '<span class="mp-caret">&#9656;</span>'
                  +     escapeHtmlMP(n.label)
                  + '</div>'
                  + '<div class="mp-children mp-collapsed" id="' + collapsibleId + '">'
                  +     renderMissionTreeMP(n.children || [], depth + 1)
                  + '</div>';
        }
    }
    return html;
}

function setMissionPicker(state) {
    const root = document.getElementById('mission-picker');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const body = document.getElementById('mission-picker-body');
    if (body) {
        body.innerHTML = renderMissionTreeMP(state.tree || [], 0);
    }
    root.style.display = 'flex';
}
```

- [ ] **Step 2: Append CSS chrome.**

In `native/assets/ui-cef/css/hello.css`, append at the end (after the `.dev-only` rule added by the developer-flag work):

```css
/* ============================================================
   Mission picker — centred modal that lists every discoverable SDK
   mission. Visibility is JS-controlled (display: flex / none); the
   .dev-only class on the root <section> keeps it hidden outside
   --developer mode regardless of JS state.
   ============================================================ */
#mission-picker {
    display: none;
    position: fixed;
    inset: 0;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.65);
    z-index: 200;  /* above #pause-menu (z-index 100) */
    font-family: "Antonio", sans-serif;
    color: #ffd;
}

.mp-panel {
    width: 42vw;
    max-height: 72vh;
    background: rgb(20, 22, 28);
    border: 1px solid rgb(80, 88, 100);
    display: flex;
    flex-direction: column;
}

.mp-header {
    background: linear-gradient(90deg, rgb(216, 94, 86) 0%, rgb(216, 132, 80) 100%);
    color: #ffd;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 6px 16px;
}

.mp-body {
    flex: 1 1 auto;
    overflow-y: auto;
    padding: 8px 0;
}

.mp-footer {
    padding: 8px 16px;
    border-top: 1px solid rgb(60, 64, 72);
    text-align: right;
}

.mp-cancel-button {
    background: rgb(40, 44, 52);
    border: 1px solid rgb(80, 88, 100);
    color: #ffd;
    font: inherit;
    padding: 6px 18px;
    cursor: pointer;
}
.mp-cancel-button:hover {
    background: rgb(60, 64, 72);
}

.mp-row {
    padding: 4px 12px;
    cursor: pointer;
    user-select: none;
}
.mp-row:hover {
    background: rgba(255, 255, 255, 0.06);
}
.mp-caret {
    display: inline-block;
    width: 1em;
    transition: transform 0.1s;
}
.mp-row.mp-family,
.mp-row.mp-episode {
    font-weight: 600;
}
.mp-mission {
    font-weight: 400;
}

.mp-children {
    /* visible by default; the .mp-collapsed class hides the children
       container, mirroring the caret state via JS. */
}
.mp-children.mp-collapsed {
    display: none;
}

.mp-indent-0 { padding-left: 12px; }
.mp-indent-1 { padding-left: 28px; }
.mp-indent-2 { padding-left: 44px; }
```

- [ ] **Step 3: Add the HTML section and script tag.**

In `native/assets/ui-cef/hello.html`, two edits:

(a) Add the `<script>` tag inside `<head>` (near the existing pause-menu script tag — search for `<script src="js/pause_menu.js">` if present, else add before `</head>`):

```html
    <script src="js/mission_picker.js"></script>
```

(b) Add the picker section inside `<body>`, immediately after the existing `<div id="pause-menu">…</div>` block (so the picker can z-index above it):

```html
    <!-- Mission picker overlay (developer-only).
         Visibility controlled by JS via setMissionPicker({tree, visible}).
         Container is gated by .dev-only so production builds never see it.
         Spec: docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md -->
    <section id="mission-picker" class="dev-only">
        <div class="mp-panel">
            <div class="mp-header">Load Mission</div>
            <div class="mp-body" id="mission-picker-body"></div>
            <div class="mp-footer">
                <button class="mp-cancel-button"
                        onclick="dauntlessEvent('mission-picker/cancel')">
                    Cancel
                </button>
            </div>
        </div>
    </section>
```

If `hello.html` doesn't yet have a `<script src="js/pause_menu.js">` tag (i.e. pause_menu.js is loaded another way), verify how other JS modules are loaded by reading lines around the existing references and use the same mechanism.

- [ ] **Step 4: Rebuild and confirm the binary still launches.**

CSS / static asset changes may need a configure-time copy per project memory:

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --smoke-check
echo "smoke exit: $?"
```

Expected: build clean; smoke exit 0.

- [ ] **Step 5: Commit.**

```bash
git add native/assets/ui-cef/hello.html native/assets/ui-cef/js/mission_picker.js native/assets/ui-cef/css/hello.css
git commit -m "feat(ui-cef): mission picker HTML, JS renderer, and CSS chrome"
```

---

## Task 5: Host-loop wiring — construct picker, register, extend side-effects, ESC priority

**Files:**
- Modify: `engine/host_loop.py`

This is the largest single-file change of the plan because the picker touches three places: construction site, ESC dispatch, and `_apply_pause_menu_side_effects`. We split it into separately-committable steps to keep each change small.

### Sub-task 5A — Extend `_apply_pause_menu_side_effects` to accept a picker

- [ ] **Step 1: Update the function signature and predicate.**

In `engine/host_loop.py`, locate `_apply_pause_menu_side_effects` (currently around line 1184). Change its signature and visibility predicate:

```python
def _apply_pause_menu_side_effects(pause: "_PauseMenuController",
                                   view_mode: "_ViewModeController",
                                   h,
                                   picker) -> None:
    """Mirror the pause flag into renderer state: show/hide the CEF
    pause-menu div and unlock the cursor while paused so the player can
    interact with the overlay. Idempotent — only fires when the
    effective visibility has changed since the last call. `h` is the
    bindings module (or fake) exposing cef_execute_javascript and
    set_cursor_locked. `picker` is the MissionPicker (or any object
    with an is_open() method); when the picker is open the pause-menu
    must hide regardless of pause.is_open so the picker isn't
    occluded.

    On close, the view-mode sync latch is invalidated so the next
    _apply_view_mode_side_effects call re-applies cursor lock + bridge
    pass state from whatever view mode is current.
    """
    target = pause.is_open and not picker.is_open()
    last = getattr(pause, "_last_synced_is_open", None)
    if last == target:
        return
    display = "'flex'" if target else "'none'"
    h.cef_execute_javascript(
        "document.getElementById('pause-menu').style.display = " + display + ";"
    )
    if target:
        h.set_cursor_locked(False)
    else:
        view_mode._last_synced_is_bridge = None
    pause._last_synced_is_open = target
```

- [ ] **Step 2: Locate the existing call site and update the argument list.**

Search for `_apply_pause_menu_side_effects(` in `engine/host_loop.py` and update each call. There is one call site in the main tick body (around line 2231 in the original code) — it passes `(pause, view_mode, _h)`. Update to `(pause, view_mode, _h, picker)`.

Picker is not yet constructed at this point in the file — it will be added in sub-task 5B. To keep this step independently committable, add a `_NullPicker` fallback used when the picker hasn't been constructed yet:

Inside the `_apply_pause_menu_side_effects` block (or as a module-level helper above it), add:

```python
class _NullPicker:
    """Stand-in used when dev_mode is disabled (no MissionPicker
    constructed). Always reports closed so the pause-menu side-effects
    predicate degrades to its original behaviour."""
    def is_open(self) -> bool:
        return False
```

Then at the call site, pass `picker if picker is not None else _NullPicker()` or — simpler — initialise a single module-local `_NULL_PICKER = _NullPicker()` and pass that when no real picker exists.

- [ ] **Step 3: Run existing host-loop tests.**

```bash
uv run pytest tests/host/ -v
```

Expected: tests PASS (other than the pre-existing `test_reset_sdk_globals_clears_state` failure noted in branch context — unrelated to this change).

- [ ] **Step 4: Verify smoke-check still works.**

```bash
cmake --build build -j
./build/dauntless --smoke-check
echo "smoke: $?"
```

Expected: builds + exits 0.

- [ ] **Step 5: Commit.**

```bash
git add engine/host_loop.py
git commit -m "refactor(host_loop): _apply_pause_menu_side_effects takes picker arg"
```

### Sub-task 5B — Construct and wire the `MissionPicker`

- [ ] **Step 1: Add imports.**

Near the existing dev-mode imports in `engine/host_loop.py` (search for `import engine.dev_mode`), add:

```python
from engine.dev_mission_picker import MissionPicker
import engine.missions as _missions
```

- [ ] **Step 2: Construct the picker on startup and register it.**

In `engine/host_loop.py`, locate the existing `PanelRegistry` construction (search for `registry = PanelRegistry(`). Just after `registry.register(target_list_view)` (or in the same neighbourhood — make sure `controller`, `pause`, `_h` are all in scope), add the picker construction:

```python
        # Dev-only mission picker. Lazily walks sdk/Build/scripts the
        # first time the picker opens — costs ~1s but only after the
        # user clicks "Load Mission…" with the game already paused.
        # See docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md.
        mission_picker = _NULL_PICKER  # noop until we know dev mode is on
        if dev_mode.is_enabled():
            _picker_registry_cache: list = [None]
            def _get_mission_registry():
                if _picker_registry_cache[0] is None:
                    from pathlib import Path
                    project_root = Path(__file__).resolve().parent.parent
                    sdk_scripts = project_root / "sdk" / "Build" / "scripts"
                    _picker_registry_cache[0] = _missions.discover(sdk_scripts)
                return _picker_registry_cache[0]

            def _on_pick_mission(module_name: str) -> None:
                controller.swap_mission(module_name)
                pause.close()

            mission_picker = MissionPicker(
                registry_getter=_get_mission_registry,
                on_pick=_on_pick_mission,
            )
            registry.register(mission_picker)
            dev_mode.register_dev_pause_menu_entry(
                "Load Mission…", mission_picker.open,
            )
```

Important: assign `mission_picker = _NULL_PICKER` outside the `if dev_mode.is_enabled()` branch so the variable is always defined for the side-effects call below.

- [ ] **Step 3: Update the `_apply_pause_menu_side_effects` call site to pass the picker.**

Search for the call to `_apply_pause_menu_side_effects(pause, view_mode, _h)` in the tick body and change to:

```python
                _apply_pause_menu_side_effects(pause, view_mode, _h, mission_picker)
```

- [ ] **Step 4: Rebuild and verify smoke-check.**

```bash
cmake --build build -j
./build/dauntless --smoke-check && echo "smoke OK"
./build/dauntless --smoke-check --developer && echo "smoke+dev OK"
PYTHONPATH=build/python:. python3 -c "import engine.host_loop" && echo "import OK"
```

All three should exit 0.

- [ ] **Step 5: Commit.**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): construct MissionPicker and register dev pause-menu entry"
```

### Sub-task 5C — ESC picker-priority + suppress pause-menu input while picker open + remove the dev-keybinding pre-register

- [ ] **Step 1: Re-route ESC when the picker is open.**

In `engine/host_loop.py`, locate the line that calls `pause.apply(_h)` (around line 2250). Wrap it with picker-priority:

Current:
```python
            if _h is not None:
                pause.apply(_h)
                _apply_pause_menu_side_effects(pause, view_mode, _h, mission_picker)
```

Becomes:
```python
            if _h is not None:
                # ESC priority: when the mission picker is open it
                # consumes ESC (closes the picker, returns to the
                # pause menu). Otherwise ESC toggles the pause menu
                # as before.
                if mission_picker.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        mission_picker.handle_key_esc()
                else:
                    pause.apply(_h)
                _apply_pause_menu_side_effects(pause, view_mode, _h, mission_picker)
```

- [ ] **Step 2: Suppress pause-menu keyboard input while the picker is open.**

Immediately below the block above, locate the `if pause.is_open:` branch (around line 2252) that calls `pause_menu.handle_input(_h)` and re-emits the pause-menu payload. While picker is open, `pause.is_open` is still True (we never modify it) so this branch runs — but the pause menu is hidden behind the picker, so navigating it with arrows or activating rows with Enter is invisible and confusing (e.g., Enter could fire "Exit Program" without the user seeing the pause menu).

Wrap the `pause_menu.handle_input(_h)` call (and the immediate `pause_menu.render_payload()` re-emit) so they only run when the picker is closed. Mouse forwarding to CEF stays in the branch unconditionally — CEF dispatches mouse to whichever DOM element is under the cursor, so clicks land on the picker's onclick handlers naturally.

Current shape of the branch (lines 2252-2256 approximately):
```python
                if pause.is_open:
                    pause_menu.handle_input(_h)
                    _script = pause_menu.render_payload()
                    if _script is not None:
                        _h.cef_execute_javascript(_script)
                    # ... mouse-forwarding block continues ...
```

Becomes:
```python
                if pause.is_open:
                    # Suppress pause-menu keyboard input when the
                    # mission picker is open — pause menu is hidden
                    # behind the picker, so navigation/Enter on it
                    # would activate invisible rows.
                    if not mission_picker.is_open():
                        pause_menu.handle_input(_h)
                        _script = pause_menu.render_payload()
                        if _script is not None:
                            _h.cef_execute_javascript(_script)
                    # ... mouse-forwarding block continues unchanged ...
```

- [ ] **Step 3: Remove the redundant pre-register of dev keybindings.**

Earlier in the file (around line 2161-2165 per the existing developer-flag wiring), there is a block:

```python
        # Pre-register dev keybindings once so default_pause_menu can list
        # them. register_for_frame is also called every tick (see input
        # dispatch) to rebind handlers with the current player/session.
        if _h is not None and dev_mode.is_enabled():
            dev_keybindings.register_for_frame(_h, controller.session, None)
```

This block exists only because `default_pause_menu` used to list keybindings. After Task 2, `default_pause_menu` no longer reads from `keybinding_descriptions()`, so the pre-register is no longer needed for menu construction. The per-tick `register_for_frame` call in the input dispatch (lower in the file) still runs every frame and keeps F10 working.

**Delete the pre-register block above** (5 lines including the comment).

- [ ] **Step 4: Rebuild and verify headlessly.**

```bash
cmake --build build -j
./build/dauntless --smoke-check && echo "smoke OK"
./build/dauntless --smoke-check --developer && echo "smoke+dev OK"
```

Both should exit 0.

- [ ] **Step 5: Commit.**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): ESC routes to picker; suppress pause-menu input while picker open; drop redundant pre-register"
```

---

## Task 6: Integration sanity-check (headless + interactive)

**Files:** none — verification only.

- [ ] **Step 1: Run the focused test suites touched by this branch.**

```bash
uv run pytest tests/unit/test_dev_mode.py tests/unit/test_pause_menu_model.py tests/unit/test_dev_mission_picker.py tests/host/test_developer_mode_binding.py tests/host/ -v
```

Expected: all PASS except the pre-existing `test_reset_sdk_globals_clears_state` (worktree-only `sdk/` gating noted in CLAUDE.md context — this plan executes on `main`'s checkout so this should also pass; if it fails, the failure is environmental, not a regression from this plan).

- [ ] **Step 2: Verify both smoke variants still pass.**

```bash
./build/dauntless --smoke-check
./build/dauntless --smoke-check --developer
```

Both should print Python repr and exit 0.

- [ ] **Step 3: Interactive verification with `--developer`.**

```bash
./build/dauntless --developer
```

Check:
- ESC → pause menu shows `Exit Program`, `Cancel`, `Load Mission…`. **No "— DEVELOPER —" row, no "Shield-hit debug (F10)" row.**
- Click `Load Mission…` → pause menu hides; mission picker modal appears centred. Family rows are collapsible; clicking expands.
- Click any mission row → picker closes, pause menu closes, game resumes on the newly loaded mission.
- Repeat: ESC → click `Load Mission…` → press Cancel → picker closes, pause menu re-appears with the same rows.
- Repeat: ESC → click `Load Mission…` → press ESC → picker closes, pause menu re-appears.
- F10 still fires the shield-hit debug effect during gameplay (no menu listing required).
- F12 → DevTools → console: `window.__DAUNTLESS_DEV__` is `true`.

- [ ] **Step 4: Interactive verification without `--developer`.**

```bash
./build/dauntless
```

Check:
- ESC → pause menu shows only `Exit Program` and `Cancel`.
- No `Load Mission…` row.
- F10 is a no-op.
- DevTools (F12) console: `window.__DAUNTLESS_DEV__` is `undefined`.

- [ ] **Step 5: Tag complete.**

No code change; nothing to commit. The plan is complete.

---

## Notes for the implementer

- **PanelRegistry routing recap.** Slash-prefixed JS events (`mission-picker/pick:X`) route to the panel whose `name` matches the prefix. Unprefixed events fall through to the legacy handler (pause-menu's `dispatch_event`). This is why dev pause-menu rows must use unprefixed action IDs.
- **`registry.register(picker)` order.** The picker must be registered with the PanelRegistry **before** the host loop starts ticking; otherwise the first `render_payload()` is never called. The construction site in Task 5B sub-step 2 places it after the existing panel registrations, which is correct — all happen before the main `while not r.should_close():` loop.
- **`_NULL_PICKER` placement.** Putting the `_NullPicker` class as a module-local helper above `_apply_pause_menu_side_effects` keeps it simple. The single instance `_NULL_PICKER` lives near the class definition. Don't construct a new `_NullPicker()` per tick.
- **Stale `.so` symptoms.** If `_dauntless_host` doesn't expose `developer_mode` (older build), `dev_mode.is_enabled()` returns False — picker isn't constructed, dev pause-menu entry never registered, behaviour matches production. Rebuild from project root: `cmake -B build -S . && cmake --build build -j`.
- **CSS / static asset reconfigure.** Per project memory, CSS edits may not be picked up by `cmake --build` alone; re-run `cmake -B build -S .` first if the new picker styling doesn't show.
- **Action ID slugification edge cases.** Labels like `"Foo / Bar"` would slugify to `"foo-bar"`. If two dev entries collide, the second gets `"foo-bar-2"`. The collision suffix is deterministic per call but not stable across registration-order changes; this is fine because action IDs are not user-visible.
- **Test isolation.** Both `tests/unit/test_dev_mode.py` and `tests/unit/test_pause_menu_model.py` mutate the same `engine.dev_mode._dev_pause_menu_entries` list. Each file has its own `reset_dev_mode*` fixture that fully restores both `developer_mode` and the list. Do not move these fixtures into `conftest.py` — keeping them file-local avoids surprising cross-test interactions.

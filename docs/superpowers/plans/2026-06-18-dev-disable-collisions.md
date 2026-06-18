# Disable Collisions Developer Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dev-only "Disable Collisions" toggle to the Combat tab of the Developer Options panel that, when On, suppresses all collision effects (impulse, de-penetration, damage) for every object.

**Architecture:** Mirror the existing `dev_combat_cheats` seam exactly. A new flag in `engine/dev_combat_cheats.py` is written by the panel via a setter and read at one gate in `engine/appc/collisions.py:tick_collisions`. The getter ANDs with `dev_mode.is_enabled()` so production collisions are byte-identical when the toggle is off. The panel and CEF JS gain a fourth Combat-tab toggle row.

**Tech Stack:** Python 3 (pytest), CEF/JavaScript for the panel UI.

## Global Constraints

- Flag defaults **Off**, is **not persisted** across launches.
- Every `*_active()` getter ANDs the stored flag with `dev_mode.is_enabled()` — when dev mode is off the getter MUST return `False` regardless of the stored flag.
- When the toggle is Off, the collision path MUST be byte-identical to today.
- Follow the exact shape of the existing three Combat-tab toggles — no new module, no new tab.
- Spec: `docs/superpowers/specs/2026-06-18-dev-disable-collisions-design.md`.

---

### Task 1: Add the `disable_collisions` flag to `dev_combat_cheats`

**Files:**
- Modify: `engine/dev_combat_cheats.py`
- Test: `tests/unit/test_dev_combat_cheats.py`

**Interfaces:**
- Consumes: `engine.dev_mode.is_enabled()` (existing).
- Produces: `set_disable_collisions(on: bool) -> None`, `disable_collisions_active() -> bool`; `reset()` also clears the new flag.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_dev_combat_cheats.py`:

```python
def test_set_disable_collisions_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_disable_collisions(True)
    assert cheats.disable_collisions_active() is True
    cheats.set_disable_collisions(False)
    assert cheats.disable_collisions_active() is False


def test_disable_collisions_gated_off_when_dev_mode_off(reset_cheats):
    import _dauntless_host
    cheats = reset_cheats
    cheats.set_disable_collisions(True)
    _dauntless_host.developer_mode = True
    assert cheats.disable_collisions_active() is True
    _dauntless_host.developer_mode = False
    assert cheats.disable_collisions_active() is False


def test_reset_clears_disable_collisions(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_disable_collisions(True)
    cheats.reset()
    assert cheats.disable_collisions_active() is False
```

Also extend the existing `test_all_flags_default_off` by appending one line:

```python
    assert cheats.disable_collisions_active() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_dev_combat_cheats.py -v`
Expected: FAIL — `AttributeError: module 'engine.dev_combat_cheats' has no attribute 'set_disable_collisions'`.

- [ ] **Step 3: Implement the flag**

In `engine/dev_combat_cheats.py`, update the module docstring's first line to read "the Developer Options → Combat-tab flags." Add the module global alongside the existing three:

```python
_disable_collisions: bool = False
```

Add the setter and getter (place them next to the existing ones):

```python
def set_disable_collisions(on: bool) -> None:
    global _disable_collisions
    _disable_collisions = bool(on)


def disable_collisions_active() -> bool:
    return _disable_collisions and dev_mode.is_enabled()
```

Update `reset()` to clear it:

```python
def reset() -> None:
    """Clear all flags. Used by tests; not wired to runtime teardown."""
    global _god_mode, _double_player_weapons, _disable_npc_shields
    global _disable_collisions
    _god_mode = False
    _double_player_weapons = False
    _disable_npc_shields = False
    _disable_collisions = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dev_combat_cheats.py -v`
Expected: PASS (all, including the new three and the extended default-off test).

- [ ] **Step 5: Commit**

```bash
git add engine/dev_combat_cheats.py tests/unit/test_dev_combat_cheats.py
git commit -m "feat(dev): add disable_collisions cheat flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Gate `tick_collisions` on the flag

**Files:**
- Modify: `engine/appc/collisions.py:244-250` (`tick_collisions`)
- Test: `tests/unit/test_collisions.py`

**Interfaces:**
- Consumes: `engine.dev_combat_cheats.disable_collisions_active()` (Task 1).
- Produces: no new public symbol; behaviour change only — `tick_collisions` returns `[]` and resolves no pairs when the flag is active.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_collisions.py` (the `_ship` helper, `App` import, and autouse `_isolate` fixture already exist in this file):

```python
def test_tick_collisions_disabled_flag_suppresses_all_effects():
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    from engine.appc.collisions import tick_collisions, _overlay_vec
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    cheats.set_disable_collisions(True)
    try:
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "test")
        a = _ship(0.0, 1000.0, +10.0)
        b = _ship(1.5, 1000.0, -10.0)
        pSet.AddObjectToSet(a, "A")
        pSet.AddObjectToSet(b, "B")
        hits = tick_collisions(1.0 / 60.0, host=None, ship_instances=None)
        assert hits == []                  # no pair resolved
        assert _overlay_vec(a) is None      # no impulse injected
        assert _overlay_vec(b) is None
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev


def test_tick_collisions_disabled_still_decays_existing_overlay():
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    from engine.appc.collisions import tick_collisions, _overlay_vec
    from engine.appc.math import TGPoint3
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    cheats.set_disable_collisions(True)
    try:
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "test")
        a = _ship(0.0, 1000.0, 0.0)
        a._collision_velocity = TGPoint3(5.0, 0.0, 0.0)
        pSet.AddObjectToSet(a, "A")
        tick_collisions(1.0 / 60.0, host=None, ship_instances=None)
        # Overlay path runs before the gate, so the existing overlay decays.
        assert _overlay_vec(a).x < 5.0
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_collisions.py -k disabled -v`
Expected: FAIL — `test_..._suppresses_all_effects` fails because `hits` has 1 entry and overlays are non-None (gate not yet present).

- [ ] **Step 3: Implement the gate**

In `engine/appc/collisions.py`, replace the body of `tick_collisions`:

```python
def tick_collisions(dt: float, host=None, ship_instances=None):
    """Per-frame entry point: consume overlays for every collidable, then
    detect + resolve all overlapping pairs. Returns the list of collision
    tuples. Call once per render frame after motion + player input have run.

    When the dev-only Disable Collisions toggle is active, existing knockback
    overlays still decay (above) but no new pair is detected or resolved, so
    impulse, de-penetration, and collision damage are all suppressed."""
    objects = list(iter_collidables())
    _apply_overlay_all(objects, dt)
    from engine.dev_combat_cheats import disable_collisions_active
    if disable_collisions_active():
        return []
    return resolve_collisions(objects, host=host, ship_instances=ship_instances)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_collisions.py -v`
Expected: PASS — the two new tests plus the pre-existing `test_tick_collisions_resolves_live_set_pair` (which runs with dev mode/flag untouched, so the gate is inactive).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(collisions): gate tick_collisions on disable_collisions flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire the toggle into `DeveloperOptionsPanel`

**Files:**
- Modify: `engine/ui/developer_options_panel.py`
- Test: `tests/unit/test_developer_options_panel.py`

**Interfaces:**
- Consumes: `cheats.disable_collisions_active()`, `cheats.set_disable_collisions()` (Task 1).
- Produces: `render_payload()` settings dict gains `"disable_collisions"`; `dispatch_event("toggle:disable_collisions")` flips it; `_focusables()` includes `("ctrl", "disable_collisions")`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_developer_options_panel.py` (the `panel` fixture and `_body` helper already exist):

```python
def test_dispatch_disable_collisions_writes_through(panel):
    p, cheats = panel
    assert cheats.disable_collisions_active() is False
    assert p.dispatch_event("toggle:disable_collisions") is True
    assert cheats.disable_collisions_active() is True
    assert p.dispatch_event("toggle:disable_collisions") is True
    assert cheats.disable_collisions_active() is False


def test_render_payload_includes_disable_collisions(panel):
    p, _ = panel
    p.open()
    body = _body(p.render_payload())
    assert "disable_collisions" in body["settings"]
    assert body["settings"]["disable_collisions"] is False


def test_open_resyncs_disable_collisions(panel):
    p, cheats = panel
    cheats.set_disable_collisions(True)
    p.open()
    body = _body(p.render_payload())
    assert body["settings"]["disable_collisions"] is True


def test_focusables_include_disable_collisions(panel):
    p, _ = panel
    assert ("ctrl", "disable_collisions") in p._focusables()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_developer_options_panel.py -k disable_collisions -v`
Expected: FAIL — `dispatch_event` returns `False` for the unknown action and `"disable_collisions"` is absent from the settings dict.

- [ ] **Step 3: Implement the panel wiring**

In `engine/ui/developer_options_panel.py`:

In `__init__`, after `self._no_npc_shields = cheats.disable_npc_shields_active()`:

```python
        self._disable_collisions = cheats.disable_collisions_active()
```

In `open`, after `self._no_npc_shields = cheats.disable_npc_shields_active()`:

```python
        self._disable_collisions = cheats.disable_collisions_active()
```

In `render_payload`, extend the `snapshot` tuple to include the new mirror:

```python
        snapshot = (
            self._visible, tuple(self._tabs), self._selected_tab,
            self._focused, self._god_mode, self._double_weapons,
            self._no_npc_shields, self._disable_collisions,
        )
```

and add the key to the `settings` dict:

```python
            "settings": {
                "god_mode": self._god_mode,
                "double_weapons": self._double_weapons,
                "no_npc_shields": self._no_npc_shields,
                "disable_collisions": self._disable_collisions,
            },
```

In `dispatch_event`, after the `toggle:no_npc_shields` block and before the `tab:` handling:

```python
        if action == "toggle:disable_collisions":
            new_val = not self._disable_collisions
            cheats.set_disable_collisions(new_val)
            self._disable_collisions = new_val
            return True
```

In `_focusables`, extend the combat-tab list:

```python
        if self._selected_tab == "combat":
            out += [("ctrl", "god_mode"), ("ctrl", "double_weapons"),
                    ("ctrl", "no_npc_shields"), ("ctrl", "disable_collisions")]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_developer_options_panel.py -v`
Expected: PASS (new tests plus all existing panel tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/developer_options_panel.py tests/unit/test_developer_options_panel.py
git commit -m "feat(ui): wire Disable Collisions toggle into Developer Options panel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Render the toggle row in the CEF panel JS

**Files:**
- Modify: `native/assets/ui-cef/js/developer_options.js`

**Interfaces:**
- Consumes: the `settings.disable_collisions` field from Task 3's `render_payload`.
- Produces: a `Disable Collisions` toggle row + focusable in the Combat tab body. (No automated test — this file has no JS test harness; verified by inspection and an in-app smoke check.)

- [ ] **Step 1: Add the focusable**

In `_doFocusableList`, inside the `if (state.selected_tab === 'combat')` block, after the `no_npc_shields` push:

```javascript
        out.push({kind: 'ctrl', target: 'disable_collisions'});
```

- [ ] **Step 2: Add the toggle row**

In `_doRenderCombatBody`, after the `Disable NPC Shields` row:

```javascript
    html += _doToggleRow('Disable Collisions', 'disable_collisions',
                         s.disable_collisions, isFoc('disable_collisions'));
```

- [ ] **Step 3: Verify ordering matches the Python focusable list**

Confirm the JS combat focusable order (`god_mode`, `double_weapons`, `no_npc_shields`, `disable_collisions`) exactly matches `_focusables()` in `developer_options_panel.py` from Task 3 — keyboard focus indices are shared between the two. Read both lists and confirm they agree.

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/js/developer_options.js
git commit -m "feat(ui): render Disable Collisions row in Developer Options CEF panel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full-suite regression check

**Files:** none (verification only).

- [ ] **Step 1: Run the affected unit tests together**

Run: `uv run pytest tests/unit/test_dev_combat_cheats.py tests/unit/test_collisions.py tests/unit/test_developer_options_panel.py -v`
Expected: PASS — all tests across the three files.

- [ ] **Step 2: Run the broader suite via the watchdog-capped runner**

Run: `scripts/run_tests.sh`
Expected: PASS / no new failures (see memory: full suite peaks ~290 MB, safe to run).

- [ ] **Step 3: Manual in-app smoke (optional, requires built engine + game/)**

Launch `./build/dauntless --developer`, open the pause menu → Developer Options → Combat tab, toggle **Disable Collisions** On, and fly the player ship through another ship / asteroid to confirm no bounce and no collision damage; toggle Off and confirm collisions resume. (No desktop automation — manual observation only, per project policy.)

---

## Self-Review

- **Spec coverage:** Flag (§Design.1 → Task 1), gate (§Design.2 → Task 2), panel (§Design.3 → Task 3), JS (§Design.4 → Task 4), testing (§Testing → Tasks 1–3 + Task 5). Non-goals (no persistence, global scope, no new tab, no SDK Appc wiring) are respected — no task adds them.
- **Placeholder scan:** none — every code/ test step shows full content.
- **Type consistency:** `set_disable_collisions`/`disable_collisions_active` names match across Tasks 1, 2, 3; settings key `disable_collisions` and focusable target `disable_collisions` match across Tasks 3 and 4; focusable ordering reconciled in Task 4 Step 3.

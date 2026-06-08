# Developer Options Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a developer-only "Developer Options" pause-menu modal (styled like the configuration panel) whose single "Combat" tab exposes three live cheats — God Mode, 2× Player Weapon Strength, Disable NPC Shields — wired into the combat damage chokepoint.

**Architecture:** A new `engine/dev_combat_cheats.py` module holds three default-off flags with dev-mode-gated getters; `combat.apply_hit` reads them at its single damage chokepoint. A `DeveloperOptionsPanel` (a `Panel` subclass mirroring `ConfigurationPanel`) writes them, rendered by a new `developer_options.js` reusing the configuration panel's `cp-*` CSS. `host_loop.py` constructs and wires the panel only under `--developer`.

**Tech Stack:** Python 3 (engine), pytest (TDD), CEF/HTML/JS/CSS (UI view), CMake/C++ (host — not modified here).

---

## Spec

`docs/superpowers/specs/2026-06-08-developer-options-menu-design.md`

## Background facts the implementer needs

- **Damage chokepoint:** `engine/appc/combat.py:apply_hit(ship, damage, hit_point, source, *, ...)`. `ship` is the victim, `source` is the firer. `import App` is already in scope inside the function.
- **Player identity:** `App.Game_GetCurrentGame().GetPlayer()`. Compare by identity (`ship is player`). In tests, set it with:
  ```python
  import App
  game = App.Game()
  App._set_current_game(game)
  game.SetPlayer(player_ship)
  ```
- **Dev-mode flag:** `engine.dev_mode.is_enabled()` reads `_dauntless_host.developer_mode`. Tests toggle it with `_dauntless_host.developer_mode = True/False`.
- **Shields:** `ShieldSubsystem` (`engine/appc/subsystems.py:1859`) has `ApplyDamage(face, amount)` (mutates, returns overflow) and `GetCurrentShields(face)` (non-mutating read).
- **Panel base:** `engine/ui/panel.py` — subclasses implement `name`, `render_payload()`, `dispatch_event(action)`, optionally `invalidate()`.
- **Registry routing:** `dauntlessEvent('developer-options/toggle:god_mode')` → registry routes prefix `developer-options` → `dispatch_event("toggle:god_mode")`.
- **MEMORY constraint:** the **full pytest suite OOMs the host (>100 GB RAM)**. NEVER run bare `pytest`. Only run the specific files/nodes named in each task.

## File structure

New:
- `engine/dev_combat_cheats.py` — cheat flag state + gated getters (Task 1).
- `engine/ui/developer_options_panel.py` — the Panel subclass (Task 3).
- `native/assets/ui-cef/js/developer_options.js` — CEF renderer (Task 4).
- `tests/unit/test_dev_combat_cheats.py` (Task 1).
- `tests/unit/test_combat_cheats.py` (Task 2).
- `tests/unit/test_developer_options_panel.py` (Task 3).

Modified:
- `engine/appc/combat.py` — cheat hooks in `apply_hit` (Task 2).
- `native/assets/ui-cef/index.html` — new section + script tag (Task 4).
- `native/assets/ui-cef/css/configuration_panel.css` — shared backdrop selector (Task 4).
- `engine/host_loop.py` — dev-mode construction + wiring (Task 5).

---

## Task 1: Cheat state module

**Files:**
- Create: `engine/dev_combat_cheats.py`
- Test: `tests/unit/test_dev_combat_cheats.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dev_combat_cheats.py`:

```python
"""Tests for engine.dev_combat_cheats — the three dev-only combat cheat
flags. Each flag defaults Off, is mutated via a setter, and its
``*_active()`` getter returns False whenever dev mode is off (so a
production build's combat path is never affected)."""
import pytest


@pytest.fixture
def reset_cheats():
    """Reset cheat flags and the dev-mode attribute around each test."""
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    cheats.reset()
    try:
        yield cheats
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev


def test_all_flags_default_off(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    assert cheats.god_mode_active() is False
    assert cheats.double_player_weapons_active() is False
    assert cheats.disable_npc_shields_active() is False


def test_set_god_mode_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_god_mode(True)
    assert cheats.god_mode_active() is True
    cheats.set_god_mode(False)
    assert cheats.god_mode_active() is False


def test_set_double_weapons_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_double_player_weapons(True)
    assert cheats.double_player_weapons_active() is True


def test_set_disable_npc_shields_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_disable_npc_shields(True)
    assert cheats.disable_npc_shields_active() is True


def test_getters_gated_off_when_dev_mode_off(reset_cheats):
    """Flags can be set, but the *_active() getters must report False
    while dev mode is off — production combat must never change."""
    import _dauntless_host
    cheats = reset_cheats
    cheats.set_god_mode(True)
    cheats.set_double_player_weapons(True)
    cheats.set_disable_npc_shields(True)
    _dauntless_host.developer_mode = False
    assert cheats.god_mode_active() is False
    assert cheats.double_player_weapons_active() is False
    assert cheats.disable_npc_shields_active() is False


def test_reset_clears_all_flags(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_god_mode(True)
    cheats.set_double_player_weapons(True)
    cheats.set_disable_npc_shields(True)
    cheats.reset()
    assert cheats.god_mode_active() is False
    assert cheats.double_player_weapons_active() is False
    assert cheats.disable_npc_shields_active() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_dev_combat_cheats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.dev_combat_cheats'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/dev_combat_cheats.py`:

```python
"""Developer-only combat cheat flags.

Single source of truth for the three Developer Options → Combat toggles.
Each flag defaults Off. ``combat.apply_hit`` reads the ``*_active()``
getters; ``DeveloperOptionsPanel`` writes them via the setters. Neither
side imports the other — this module is the seam.

Every ``*_active()`` getter ANDs the stored flag with
``dev_mode.is_enabled()``. Gating inside the getter is defense-in-depth:
even if a flag were somehow set in a production build, combat behaviour
cannot change.

Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
"""
from engine import dev_mode

_god_mode: bool = False
_double_player_weapons: bool = False
_disable_npc_shields: bool = False


def set_god_mode(on: bool) -> None:
    global _god_mode
    _god_mode = bool(on)


def set_double_player_weapons(on: bool) -> None:
    global _double_player_weapons
    _double_player_weapons = bool(on)


def set_disable_npc_shields(on: bool) -> None:
    global _disable_npc_shields
    _disable_npc_shields = bool(on)


def god_mode_active() -> bool:
    return _god_mode and dev_mode.is_enabled()


def double_player_weapons_active() -> bool:
    return _double_player_weapons and dev_mode.is_enabled()


def disable_npc_shields_active() -> bool:
    return _disable_npc_shields and dev_mode.is_enabled()


def reset() -> None:
    """Clear all three flags. Used by tests; not wired to runtime teardown."""
    global _god_mode, _double_player_weapons, _disable_npc_shields
    _god_mode = False
    _double_player_weapons = False
    _disable_npc_shields = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_dev_combat_cheats.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/dev_combat_cheats.py tests/unit/test_dev_combat_cheats.py
git commit -m "feat(dev): combat cheat flag module (god mode, 2x weapons, no NPC shields)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Combat hooks in apply_hit

**Files:**
- Modify: `engine/appc/combat.py` (the `apply_hit` function, `engine/appc/combat.py:317`)
- Test: `tests/unit/test_combat_cheats.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_combat_cheats.py`:

```python
"""combat.apply_hit must honour the three dev combat cheats when dev mode
is on: god mode (player takes no damage but feedback still fires), 2x
player weapon strength (player's outgoing damage doubled), and disable
NPC shields (non-player shields stop absorbing). All cheats are no-ops
when dev mode is off. Builds on the ship fixtures used by
test_combat_skips_disabled_shields.py."""
from unittest.mock import patch

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _ship(name, hull_max=2000.0, face_max=1000.0):
    """Yellow-alert ship with a healthy powered shield generator + hull."""
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    ss.SetDisabledPercentage(0.25)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


@pytest.fixture
def env():
    """Dev mode on; a current game with a designated player; cheats reset
    before and after. Yields (player, npc)."""
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    player = _ship("Player")
    npc = _ship("NPC")
    game = App.Game()
    App._set_current_game(game)
    game.SetPlayer(player)
    try:
        yield player, npc
    finally:
        cheats.reset()
        App._set_current_game(None)
        _dauntless_host.developer_mode = original_dev


# ---- god mode -------------------------------------------------------------

def test_god_mode_player_takes_no_damage_but_feedback_fires(env):
    player, _ = env
    import engine.dev_combat_cheats as cheats
    cheats.set_god_mode(True)
    with patch("engine.appc.hit_feedback.dispatch") as mock_dispatch:
        apply_hit(player, 5000.0, TGPoint3(0, 10, 0), source=None)
    # Shields and hull untouched.
    assert player.GetShields().GetCurrentShields(0) == 1000.0
    assert player.GetHull().GetCondition() == 2000.0
    # Hit feedback still fired (player still sees/hears the impact).
    assert mock_dispatch.called


def test_god_mode_does_not_protect_npc(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_god_mode(True)
    # 500 < 1000 shield, so shields absorb and drop to 500; hull intact.
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=None)
    assert npc.GetShields().GetCurrentShields(0) == 500.0


# ---- 2x player weapon strength -------------------------------------------

def test_double_weapons_doubles_player_outgoing_damage(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_double_player_weapons(True)
    # Drain NPC shields first so damage reaches the hull predictably.
    npc.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=player)
    # 500 doubled to 1000 → hull 2000 - 1000 = 1000.
    assert npc.GetHull().GetCondition() == 1000.0


def test_double_weapons_ignores_non_player_source(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_double_player_weapons(True)
    npc.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=None)  # not the player
    assert npc.GetHull().GetCondition() == 1500.0  # un-doubled


# ---- disable NPC shields --------------------------------------------------

def test_disable_npc_shields_bypasses_npc_absorption(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_disable_npc_shields(True)
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=player)
    # Shields bypassed: face HP preserved, hull takes the full hit.
    assert npc.GetShields().GetCurrentShields(0) == 1000.0
    assert npc.GetHull().GetCondition() == 1500.0


def test_disable_npc_shields_leaves_player_shields_intact(env):
    player, _ = env
    import engine.dev_combat_cheats as cheats
    cheats.set_disable_npc_shields(True)
    apply_hit(player, 500.0, TGPoint3(0, 10, 0), source=None)
    # Player is not an NPC: shields still absorb.
    assert player.GetShields().GetCurrentShields(0) == 500.0


# ---- gating ---------------------------------------------------------------

def test_cheats_are_noops_when_dev_mode_off(env):
    player, npc = env
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    cheats.set_god_mode(True)
    cheats.set_double_player_weapons(True)
    cheats.set_disable_npc_shields(True)
    _dauntless_host.developer_mode = False  # gate everything off
    apply_hit(player, 500.0, TGPoint3(0, 10, 0), source=player)
    # God mode off → player shields absorb normally.
    assert player.GetShields().GetCurrentShields(0) == 500.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_combat_cheats.py -v`
Expected: FAIL — god-mode/2x/disable-shields assertions fail because `apply_hit` does not yet consult the cheats (e.g. `test_god_mode_...` sees shields drained to 500, not 1000).

- [ ] **Step 3: Write the cheat-resolution block**

In `engine/appc/combat.py`, find the top of `apply_hit` (the imports + `r_hit = ...`):

```python
    from engine.appc.events import WeaponHitEvent
    from engine.appc import hit_feedback
    import App

    r_hit = weapon_splash_radius(hardpoint_weapon, payload_template)
```

Replace it with:

```python
    from engine.appc.events import WeaponHitEvent
    from engine.appc import hit_feedback
    from engine.appc import dev_combat_cheats as _cheats
    import App

    r_hit = weapon_splash_radius(hardpoint_weapon, payload_template)

    # ── Developer combat cheats (dev-mode only; no-ops in production). ──
    # Resolve the player once, then apply: 2x player weapons (source is
    # player), god mode (target is player -> suppress all state mutation
    # but keep feedback), and disable-NPC-shields (target is not player).
    # Every getter ANDs with dev_mode, so a production build is unaffected.
    # Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
    try:
        _game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        _player = _game.GetPlayer() if _game is not None and hasattr(_game, "GetPlayer") else None
    except Exception:
        _player = None
    _target_is_player = _player is not None and ship is _player
    _source_is_player = _player is not None and source is _player

    if _cheats.double_player_weapons_active() and _source_is_player:
        damage = float(damage) * 2.0

    # When god mode protects the player, mutation calls are skipped but the
    # absorbed_* amounts are still computed so hit feedback fires unchanged.
    _commit = not (_cheats.god_mode_active() and _target_is_player)
```

- [ ] **Step 4: Gate the shield bite (disable-NPC-shields + god mode)**

Find:

```python
    shields_online = (shields is not None and shields_on
                      and not shields_disabled and not shields_destroyed)
    if shields_online and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        before = remaining
        remaining = shields.ApplyDamage(face, remaining)
        absorbed_shields = before - remaining
```

Replace with:

```python
    shields_online = (shields is not None and shields_on
                      and not shields_disabled and not shields_destroyed)
    # Disable-NPC-shields cheat: every non-player ship's shields stop
    # absorbing, so full damage reaches the hull/subsystems.
    if _cheats.disable_npc_shields_active() and not _target_is_player:
        shields_online = False
    if shields_online and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        before = remaining
        if _commit:
            remaining = shields.ApplyDamage(face, remaining)
        else:
            # God mode: compute the overflow WITHOUT draining the face, so
            # the shield flash still fires but the player's shields stay full.
            cur = (shields.GetCurrentShields(face)
                   if hasattr(shields, "GetCurrentShields") else before)
            remaining = max(0.0, remaining - cur)
        absorbed_shields = before - remaining
```

- [ ] **Step 5: Gate the hull damage (god mode)**

Find:

```python
        # 2. Hull always takes full post-shield damage.
        if hull is not None and hasattr(ship, "DamageSystem"):
            ship.DamageSystem(hull, post_shield)
            absorbed_hull = post_shield
```

Replace with:

```python
        # 2. Hull always takes full post-shield damage.
        if hull is not None and hasattr(ship, "DamageSystem"):
            if _commit:
                ship.DamageSystem(hull, post_shield)
            absorbed_hull = post_shield
```

- [ ] **Step 6: Gate the subsystem damage (god mode)**

Find:

```python
            if hasattr(ship, "DamageSystem"):
                before_flags = _subsystem_state_flags(sub)
                ship.DamageSystem(sub, amount)
                absorbed_subsystem_total += amount
                after_flags = _subsystem_state_flags(sub)
                transition = _diff_state(before_flags, after_flags)
                if transition is not None and primary_transition is None:
                    primary_transition = transition
```

Replace with:

```python
            if hasattr(ship, "DamageSystem"):
                before_flags = _subsystem_state_flags(sub)
                if _commit:
                    ship.DamageSystem(sub, amount)
                absorbed_subsystem_total += amount
                after_flags = _subsystem_state_flags(sub)
                transition = _diff_state(before_flags, after_flags)
                if transition is not None and primary_transition is None:
                    primary_transition = transition
```

- [ ] **Step 7: Run the new tests + the combat regression tests**

Run: `uv run pytest tests/unit/test_combat_cheats.py tests/unit/test_combat_skips_disabled_shields.py tests/unit/test_combat_skips_powered_down_shields.py tests/unit/test_combat_hit_resolution.py -v`
Expected: PASS (new cheat tests pass; existing combat tests still green — cheats are no-ops when no player/cheat is set).

- [ ] **Step 8: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_combat_cheats.py
git commit -m "feat(combat): god mode, 2x player weapons, disable-NPC-shields hooks in apply_hit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: DeveloperOptionsPanel

**Files:**
- Create: `engine/ui/developer_options_panel.py`
- Test: `tests/unit/test_developer_options_panel.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_developer_options_panel.py`:

```python
"""Tests for DeveloperOptionsPanel — the dev-only Combat cheats modal.
Mirrors test_configuration_panel.py: covers state, dispatch (which must
write through to engine.dev_combat_cheats), render_payload dedup, and
keyboard input. Dev mode is forced on so the cheats getters reflect set
values."""
import json

import pytest


@pytest.fixture
def panel():
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    p = DeveloperOptionsPanel()
    try:
        yield p, cheats
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev


def _body(payload):
    return json.loads(payload[len("setDeveloperOptions("):-2])


# ---- construction / open-close -------------------------------------------

def test_name_is_developer_options(panel):
    p, _ = panel
    assert p.name == "developer-options"


def test_initially_closed(panel):
    p, _ = panel
    assert p.is_open() is False


def test_open_close_round_trip(panel):
    p, _ = panel
    p.open()
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


def test_open_resyncs_from_cheats_module(panel):
    p, cheats = panel
    cheats.set_god_mode(True)
    p.open()
    body = _body(p.render_payload())
    assert body["settings"]["god_mode"] is True


# ---- dispatch_event writes through to the cheats module ------------------

def test_toggle_god_mode_sets_cheat(panel):
    p, cheats = panel
    p.open()
    assert p.dispatch_event("toggle:god_mode") is True
    assert cheats.god_mode_active() is True
    assert p.dispatch_event("toggle:god_mode") is True
    assert cheats.god_mode_active() is False


def test_toggle_double_weapons_sets_cheat(panel):
    p, cheats = panel
    p.open()
    assert p.dispatch_event("toggle:double_weapons") is True
    assert cheats.double_player_weapons_active() is True


def test_toggle_no_npc_shields_sets_cheat(panel):
    p, cheats = panel
    p.open()
    assert p.dispatch_event("toggle:no_npc_shields") is True
    assert cheats.disable_npc_shields_active() is True


def test_dispatch_cancel_closes(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False


def test_dispatch_tab_combat_ok(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("tab:combat") is True


def test_dispatch_unknown_tab_returns_false(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("tab:nope") is False


def test_dispatch_unknown_returns_false(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("bogus") is False


# ---- render_payload -------------------------------------------------------

def test_render_payload_shape(panel):
    p, _ = panel
    p.open()
    body = _body(p.render_payload())
    assert body["visible"] is True
    assert body["tabs"] == [{"id": "combat", "label": "Combat"}]
    assert body["selected_tab"] == "combat"
    assert body["settings"] == {
        "god_mode": False, "double_weapons": False, "no_npc_shields": False,
    }


def test_render_payload_dedups(panel):
    p, _ = panel
    p.open()
    assert p.render_payload() is not None
    assert p.render_payload() is None


def test_render_payload_re_emits_after_toggle(panel):
    p, _ = panel
    p.open()
    p.render_payload()
    p.dispatch_event("toggle:god_mode")
    body = _body(p.render_payload())
    assert body["settings"]["god_mode"] is True


def test_render_payload_close_emits_hide(panel):
    p, _ = panel
    p.open()
    p.render_payload()
    p.close()
    out = p.render_payload()
    assert _body(out) == {"visible": False}


def test_invalidate_re_emits(panel):
    p, _ = panel
    p.open()
    first = p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() == first


# ---- keyboard input -------------------------------------------------------

class _Keys:
    KEY_UP = 1; KEY_DOWN = 2; KEY_LEFT = 3; KEY_RIGHT = 4
    KEY_SPACE = 5; KEY_ENTER = 6; KEY_ESCAPE = 7


class _Reader:
    def __init__(self):
        self.keys = _Keys()
        self._pressed = set()
    def press(self, key):
        self._pressed.add(key)
    def key_pressed(self, key):
        if key in self._pressed:
            self._pressed.discard(key)
            return True
        return False


def test_handle_input_when_closed_is_noop(panel):
    p, cheats = panel
    r = _Reader()
    r.press(r.keys.KEY_DOWN)
    p.handle_input(r)
    assert cheats.god_mode_active() is False


def test_focusables_order(panel):
    p, _ = panel
    assert p._focusables() == [
        ("tab", "combat"),
        ("ctrl", "god_mode"),
        ("ctrl", "double_weapons"),
        ("ctrl", "no_npc_shields"),
    ]


def test_space_on_god_mode_row_toggles(panel):
    p, cheats = panel
    p.open()
    r = _Reader()
    steps = p._focusables().index(("ctrl", "god_mode")) + 1
    for _ in range(steps):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_SPACE); p.handle_input(r)
    assert cheats.god_mode_active() is True


def test_handle_key_esc_when_open_closes(panel):
    p, _ = panel
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_developer_options_panel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ui.developer_options_panel'`.

- [ ] **Step 3: Write the panel**

Create `engine/ui/developer_options_panel.py`:

```python
"""Developer Options panel — dev-only pause-menu modal with combat cheats.

Mirrors engine.ui.configuration_panel.ConfigurationPanel: a Panel
subclass pumped by PanelRegistry, rendered as a pause-menu modal that
reuses the configuration panel's cp-* CSS. A single "Combat" tab exposes
three toggles wired to engine.dev_combat_cheats. Dev-mode only —
constructed in host_loop.py inside ``if dev_mode.is_enabled():``.

Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from engine.ui.panel import Panel
from engine.appc import dev_combat_cheats as cheats


class DeveloperOptionsPanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        self._tabs: List[Tuple[str, str]] = [("combat", "Combat")]
        self._selected_tab = "combat"
        self._god_mode = cheats.god_mode_active()
        self._double_weapons = cheats.double_player_weapons_active()
        self._no_npc_shields = cheats.disable_npc_shields_active()
        self._visible = False
        self._focused = -1
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "developer-options"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        # Re-sync the local mirror from the cheats module so a reopened
        # panel reflects whatever the flags currently are.
        self._god_mode = cheats.god_mode_active()
        self._double_weapons = cheats.double_player_weapons_active()
        self._no_npc_shields = cheats.disable_npc_shields_active()
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._focused = -1

    def render_payload(self) -> Optional[str]:
        snapshot = (
            self._visible, tuple(self._tabs), self._selected_tab,
            self._focused, self._god_mode, self._double_weapons,
            self._no_npc_shields,
        )
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setDeveloperOptions(" + json.dumps({"visible": False}) + ");"
        payload = {
            "visible": True,
            "tabs": [{"id": tid, "label": label} for tid, label in self._tabs],
            "selected_tab": self._selected_tab,
            "focused": self._focused,
            "settings": {
                "god_mode": self._god_mode,
                "double_weapons": self._double_weapons,
                "no_npc_shields": self._no_npc_shields,
            },
        }
        return "setDeveloperOptions(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action == "toggle:god_mode":
            self._god_mode = not self._god_mode
            cheats.set_god_mode(self._god_mode)
            return True
        if action == "toggle:double_weapons":
            self._double_weapons = not self._double_weapons
            cheats.set_double_player_weapons(self._double_weapons)
            return True
        if action == "toggle:no_npc_shields":
            self._no_npc_shields = not self._no_npc_shields
            cheats.set_disable_npc_shields(self._no_npc_shields)
            return True
        if action.startswith("tab:"):
            tab_id = action[len("tab:"):]
            if any(tid == tab_id for tid, _ in self._tabs):
                self._selected_tab = tab_id
                return True
            return False
        return False

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def _focusables(self) -> list:
        """Ordered focusable list: the tab row then the combat controls."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "combat":
            out += [("ctrl", "god_mode"), ("ctrl", "double_weapons"),
                    ("ctrl", "no_npc_shields")]
        return out

    def handle_input(self, h) -> None:
        """Poll ↑/↓ to move focus and Space/Enter to activate. Mirrors
        ConfigurationPanel.handle_input; optional keys degrade silently."""
        if not self._visible:
            return
        keys = h.keys
        focusables = self._focusables()
        if not focusables:
            return
        if h.key_pressed(keys.KEY_DOWN):
            self._focused = 0 if self._focused < 0 else (self._focused + 1) % len(focusables)
        if h.key_pressed(keys.KEY_UP):
            self._focused = (len(focusables) - 1) if self._focused < 0 \
                else (self._focused - 1) % len(focusables)
        kind, target = focusables[self._focused] if self._focused >= 0 else (None, None)
        k_space = getattr(keys, "KEY_SPACE", None)
        k_enter = getattr(keys, "KEY_ENTER", None)

        def _pressed(code):
            return code is not None and h.key_pressed(code)

        activate = _pressed(k_space) or _pressed(k_enter)
        if activate and kind == "ctrl":
            self.dispatch_event("toggle:" + target)
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_developer_options_panel.py -v`
Expected: PASS (all panel tests green).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/developer_options_panel.py tests/unit/test_developer_options_panel.py
git commit -m "feat(ui): DeveloperOptionsPanel — Combat cheats modal

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: CEF view (HTML + JS + CSS)

No automated test — this is the browser view. Verified manually in Task 6.

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Create: `native/assets/ui-cef/js/developer_options.js`
- Modify: `native/assets/ui-cef/css/configuration_panel.css`

- [ ] **Step 1: Add the HTML section**

In `native/assets/ui-cef/index.html`, find the configuration overlay `</section>` (the block whose root is `<section id="configuration-panel">`, ending at `</section>` right before `<!-- Tactical-view layout zones.`). Immediately after that `</section>`, insert:

```html

    <!-- Developer Options overlay (developer-only).
         setDeveloperOptions({...}) drives state; clicks fire
         dauntlessEvent('developer-options/<verb>:<arg>'). ESC and the
         Done button both fire 'developer-options/cancel'. The .dev-only
         class keeps it hidden outside --developer; the panel is also only
         registered with the PanelRegistry under --developer.
         Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md -->
    <section id="developer-options-panel" class="dev-only">
      <div class="cp-modal">
        <div class="cp-header">Developer Options</div>
        <div class="cp-content">
          <nav class="cp-tabstrip" id="do-tabstrip"></nav>
          <div class="cp-body" id="do-body"></div>
        </div>
        <div class="cp-footer">
          <button class="cp-done-button"
                  onclick="dauntlessEvent('developer-options/cancel')">
            Done
          </button>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: Add the script tag**

In `native/assets/ui-cef/index.html`, find:

```html
    <script src="js/configuration_panel.js"></script>
```

Add immediately after it:

```html
    <script src="js/developer_options.js"></script>
```

- [ ] **Step 3: Create the renderer JS**

Create `native/assets/ui-cef/js/developer_options.js`:

```javascript
// Developer Options panel render fn. Driven by Python via
// cef_execute_javascript:
//   setDeveloperOptions({visible:true, tabs, selected_tab, focused, settings});
//   setDeveloperOptions({visible:false});
// Click events fire dauntlessEvent('developer-options/<verb>:<arg>').
// Reuses the cp-* classes from css/configuration_panel.css so the look
// matches the configuration panel.
// Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md.

function escapeHtmlDO(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _doFocusableList(state) {
    const out = state.tabs.map(t => ({kind: 'tab', target: t.id}));
    if (state.selected_tab === 'combat') {
        out.push({kind: 'ctrl', target: 'god_mode'});
        out.push({kind: 'ctrl', target: 'double_weapons'});
        out.push({kind: 'ctrl', target: 'no_npc_shields'});
    }
    return out;
}

function _doRenderTabstrip(state, focusables) {
    let html = '';
    for (let i = 0; i < state.tabs.length; ++i) {
        const t = state.tabs[i];
        const isActive = t.id === state.selected_tab;
        const f = focusables[state.focused];
        const isFocused = f && f.kind === 'tab' && f.target === t.id;
        const cls = 'cp-tab'
                  + (isActive ? ' cp-tab--active' : '')
                  + (isFocused ? ' cp-focused' : '');
        html += '<div class="' + cls + '"'
              +   ' onclick="dauntlessEvent(\'developer-options/tab:' + t.id + '\')">'
              +     escapeHtmlDO(t.label)
              + '</div>';
    }
    return html;
}

function _doToggleRow(label, key, on, focused) {
    return '<div class="cp-row' + (focused ? ' cp-focused' : '') + '">'
         +   '<div class="cp-row__label">' + escapeHtmlDO(label) + '</div>'
         +   '<div class="cp-row__control">'
         +     '<button class="cp-toggle' + (on ? ' cp-toggle--on' : '') + '"'
         +        ' onclick="dauntlessEvent(\'developer-options/toggle:' + key + '\')">'
         +       (on ? 'On' : 'Off')
         +     '</button>'
         +   '</div>'
         + '</div>';
}

function _doRenderCombatBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';
    html += _doToggleRow('God Mode', 'god_mode', s.god_mode, isFoc('god_mode'));
    html += _doToggleRow('2× Player Weapon Strength', 'double_weapons',
                         s.double_weapons, isFoc('double_weapons'));
    html += _doToggleRow('Disable NPC Shields', 'no_npc_shields',
                         s.no_npc_shields, isFoc('no_npc_shields'));
    return html;
}

function setDeveloperOptions(state) {
    const root = document.getElementById('developer-options-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const focusables = _doFocusableList(state);
    const tabstrip = document.getElementById('do-tabstrip');
    if (tabstrip) tabstrip.innerHTML = _doRenderTabstrip(state, focusables);
    const body = document.getElementById('do-body');
    if (body) {
        body.innerHTML = (state.selected_tab === 'combat')
            ? _doRenderCombatBody(state, focusables)
            : '';
    }
    root.style.display = 'flex';
}
```

- [ ] **Step 4: Share the backdrop CSS**

In `native/assets/ui-cef/css/configuration_panel.css`, find:

```css
#configuration-panel {
    display: none;
    position: fixed;
    inset: 0;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.55);
    z-index: 50;
    font-family: "Antonio", sans-serif;
}
```

Replace the selector line so both panels share the backdrop chrome:

```css
#configuration-panel,
#developer-options-panel {
    display: none;
    position: fixed;
    inset: 0;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.55);
    z-index: 50;
    font-family: "Antonio", sans-serif;
}
```

- [ ] **Step 5: Sanity-check the JS parses**

Run: `node --check native/assets/ui-cef/js/developer_options.js`
Expected: no output (exit 0). If `node` is unavailable, skip — the file is verified live in Task 6.

- [ ] **Step 6: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/developer_options.js native/assets/ui-cef/css/configuration_panel.css
git commit -m "feat(ui-cef): Developer Options view (HTML + renderer JS, shared cp- styling)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Wire the panel into host_loop (dev-mode only)

No automated test — host_loop is the heavyweight integration layer (and the full suite OOMs). Verified live in Task 6. Make the edits carefully.

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Default the panel to the null stand-in**

In `engine/host_loop.py`, find the mission-picker default line (inside the run loop, around `engine/host_loop.py:2031`):

```python
        mission_picker = _NULL_PICKER  # noop until we know dev mode is on
        if dev_mode.is_enabled():
```

Replace with:

```python
        mission_picker = _NULL_PICKER  # noop until we know dev mode is on
        developer_options_panel = _NULL_PICKER  # noop until dev mode confirmed
        if dev_mode.is_enabled():
```

- [ ] **Step 2: Construct the panel + register its pause-menu row**

Still inside that `if dev_mode.is_enabled():` block, find:

```python
            dev_mode.register_dev_pause_menu_entry(
                "Load Mission…", mission_picker.open,
            )
```

Add immediately after it (still inside the `if`):

```python

            from engine.ui.developer_options_panel import DeveloperOptionsPanel
            developer_options_panel = DeveloperOptionsPanel()
            dev_mode.register_dev_pause_menu_entry(
                "Developer Options…", developer_options_panel.open,
            )
```

- [ ] **Step 3: Register the panel with the PanelRegistry**

Find:

```python
        if dev_mode.is_enabled():
            registry.register(mission_picker)
```

Replace with:

```python
        if dev_mode.is_enabled():
            registry.register(mission_picker)
            registry.register(developer_options_panel)
```

- [ ] **Step 4: Add the panel to the ESC priority chain + blocker list**

Find:

```python
                if mission_picker.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        mission_picker.handle_key_esc()
                elif configuration_panel.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        configuration_panel.handle_key_esc()
                else:
                    pause.apply(_h)
                _apply_pause_menu_side_effects(
                    pause, view_mode, _h,
                    [mission_picker, configuration_panel],
                )
```

Replace with:

```python
                if mission_picker.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        mission_picker.handle_key_esc()
                elif developer_options_panel.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        developer_options_panel.handle_key_esc()
                elif configuration_panel.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        configuration_panel.handle_key_esc()
                else:
                    pause.apply(_h)
                _apply_pause_menu_side_effects(
                    pause, view_mode, _h,
                    [mission_picker, developer_options_panel, configuration_panel],
                )
```

- [ ] **Step 5: Add the panel to the keyboard-input dispatch chain**

Find:

```python
                if pause.is_open:
                    # When the configuration panel is open it consumes
                    # keyboard input — pause-menu navigation would
                    # otherwise activate rows hidden behind the modal.
                    if configuration_panel.is_open():
                        configuration_panel.handle_input(_h)
                    elif not mission_picker.is_open():
                        pause_menu.handle_input(_h)
                        _script = pause_menu.render_payload()
                        if _script is not None:
                            _h.cef_execute_javascript(_script)
```

Replace with:

```python
                if pause.is_open:
                    # When a settings modal is open it consumes keyboard
                    # input — pause-menu navigation would otherwise activate
                    # rows hidden behind the modal.
                    if configuration_panel.is_open():
                        configuration_panel.handle_input(_h)
                    elif developer_options_panel.is_open():
                        developer_options_panel.handle_input(_h)
                    elif not mission_picker.is_open():
                        pause_menu.handle_input(_h)
                        _script = pause_menu.render_payload()
                        if _script is not None:
                            _h.cef_execute_javascript(_script)
```

- [ ] **Step 6: Byte-compile to catch syntax errors**

Run: `uv run python -m py_compile engine/host_loop.py`
Expected: no output (exit 0).

- [ ] **Step 7: Run the touched unit suites to confirm nothing regressed**

Run: `uv run pytest tests/unit/test_dev_combat_cheats.py tests/unit/test_combat_cheats.py tests/unit/test_developer_options_panel.py tests/unit/test_dev_mode.py tests/unit/test_configuration_panel.py tests/unit/test_panel_registry.py -v`
Expected: PASS (all green).

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): wire Developer Options panel into the pause menu (dev mode only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Live verification

No code changes — confirm the feature end-to-end in the real app.

- [ ] **Step 1: Build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds `build/dauntless` with no errors. (CSS/JS/HTML changes need no rebuild, but the host loop change does not either — this rebuild is belt-and-braces in case the binary is stale.)

- [ ] **Step 2: Production run — menu must be ABSENT**

Run: `./build/dauntless` (no `--developer`). Open the pause menu (ESC).
Expected: NO "Developer Options…" row. The configuration panel still works.

- [ ] **Step 3: Developer run — menu present + styled**

Run: `./build/dauntless --developer`. Open the pause menu (ESC).
Expected: a "Developer Options…" row appears after "Load Mission…". Click it.
Expected: a modal styled identically to the configuration panel (maroon→orange gradient header reading "Developer Options", dark body, purple "Combat" tab active), with three Off toggles: God Mode, 2× Player Weapon Strength, Disable NPC Shields. ESC and Done return to the pause menu.

- [ ] **Step 4: Functional check — each cheat**

In a mission with the player and at least one hostile:
- Toggle **God Mode** On → take fire → player hull/shields do not drop; shield flashes / hull sparks still show.
- Toggle **2× Player Weapon Strength** On → enemy ships die roughly twice as fast under player fire.
- Toggle **Disable NPC Shields** On → enemy shield bubbles stop absorbing; hull damage lands immediately.

- [ ] **Step 5: Update CLAUDE.md reference table**

Add a row to the reference table in `CLAUDE.md` (near the "Dev mission loader" row):

```markdown
| Developer Options menu | `engine/ui/developer_options_panel.py`, `engine/dev_combat_cheats.py`, `native/assets/ui-cef/js/developer_options.js`, `docs/superpowers/specs/2026-06-08-developer-options-menu-design.md` | Developer-only pause-menu "Developer Options…" modal styled like the configuration panel. Combat tab toggles God Mode, 2× player weapon strength, and Disable NPC Shields — all hook `combat.apply_hit` via the dev-mode-gated flags in `dev_combat_cheats`. Off by default, not persisted, dev-mode only. |
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record Developer Options menu in CLAUDE.md reference table

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** cheat module (Task 1) ✓; combat hooks for all three cheats incl. god-mode no-mutation-but-feedback (Task 2) ✓; panel mirroring ConfigurationPanel (Task 3) ✓; HTML/JS reusing cp- styling + shared backdrop selector (Task 4) ✓; dev-only wiring in host_loop incl. ESC priority + input dispatch + null stand-in (Task 5) ✓; dev-only visibility + no-persistence verified (Task 6) ✓.
- **Naming consistency:** module getters `god_mode_active` / `double_player_weapons_active` / `disable_npc_shields_active` and setters `set_god_mode` / `set_double_player_weapons` / `set_disable_npc_shields` are used identically across Tasks 1–3 and 5. Event/JS keys `god_mode` / `double_weapons` / `no_npc_shields` are consistent between the panel `dispatch_event`, `developer_options.js`, and the focusable lists.
- **Camera shake under god mode:** intentionally follows the existing shield-absorbed rule (no shake when shields take it) per the spec; no extra code needed.
```

# Developer Options menu — design

**Date:** 2026-06-08
**Status:** approved, pre-implementation

## Summary

A developer-only "Developer Options" modal, opened from a dev-gated
pause-menu row, styled identically to the existing configuration panel.
It carries a single tab for now — **Combat** — exposing three toggles:

1. **God Mode** — On/Off (default Off): the player ship takes no damage.
2. **2× Player Weapon Strength** — On/Off (default Off): the player's
   outgoing weapon damage is doubled.
3. **Disable NPC Shields** — On/Off (default Off): every non-player
   ship's shields stop absorbing damage.

All three are runtime cheats for development/testing. They are reachable
**only** when the binary is launched with `--developer`, default Off,
apply live, and are **not** persisted across launches (matching the
configuration panel).

## Context

The existing pieces this builds on:

- **`ConfigurationPanel`** (`engine/ui/configuration_panel.py`,
  `native/assets/ui-cef/js/configuration_panel.js`,
  `css/configuration_panel.css`) — a `Panel` subclass pumped by
  `PanelRegistry`, rendered as a pause-menu modal with a left tabstrip +
  per-tab body. The Developer Options panel mirrors its shape and reuses
  its `cp-*` CSS classes.
- **`MissionPicker`** (`engine/dev_mission_picker.py`) — the established
  pattern for a **dev-only** pause-menu row: constructed inside
  `if dev_mode.is_enabled():`, registered via
  `dev_mode.register_dev_pause_menu_entry(label, handler)`, and added to
  the `PanelRegistry`.
- **`combat.apply_hit(ship, damage, hit_point, source, …)`**
  (`engine/appc/combat.py:317`) — the single chokepoint through which
  all weapon damage flows. `ship` is the victim; `source` is the firer.
  The player is identified by identity comparison against
  `App.Game_GetCurrentGame().GetPlayer()`, the same pattern
  `hit_feedback.py:157` uses.
- **`ShieldSubsystem`** (`engine/appc/subsystems.py:1859`) — exposes
  `ApplyDamage(face, amount)` (mutates + returns overflow) and a
  non-mutating reader `GetCurrentShields(face)`.

## Architecture

Five units, each with one purpose.

### 1. Cheat state — `engine/dev_combat_cheats.py` (new)

Single source of truth for the three flags. Module-level booleans, all
default `False`, with setters and getters:

```
set_god_mode(b) / god_mode_active() -> bool
set_double_player_weapons(b) / double_player_weapons_active() -> bool
set_disable_npc_shields(b) / disable_npc_shields_active() -> bool
```

Each `*_active()` getter returns `_flag and dev_mode.is_enabled()`.
Gating on the dev flag inside the getter is defense-in-depth: even if a
flag were somehow set in a production build, combat behaviour cannot
change. There is also a `reset()` helper that clears all three (used by
tests; not wired to any runtime teardown).

**Why a separate module:** `combat.apply_hit` must read the flags
without importing the UI layer, and the panel must write them without
importing combat. The module is the seam — neither side depends on the
other.

### 2. Combat hooks — `engine/appc/combat.py:apply_hit`

At the top of `apply_hit`, resolve the player once (guarded; `None` if
no game/player). Compute `target_is_player = player is not None and
ship is player` and `source_is_player = player is not None and source is
player`. Then:

- **2× weapons** — if `double_player_weapons_active()` and
  `source_is_player`: `damage = float(damage) * 2.0`. Done before the
  shield/hull math so the doubled value flows through everything,
  including `hit_feedback.dispatch(damage=…)` and `WeaponHitEvent`.

- **Disable NPC shields** — if `disable_npc_shields_active()` and **not**
  `target_is_player`: force the local `shields_online = False`. The
  shield bite is skipped; full damage reaches hull/subsystems and no NPC
  shield flash fires.

- **God mode** — `commit = not (god_mode_active() and target_is_player)`.
  The three state-mutating calls are guarded by `commit`:
  - `shields.ApplyDamage(face, remaining)` runs only when `commit`;
    under no-commit, absorption is computed without draining via
    `absorbed = min(remaining, shields.GetCurrentShields(face))` and
    `remaining -= absorbed`.
  - hull `ship.DamageSystem(hull, post_shield)` runs only when `commit`;
    `absorbed_hull` is still set for feedback.
  - subsystem `ship.DamageSystem(sub, amount)` runs only when `commit`;
    allocations and `absorbed_subsystem_total` are still accumulated for
    feedback. (Because no `DamageSystem` runs, `_subsystem_state_flags`
    before/after are identical, so `primary_transition` stays `None` —
    no spurious CRITICAL severity.)

  `hit_feedback.dispatch(...)` and the `WeaponHitEvent` broadcast run
  unchanged. Net effect: the player sees the shield flash (shields up)
  or hull spark + camera shake (shields down) and hears audio, but no
  hull/subsystem/shield state changes.

**Camera shake under god mode:** follows the existing rule
(`hit_feedback.py:157`) — shake fires only for non-`SHIELD` severity.
So a shields-up god-mode hit flashes + plays audio but does **not**
shake; shake returns once shields are down. This is the faithful
behaviour and is intentional.

All three reads default Off and are no-ops outside dev mode, so a
production build's combat path is byte-identical to today.

### 3. Panel — `engine/ui/developer_options_panel.py` (new)

`DeveloperOptionsPanel(Panel)`, closely mirroring `ConfigurationPanel`:

- `name` = `"developer-options"`.
- `tabs` = `[("combat", "Combat")]`; `_selected_tab = "combat"`.
- Holds the three toggle booleans, initialised from the
  `dev_combat_cheats` getters so the panel opens reflecting live state.
- `open()`, `close()` (resets focus), `is_open()`.
- `render_payload()` builds the state dict and emits
  `setDeveloperOptions({...});`, deduped against `_last_pushed` exactly
  like the config panel. Emits `{"visible": False}` when closed.
- `dispatch_event(action)` handles: `"cancel"` (close), `"tab:combat"`,
  `"toggle:god_mode"`, `"toggle:double_weapons"`,
  `"toggle:no_npc_shields"`. Each toggle flips local state **and** calls
  the matching `dev_combat_cheats.set_*`.
- `invalidate()` clears `_last_pushed` (CEF reload hook).
- `handle_key_esc()` closes when visible.
- `handle_input(h)` polls ↑/↓ to move focus and Space/Enter to activate,
  reusing the focusable-list shape from `ConfigurationPanel`
  (`[("tab","combat"), ("ctrl","god_mode"), ("ctrl","double_weapons"),
  ("ctrl","no_npc_shields")]`).

### 4. CEF view — reuses configuration-panel styling

- **`native/assets/ui-cef/index.html`** — new
  `<section id="developer-options-panel">` with the same inner structure
  as `#configuration-panel` (`cp-modal` / `cp-header` / `cp-content` /
  `cp-tabstrip` / `cp-body` / `cp-footer` / `cp-done-button`), reusing
  the `cp-*` classes so the styling is identical. Header text
  "Developer Options"; Done button fires
  `dauntlessEvent('developer-options/cancel')`. Add
  `<script src="js/developer_options.js"></script>`.
- **`native/assets/ui-cef/js/developer_options.js`** (new) — exposes
  `setDeveloperOptions(state)`, a parallel of `configuration_panel.js`:
  renders the tabstrip and the combat body (three `cp-toggle` rows).
  Click handlers fire `dauntlessEvent('developer-options/<verb>:<arg>')`.
- **`native/assets/ui-cef/css/configuration_panel.css`** — the only CSS
  change: extend the backdrop selector to cover both roots:
  `#configuration-panel, #developer-options-panel { … }`. Everything
  else is the shared `cp-*` classes. The future `chrome.css` / `row.css`
  extraction stays deferred.

### 5. Wiring — `engine/host_loop.py` (dev-mode only)

Inside the existing `if dev_mode.is_enabled():` block where the mission
picker is constructed:

- Construct `DeveloperOptionsPanel`.
- `dev_mode.register_dev_pause_menu_entry("Developer Options…",
  developer_options_panel.open)` — appears after "Load Mission…".
- Register it with the `PanelRegistry` (alongside the dev-gated mission
  picker registration).
- Add it to the ESC handler and the `handle_input` polling list next to
  `configuration_panel` / `mission_picker`.

## Data flow

```
pause menu row "Developer Options…"  (dev only)
        │ click
        ▼
DeveloperOptionsPanel.open()  →  render_payload()  →  setDeveloperOptions(state)
        ▲                                                     │ toggle click
        │ set local state                                     ▼
        └──────── dispatch_event("toggle:god_mode") ◄── dauntlessEvent(...)
                        │
                        ▼
            dev_combat_cheats.set_god_mode(True)
                        │ flag read each hit
                        ▼
        combat.apply_hit(...)  →  god_mode_active() etc.  →  damage routing
```

## Testing

Focused unit tests only — **the full pytest suite OOMs the host**
(>100 GB RAM); always run targeted subsets.

- **`dev_combat_cheats`** — all flags default Off; setters flip them;
  `*_active()` returns `False` when dev mode is off regardless of the
  underlying flag; `reset()` clears all three.
- **`combat.apply_hit` under cheats** (reuse existing combat test
  fakes/patterns):
  - God mode On + target is player → no `DamageSystem` / `ApplyDamage`
    calls; `hit_feedback.dispatch` still invoked; `WeaponHitEvent` still
    broadcast.
  - God mode On + target is NOT player → damage applied normally.
  - 2× On + source is player → downstream damage doubled; source not
    player → unchanged.
  - Disable NPC shields On + target is NPC → shield bite skipped (full
    damage to hull); target is player → shields untouched.
  - All cheats Off / dev mode off → behaviour identical to today.
- **`DeveloperOptionsPanel`** — toggles flip both local state and the
  `dev_combat_cheats` module; `render_payload` shape + dedup; ESC closes;
  `tab:combat` is accepted, unknown tabs rejected.

## Out of scope (YAGNI)

- No persistence across launches (matches the configuration panel).
- No keybindings — menu access only.
- No additional tabs or cheats beyond Combat's three.
- No `chrome.css` / `row.css` extraction (separate deferred refactor).

## Files

New:
- `engine/dev_combat_cheats.py`
- `engine/ui/developer_options_panel.py`
- `native/assets/ui-cef/js/developer_options.js`
- tests under `tests/` mirroring existing panel/combat test locations.

Modified:
- `engine/appc/combat.py` — cheat hooks in `apply_hit`.
- `engine/host_loop.py` — dev-mode construction + wiring.
- `native/assets/ui-cef/index.html` — new section + script tag.
- `native/assets/ui-cef/css/configuration_panel.css` — shared backdrop
  selector.

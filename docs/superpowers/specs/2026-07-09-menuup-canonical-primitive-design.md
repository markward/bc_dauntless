# `MenuUp()` as the canonical menu primitive + `AT_MENU_UP` / `AT_MENU_DOWN` dispatch

**Date:** 2026-07-09
**Status:** Design — approved, pending spec review
**Branch:** none yet (spec authored on `main`, intentionally uncommitted)
**Follows:** SP-E from the E1M1 walk-on / orientation-family follow-up list
(`docs/superpowers/specs/2026-07-08-orientation-family-design.md`).

## Problem

Two related defects, one root cause.

**1. The scripted menu actions are no-ops.** `AT_MENU_UP` / `AT_MENU_DOWN`
(`CharacterAction` types 20/21) fall through to the inline no-op path in
`CharacterAction.Play` (`engine/appc/ai.py`). Missions fire them to bring an
officer's menu up mid-scene:

- **E1M1 crew-intro** (`E1M1.py:2106`): `AT_MENU_UP(Brex)` is followed by
  `MoveMouseToButton(pReportButton)` and
  `SetUIObjectHighlighted(pBrexMenu, pReportButton)` — the tutorial points the
  cursor at and highlights **buttons inside Brex's menu**, which only works if
  the menu is open. `AT_MENU_DOWN(Brex)` closes it.
- **E8M2** (`E8M2.py:3443`): `AT_MENU_UP(Liu)` raises Liu's Battle Group menu;
  `AT_MENU_DOWN` closes it.
- **QuickBattle intro** (`QuickBattle.py:3632`): `AT_MENU_UP(XO)` inside
  `QBExposition`.

**2. `CharacterClass.MenuUp()` opens nothing — the layering is inverted.** In BC,
`MenuUp()` is the **native primitive that brings the officer's menu up**:

- `BridgeHandlers.py:612` — the officer-click seam:
  `if (pCharacter.MenuUp()): CharacterInteraction(pCharacter)` — "bring up their
  menu; if it came up, do the interaction."
- `QuickBattle.py:3367-3368` — commented `# Bring up saffi's menu` /
  `g_pXO.MenuUp()`.
- `AT_MENU_UP` is merely the **sequenceable wrapper** around that same method.

Our engine inverted it: the CEF panel opens the menu (`crew_menu_panel.toggle_menu`)
and then calls `officer.MenuUp()` **downstream** as a notification that only sets a
state flag and requests the turn-to-captain
(`engine/appc/characters.py:626`, `engine/ui/crew_menu_panel.py:248`). So
`MenuUp()` opens nothing, and **every SDK script that calls it directly is
silently dead** — including QuickBattle's `g_pXO.MenuUp()`, the `BridgeHandlers`
click seam, `pViewscreen.MenuUp()`, and `HelmMenuHandlers.pHelm.MenuDown()`.

The turn-to-captain itself *is* faithful today (it resolves the SDK-registered
`<location>TurnCaptain` animation through the real controller). Only the
**menu-open layering** is wrong.

### The acknowledgement trap

`CharacterInteraction()` (`BridgeHandlers.py:640`) is what plays the officer's
"Yes sir" line (`AT_SAY_LINE` via `GetYesSir()`), and BC calls it **after**
`MenuUp()` on the **click path only** — it is **not** inside `MenuUp()`.

Our `toggle_menu` calls `_acknowledge` on *every* open. If the refactor leaves it
there, a **scripted** `AT_MENU_UP` would make officers bark "Yes sir" over the
mission's own dialogue (E1M1's crew-intro). The acknowledgement must move onto
the click path.

## Goals / scope

### In scope

Restore BC's layering and make the scripted actions real:

1. `CharacterClass.MenuUp()` / `MenuDown()` become **the** primitive that opens /
   closes the officer's menu (driving the panel), sets the state flag, and drives
   the turn.
2. The crew-menu panel becomes a **consumer**: pure `show_menu` / `hide_menu`
   view-state methods that never call back into `MenuUp`/`MenuDown`.
3. `AT_MENU_UP` / `AT_MENU_DOWN` dispatch becomes a thin wrapper calling them.
4. The spoken acknowledgement moves onto the **click** path only (BC's
   `CharacterInteraction`), so scripted opens are silent.

### Out of scope (explicit follow-ups)

- **E1M1 crew-intro choreography.** The mouse-cursor and UI-highlight script
  actions the tutorial layers on top (`MoveMouseToButton`,
  `SetUIObjectHighlighted`, `HoldMouseAtButton`, `MoveMouseToCenter`,
  `HoldMouseAtCenter`). This spec is a **prerequisite** for that slice, not part
  of it.
- **The QuickBattle XO *setup* menu** (`g_pXOMenu`, the QB config panel) if it is
  not reachable as the XO's `GetMenu()`. Verify per-mission; wiring it is separate.

## Architecture

Three layers, mirroring BC. **No native/renderer change** — pure Python.

### 1. View state — `engine/ui/crew_menu_panel.py`

- `show_menu(menu) -> None` — **pure** view open: set `_open_menu_id`, clear
  `_expanded_ids`, `menu.SendActivationEvent()` (BC broadcasts activation on
  open). Idempotent (already-open → no-op).
- `hide_menu() -> None` — **pure** view close: clear `_open_menu_id` and
  `_expanded_ids`. Idempotent.
- `open_officer() -> CharacterClass | None` — new **public** reader for the
  officer whose menu is currently open (promotes the existing private
  `_menu_officer()`); `MenuUp` needs it to enforce the single-open invariant.
- **Neither `show_menu` nor `hide_menu` calls `MenuUp`/`MenuDown`, and neither
  acknowledges.** This is what makes recursion impossible by construction.
- `_reconcile_turn` is **retired** — the turn moves into `MenuUp`/`MenuDown`.
- Existing readers (`open_menu_label`, `has_open_menu`) are unchanged.

### 2. Canonical primitive — `engine/appc/characters.py` `CharacterClass`

```
MenuUp() -> int:
    menu = self.GetMenu()                     # STTopLevelMenu, or falsy _NULL_MENU
    if not menu or not menu.IsEnabled(): return 0   # nothing to raise (stock BC)
    panel = crew_menu_hotkeys.get_panel()     # None when headless
    if panel is not None:
        other = panel.open_officer()          # single-open invariant
        if other is not None and other is not self:
            other.MenuDown()                  # closes + turns them back
        panel.show_menu(menu)
    self._data["MenuUp"] = True
    self._notify_menu(turn=True)              # existing helper: turn-to-captain,
                                              # already None-controller guarded
    dispatch_character_menu(self, is_open=True)
    return 1

MenuDown() -> None:
    panel = crew_menu_hotkeys.get_panel()
    if panel is not None and panel.open_officer() is self:
        panel.hide_menu()
    self._data["MenuUp"] = False
    self._notify_menu(turn=False)             # existing helper: turn-back
    dispatch_character_menu(self, is_open=False)
```

- **Headless** (no panel): flag + turn + event still fire; no view change. Missions
  and tests behave without a UI.
- **No acknowledgement here** (BC does it in `CharacterInteraction`).
- Best-effort: a panel/menu miss degrades to flag+turn, never raises.

### 3. Callers

- **User click / hotkey** — `toggle_menu(menu)` (CEF title clicks,
  `crew_menu_hotkeys.open_menu_for_label`, `bridge_officer_picking`): resolve the
  menu's officer; if that menu is already open → `officer.MenuDown()`; else
  `officer.MenuUp()` and, on a `1` return, fire `_acknowledge(menu)` — our
  `CharacterInteraction` equivalent.
- **ESC / modal ladder** — `close_open_menu()`: resolve the open officer →
  `officer.MenuDown()`; return whether one was open.
- **Mission dispatch** — `engine/appc/ai.py` `CharacterAction.Play()`:
  `AT_MENU_UP` → `cc.MenuUp()`; `AT_MENU_DOWN` → `cc.MenuDown()`. Completes
  **inline** (open/close is instant; sequences supply their own delays).
  Best-effort: no cast / no menu / no panel / exception → inline `Completed()`, so
  a `TGSequence` can never stall. **No acknowledgement.**

### Seam

`engine/ui/crew_menu_hotkeys.py` gains `get_panel()` returning the already-wired
`_wired_panel` (or `None`). `characters.py` and `ai.py` reach the panel through
it with a deferred import, best-effort.

## Data flow

```
Mission TGSequence: AT_MENU_UP(Brex)        User clicks Brex on the bridge
        │                                            │
        ▼                                            ▼
CharacterAction.Play                          panel.toggle_menu(BrexMenu)
  cc.MenuUp()  ──────────────┐                  officer = Brex
  Completed() (inline)       │                  Brex.MenuUp() ────┐
  (no ack)                   │                  if returned 1:    │
                             ▼                     _acknowledge() │  ("Yes sir")
                   CharacterClass.MenuUp()  ◄──────────────────────┘
                     close other officer's menu (their MenuDown)
                     panel.show_menu(GetMenu())   # pure view
                     flag = True; turn-to-captain; tutorial event
                     return 1
```

## Error handling

Every step is best-effort and degrades rather than raising: a falsy/disabled
`GetMenu()` returns `0` (nothing raised); a missing panel (headless) still sets
the flag, turns, and fires the event; any exception in the dispatch path
completes the action inline so a mission `TGSequence` never stalls. The
dialogue/audio path is untouched.

## Testing

- **`MenuUp`/`MenuDown` units** (fake panel): opens via `show_menu`, sets the
  flag, requests the turn, fires the tutorial event, returns `1`; falsy or
  disabled `GetMenu()` → returns `0` and no view change; **single-open** — opening
  B closes A *and* turns A back; headless (no panel) → flag + turn only, no raise.
- **Panel units**: `show_menu`/`hide_menu` are pure and idempotent and never call
  `MenuUp`/`MenuDown` (guards the recursion invariant); `toggle_menu` delegates to
  `officer.MenuUp()`/`MenuDown()`; `close_open_menu` → `officer.MenuDown()`.
- **Acknowledgement regression** (the trap): a **scripted** `AT_MENU_UP` fires
  **no** "Yes sir"; a **user click** does.
- **Dispatch units**: `AT_MENU_UP`/`AT_MENU_DOWN` call `cc.MenuUp()`/`MenuDown()`,
  complete inline, and every best-effort miss still completes.
- **Regression**: existing crew-menu, hotkey, ESC-ladder, turn-to-captain, and the
  E1M1 character-select tutorial tests stay green (the click path must be
  observably unchanged).
- **Gate**: `scripts/check_tests.sh` (pytest + ctest) green; no new
  `tests/known_failures.txt` entries.
- **GUI verify**: clicking an officer opens their menu, turns them to the captain,
  and plays "Yes sir"; E8M2's Liu Battle Group menu raises on its scripted beat;
  E1M1's crew-intro raises/closes Brex's menu with **no** spurious "Yes sir"; and
  QuickBattle's win-sequence `g_pXO.MenuUp()` brings Saffi's menu up (dead today).

## Follow-ups (do not lose)

1. **E1M1 crew-intro choreography** — the mouse-cursor / UI-highlight script
   actions this spec unblocks.
2. **QB XO setup menu** (`g_pXOMenu`) — verify it is reachable as the XO's
   `GetMenu()`; wire it if not.
3. Still open from the walk-on list: SP-A bug #7 (concurrent `AT_MOVE` overwrite),
   SP-B other-mission `AT_MOVE` sweep, SP-D lift-door ownership. Plus the
   orientation-family leftovers (`CS_TURNED` home in the `AT_TURN` flow; `_NOW`
   is instant-completion not snap-to-pose; the snap-fallback edge).

## Related memories

`project_orientation_family`, `project_e1m1_character_walkon`,
`project_crew_menu_panel`, `project_bridge_officer_speech`,
`project_quickbattle_boot_and_panel`, `feedback_sdk_drives_everything`.

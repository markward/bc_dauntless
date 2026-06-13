# Crew menu panel restyle + layout integration — design

**Date:** 2026-06-13
**Status:** Spec draft, awaiting user review.
**Motivation:** The crew menu (F1–F5 bridge menus) currently renders in a
bespoke blue palette (`rgba(10,20,40)` / `#3a6bb8`), absolutely positioned at
the top-left with a z-index, and nests via hover-activated flyout sub-panels.
Every other tactical panel (ship-display, target-list, sensors, weapons-display)
shares one visual language — the salmon-orange LCARS chrome (`--bc-menu1-base`
gradient header with black uppercase title, near-opaque `--bc-body-bg` body,
4px `--bc-menu1-base` left border, Antonio font, `--bc-label-text`) — and lives
as an in-flow flex child of a layout zone that sizes and scales it. The crew
menu is the lone outlier. `#tactical-left-column > #tactical-target-stack`
already reserves its top slot in an HTML comment for "officer/tactical menus
(future)".

---

## Goals

1. **Reparent:** the crew menu mounts as the **first child of
   `#tactical-target-stack`**, above `#ship-display-target` and
   `#target-list-panel`. It is a plain in-flow flex child — no absolute
   positioning, no z-index. Closed → renders nothing → collapses to zero
   height (target panels sit at the top). Open → pushes the target panels down.
2. **Panel chrome:** the open menu renders as `<section class="bc-panel
   crew-menu">` with `.bc-panel__header` (title = crew role, e.g. "HELM") +
   `.bc-panel__body`, visually identical to ship-display / target-list.
3. **Child styling:** body rows mirror the target-list row vocabulary
   (`.target-list__row` / `__sub` / `__leaf` indentation + ▸/▾ caret), so the
   crew menu and the target list directly below it share one styling language.
4. **Accordion submenus:** nested SDK menus expand inline as indented rows
   (click parent to expand/collapse), Python-owned expand-state exactly like
   the target list's `expanded` flag — no hover flyouts.

## Non-goals

- **No change to the F1–F5 hotkey chain**, `toggle_menu`/`close_open_menu`/
  open-state, leaf `click:` dispatch (`SendActivationEvent`), or ESC ordering.
  All stay byte-identical.
- **No CSS hoist.** `.bc-panel__header`/`.bc-panel__body` remain defined in
  `panels/ship_display/ship_display.css` and used as global selectors (weapons-
  display already depends on this load order; index.html loads ship_display.css
  before crew_menus.css). The pre-existing implicit dependency is left as-is —
  hoisting the bc-panel base into global.css is a separate cleanup.
- **No bridge-character-click access path** (clicking a crew member in the 3D
  bridge). Still F-keys only; deferred.
- **No persistent menu bar** (already removed) — only the open menu renders.

---

## Design

### HTML (`native/assets/ui-cef/index.html`)

- Delete the `<div id="crew-menu-bar"></div>` near the bottom (after the
  sdk-mirror slots) and its comment.
- Insert as the **first child** of `#tactical-target-stack`, before
  `#ship-display-target`:

  ```html
  <!-- Crew-menu panel — officer/tactical menus summoned by F1-F5
       (CrewMenuPanel). Empty until a menu is open; renders a single
       .bc-panel matching the target panels below it. Spec:
       docs/superpowers/specs/2026-06-13-crew-menu-panel-restyle-design.md -->
  <div id="crew-menu-host"></div>
  ```

### CSS (`native/assets/ui-cef/css/crew_menus.css` — full rewrite)

- Remove `#crew-menu-bar` absolute positioning, z-index, and the blue palette.
- `#crew-menu-host { width: 100%; font-family: "Antonio","Antonio-Regular",
  sans-serif; -webkit-font-smoothing: antialiased; }` — fills the column,
  matching `#target-list-panel`.
- `.crew-menu` is the `.bc-panel` (header + body inherited from the global
  bc-panel classes). No per-element chrome — reuse `.bc-panel__header` /
  `.bc-panel__body`.
- Row classes mirroring target-list (own namespace so they don't collide):
  - `.crew-menu__row` — `display:flex; align-items:center; padding:6px 12px;
    cursor:pointer;` + neutral hover tint `rgba(216,94,86,0.18)` (a tint of
    `--bc-menu1-base`, since crew rows have no affiliation colour).
  - `.crew-menu__row[data-depth="1"] { padding-left: 28px; }` and
    `[data-depth="2"] { padding-left: 44px; }` (mirrors `__sub` / `__leaf`
    indentation; depth is clamped to 2 for indentation, deeper levels reuse 44px).
  - `.crew-menu__caret` — `width:14px; text-align:center; margin-right:8px;
    color:white;` (mirrors `.target-list__caret`; glyph swapped in JS, no CSS
    rotate — keeps text crisp per the target-list comment).
  - `.crew-menu__label` — `flex:1 1 auto; font-size:13px; letter-spacing:0.04em;`.
  - `.crew-menu__row.disabled { opacity:0.4; cursor:default; }`.
- Tokens (`--bc-menu1-base`, `--bc-body-bg`, `--bc-label-text`) are already in
  `:root` via target_list.css (loaded earlier); crew_menus.css consumes them.

### JS (`native/assets/ui-cef/js/crew_menus.js` — rewrite of render fns)

- `setCrewMenus(payload)` targets `#crew-menu-host`, clears it, and appends the
  one menu whose `open` is true (unchanged open-only behaviour).
- `renderCrewMenu(menu)` builds:
  ```
  <section class="bc-panel crew-menu">
    <header class="bc-panel__header">
      <span class="bc-panel__title">{LABEL}</span>
    </header>
    <div class="bc-panel__body">{rows}</div>
  </section>
  ```
- Rows are built recursively with a `depth` argument:
  - A node with children → a `.crew-menu__row` carrying a caret (▾ when
    `node.expanded`, ▸ otherwise); `onclick` →
    `dauntlessEvent("crew-menu/expand:" + node.id)`. When `node.expanded`, its
    children render immediately below at `depth+1`.
  - A leaf node (`type === "button"`) → a `.crew-menu__row` (no caret);
    enabled → `onclick` → `dauntlessEvent("crew-menu/click:" + node.id)`;
    disabled → `.disabled`, no handler.
  - `node.visible === false` rows are skipped (existing behaviour).
- DOM built via `createElement` + `textContent` (current safe approach; labels
  from TGL never reach innerHTML).
- Remove `.crew-menu-title` / `.crew-menu-drop` / `.crew-menu-sub` rendering.

### Python (`engine/ui/crew_menu_panel.py`)

- Add `self._expanded_ids: set[int] = set()`.
- `_snapshot_node`: for any node with children, add `"expanded":
  (wid in self._expanded_ids)`. (Top-level `"open"` flag unchanged.)
- `dispatch_event`: new branch before `toggle:` / `click:` —
  ```
  if action.startswith("expand:"):
      parse id (malformed → log + True);
      resolve via _widgets_by_id (stale → log + True);
      toggle membership in _expanded_ids;
      return True
  ```
- `toggle_menu(menu)`: when it closes or switches the open menu, clear
  `_expanded_ids` (reopened menus start collapsed — matches BC).
- `close_open_menu()`: also clear `_expanded_ids`.
- `invalidate()`: also clear `_expanded_ids` (mission-swap safety, like
  `_open_menu_id`).

## Error handling

- `expand:` malformed / stale ids: logged once, dropped, return True — same
  discipline as `toggle:` / `click:`.
- Unchanged: leaf click on disabled widget no-ops; unknown widget types skipped.

## Testing

Focused subsets only (`.venv/bin/python -m pytest`).

- **Unit (`test_crew_menu_panel.py`, extend):** `expand:<id>` toggles
  `_expanded_ids` and flips the node's `"expanded"` flag in the payload;
  `expanded` nodes carry their children; closing/switching the menu and
  `invalidate()` clear `_expanded_ids`; stale/malformed `expand:` dropped
  (return True). Existing 17 stay green.
- **Regression:** `test_crew_menu_hotkeys.py`, `test_fkey_*`,
  `test_bridge_menu_hotkeys.py`, `test_bridge_menu_activation.py`,
  `test_crew_menu_round_trip.py`, `test_host_loop_unit.py` — payload still
  carries every menu, widget ids stable, so all pass unchanged.
- **Visual:** press F1 → Helm renders as a `.bc-panel` in the left column,
  first above the target list, visually identical in chrome and row styling;
  a submenu (e.g. Set Course) expands inline indented; ESC/F1 closes and the
  column collapses back.

## Follow-ups unlocked

Hoisting the `.bc-panel*` base + shared `:root` tokens into global.css (removes
the implicit ship_display.css dependency for all panels); bridge-character
click-to-open path.

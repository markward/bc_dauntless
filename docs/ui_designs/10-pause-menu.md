# 10 — Pause menu

Visual reference: [10-pause-menu.html](10-pause-menu.html)

The in-game pause menu. Opens on `ESC` during a mission, freezes the simulation, and presents a vertical list of actions. Replaces the original engine's `MWT_OPTIONS` window (a C++-only widget — no SDK Python defines it; see `DefaultKeyboardBinding.py:25`).

Dauntless ships with two actions — **Resume** and **Exit Program**. The original game's "Abort Mission" is omitted: there is no main menu to return to. The shape is intentionally extensible: adding a row is a single `model.add_item(label, action_id)` call in Python with a matching handler registered on the model. The two ends are pinned: **Resume** is always the first row (the safe back-out) and **Exit Program** is always the last (the destructive quit), so neither drifts mid-list as rows are added between them.

## Structure

This widget composes two primitives from elsewhere in the design language — no new chrome:

- The outer panel is the shared **[panel chrome](00-panel-chrome.md)** with Menu1 (salmon-orange) header + 3 px salmon left stripe.
- Each row is the shared **[officer-menu row primitive](01-officer-menu.md)** with the available / chosen / disabled tri-state.

```
        ┌────────────────────────────────────────┐
        │  GAME PAUSED                           │  ← shared chrome header (Menu1 gradient)
        ╞════════════════════════════════════════╡
        ║                                        │
        ║    ▸ Resume                ←  chosen   │  ← row primitive, chosen state
        ║    ▸ Exit Program                      │  ← row primitive, available state
        ║                                        │
        └────────────────────────────────────────┘
```

The pause menu is **modal** — a full-viewport dim sits behind the panel and blocks pointer events outside it. That's the only deviation from the persistent-panel chrome.

## Backdrop (modal-only addition)

| Token | Value |
|---|---|
| Background | `rgba(0, 0, 0, 0.55)` flat dim |
| Pointer events | Blocked outside `.pause-panel` |
| z-index | `100` (above all bridge HUD panels) |

The dim is intentionally flat rather than the radial gradient used by [08 modal-dialog](08-modal-dialog.md) — the pause menu is a navigation surface, not a confirmation prompt, so the focal-centre framing isn't load-bearing.

## Panel

| Element | Token | Value |
|---|---|---|
| Width | n/a | 360 px |
| Header height | n/a | 28 px |
| Header bg | `--bc-menu1-base` → `--bc-menu1-accent` | `linear-gradient(90deg, rgb(216,94,86) 0%, rgb(216,132,80) 100%)` |
| Header text | `--bc-header-fg` | `#ffd` |
| Header corner | n/a | `border-radius: 0 14px 0 0` (top-right only) |
| Body bg | `--bc-panel-bg` | `rgba(10, 10, 16, 0.85)` |
| Body left stripe | `--bc-panel-edge` | `3px solid rgb(216, 94, 86)` |
| Body padding | n/a | `12px 10px` |
| Row gap | n/a | `2px` (vertical margin between rows) |

Header reads `GAME PAUSED` (Antonio 600, 14 px, uppercase, letter-spacing 1.5 px) with **no** `▼` collapse glyph — the menu is dismissed by ESC or the Resume row, not by collapsing the panel.

## Rows

Uses the officer-menu row primitive's available / disabled states verbatim, but a **higher-contrast** chosen/hover variant than the officer menu — the pause menu is a modal navigation surface and the player must read the active row at a glance.

| State | Background | Foreground | Edge | Caret |
|---|---|---|---|---|
| **available** (default) | `rgb(37, 26, 64)` | `rgb(220, 210, 255)` | `rgb(147, 103, 255)` (3 px) | edge colour |
| **chosen** (focused / hover) | `--bc-menu2-highlight` `rgb(173, 132, 255)` (filled) | `#ffffff` | `--bc-chosen-gold` `rgb(255, 210, 90)` (3 px) | gold (matches edge) |
| **pressed** (click `:active`) | `--bc-menu2-base` `rgb(147, 103, 255)` | `#ffffff` | `rgb(255, 210, 90)` | gold |
| **disabled** | `rgb(16, 16, 16)` | `rgb(110, 110, 110)` | `rgb(64, 64, 64)` (3 px) | dim grey |

Row anatomy: 6 px 12 px padding, 13 px Antonio regular, leading `▸` caret with 10 px right margin. Cursor `pointer` to advertise clickability. 80 ms linear transition on background / foreground / edge so the highlight reads as a soft swap rather than a jump.

The chosen+hover treatment intentionally diverges from the officer menu's near-identical "row got a touch brighter" variant: ESC pause is a low-frequency surface (you stop to use it), so the chrome can be louder without polluting the always-on bridge HUD vocabulary.

## SDK runtime contract

There is none — the pause menu is dauntless-native. The model lives in [`engine/ui/pause_menu.py`](../../engine/ui/pause_menu.py) and is driven from the host loop.

```python
from engine.ui.pause_menu import PauseMenuModel

model = PauseMenuModel()
model.add_item("Resume",       "resume", handler=lambda: pause.toggle())
model.add_item("Exit Program", "exit",   handler=lambda: pause.request_quit())

# host_loop, per tick while pause.is_open:
model.handle_input(h)              # ↑/↓ move focus; Enter activates
script = model.render_payload()    # "setPauseMenu({items:[...], focused:0});"
if script:                          # None when state is unchanged (idempotent)
    h.cef_execute_javascript(script)
```

### Adding a new action

```python
model.add_item("Save Game", "save", handler=save_handler)
```

That's it. The HTML/JS view re-renders from the model state on the next push — no markup changes required.

### Action handlers

Handlers are plain callables `() -> None`. They run on the host-loop thread, on the tick the user activates the row. They should be cheap — anything heavier than flipping a flag (file I/O, network) belongs on a deferred task queue.

`"exit"` sets a quit-requested flag on the host loop's `_PauseMenuController`. The loop sees it on the next iteration and breaks out of `while not r.should_close()` cleanly, falling through into the existing CEF/GL teardown.

## Input

| Source | Action |
|---|---|
| `ESC` | Open / close the menu (edge-triggered) |
| `↑` / `↓` | Move focus up / down with wrap |
| `Enter` | Activate the focused row |
| Mouse hover | Highlights the row under the cursor (CSS `:hover` mirrors `--chosen`) |
| Left click | Activates the row under the cursor |

Mouse handling depends on two C++ side-effects:

1. **Mouse event forwarding** — the host loop pushes `cursor_pos()` to CEF via `cef_send_mouse_move(x, y)` and forwards left-click edges via `cef_send_mouse_click(x, y, button, is_down)`. Only forwarded while the pause menu is open, so normal gameplay input is untouched.

2. **JS→Python event channel** — clicks in the JS layer call `dauntlessEvent('exit')`, which emits `console.info("dauntless-event:exit")`. The `CefDisplayHandler::OnConsoleMessage` override in `cef_client` recognises the `dauntless-event:` prefix, suppresses the default log, and invokes a Python callback registered via `cef_set_event_handler(cb)`. Python dispatches the name to the pause-menu model's handler dictionary.

Why console messages and not a custom URL scheme: Chromium will silently reject navigation to unregistered schemes before `OnBeforeBrowse` fires, so `dauntless://event/<name>` looked like a dead link. Console messages always reach `OnConsoleMessage` regardless of scheme/navigation policy, and DevTools (F12) shows every emit — making the channel trivially debuggable. No `CefMessageRouter`, no subprocess routing.

## Variants

Single layout for now. Possible future variants:

- **Confirm-quit nested modal** — Exit Program could open the [08 modal-dialog](08-modal-dialog.md) for an "Are you sure?" pass. We currently exit on the first activation; if quit-by-accident becomes a real problem, route Exit through the modal first.
- **Sub-menus** — e.g. "Save Game" expanding to a save-slot picker. Same row chrome; a row's handler can replace the model's item list with sub-menu items and a "Back" row.

## CSS reference

`native/assets/ui-cef/css/hello.css` (pause-menu rules) — until the chrome + row primitives migrate to dedicated `chrome.css` / `row.css` files alongside the other panels.

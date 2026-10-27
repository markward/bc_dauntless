# 01 — Officer menu

Visual reference: [01-officer-menu.html](01-officer-menu.html)

A vertical list of officer / department actions. Used by every F-key that opens a "talk to officer" menu: F1 Helm, F3 XO, F6 Guest, plus departmental sub-menus (e.g. Engineering crew assignments).

## Structure

```
┌──────────────────────┐
│  EXECUTIVE OFFICER ▼ │
╞══════════════════════╡
║  ▸ Helm              │
║  ▸ Tactical          │
║  ▸ Science       ←   │   ← chosen (brighter, accented stripe)
║  ▸ Engineering       │
║  ▸ Comms  (disabled) │   ← muted, no caret colour
└──────────────────────┘
```

Width: **240 px canonical**. The mockup's section sub-headers (e.g. "REPAIR TEAM ASSIGNMENTS") apply to the engineering-officer sub-menu specifically, but the row primitive is reused everywhere.

## Row states

Every row has three states. The colour token controls the row background + caret colour + 3 px left edge:

| State | Background | Foreground | Edge | Caret |
|---|---|---|---|---|
| **available** (default) | `--bc-row-available-bg` `rgb(37, 26, 64)` | `--bc-row-available-fg` `rgb(220, 210, 255)` | `--bc-row-available-edge` `rgb(147, 103, 255)` | edge colour |
| **chosen / hover** | `--bc-row-chosen-bg` `rgb(43, 33, 64)` | `--bc-row-chosen-fg` `rgb(235, 225, 255)` | `--bc-row-chosen-edge` `rgb(173, 132, 255)` | edge colour |
| **disabled** | `--bc-row-disabled-bg` `rgb(16, 16, 16)` | `--bc-row-disabled-fg` `rgb(110, 110, 110)` | `--bc-row-disabled-edge` `rgb(64, 64, 64)` | dim grey |

## Row anatomy

- 6 px 12 px padding
- 2 px vertical margin between rows
- Leading `▸` caret with 10 px right margin (chosen rows: same caret, brighter edge colour)
- Body text in `--bc-font-body` 13 px regular
- Optional right-aligned `value` text in tabular numerics, smaller (12 px), dimmer

## SDK runtime contract

| SDK call | What it does |
|---|---|
| `STTopLevelMenu_CreateW(text)` | Creates the menu shell + header |
| `pMenu.AddChild(button)` | Appends a row whose label = button's text |
| `pButton.SetEnabled(False)` | Sets that row to the disabled state |
| `pButton.SetChosen(True)` | Sets that row to the chosen state (radio selection) |
| `pButton.SetLabel(text)` | Updates the row's text |
| `pButton._on_click(event)` | Fires when user clicks the row |

## Section sub-headers (optional)

Some officer menus group rows under sub-headers like "REPAIR TEAM ASSIGNMENTS", "DAMAGED SYSTEMS", "DESTROYED SYSTEMS". Specs:

- Font: Antonio 11 px, weight 600
- Letter-spacing: 1 px
- Colour: `--bc-section-fg` `rgb(216, 132, 80)` (the chrome accent)
- Underline: 1 px solid in the same colour
- Margin: 8 px top, 2 px bottom

These are static labels emitted by the SDK as part of the menu's row list — not interactive.

## CSS reference

`native/assets/ui-cef/css/xo.css` + the row primitives in `chrome.css`.

# 08 — Modal dialog

Visual reference: [08-modal-dialog.html](08-modal-dialog.html)

A centred modal dialog used for confirmation prompts ("Return to Main Menu?", "Save?", "Quit Mission?"). Includes a backdrop dim and an LCARS-style pill button row.

## Structure

```
                                                       ← full-viewport radial dim
                                                          (centre 0.4 alpha → edge 0.85 alpha)

          ┌─ RETURN TO MAIN MENU ─────────────────▼┐  ← Menu1 gradient header
         ┌║                                         │← 3-sided red U-frame border
         │║ Returning to the main menu will end     │   (left, right, bottom — header is the top)
         │║ the current mission. Any progress       │
         │║ since the last save will be lost.       │
         │║                                         │
         │║          ╓─ CANCEL ─╖  ╓─ QUIT MISSION ─╖
         │║          ║          ║  ║   (purple)     ║ ← LCARS pill buttons with red end-caps
         │║          ╙──────────╜  ╙────────────────╜
         └└─────────────────────────────────────────┘
```

## Backdrop

A full-viewport overlay that dims the underlying scene:
- Background: `radial-gradient(circle at centre, rgba(0,0,0,0.4) 0%, rgba(0,0,0,0.85) 70%)`
- Pointer events: blocked except on the dialog itself
- z-index: above all other panels

Token: `--bc-modal-backdrop` (full gradient declaration).

## Dialog box

Three-sided red border ("U-frame"): left, right, bottom in `--bc-menu1-base` `rgb(216, 94, 86)`. The top edge is the panel header itself (whose gradient continues the red theme).

| Element | Token | Value |
|---|---|---|
| Dialog body bg | `--bc-modal-bg` | `rgba(10, 10, 16, 0.92)` (slightly more opaque than ambient panels) |
| U-frame left/right/bottom | `--bc-menu1-base` | `rgb(216, 94, 86)` |
| Body text | `--bc-modal-body-fg` | `rgb(190, 178, 220)` (dim violet) |
| Body padding | n/a | 16 px |
| Width | n/a | 440 px (canonical); adapts to content above min-width |

Body text is Antonio 13 px regular, line-height 1.5.

## LCARS pill button row

The bottom of the dialog has 1 or 2 buttons arranged in an LCARS pill row:

```
  ╓──╖  ╓ Cancel ╖  ╓ Quit Mission ╖  ╓──╖
  ║ ●║  ║        ║  ║    (primary)  ║  ║● ║
  ╙──╜  ╙────────╜  ╙────────────────╜  ╙──╜
   ↑                                       ↑
   left red end-cap                  right red end-cap
```

The end-caps are decorative; they're filled red half-pills.

### Button states

| Button kind | Token | Background | Text |
|---|---|---|---|
| **Primary** (e.g. "QUIT MISSION") | `--bc-btn-primary-bg`, `--bc-btn-primary-fg` | `rgb(166, 124, 235)` (vivid purple) | `#fff` |
| **Secondary** (e.g. "CANCEL") | `--bc-btn-secondary-edge`, `--bc-btn-secondary-fg` | Transparent, 1 px border in `rgb(180, 170, 220)` | `rgb(220, 210, 255)` |
| **Disabled** | `--bc-btn-disabled-bg`, `--bc-btn-disabled-fg` | `rgb(60, 55, 70)` | `rgb(110, 110, 110)` |

### Button geometry

- Height: 28 px
- Min-width: 90 px
- Padding: 0 18 px
- Font: Antonio 12 px, weight 600, uppercase, letter-spacing 1 px
- Border-radius: 0 (the pill shape comes from end-caps, not per-button)

## SDK runtime contract

```python
pModal = App.ModalDialogWindow_Cast(...)
pModal.SetTitle("Return to Main Menu")
pModal.SetBody("Returning to the main menu will end the current mission.\n"
                "Any progress since the last save will be lost.")
pModal.AddButton("Cancel",       primary=False, event="modal-cancel")
pModal.AddButton("Quit Mission", primary=True,  event="modal-ok")
pModal.Show()
# Engine fires `modal-ok` or `modal-cancel` event when the user clicks.
```

The SDK's `ModalDialogWindow` calls `.Run()` to spawn the modal; the engine layer maps that to opening `panels/modal.html` into the `#modal` slot. Click dispatch routes back to the SDK's event bus.

## Variants

The mockup shows the **simple confirmation** form (title + body + 2 buttons). The mockup also documents a "complex modal" (Quick Battle Setup with tabs and three columns), out of scope for this widget — see the longer dialog mockup if/when needed.

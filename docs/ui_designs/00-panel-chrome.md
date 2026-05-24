# 00 — Panel chrome (shared)

Visual reference: [00-panel-chrome.html](00-panel-chrome.html)

The chrome wrapper every other panel reuses. Defines:
- Header bar with gradient + uppercase title + optional collapse glyph
- Translucent dark panel body
- 4 px coloured left-edge stripe (no full border)
- Top-right corner rounding on the header

## Structure

```
┌───────────────────────────────────────────┐
│ TITLE            (gradient L→R)        ▼ │   ← header (rounded TR)
├───────────────────────────────────────────┤
║                                           │
║   panel body content                      │   ← 4 px left stripe (║)
║                                           │
└───────────────────────────────────────────┘
```

## Palette tokens (see SDK_UI_API.md)

| Element | Token | Value |
|---|---|---|
| Header gradient start | `--bc-menu1-base` | `rgb(216, 94, 86)` |
| Header gradient end | `--bc-menu1-accent` | `rgb(216, 132, 80)` |
| Header text | `--bc-header-fg` | `#ffd` (off-white) |
| Body background | `--bc-panel-bg` | `rgba(10, 10, 16, 0.85)` |
| Left edge stripe | `--bc-panel-edge` | `rgb(216, 94, 86)` |

Sub-menu panels (Manoeuvres, Tactics, etc.) swap `--bc-menu1-*` for `--bc-menu3-*` (pink — `rgb(195, 95, 175)` start, `rgb(220, 145, 170)` end).

## Header specs

- Font family: Antonio
- Weight: 600
- Letter-spacing: 2 px
- Text transform: uppercase
- Font-size: 14 px
- Padding: 6 px 16 px
- Border-radius: `0 14px 0 0` (top-right only)
- Collapse indicator: `▼` or `▲` at the right edge — usually a `<span>` child, optional

## Body specs

- Background: translucent dark (panel reads over the 3D scene)
- Left border: 4 px solid in the chrome family colour
- Padding: 8 px 6 px
- Content gap: 2 px between immediate children
- No top / right / bottom border

## When to use

Every interactive panel uses this chrome. The header colour family signals the panel's hierarchy:
- **Menu1 (salmon-orange)** = primary / top-level (Tactical menu, Engineer panel, Officer menus)
- **Menu3 (pink)** = sub-menu (Manoeuvres, Tactics)

Readout-only panels (Shields, Weapons-Speed, Sensors) use Menu1 chrome.

## CSS reference

In the runtime the chrome is `.bc-panel` + `.bc-panel-header` + `.bc-panel-body`. See `native/assets/ui-cef/css/chrome.css` for the canonical implementation.

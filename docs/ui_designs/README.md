# Bridge UI Designs

Canonical mockups + descriptions for every bridge-UI widget the dauntless engine needs to render. Each design has a paired `.html` (the visual reference — open in a browser) and `.md` (the description: purpose, palette, layout, runtime data, interactions).

The HTML files are direct copies of the brainstormed mockups under `.superpowers/brainstorm/`. Treat them as **read-only canonical sources**. Any divergence between a runtime render and its `.html` here is a fidelity bug in the runtime, not a sign the design needs revisiting.

## Widget index

| # | File | Purpose | SDK trigger |
|---|---|---|---|
| 00 | [panel-chrome](00-panel-chrome.md) | Shared header + body + left-edge stripe used by every panel | n/a (shared chrome) |
| 01 | [officer-menu](01-officer-menu.md) | Vertical list of officer / department actions | `STTopLevelMenu_Create` (F1 Helm, F3 XO, F6 Guest, departmental sub-menus) |
| 02 | [tactical-cluster](02-tactical-cluster.md) | TACTICAL + ORDERS + MANOEUVRES + TACTICS four-panel menu cluster | F2 Tactical; nested STMenu hierarchy |
| 03 | [shields-readout](03-shields-readout.md) | Player + target shields with hull integrity bars | `ShieldDisplay` widget; updates per tick |
| 04 | [weapons-and-speed](04-weapons-and-speed.md) | Weapon cycle (torpedo + phaser config) + speed readout | `WeaponsDisplay_Create`, `SpeedDisplay_Create` |
| 05 | [sensors-radar](05-sensors-radar.md) | Perspective-disc radar with friendly/hostile/neutral blips | `RadarDisplay_Create` (F4 Science) |
| 06 | [engineer-panel](06-engineer-panel.md) | Engineering: power sliders + used/available grid bars + battery-glyph pillars + tractor/cloak siphon toggles | F5 Engineer; composes power grid + system rows |
| 07 | [power-transmission-grid](07-power-transmission-grid.md) | (retired — folded into 06) | — |
| 08 | [modal-dialog](08-modal-dialog.md) | Centred modal with U-frame border + LCARS pill buttons | `ModalDialogWindow_Cast` (quit, save, confirm prompts) |
| 09 | [welcome-screen](09-welcome-screen.md) | Pre-game / between-mission welcome panel | Mission picker; loads on startup before a session |
| 10 | [pause-menu](10-pause-menu.md) | ESC-opened in-game pause menu — vertical row list (Exit Program / Cancel; extensible) | Dauntless-native (no SDK Python); `ESC` keybind from `DefaultKeyboardBinding.py:25` |

## Design language

The bridge UI is **LCARS-inspired** but not a literal LCARS clone: salmon-orange / pink chrome, deep dark panel bodies, identifying colours per ship subsystem, large legible numerics.

- **Single canonical palette** lives in [SDK_UI_API.md](SDK_UI_API.md) §"Colour palette". Every panel reuses those exact tokens; no panel invents its own colours.
- **Two chrome families**: Menu1 (salmon-orange — primary panels, top-level menus) and Menu3 (pink — sub-menus / secondary panels). The mockups derive both from a single base hue with a +20° hue-shift for the secondary tier.
- **Display font: Antonio** (condensed sans, 600 weight) — used for all headers, labels, percentages, and any "screen text" surface. Body font is the same display family at lower weight.
- **No outer panel borders**. The left edge is a 4 px coloured stripe; the header carries a top-right 14 px rounded corner. The body uses a translucent dark fill so the 3D scene behind reads through subtly. **Exception: the Engineering panel (06) is headerless** — its chrome is the 4 px salmon left stripe only; no header bar.
- **Row affordance**: every interactive row has a leading `▸` caret in the row's edge colour, a 3 px left stripe, and a body-text label.

See [SDK_UI_API.md](SDK_UI_API.md) for the engine contract — what SDK calls the UI layer must service, with arguments + colour mappings.

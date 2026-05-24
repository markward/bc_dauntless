# 02 — Tactical menu cluster

Visual reference: [02-tactical-cluster.html](02-tactical-cluster.html)

The tactical menu shown by F2 Tactical. **Four sub-panels** arranged together:
- **TACTICAL** (Menu1 chrome, the parent menu) — radio rows for top-level fire-control modes
- **ORDERS** (Menu1 chrome) — 2×2 grid of action-order radio choices (Destroy / Disable / Stop / Evade)
- **MANOEUVRES** (Menu3 chrome) — pink sub-menu of helm-officer manoeuvre orders
- **TACTICS** (Menu3 chrome) — pink sub-menu of formation/fire-pattern orders

## Layout

The mockup arranges them horizontally in a row (TACTICAL on the left, then a small gap, then ORDERS + MANOEUVRES + TACTICS clustered to the right). The vertical positioning in-game is **top-left of the viewport**.

```
┌─ TACTICAL ─────────▼┐   ┌─ ORDERS ──────▼┐ ┌─ MANOEUVRES ─▼┐ ┌─ TACTICS ─▼┐
║ ▸ Report             │   ║ ▸ Destroy ○ Disable │ ║ ▸ At Will         │ ║ ▸ At Will  │
║ ○ Manual Fire        │   ║ ○ Stop    ○ Evade   │ └────────────────────┘ └────────────┘
║ ○ Phasers Only       │   └─────────────────────┘
║ ● Target At Will     │ ← chosen (gold filled bullet)
└──────────────────────┘
```

## Row affordances

The TACTICAL parent menu uses **radio rows** — exactly one chosen at a time:
- **Chosen**: gold filled circle indicator (`●` in `--bc-gold` `rgb(255, 210, 90)`) instead of the row caret. Row background uses Menu1 accent darker tone.
- **Available**: open circle (`○`) in Menu1 base colour. Row background is the standard available state from chrome.css.
- **Caret rows** (no radio) use the standard `▸` from chrome.

ORDERS uses the same 2×2 grid pattern, same radio mechanics.

MANOEUVRES + TACTICS (Menu3 pink chrome) use the standard caret rows — they're sub-menus that expand on selection rather than radio groups.

## Open vs closed state

The "open" state in the mockup shows TACTICS expanded into a longer column (At Will / Left Phaser Attack / Right Phaser Attack / Fore Attack / Aft Attack / Top Shields / Bottom Shields). When a sub-menu is "open", its header collapse indicator flips from `▼` to `▲`.

## SDK runtime contract

The tactical cluster is composed by `Bridge/TacticalMenuHandlers.py` from these SDK calls:

```python
pTactical    = App.STTopLevelMenu_CreateW("Tactical")      # Menu1 chrome
pOrders      = App.STMenu_CreateW("Orders")                # Menu1 chrome (child)
pManoeuvres  = App.STMenu_CreateW("Manoeuvres")            # Menu3 chrome
pTactics     = App.STMenu_CreateW("Tactics")               # Menu3 chrome

pTactical.AddChild(report_button)        # caret row
pTactical.AddChild(manual_fire_button)   # radio row
pTactical.AddChild(phasers_only_button)  # radio row
pTactical.AddChild(target_at_will_button) # radio row (chosen)
```

The engine layer must dispatch radio-group semantics: when the SDK calls `pButton.SetChosen(True)` on one button in a radio menu, ALL siblings get their chosen state cleared on the next frame.

## Palette tokens

| Element | Token | Value |
|---|---|---|
| TACTICAL/ORDERS header (Menu1) | `--bc-menu1-base` → `--bc-menu1-accent` gradient | salmon orange |
| MANOEUVRES/TACTICS header (Menu3) | `--bc-menu3-base` → `--bc-menu3-accent` gradient | pink |
| Radio chosen indicator | `--bc-gold` | `rgb(255, 210, 90)` |
| Radio available indicator | `--bc-menu1-base` (or row edge) | salmon |
| Row body | `--bc-row-available-bg` (default purple) | `rgb(37, 26, 64)` |
| Chosen row body | darker Menu1 tint, e.g. `rgb(107, 53, 47)` | (custom — see HTML) |

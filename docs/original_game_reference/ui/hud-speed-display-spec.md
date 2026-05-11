# Speed / Phaser Arc / Torpedo Readiness — UI Specification

A combined readout of ship speed, phaser-array readiness and torpedo-tube readiness. Anchored to the **lower-right corner**.

Companion to: [tactical-mode.md § Phaser Arc / Torpedo Display](tactical-mode.md#phaser-arc--torpedo-display-lower-right).

---

## Panel anatomy

```
┌── Speed 0 : 0 kph ─────────┐ ▼
│                            │
│  ┌────────────────────┐    │
│  │  ◔ ◔ ◔ ◔ ◔        │    │   ← dorsal phaser strip layer
│  │   ◯◯  ship  ◯◯    │    │     (ship icon centred)
│  │  ◔ ◔ ◔ ◔ ◔        │    │   ← ventral phaser strip layer
│  └────────────────────┘    │
│                            │
│  ●●   fore torpedo tubes   │   ← per-tube readiness dots
│  ●●   aft torpedo tubes    │
└────────────────────────────┘
```

- Frame: thin coral-red outline `#CC3333` on black `#000000`.
- Title bar reads `Speed <current> : <max> kph` — both values update live.
- `▼` collapse arrow in the upper-right.

### Title text

Shows live speed in the format `Speed 0 : 0 kph` (current : maximum). The maximum reflects the engineering Engines slider's current allocation. Visible in screenshots 5, 8, 9, 10, 11, 12, 13, 14.

### Phaser-strip readout

A miniature ship icon centred in the panel, with **phaser-strip overlays** wrapping it in two layers:

- **Dorsal** strips above the ship icon.
- **Ventral** strips below.

Each strip represents one phaser array on the hull. Per-strip colour reflects charge:

| Strip state | Human name | Hex (approx.) |
|---|---|---|
| Fully charged | Bright green | `#33FF33` |
| Charging | Yellow | `#FFCC00` |
| Heavily depleted | Red | `#FF3300` |
| Drained | Black | `#000000` |
| Disabled | Grey | `#888888` |
| Destroyed | strip absent | — |

### Firing-arc indicator

A **transparent blue / grey wedge** emanates from the ship icon toward whichever strips can fire on the current target (within arc). A target may be in more than one arc at once. **No indicator = target is in a blind spot.**

Indicator colour: pale cyan / steel blue `#99CCCC` at low opacity.

### Torpedo readiness dots

Small circular dots near the bow and stern of the ship icon, one per torpedo tube:

| Dot colour | Human name | Hex | Meaning |
|---|---|---|---|
| Green | Bright green | `#33FF33` | Loaded, ready to fire |
| Red | Crimson | `#CC3333` | Loading, or out of torpedoes |
| Grey | Mid-grey | `#888888` | Tube disabled |
| (absent) | — | — | Tube destroyed |

Phaser recharge speed scales with the **Weapons** slider in Engineering's Power Transmission Grid; the strip-state animation reflects the current rate.

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Frame outline | Coral red | `#CC3333` |
| Title bar text | Yellow gold | `#FFCC00` |
| Ship icon | Light grey | `#CCCCCC` |
| Firing-arc wedge | Pale cyan, transparent | `#99CCCC` @ ~30% α |
| Collapse arrow `▼` | Yellow | `#FFCC00` |

---

## Interactions

- Click `▼` → minimise to title bar.
- The panel is otherwise **read-only**.

---

## Interior vs exterior behaviour

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Always visible? | **No** — only when Tactical menu is open or Red Alert is active | **Yes** — persistent |
| Position | Lower-right | Lower-right |
| Behaviour | Identical | Identical |
| Green-alert content | Title bar shows speed only; phaser strips and torpedo dots still visible but inactive looking (everything green / loaded by default) | Same |

> Combat tip the manual emphasises: rotate the ship to keep moving the target between phaser arcs, so no single array gets drained and so enemies are kept out of blind spots.
